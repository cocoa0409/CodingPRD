"""HTTP-layer helpers: response envelope, auth, body parsing, pagination.

Envelope shapes come straight from PRD 2.2 / SCAFFOLD response_envelope:
  success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
  error:   {"meta": {...}, "response_type": "error",
            "data": {"error_id": ..., "message": ...}}
Pagination fields: limit / offset / total_count / has_more (defaults 10 / 0).
Auth headers: X-User-ID + X-User-Role (PRD 2.1).
"""

from flask import jsonify, request

import errors as errmod
import util
from errors import ApiError

ALL_ROLES = [
    "DeskAdministrator",
    "VendorFeed",
    "EventAnalyst",
    "OperationsManager",
    "AccountHolder",
    "ClaimsExaminer",
    "CustodianFeed",
]


# ---------------------------------------------------------------------------
# envelope
# ---------------------------------------------------------------------------

def _meta():
    return {
        "api_request_id": util.new_request_id(),
        "api_request_timestamp": util.now_iso(),
    }


def respond(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def respond_list(items, page_meta):
    meta = _meta()
    meta.update(page_meta)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.status


# ---------------------------------------------------------------------------
# auth (validation priorities 1 and 2)
# ---------------------------------------------------------------------------

def require_roles(*roles):
    """Validate identity headers then endpoint role permission. Returns user id."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not user_id.strip() or not role.strip():
        raise ApiError(errmod.E_MISSING_HEADERS, 400,
                       "X-User-ID and X-User-Role headers must be present and non-empty")
    if role not in roles:
        raise ApiError(errmod.E_INSUFFICIENT_PERMISSIONS, 403,
                       "Role %s is not permitted for this endpoint" % role)
    return user_id.strip()


# ---------------------------------------------------------------------------
# body parsing & field validation (validation priority 3)
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(errmod.E_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def _missing(data, field):
    return field not in data or data[field] is None


def require_fields(data, fields):
    for f in fields:
        if _missing(data, f):
            raise ApiError(errmod.E_INVALID_REQUEST, 400,
                           "Required field missing: %s" % f)


def req_str(data, field, allow_empty=False):
    if _missing(data, field):
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Required field missing: %s" % field)
    v = data[field]
    if not isinstance(v, str) or (not allow_empty and not v.strip()):
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Field %s must be a non-empty string" % field)
    return v


def opt_str(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Field %s must be a string" % field)
    return v


def req_int(data, field):
    if _missing(data, field):
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Required field missing: %s" % field)
    return as_int(data[field], field)


def opt_int(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    return as_int(v, field)


def as_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Field %s must be an integer" % field)
    return v


def opt_bool(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Field %s must be a boolean" % field)
    return v


def req_enum(data, field, members):
    v = req_str(data, field)
    if v not in members:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Field %s has invalid value %r" % (field, v))
    return v


def req_date(data, field):
    v = req_str(data, field)
    try:
        return v, util.parse_date_iso(v)
    except ValueError:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Field %s must be an ISO date" % field)


def req_datetime(data, field):
    v = req_str(data, field)
    try:
        return v, util.parse_datetime_iso(v)
    except ValueError:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Field %s must be an ISO 8601 datetime" % field)


def opt_datetime(data, field):
    v = data.get(field)
    if v is None:
        return None, None
    if not isinstance(v, str):
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Field %s must be an ISO 8601 datetime" % field)
    try:
        return v, util.parse_datetime_iso(v)
    except ValueError:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Field %s must be an ISO 8601 datetime" % field)


# ---------------------------------------------------------------------------
# pagination (PRD 2.3)
# ---------------------------------------------------------------------------

def paginate(items):
    """Parse limit/offset, slice, and build the meta pagination fields."""
    args = request.args
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(errmod.E_INVALID_REQUEST, 400,
                           "Query parameter limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(errmod.E_INVALID_REQUEST, 400,
                           "Query parameter limit must be between 1 and 100")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(errmod.E_INVALID_REQUEST, 400,
                           "Query parameter offset must be an integer")
        if offset < 0:
            raise ApiError(errmod.E_INVALID_REQUEST, 400,
                           "Query parameter offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def apply_filters(rows, filters):
    """filters: list of (query_param, record_field). Exact equality matching."""
    for param, field in filters:
        raw = request.args.get(param)
        if raw is None:
            continue
        rows = [r for r in rows if str(r.get(field)) == raw]
    return rows


# ---------------------------------------------------------------------------
# record plumbing
# ---------------------------------------------------------------------------

def stamp_new(record):
    """Attach common system fields for a mutable resource (PRD 2.5)."""
    record.setdefault("id", util.new_id())
    record["created_at"] = util.now_iso()
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    record["_seq"] = util.next_seq()
    return record


def stamp_immutable(record):
    """Immutable audit/ledger records carry only id + created_at (PRD 2.5)."""
    record.setdefault("id", util.new_id())
    record["created_at"] = util.now_iso()
    record["_seq"] = util.next_seq()
    return record


def touch(record):
    """A mutation refreshes updated_at and increments version (PRD 2.5)."""
    record["updated_at"] = util.now_iso()
    record["version"] = record.get("version", 1) + 1
