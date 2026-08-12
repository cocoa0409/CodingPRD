"""Auth middleware, request body parsing, field validators, pagination.

Validation order per PRD §2.6:
  1. identity headers (ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)
  2. role authorization (ERR_INSUFFICIENT_PERMISSIONS, 403)
  3. left-to-right path existence (ERR_NOT_FOUND, 404)
  4. payload shape (ERR_INVALID_REQUEST, 400)
  5. state-machine precondition (ERR_INVALID_STATE, 409)
  6. business rules (various)
  7. stale-version OCC check last (ERR_STALE_VERSION, 412)
"""

from flask import request

from db import store
from errors import (
    ApiError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)
from util import parse_dt, fmt_dt

ROLES = {
    "ContractorScheduler",
    "ProjectControlsEngineer",
    "OwnerRepresentative",
    "ClaimsConsultant",
    "SystemAdmin",
}

ANY_ROLE = tuple(sorted(ROLES))


def require_roles(*allowed):
    """Priority 1 + 2 checks. Returns the acting user id."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "Required X-User-ID / X-User-Role headers missing or malformed",
        )
    if allowed and role not in allowed:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "Role not authorized for this operation",
        )
    return uid


def json_body():
    """Parse the request JSON body. Absent body -> {}; malformed -> 400."""
    raw = request.get_data()
    if not raw:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be valid JSON")
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def _bad(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def req_field(data, name):
    if name not in data or data[name] is None:
        _bad("Missing required field: %s" % name)
    return data[name]


def as_str(value, name):
    if not isinstance(value, str) or value == "":
        _bad("Field '%s' must be a non-empty string" % name)
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer" % name)
    return value


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '%s' must be a number" % name)
    return value


def as_datetime(value, name):
    """Validate + normalize to canonical ISO string."""
    if not isinstance(value, str):
        _bad("Field '%s' must be an ISO 8601 datetime string" % name)
    return fmt_dt(parse_dt(value, name))


def as_enum(value, name, allowed):
    value = as_str(value, name)
    if value not in allowed:
        _bad("Field '%s' must be one of %s" % (name, sorted(allowed)))
    return value


def as_str_list(value, name):
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        _bad("Field '%s' must be an array of strings" % name)
    return list(value)


def paginate(items):
    """Apply limit/offset per PRD §2.3 (defaults 10/0, limit clamped to 1..100)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            _bad("Query parameter 'limit' must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            _bad("Query parameter 'offset' must be an integer")
        if offset < 0:
            offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


def sorted_items(items):
    """Default list ordering: creation timestamp ascending (§2.3).

    The logical clock only moves when explicitly set, so a global insertion
    sequence number breaks ties deterministically.
    """
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


def touch(resource):
    """Refresh updated_at and increment version where the resource carries one."""
    resource["updated_at"] = fmt_dt(store.clock.now())
    if "version" in resource:
        resource["version"] += 1


def serialize(resource):
    return {k: v for k, v in resource.items() if not k.startswith("_")}
