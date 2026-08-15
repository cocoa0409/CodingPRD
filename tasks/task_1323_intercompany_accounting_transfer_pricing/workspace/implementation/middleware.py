"""Auth, body parsing, shape validation, pagination, and existence helpers.

Validation precedence (PRD 2.8):
  1 auth headers -> 2 role -> 3 existence -> (unparseable body short-circuit)
  -> 4 state -> 5 segregation -> 6 entity referential -> 7 temporal
  -> 8 structural business -> 9 fiscal obligations -> 10 body shape.
"""
from datetime import date, datetime, timezone

from flask import request

from errors import (
    ApiError, MISSING_CONTEXT, FORBIDDEN, INVALID_REQUEST, NOT_FOUND,
)

ALL_ROLES = [
    "GroupTaxAdmin", "TaxAnalyst", "TaxManager", "TransferPricingLead", "TreasuryManager",
]


def require_auth(allowed_roles):
    """Priority 1 + 2. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or not role.strip():
        raise ApiError(MISSING_CONTEXT, 400,
                       "X-User-ID and X-User-Role headers must be present and non-empty")
    role = role.strip()
    if role not in allowed_roles:
        raise ApiError(FORBIDDEN, 403, "Caller role is not admitted by this endpoint")
    return uid.strip(), role


def get_body():
    """Parse a JSON object body. Empty body -> {}. Unparseable -> ERR_INVALID_REQUEST
    (short-circuits before the state check, per PRD 2.8)."""
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    data = request.get_json(silent=True, force=True)
    if data is None or not isinstance(data, dict):
        raise ApiError(INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def get_path(table, rid):
    """Priority 3 (path identifiers, left to right)."""
    res = table.get(rid)
    if res is None:
        raise ApiError(NOT_FOUND, 404, "Resource not found: %s" % rid)
    return res


def require_fk(table, value, name):
    """Priority 3 for body-supplied foreign keys, in declared order.

    Only fires when the value is a well-formed string that fails to resolve;
    missing/wrong-typed values are left for the priority-10 shape check.
    """
    if isinstance(value, str) and value and value not in table:
        raise ApiError(NOT_FOUND, 404, "Referenced resource not found: %s" % name)


# ---- shape validators (priority 10) ----

def shape_str(body, field, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise ApiError(INVALID_REQUEST, 400, "%s is required" % field)
        return None
    if not isinstance(v, str) or not v:
        raise ApiError(INVALID_REQUEST, 400, "%s must be a non-empty string" % field)
    return v


def shape_int(body, field, min_v=None, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise ApiError(INVALID_REQUEST, 400, "%s is required" % field)
        return None
    if not is_int(v):
        raise ApiError(INVALID_REQUEST, 400, "%s must be an integer" % field)
    if min_v is not None and v < min_v:
        raise ApiError(INVALID_REQUEST, 400, "%s must be >= %d" % (field, min_v))
    return v


def shape_enum(body, field, values, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise ApiError(INVALID_REQUEST, 400, "%s is required" % field)
        return None
    if v not in values:
        raise ApiError(INVALID_REQUEST, 400,
                       "%s must be one of %s" % (field, ", ".join(values)))
    return v


def parse_date(v):
    if not isinstance(v, str):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def shape_date(body, field, required=True):
    v = body.get(field)
    if v is None:
        if required:
            raise ApiError(INVALID_REQUEST, 400, "%s is required" % field)
        return None
    d = parse_date(v)
    if d is None:
        raise ApiError(INVALID_REQUEST, 400, "%s must be an ISO date" % field)
    return v


def parse_instant(v):
    if not isinstance(v, str):
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_days(start, end):
    """Whole (floor) days between two instants."""
    return int((end - start).total_seconds() // 86400)


def pagination_params():
    """limit/offset per scaffold response_envelope (default 10/0, min 1, max 100)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        raise ApiError(INVALID_REQUEST, 400, "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise ApiError(INVALID_REQUEST, 400, "offset must be an integer")
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    return limit, offset


def list_page(items, filters):
    """Filter (exact match), sort by creation order (created_at ASC), paginate."""
    out = [r for r in items
           if all(r.get(field) == val for field, val in filters if val is not None)]
    out.sort(key=lambda r: r["_seq"])
    limit, offset = pagination_params()
    total = len(out)
    page = out[offset:offset + limit]
    return page, limit, offset, total
