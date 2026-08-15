"""Auth header extraction, role checking, request-body validators, pagination.

Header scheme per PRD §2.1: X-User-ID + X-User-Role on every request.
"""
from datetime import datetime, timezone

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_INVALID_REQUEST, bad_request

ROLES = [
    "Customer",
    "SalesRep",
    "CratingDesigner",
    "ShopForeman",
    "ComplianceOfficer",
    "LogisticsCoordinator",
    "ClaimsAdjuster",
    "PlatformAdmin",
]
ALL_OPERATIONAL = [r for r in ROLES if r != "PlatformAdmin"]


def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing or unknown X-User-ID / X-User-Role headers", 401)
    return uid, role


def require_roles(allowed):
    """Tier 1 (auth) then tier 2 (role admitted)."""
    uid, role = require_auth()
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, "Role %s is not admitted by this endpoint" % role, 403)
    return uid, role


# --------------------------------------------------------------------------
# Request body helpers
# --------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data(cache=True)
        if raw and raw.strip():
            import json as _json
            try:
                data = _json.loads(raw)
            except ValueError:
                raise bad_request("Request body is not valid JSON")
        else:
            return {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object")
    return data


def _is_int(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    if isinstance(v, float) and v.is_integer():
        return True
    return False


def _is_num(v):
    if isinstance(v, bool):
        return False
    return isinstance(v, (int, float)) and v == v and v not in (float("inf"), float("-inf"))


def req_str(d, key):
    v = d.get(key)
    if not isinstance(v, str):
        raise bad_request("Field '%s' is required and must be a string" % key)
    return v


def opt_str(d, key):
    v = d.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise bad_request("Field '%s' must be a string" % key)
    return v


def req_int(d, key, minimum=None, maximum=None):
    v = d.get(key)
    if not _is_int(v):
        raise bad_request("Field '%s' is required and must be an integer" % key)
    v = int(v)
    if minimum is not None and v < minimum:
        raise bad_request("Field '%s' must be >= %s" % (key, minimum))
    if maximum is not None and v > maximum:
        raise bad_request("Field '%s' must be <= %s" % (key, maximum))
    return v


def opt_int(d, key, minimum=None, maximum=None):
    if key not in d or d.get(key) is None:
        return None
    return req_int(d, key, minimum, maximum)


def req_num(d, key, gt=None, gte=None):
    v = d.get(key)
    if not _is_num(v):
        raise bad_request("Field '%s' is required and must be a number" % key)
    v = float(v)
    if gt is not None and not v > gt:
        raise bad_request("Field '%s' must be > %s" % (key, gt))
    if gte is not None and not v >= gte:
        raise bad_request("Field '%s' must be >= %s" % (key, gte))
    return v


def opt_num(d, key, gt=None, gte=None):
    if key not in d or d.get(key) is None:
        return None
    return req_num(d, key, gt, gte)


def req_bool(d, key):
    v = d.get(key)
    if not isinstance(v, bool):
        raise bad_request("Field '%s' is required and must be a boolean" % key)
    return v


def opt_bool(d, key):
    if key not in d or d.get(key) is None:
        return None
    return req_bool(d, key)


def req_enum(d, key, allowed):
    v = d.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise bad_request("Field '%s' is required and must be one of %s" % (key, sorted(allowed)))
    return v


def opt_enum(d, key, allowed):
    if key not in d or d.get(key) is None:
        return None
    return req_enum(d, key, allowed)


def parse_dt(v, key):
    if not isinstance(v, str):
        raise bad_request("Field '%s' must be an ISO 8601 datetime string" % key)
    s = v.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise bad_request("Field '%s' is not a valid ISO 8601 datetime" % key)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def req_dt(d, key):
    if key not in d or d.get(key) is None:
        raise bad_request("Field '%s' is required" % key)
    return parse_dt(d.get(key), key)


def req_list(d, key):
    v = d.get(key)
    if not isinstance(v, list):
        raise bad_request("Field '%s' is required and must be an array" % key)
    return v


# --------------------------------------------------------------------------
# Pagination (PRD §2.3: limit default 10 min 1 max 100, offset default 0)
# --------------------------------------------------------------------------

def page_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(records):
    """records must already be filtered and sorted by created_at ascending."""
    limit, offset = page_params()
    total = len(records)
    page = records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def enum_filter(name, allowed):
    """Optional enum query filter; invalid member -> 400."""
    v = request.args.get(name)
    if v is None:
        return None
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST,
                       "Query parameter '%s' must be one of %s" % (name, sorted(allowed)), 400)
    return v


def str_filter(name):
    return request.args.get(name)
