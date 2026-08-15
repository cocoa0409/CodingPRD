"""HTTP plumbing: API error type, response envelope, auth, request parsing,
pagination. Field names follow the scaffold response_envelope exactly:
success { meta{api_request_id, api_request_timestamp[, limit, offset,
total_count, has_more]}, response_type: object|array, data }
error   { meta{api_request_id, api_request_timestamp}, response_type: "error",
          data{error_id, message} }
"""
import secrets
import string

from flask import jsonify, request

from state import dec, fmt_dt, parse_dt, wall_now

ROLES = ("ProgramAdmin", "SiteSupervisor", "HaulerPartner", "Resident", "Volunteer", "Anonymous")


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
_ALPHABET = string.ascii_letters + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(20)),
        "api_request_timestamp": fmt_dt(wall_now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def err(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Auth (PRD 2.1): X-User-ID + X-User-Role on every endpoint without exception
# ---------------------------------------------------------------------------
def auth(allowed=None):
    """Validate headers; optionally enforce the endpoint's role list.

    Returns (user_id, role). Priority 1 -> ERR_UNAUTHENTICATED (401);
    priority 2 -> ERR_FORBIDDEN (403).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "X-User-ID and X-User-Role headers are required and the role must be a declared role",
        )
    if allowed is not None and role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role is not permitted for this endpoint")
    return user_id, role


def forbidden(message="Ownership check failed"):
    raise ApiError("ERR_FORBIDDEN", 403, message)


# ---------------------------------------------------------------------------
# Request body and field validators (malformed -> ERR_VALIDATION, HTTP 400)
# ---------------------------------------------------------------------------
def body():
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError("ERR_VALIDATION", 400, "Request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
        return data
    return {}


def req_field(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % field)
    return data[field]


def v_str(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be a string" % field)
    return v


def v_int(v, field, lo=None, hi=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be an integer" % field)
    if lo is not None and v < lo:
        raise ApiError("ERR_VALIDATION", 400, "Field %s is out of range" % field)
    if hi is not None and v > hi:
        raise ApiError("ERR_VALIDATION", 400, "Field %s is out of range" % field)
    return v


def v_dec(v, field, lo=None, hi=None):
    try:
        d = dec(v)
    except (ValueError, ArithmeticError):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be a number" % field)
    if lo is not None and d < lo:
        raise ApiError("ERR_VALIDATION", 400, "Field %s is out of range" % field)
    if hi is not None and d > hi:
        raise ApiError("ERR_VALIDATION", 400, "Field %s is out of range" % field)
    return d


def v_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be a boolean" % field)
    return v


def v_enum(v, field, choices):
    if v not in choices:
        raise ApiError(
            "ERR_VALIDATION", 400, "Field %s must be one of %s" % (field, sorted(choices))
        )
    return v


def v_dt(v, field):
    v_str(v, field)
    try:
        return parse_dt(v)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be an ISO 8601 timestamp" % field)


def occ_field(data, field, current):
    """OCC guard (PRD 2.6): the version field is a non-optional input."""
    if field not in data or data[field] is None:
        raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % field)
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be an integer" % field)
    if v != current:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "%s does not match the current version (optimistic concurrency)" % field,
        )
    return v


# ---------------------------------------------------------------------------
# Pagination (scaffold response_envelope.pagination_fields/defaults)
# ---------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def paged(items):
    """items: full filtered+sorted list of serialized dicts."""
    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list(page, total, limit, offset)
