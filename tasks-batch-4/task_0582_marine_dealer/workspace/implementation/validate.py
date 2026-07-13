"""Structural request-validation helpers. All raise ERR_INVALID_REQUEST (400)
on failure unless a more specific error is indicated by the caller."""
from errors import err, ERR_INVALID_REQUEST


def _bad(field, why):
    return err(ERR_INVALID_REQUEST, "Field '%s' %s" % (field, why))


def present(body, field):
    return field in body and body[field] is not None


def req(body, field):
    if not present(body, field):
        raise _bad(field, "is required")
    return body[field]


def as_str(v, field):
    if not isinstance(v, str) or v == "":
        raise _bad(field, "must be a non-empty string")
    return v


def as_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int):
        raise _bad(field, "must be an integer")
    return v


def as_num(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _bad(field, "must be a number")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise _bad(field, "must be a boolean")
    return v


def as_enum(v, field, allowed):
    if v not in allowed:
        raise _bad(field, "must be one of %s" % sorted(allowed))
    return v


def req_str(body, field):
    return as_str(req(body, field), field)


def req_int(body, field):
    return as_int(req(body, field), field)


def req_num(body, field):
    return as_num(req(body, field), field)


def req_enum(body, field, allowed):
    return as_enum(req(body, field), field, allowed)


def opt_int(body, field, default=None):
    if not present(body, field):
        return default
    return as_int(body[field], field)


def opt_num(body, field, default=None):
    if not present(body, field):
        return default
    return as_num(body[field], field)


def opt_bool(body, field, default=None):
    if not present(body, field):
        return default
    return as_bool(body[field], field)


def opt_str(body, field, default=None):
    if not present(body, field):
        return default
    return as_str(body[field], field)
