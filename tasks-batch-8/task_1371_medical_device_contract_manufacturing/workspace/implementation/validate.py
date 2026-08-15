"""Request body shape validators (validation step 3) and existence helpers
(validation step 4)."""
from flask import request

from errors import err_not_found, err_validation
from store import DB
from timeutil import parse_iso


def get_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _missing_or_null(data, name):
    return name not in data or data[name] is None


def req_str(data, name):
    v = data.get(name)
    if not isinstance(v, str):
        raise err_validation("Field '%s' is required and must be a string" % name)
    return v


def opt_str(data, name, default=None):
    if _missing_or_null(data, name):
        return default
    v = data[name]
    if not isinstance(v, str):
        raise err_validation("Field '%s' must be a string" % name)
    return v


def req_bool(data, name):
    v = data.get(name)
    if type(v) is not bool:
        raise err_validation("Field '%s' is required and must be a boolean" % name)
    return v


def opt_bool(data, name, default=False):
    if _missing_or_null(data, name):
        return default
    v = data[name]
    if type(v) is not bool:
        raise err_validation("Field '%s' must be a boolean" % name)
    return v


def req_int(data, name, min_value=None):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation("Field '%s' is required and must be an integer" % name)
    if min_value is not None and v < min_value:
        raise err_validation("Field '%s' is out of range" % name)
    return v


def opt_int(data, name, default=None, min_value=None):
    if _missing_or_null(data, name):
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation("Field '%s' must be an integer" % name)
    if min_value is not None and v < min_value:
        raise err_validation("Field '%s' is out of range" % name)
    return v


def req_enum(data, name, values):
    v = data.get(name)
    if not isinstance(v, str) or v not in values:
        raise err_validation("Field '%s' must be one of %s" % (name, ", ".join(values)))
    return v


def req_dt(data, name):
    v = data.get(name)
    dt = parse_iso(v)
    if dt is None:
        raise err_validation("Field '%s' is required and must be an ISO 8601 datetime" % name)
    return dt


def opt_dt(data, name, default=None):
    if _missing_or_null(data, name):
        return default
    dt = parse_iso(data[name])
    if dt is None:
        raise err_validation("Field '%s' must be an ISO 8601 datetime" % name)
    return dt


def opt_fk(data, name):
    """Optional body-referenced foreign key: must be a string when present."""
    return opt_str(data, name, None)


def get_or_404(kind, id_):
    obj = DB[kind].get(id_) if isinstance(id_, str) else None
    if obj is None:
        raise err_not_found("Resource %s/%s does not exist" % (kind, id_))
    return obj
