"""Level-7 request-shape validation (PRD §2.7) and pagination (PRD §2.3).

Two conventions from §2.7 are honoured here: unknown body keys are ignored
rather than rejected, and any field the system computes or owns itself is
silently ignored when a client supplies it.
"""

from flask import request

from core import D, fail, parse_instant, valid_date

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _present(data, key):
    return key in data and data[key] is not None


def req_present(data, key):
    if not _present(data, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    return data[key]


def as_str(value, key, min_len=None, max_len=None):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % key)
    return value


def as_int(value, key, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (key, maximum))
    return value


def as_number(value, key, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (key, maximum))
    return value


def as_bool(value, key):
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return value


def as_enum(value, key, allowed):
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (key, list(allowed)))
    return value


def as_instant(value, key):
    if not isinstance(value, str) or parse_instant(value) is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an RFC 3339 UTC instant." % key)
    return value


def as_date(value, key):
    if not valid_date(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM-DD date." % key)
    return value


def as_ref(value, key):
    if not isinstance(value, str) or value == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a reference string." % key)
    return value


# --- required readers ------------------------------------------------------
def rstr(data, key, min_len=None, max_len=None):
    return as_str(req_present(data, key), key, min_len, max_len)


def rint(data, key, minimum=None, maximum=None):
    return as_int(req_present(data, key), key, minimum, maximum)


def rnum(data, key, minimum=None, maximum=None):
    return as_number(req_present(data, key), key, minimum, maximum)


def rbool(data, key):
    return as_bool(req_present(data, key), key)


def renum(data, key, allowed):
    return as_enum(req_present(data, key), key, allowed)


def rinstant(data, key):
    return as_instant(req_present(data, key), key)


def rdate(data, key):
    return as_date(req_present(data, key), key)


def rref(data, key):
    return as_ref(req_present(data, key), key)


# --- optional readers ------------------------------------------------------
def ostr(data, key, default=None, min_len=None, max_len=None):
    if not _present(data, key):
        return default
    return as_str(data[key], key, min_len, max_len)


def oint(data, key, default=None, minimum=None, maximum=None):
    if not _present(data, key):
        return default
    return as_int(data[key], key, minimum, maximum)


def onum(data, key, default=None, minimum=None, maximum=None):
    if not _present(data, key):
        return default
    return as_number(data[key], key, minimum, maximum)


def obool(data, key, default=None):
    if not _present(data, key):
        return default
    return as_bool(data[key], key)


def oenum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return as_enum(data[key], key, allowed)


def oinstant(data, key, default=None):
    if not _present(data, key):
        return default
    return as_instant(data[key], key)


def oref(data, key, default=None):
    if not _present(data, key):
        return default
    return as_ref(data[key], key)


def window_order(start, end, start_key, end_key):
    """A window's start must be strictly earlier than its end."""
    if D(start) >= D(end):
        fail("ERR_INVALID_REQUEST", "'%s' must be strictly before '%s'." % (start_key, end_key))


# --- query parameters ------------------------------------------------------
def _query_int(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if value < minimum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be <= %s." % (name, maximum))
    return value


def page_window():
    limit = _query_int(
        "limit", PAGINATION_LIMIT_DEFAULT, PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX
    )
    offset = _query_int("offset", PAGINATION_OFFSET_DEFAULT, PAGINATION_OFFSET_MIN)
    return limit, offset


def qstr(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def qenum(name, allowed):
    raw = qstr(name)
    if raw is None:
        return None
    if raw not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be one of %s." % (name, list(allowed)))
    return raw


def qbool(name):
    raw = qstr(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)


def qinstant(name, required=False):
    raw = qstr(name)
    if raw is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Query parameter '%s' is required." % name)
        return None
    return as_instant(raw, name)


def qrequired_enum(name, allowed):
    raw = qstr(name)
    if raw is None:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is required." % name)
    return as_enum(raw, name, allowed)


def fk(data, key, collection_name):
    """Level 5: resolve a body foreign key.

    Level 5 outranks level 7, so a supplied-but-unresolvable reference is
    reported as a not-found before any shape complaint. A reference that is
    absent or not a string cannot be resolved at all and falls through to the
    level-7 shape check performed by the caller.
    """
    from core import must_exist

    if not _present(data, key):
        return None
    value = data[key]
    if not isinstance(value, str):
        return None
    return must_exist(collection_name, value)
