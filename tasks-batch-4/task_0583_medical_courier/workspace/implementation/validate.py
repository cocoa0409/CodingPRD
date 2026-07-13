"""Structural request-body validation helpers.

Every failure raises ERR_VALIDATION (400) — PRD 2.8 step 4.
"""
from errors import err, ERR_VALIDATION
from store import parse_dt


def _bad(field, why):
    return err(ERR_VALIDATION, "Field '%s' %s" % (field, why))


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


def as_dt(v, field):
    dt = parse_dt(as_str(v, field))
    if dt is None:
        raise _bad(field, "must be an ISO 8601 timestamp")
    return dt


def non_negative(v, field):
    if v < 0:
        raise _bad(field, "must be >= 0")
    return v


def at_least(v, field, minimum):
    if v < minimum:
        raise _bad(field, "must be >= %s" % minimum)
    return v


# ---- required ----

def req_str(body, field):
    return as_str(req(body, field), field)


def req_int(body, field):
    return as_int(req(body, field), field)


def req_num(body, field):
    return as_num(req(body, field), field)


def req_bool(body, field):
    return as_bool(req(body, field), field)


def req_enum(body, field, allowed):
    return as_enum(req(body, field), field, allowed)


def req_dt(body, field):
    return as_dt(req(body, field), field)


def req_int_nn(body, field):
    return non_negative(req_int(body, field), field)


def req_num_nn(body, field):
    return non_negative(req_num(body, field), field)


# ---- optional ----

def opt_str(body, field, default=None):
    if not present(body, field):
        return default
    return as_str(body[field], field)


def opt_int(body, field, default=None):
    if not present(body, field):
        return default
    return as_int(body[field], field)


def opt_enum(body, field, allowed, default=None):
    if not present(body, field):
        return default
    return as_enum(body[field], field, allowed)


def opt_dt(body, field, default=None):
    if not present(body, field):
        return default
    return as_dt(body[field], field)
