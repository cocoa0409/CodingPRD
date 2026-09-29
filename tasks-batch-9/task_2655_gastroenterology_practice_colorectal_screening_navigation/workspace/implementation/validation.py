"""Auth / RBAC (PRD 2.1) and request-shape validation (precedence step 3)."""
from flask import request

from core import ROLES, fail, parse_date, parse_instant

_MISSING = object()


# --------------------------------------------------------------------------
# Precedence 1 + 2
# --------------------------------------------------------------------------
def auth(*allowed_roles):
    """Validate the auth headers then the endpoint role list.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Valid X-User-ID and X-User-Role headers are required.")
    if allowed_roles and role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    return user_id, role


# --------------------------------------------------------------------------
# Precedence 3 - body / query shape
# --------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _present(data, name):
    return name in data and data[name] is not None


def req_string(data, name, minlen=1, maxlen=None):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field %s is required." % name)
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field %s must be a string." % name)
    if minlen is not None and len(value) < minlen:
        fail("ERR_INVALID_REQUEST", "Field %s must be at least %d characters." % (name, minlen))
    if maxlen is not None and len(value) > maxlen:
        fail("ERR_INVALID_REQUEST", "Field %s must be at most %d characters." % (name, maxlen))
    return value


def opt_string(data, name, default=None, minlen=1, maxlen=None):
    if not _present(data, name):
        return default
    return req_string(data, name, minlen=minlen, maxlen=maxlen)


def req_enum(data, name, values):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field %s is required." % name)
    value = data[name]
    if not isinstance(value, str) or value not in values:
        fail("ERR_INVALID_REQUEST", "Field %s must be one of %s." % (name, ", ".join(values)))
    return value


def opt_enum(data, name, values, default=None):
    if not _present(data, name):
        return default
    return req_enum(data, name, values)


def _int_value(name, value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field %s must be an integer." % name)
    if lo is not None and value < lo:
        fail("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (name, lo))
    if hi is not None and value > hi:
        fail("ERR_INVALID_REQUEST", "Field %s must be <= %s." % (name, hi))
    return value


def req_int(data, name, lo=None, hi=None):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field %s is required." % name)
    return _int_value(name, data[name], lo, hi)


def opt_int(data, name, lo=None, hi=None, default=None):
    if not _present(data, name):
        return default
    return _int_value(name, data[name], lo, hi)


def _num_value(name, value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field %s must be a number." % name)
    if lo is not None and value < lo:
        fail("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (name, lo))
    if hi is not None and value > hi:
        fail("ERR_INVALID_REQUEST", "Field %s must be <= %s." % (name, hi))
    return value


def opt_number(data, name, lo=None, hi=None, default=None):
    if not _present(data, name):
        return default
    return _num_value(name, data[name], lo, hi)


def req_bool(data, name):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field %s is required." % name)
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field %s must be a boolean." % name)
    return value


def opt_bool(data, name, default=None):
    if not _present(data, name):
        return default
    return req_bool(data, name)


def req_date(data, name):
    raw = req_string(data, name)
    if parse_date(raw) is None:
        fail("ERR_INVALID_REQUEST", "Field %s must be a YYYY-MM-DD calendar date." % name)
    return raw


def req_instant(data, name):
    raw = req_string(data, name)
    parsed = parse_instant(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 UTC instant." % name)
    return parsed


def req_id(data, name):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field %s is required." % name)
    value = data[name]
    if not isinstance(value, str) or not value:
        fail("ERR_INVALID_REQUEST", "Field %s must be a string identifier." % name)
    return value


def opt_id(data, name):
    if not _present(data, name):
        return None
    return req_id(data, name)


# --------------------------------------------------------------------------
# Pagination + filters (PRD 2.3)
# --------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except Exception:
            fail("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
        if str(raw).strip() != str(limit):
            fail("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except Exception:
            fail("ERR_INVALID_REQUEST", "offset must be a non-negative integer.")
        if str(raw).strip() != str(offset):
            fail("ERR_INVALID_REQUEST", "offset must be a non-negative integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be a non-negative integer.")
    return limit, offset


def filter_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def filter_enum(name, values):
    value = filter_value(name)
    if value is None:
        return None
    if value not in values:
        fail("ERR_INVALID_REQUEST", "Filter %s must be one of %s." % (name, ", ".join(values)))
    return value


def apply_page(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
