"""Auth headers, RBAC, pagination and request-shape helpers (PRD 2.1/2.3/2.8)."""
import functools

from flask import g, request

import db
from errors import ApiError
from response import (
    PAGE_DEFAULT_LIMIT,
    PAGE_DEFAULT_OFFSET,
    PAGE_MAX_LIMIT,
    PAGE_MIN_LIMIT,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLES = (
    "SelectionAnalyst",
    "FieldAuditor",
    "AuditSupervisor",
    "Taxpayer",
    "AppealsOfficer",
    "TaxTribunalJudge",
    "CollectionsAgent",
)


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = str(user_id).strip()
    g.role = role
    return g.user_id, g.role


def guard(*allowed_roles):
    """Tier 1 (auth) then tier 2 (role) for a single endpoint."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed_roles:
                raise ApiError("ERR_ROLE_NOT_PERMITTED")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ------------------------------------------------------------------------ body
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, min_len=1, max_len=None):
    if not present(data, name):
        bad("%s is required." % name)
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if len(value) < min_len:
        bad("%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (name, max_len))
    return value


def opt_str(data, name, min_len=1, max_len=None, default=None):
    if not present(data, name):
        return default
    return req_str(data, name, min_len, max_len)


def _as_int(name, value):
    if isinstance(value, bool):
        bad("%s must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text)
        except ValueError:
            bad("%s must be an integer." % name)
    bad("%s must be an integer." % name)


def req_int(data, name, minimum=None, maximum=None):
    if not present(data, name):
        bad("%s is required." % name)
    value = _as_int(name, data[name])
    _range(name, value, minimum, maximum)
    return value


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if not present(data, name):
        return default
    value = _as_int(name, data[name])
    _range(name, value, minimum, maximum)
    return value


def _range(name, value, minimum, maximum):
    if minimum is not None and value < minimum:
        bad("%s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s." % (name, maximum))


def req_bool(data, name):
    if not present(data, name):
        bad("%s is required." % name)
    value = data[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def opt_bool(data, name, default=None):
    if not present(data, name):
        return default
    return req_bool(data, name)


def req_enum(data, name, allowed):
    value = req_str(data, name, 1, None)
    if value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, name, allowed, default=None):
    if not present(data, name):
        return default
    return req_enum(data, name, allowed)


def req_date(data, name):
    if not present(data, name):
        bad("%s is required." % name)
    parsed = db.parse_date(data[name])
    if parsed is None:
        bad("%s must be an ISO 8601 calendar date." % name)
    return parsed


def opt_date(data, name, default=None):
    if not present(data, name):
        return default
    return req_date(data, name)


def req_id(data, name):
    if not present(data, name):
        bad("%s is required." % name)
    value = data[name]
    if not isinstance(value, str) or not value.strip():
        bad("%s must be a string identifier." % name)
    return value


def opt_id(data, name):
    if not present(data, name):
        return None
    return req_id(data, name)


# ------------------------------------------------------------------ pagination
def pagination():
    args = request.args
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except ValueError:
            bad("limit must be an integer.")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            bad("limit must be between %d and %d." % (PAGE_MIN_LIMIT, PAGE_MAX_LIMIT))
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except ValueError:
            bad("offset must be an integer.")
        if offset < 0:
            bad("offset must be >= 0.")
    return limit, offset


def filter_arg(name, allowed=None):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if allowed is not None and value not in allowed:
        bad("%s filter must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def paginate(items, limit, offset):
    return items[offset : offset + limit]
