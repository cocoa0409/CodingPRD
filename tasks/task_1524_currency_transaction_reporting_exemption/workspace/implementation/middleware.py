"""Auth, body parsing, field validators, pagination, and list helpers."""
from flask import g, request

from db import ROLES, parse_date_strict, parse_dt, store
from errors import (
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ApiError,
    bad_request,
)


def authenticate(allowed_roles):
    """Priority 1-2: authentication then authorization."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is not None:
        role = role.strip()
    if uid is not None:
        uid = uid.strip()
    if not role or not uid or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "Missing or invalid X-User-Role / X-User-ID headers",
            401,
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_UNAUTHORIZED,
            "Role %s is not authorized for this endpoint" % role,
            403,
        )
    g.user_id = uid
    g.user_role = role


def body():
    """Return the request JSON object; {} when no body was sent."""
    raw = request.get_data()
    if not raw:
        return {}
    parsed = request.get_json(silent=True, force=True)
    if not isinstance(parsed, dict):
        raise bad_request("Request body must be a JSON object")
    return parsed


def f_str(b, name):
    """Required string field."""
    v = b.get(name)
    if not isinstance(v, str):
        raise bad_request("Field '%s' is required and must be a string" % name)
    return v


def f_str_opt(b, name, default=None):
    """Optional nullable string field."""
    if name not in b or b.get(name) is None:
        return default
    v = b.get(name)
    if not isinstance(v, str):
        raise bad_request("Field '%s' must be a string or null" % name)
    return v


def f_int(b, name):
    """Required integer field (booleans rejected)."""
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request("Field '%s' is required and must be an integer" % name)
    return v


def f_enum(b, name, values):
    v = b.get(name)
    if not isinstance(v, str) or v not in values:
        raise bad_request(
            "Field '%s' is required and must be one of %s" % (name, list(values))
        )
    return v


def f_datetime(b, name):
    """Required ISO 8601 datetime field. Returns (raw_string, datetime)."""
    v = b.get(name)
    dt = parse_dt(v)
    if dt is None:
        raise bad_request("Field '%s' is required and must be an ISO 8601 datetime" % name)
    return v, dt


def f_date(b, name):
    """Required strict YYYY-MM-DD date field. Returns (raw_string, date)."""
    v = b.get(name)
    d = parse_date_strict(v)
    if d is None:
        raise bad_request("Field '%s' is required and must be a YYYY-MM-DD date" % name)
    return v, d


def f_version(b, name):
    """Required OCC expected-version field."""
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request("Field '%s' is required and must be an integer" % name)
    return v


def pagination_params():
    """limit: default 10, min 1, max 100; offset: default 0, min 0."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be >= 0")
    return limit, offset


def sorted_page(items):
    """Sort by created_at ASC (stable via insertion sequence) and paginate."""
    limit, offset = pagination_params()
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset : offset + limit]
    return page, limit, offset, total
