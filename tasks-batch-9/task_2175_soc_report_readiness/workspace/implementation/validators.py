"""Request-shape validation (PRD 2.7 step 7). Every failure is ERR_VALIDATION."""
import store
from errors import ApiError

MISSING = object()


def _bad():
    raise ApiError("ERR_VALIDATION")


def present(body, field):
    return field in body and body[field] is not None


def req_str(body, field, minlen=1, maxlen=None, upper=False):
    value = body.get(field)
    if not isinstance(value, str):
        _bad()
    if len(value) < minlen:
        _bad()
    if maxlen is not None and len(value) > maxlen:
        _bad()
    if upper and value != value.upper():
        _bad()
    return value


def opt_str(body, field, minlen=1, maxlen=None, default=None):
    if field not in body or body[field] is None:
        return default
    return req_str(body, field, minlen=minlen, maxlen=maxlen)


def req_enum(body, field, choices):
    value = body.get(field)
    if not isinstance(value, str) or value not in choices:
        _bad()
    return value


def opt_enum(body, field, choices, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, choices)


def req_int(body, field, minv=None, maxv=None):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        _bad()
    if minv is not None and value < minv:
        _bad()
    if maxv is not None and value > maxv:
        _bad()
    return value


def opt_int(body, field, minv=None, maxv=None, default=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, minv=minv, maxv=maxv)


def req_dt(body, field):
    value = body.get(field)
    if not isinstance(value, str):
        _bad()
    parsed = store.parse_iso(value)
    if parsed is None:
        _bad()
    return parsed


def opt_dt(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_dt(body, field)


def req_enum_array(body, field, choices, allow_duplicates=False):
    value = body.get(field)
    if not isinstance(value, list) or len(value) == 0:
        _bad()
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in choices:
            _bad()
        if not allow_duplicates and item in seen:
            _bad()
        seen.add(item)
    return list(value)


def opt_enum_array(body, field, choices, default=None, allow_duplicates=False):
    if field not in body or body[field] is None:
        return list(default) if default is not None else None
    return req_enum_array(body, field, choices, allow_duplicates=allow_duplicates)


def req_id(body, field):
    value = body.get(field)
    if not isinstance(value, str) or value == "":
        _bad()
    return value


def opt_id(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_id(body, field)


def fk(body, field, collection):
    """PRD 2.7 step 6: resolve a body foreign key before shape validation.

    Returns the row, or None when the field is absent / not a usable string
    (which the later shape check will report as ERR_VALIDATION).
    """
    from errors import NOT_FOUND

    value = body.get(field)
    if isinstance(value, str) and value != "":
        row = store.DB[collection].get(value)
        if row is None:
            raise ApiError(NOT_FOUND[collection])
        return row
    return None
