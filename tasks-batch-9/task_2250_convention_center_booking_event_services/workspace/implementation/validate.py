"""Request body / query validation primitives.

Every failure here raises ERR_INVALID_REQUEST (HTTP 400), which is step 7 of the
PRD 2.11 precedence ladder.
"""

from errors import err
from util import parse_date

MISSING = object()


def _bad(field, why):
    return err("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def req_present(body, field):
    if field not in body or body[field] is None:
        raise _bad(field, "is required")
    return body[field]


def req_string(body, field, allow_empty=False):
    value = req_present(body, field)
    if not isinstance(value, str) or (not allow_empty and value.strip() == ""):
        raise _bad(field, "must be a non-empty string")
    return value


def opt_string(body, field, default=None, allow_empty=True):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, str) or (not allow_empty and value.strip() == ""):
        raise _bad(field, "must be a string")
    return value


def req_enum(body, field, allowed):
    value = req_present(body, field)
    if not isinstance(value, str) or value not in allowed:
        raise _bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, allowed)


def req_int(body, field, minimum=None, maximum=None):
    value = req_present(body, field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        raise _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        raise _bad(field, "must be <= %s" % maximum)
    return value


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, minimum, maximum)


def req_number(body, field, minimum=None, maximum=None,
               exclusive_min=None, exclusive_max=None):
    value = req_present(body, field)
    if not is_number(value):
        raise _bad(field, "must be a number")
    if minimum is not None and value < minimum:
        raise _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        raise _bad(field, "must be <= %s" % maximum)
    if exclusive_min is not None and value <= exclusive_min:
        raise _bad(field, "must be > %s" % exclusive_min)
    if exclusive_max is not None and value >= exclusive_max:
        raise _bad(field, "must be < %s" % exclusive_max)
    return value


def opt_number(body, field, default=None, minimum=None, maximum=None,
               exclusive_min=None, exclusive_max=None):
    if field not in body or body[field] is None:
        return default
    return req_number(body, field, minimum, maximum, exclusive_min, exclusive_max)


def req_bool(body, field):
    value = req_present(body, field)
    if not isinstance(value, bool):
        raise _bad(field, "must be a boolean")
    return value


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_bool(body, field)


def req_date(body, field):
    value = req_string(body, field)
    parsed = parse_date(value)
    if parsed is None:
        raise _bad(field, "must be an ISO 8601 calendar date (YYYY-MM-DD)")
    return parsed


def opt_id(body, field):
    """A foreign key reference: returned as-is when supplied, else None."""
    if field not in body or body[field] is None:
        return None
    return body[field]
