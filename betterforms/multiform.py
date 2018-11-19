from itertools import chain
from operator import add

try:
    from collections import OrderedDict
except ImportError:  # Python 2.6, Django < 1.7
    from django.utils.datastructures import SortedDict as OrderedDict  # NOQA

try:
    from django.forms.utils import ErrorDict, ErrorList
except ImportError:  # Django < 1.7
    from django.forms.util import ErrorDict, ErrorList  # NOQA

from django.core.exceptions import ValidationError, NON_FIELD_ERRORS
from django.utils.encoding import python_2_unicode_compatible
from django.utils.safestring import mark_safe
from django.utils.six.moves import reduce
from django.http import QueryDict
from django.db import models
from django_fake_model.models import FakeModel
from django.db.models.fields import AutoField
from django.forms.models import ModelFormMetaclass
from collections import OrderedDict
import pprint

@python_2_unicode_compatible
class MultiForm(object):
    """
    A container that allows you to treat multiple forms as one form.  This is
    great for using more than one form on a page that share the same submit
    button.  MultiForm imitates the Form API so that it is invisible to anybody
    else that you are using a MultiForm.
    """
    form_classes = {}

    def __init__(self, data=None, files=None, *args, **kwargs):
        # Some things, such as the WizardView expect these to exist.
        self.data, self.files = data, files
        kwargs.update(
            data=data,
            files=files,
        )

        self.initials = kwargs.pop('initial', None)
        if self.initials is None:
            self.initials = {}
        self.forms = OrderedDict()
        self.crossform_errors = []

        self.form_keys = []
        for key, form_class in self.form_classes.items():
            fargs, fkwargs = self.get_form_args_kwargs(key, args, kwargs)
            self.forms[key] = form_class(*fargs, **fkwargs)
            self.form_keys.append(key)

        self.form_index = 0

    def __iter__(self):
        return self

    def next(self): # Python 3: def __next__(self)
        if self.form_index >= len(self.form_keys):
            raise StopIteration
        else:
            self.form_index += 1
            return self.forms[self.form_keys[self.form_index]]

    def get_form_args_kwargs(self, key, args, kwargs):
        """
        Returns the args and kwargs for initializing one of our form children.
        """
        fkwargs = kwargs.copy()
        prefix = kwargs.get('prefix')
        if prefix is None:
            prefix = key
        else:
            prefix = '{0}__{1}'.format(key, prefix)
        fkwargs.update(
            initial=self.initials.get(key),
            prefix=prefix,
        )
        return args, fkwargs

    def __str__(self):
        return self.as_table()

    def __getitem__(self, key):
        return self.forms[key]

    @property
    def errors(self):
        errors = {}
        for form_name in self.forms:
            form = self.forms[form_name]
            for field_name in form.errors:
                errors[form.add_prefix(field_name)] = form.errors[field_name]
        if self.crossform_errors:
            errors[NON_FIELD_ERRORS] = self.crossform_errors
        return errors

    @property
    def fields(self):
        fields = []
        for form_name in self.forms:
            form = self.forms[form_name]
            for field_name in form.fields:
                fields += [form.add_prefix(field_name)]
        return fields

    def __iter__(self):
        # TODO: Should the order of the fields be controllable from here?
        return chain.from_iterable(self.forms.values())

    @property
    def is_bound(self):
        return any(form.is_bound for form in self.forms.values())

    def clean(self):
        """
        Raises any ValidationErrors required for cross form validation. Should
        return a dict of cleaned_data objects for any forms whose data should
        be overridden.
        """
        return self.cleaned_data

    def add_crossform_error(self, e):
        self.crossform_errors.append(e)

    def is_valid(self):
        forms_valid = all(form.is_valid() for form in self.forms.values())
        try:
            self.cleaned_data = self.clean()
        except ValidationError as e:
            self.add_crossform_error(e)
        return forms_valid and not self.crossform_errors

    def non_field_errors(self):
        form_errors = (
            form.non_field_errors() for form in self.forms.values()
            if hasattr(form, 'non_field_errors')
        )
        return ErrorList(chain(self.crossform_errors, *form_errors))

    def as_table(self):
        return mark_safe(''.join(form.as_table() for form in self.forms.values()))

    def as_ul(self):
        return mark_safe(''.join(form.as_ul() for form in self.forms.values()))

    def as_p(self):
        return mark_safe(''.join(form.as_p() for form in self.forms.values()))

    def is_multipart(self):
        return any(form.is_multipart() for form in self.forms.values())

    @property
    def media(self):
        return reduce(add, (form.media for form in self.forms.values()))

    def hidden_fields(self):
        # copy implementation instead of delegating in case we ever
        # want to override the field ordering.
        return [field for field in self if field.is_hidden]

    def visible_fields(self):
        return [field for field in self if not field.is_hidden]

    @property
    def cleaned_data(self):
        return OrderedDict(
            (key, form.cleaned_data)
            for key, form in self.forms.items() if form.is_valid()
        )

    @cleaned_data.setter
    def cleaned_data(self, data):
        for key, value in data.items():
            child_form = self[key]
            if hasattr(child_form, 'forms'):
                for formlet, formlet_data in zip(child_form.forms, value):
                    formlet.cleaned_data = formlet_data
            else:
                child_form.cleaned_data = value


class MultiModelForm(MultiForm):
    """
    MultiModelForm adds ModelForm support on top of MultiForm.  That simply
    means that it includes support for the instance parameter in initialization
    and adds a save method.
    """
    def __init__(self, *args, **kwargs):
        self.instance = kwargs.pop('instance', None)
        #import pdb; pdb.set_trace()
#        if self.instances == None:
#            None
#            self.instances = {}
#            #self.instances = self.get_objects()

        self.formsDict = {}
        self.formsPopulated = None
        self.requestData = QueryDict(mutable=True)
        self.objects = {}
        self.form_keys = []
        self.is_update = False

        # populate the multiform with data (usually after a post)
        if ('data' in kwargs.keys()):
            data = kwargs['data']
            tmpRequestData = {}
            for dat in data.keys():
                if (len(dat.split('__')) >= 2):
                    model = dat.split('__')[0]
                    field = dat.split('__')[1]

                    if (tmpRequestData.get(model, 0) == 0):
                        tmpRequestData[model] = {field : data[dat]}
                    else:
                        tmpRequestData[model][field] = data[dat]

            for modelLabel in tmpRequestData.keys():
                for cls in self.form_classes.values():
                    if (cls.Meta.model.__name__.lower() == modelLabel.lower()):
                        qd = QueryDict(mutable=True)
                        for field in tmpRequestData[modelLabel].keys():
                            qd[field] = tmpRequestData[modelLabel][field]

                        tmpRequestData[modelLabel][field]
                        oForm = self.form_classes[modelLabel](qd)
                        self.formsDict[modelLabel.lower()] = oForm

            self.formsPopulated = [ (x, self.formsDict[x]) for x in self.formsDict.keys() ]
 
        if (self.instance != None):
            self.is_update = True
            tmpRequestData = {}
            for key in self.instance.keys():
                model = key.lower()
                formClass = self.form_classes[model](instance=self.instance[model])

                for field_name in formClass.fields:
                    bound_field = formClass[field_name]

                    field_name = '%s__%s' % (model, field_name)
                    if (tmpRequestData.get(model, 0) == 0):
                        tmpRequestData[model] = {field_name : bound_field}
                    else:
                        tmpRequestData[model][field_name] = bound_field

            for modelLabel in tmpRequestData.keys():
                for cls in self.form_classes.values():
                    if (cls.Meta.model.__name__.lower() == modelLabel.lower()):
                        for field in tmpRequestData[modelLabel].keys():
                            # populating request data for MultiModelForm instance creation (for updates)
                            self.requestData[field] = (cls, tmpRequestData[modelLabel][field])
 
            self.form_keys = []
            self.model = self.get_proxy_model(self.instance)
        super(MultiModelForm, self).__init__(*args, **kwargs)

    def get_proxy_model(self, objects):

        self.proxyFields = {}

        for model_name in objects:
            for field in objects[model_name]._meta.fields:
                if (not isinstance(field, AutoField)):
                    #setattr(self, field.__str__().split('.')[-1], models.CharField(max_length=100))
                    self.proxyFields['%s__%s' % (model_name, field.__str__().split('.')[-1])] = ( field.__str__(), models.CharField(max_length=100) )

        class ProxyModel(FakeModel):

#            proxyFields = {}

            def __init__(self, objects, *args, **kwargs):
#                for model_name in objects:
#                    for field in objects[model_name]._meta.fields:
#                        if (not isinstance(field, AutoField)):
#                            #setattr(self, field.__str__().split('.')[-1], models.CharField(max_length=100))
#                            proxyFields['%s__%s' % (model_name, field.__str__().split('.')[-1])] = models.CharField(max_length=100)
                return super(ProxyModel, self).__init__(*args, **kwargs)

        class Meta(ModelFormMetaclass):
#                fields = OrderedDict([ (x, self.proxyFields[x]) for x in self.proxyFields ])
#                for model_name in objects:
#                    fields.update(objects[model_name])
            ordering = ('pk',)
            verbose_name = 'Proxy Model'
            verbose_name_plural = 'Proxy Models'
            permissions = (
                ("view_dataplanreply_attributes", "Can see plan reply attributes"),
            )


        proxyModel = ProxyModel(objects)

        # for verbose_namel.title() # cruds utils.py line 73
        #proxyModel._meta = Meta('', ('',), {})
        proxyModel._meta.fields = [ self.proxyFields[x][1] for x in self.proxyFields.keys() ]
        proxyModel._meta.fields = tuple(proxyModel._meta.fields)
        #import pdb; pdb.set_trace()
        return proxyModel

    def get_objects(self, pk = None):
        for cls in self.form_classes.values():
            if (pk == None):
                raise Exception('No pk specified, update urls must include a pk id')

        return self.get_objects(pk)

    def set_objects(self, pk = None):
        for cls in self.form_classes.values():
            if (pk == None):
                raise Exception('No pk specified, update urls must include a pk id')
        self.objects = self.get_objects(pk)
        None

    @property
    def fields(self):
        #return OrderedDict([ (x, self.proxyFields[x]) for x in self.proxyFields.keys() ])
        return OrderedDict([ (x, self.requestData[x]) for x in self.requestData.keys() ])

        fields = []
        for form_name in self.forms:
            form = self.forms[form_name]
            for field_name in form.fields:
                fields += [form.add_prefix(field_name)]
        return fields

    def get_form_args_kwargs(self, key, args, kwargs):
        fargs, fkwargs = super(MultiModelForm, self).get_form_args_kwargs(key, args, kwargs)

        self.object = self.get_proxy_model(self.get_objects(pk=1))
        if hasattr(self, 'object'):
            kwargs.update({'instance': self.object})

        return fargs, fkwargs

    def save(self, commit=True):
        if (len(self.formsDict) > 0):
            objects = OrderedDict(
                (key, form.save(commit))
                for key, form in self.formsPopulated
            )
        else:
            objects = OrderedDict(
                (key, form.save(commit))
                for key, form in self.forms.items()
            )

        if any(hasattr(form, 'save_m2m') for form in self.forms.values()):
            def save_m2m():
                for form in self.forms.values():
                    if hasattr(form, 'save_m2m'):
                        form.save_m2m()
            self.save_m2m = save_m2m

        return objects
