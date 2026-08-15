"""Auth context (tier 1/2) and request-shape validators (tier 3)."""
import re
from datetime import date

from flask import request

from errors import ApiError, ERR_MISSING_CONTEXT, ERR_FORBIDDEN, ERR_INVALID_REQUEST

ROLES = {"RevenueAccountant", "RevenueManager", "ContractReviewer", "Controller", "SystemAdmin"}
BUSINESS_ROLES = ("RevenueAccountant", "RevenueManager", "ContractReviewer", "Controller")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def caller():
    """Tier 1: request context headers."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or not str(uid).strip() or not str(role).strip() or role not in ROLES:
        raise ApiError(ERR_MISSING_CONTEXT, 400,
                       "X-User-ID and X-User-Role headers must be present, non-empty, and name a declared role")
    return uid, role


def require_roles(*roles):
    """Tier 1 then tier 2: context headers, then endpoint role permission."""
    uid, role = caller()
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN, 403, "The caller's role is not permitted on this endpoint")
    return uid


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def _bad(name, why):
    raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}': {why}")


def req_str(data, name):
    v = data.get(name)
    if not isinstance(v, str) or v == "":
        _bad(name, "required non-empty string")
    return v


def opt_str(data, name):
    v = data.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        _bad(name, "must be a string")
    return v


def req_int(data, name):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name, "required integer")
    return v


def opt_int(data, name):
    v = data.get(name)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name, "must be an integer")
    return v


def req_bool(data, name):
    v = data.get(name)
    if not isinstance(v, bool):
        _bad(name, "required boolean")
    return v


def opt_bool(data, name, default=None):
    v = data.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        _bad(name, "must be a boolean")
    return v


def req_enum(data, name, members):
    v = data.get(name)
    if not isinstance(v, str) or v not in members:
        _bad(name, f"must be one of {sorted(members)}")
    return v


def parse_date(v, name):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        _bad(name, "must be an ISO yyyy-mm-dd date string")
    try:
        return date.fromisoformat(v)
    except ValueError:
        _bad(name, "is not a valid calendar date")


def req_date(data, name):
    if name not in data or data.get(name) is None:
        _bad(name, "required ISO yyyy-mm-dd date string")
    return parse_date(data.get(name), name)


def opt_date(data, name):
    v = data.get(name)
    if v is None:
        return None
    return parse_date(v, name)


def pagination():
    """limit: default 10, min 1, max 100. offset: default 0. Out-of-range
    values clamp; non-integer values are malformed."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'limit' must be an integer")
    limit = max(1, min(100, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'offset' must be an integer")
    offset = max(0, offset)
    return limit, offset
