"""Authentication, authorisation, and request-schema helpers.

Precedence (PRD 2.13): 1 authentication, 2 authorisation, 3 request schema.
Every route therefore calls require_roles() before it looks at the body.
"""
from flask import request

from constants import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
    ROLES,
)
from errors import ApiError

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return Actor(user_id, role)


def require_roles(*allowed):
    actor = authenticate()
    if actor.role not in allowed:
        raise ApiError("ERR_ROLE_FORBIDDEN")
    return actor


# ---------------------------------------------------------------- body / schema
def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def require_field(payload, name):
    if name not in payload or payload[name] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return payload[name]


def require_string(payload, name):
    value = require_field(payload, name)
    if not isinstance(value, str) or value.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % name)
    return value


def optional_string(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    return value


def require_enum(payload, name, allowed):
    value = require_field(payload, name)
    if not isinstance(value, str) or value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def optional_enum(payload, name, allowed, default=None):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def require_int(payload, name, minimum=None, maximum=None):
    value = require_field(payload, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be at most %d." % (name, maximum))
    return value


def optional_int(payload, name, default=None, minimum=None, maximum=None):
    if name not in payload or payload[name] is None:
        return default
    return require_int(payload, name, minimum, maximum)


def require_bool(payload, name):
    value = require_field(payload, name)
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def optional_bool(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def require_datetime(payload, name):
    import db as _db
    raw = require_field(payload, name)
    parsed = _db.parse_datetime(raw) if isinstance(raw, str) else None
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 datetime." % name)
    return parsed


def optional_datetime(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return default
    return require_datetime(payload, name)


def require_date(payload, name):
    import db as _db
    raw = require_field(payload, name)
    parsed = _db.parse_date(raw) if isinstance(raw, str) else None
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an ISO date (YYYY-MM-DD)." % name)
    return raw.strip()


def optional_date(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return default
    return require_date(payload, name)


# ---------------------------------------------------------------- pagination
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < PAGE_OFFSET_DEFAULT:
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be at least 0.")
    return limit, offset


def apply_filters(rows, names):
    """Exact-match filters on stored values, taken from the query string."""
    out = rows
    for name in names:
        raw = request.args.get(name)
        if raw is None or raw == "":
            continue
        out = [r for r in out if _matches(r.get(name), raw)]
    return out


def _matches(stored, raw):
    if stored is None:
        return False
    if isinstance(stored, bool):
        return raw.lower() == ("true" if stored else "false")
    if isinstance(stored, int):
        try:
            return stored == int(raw)
        except (TypeError, ValueError):
            return False
    return str(stored) == raw
