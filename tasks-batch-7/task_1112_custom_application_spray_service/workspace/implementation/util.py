"""Shared utilities: errors, response envelope, time helpers, validation helpers,
pagination, and auth header handling. All structural names read from SCAFFOLD.yaml
§1.0 / PRD §2: envelope meta/response_type/data, error body error_id/message,
pagination limit/offset/total_count/has_more, headers X-User-ID / X-User-Role."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import request, jsonify

from store import store

ROLES = {"Grower", "Agronomist", "Dispatcher", "Applicator", "ComplianceOfficer", "CoopAdmin"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err(error_id, status, message):
    return ApiError(error_id, message, status)


def validation_error(message):
    return ApiError("ERR_VALIDATION", message, 400)


def not_found(message="resource not found"):
    return ApiError("ERR_NOT_FOUND", message, 404)


def forbidden(message="forbidden"):
    return ApiError("ERR_FORBIDDEN", message, 403)


def invalid_state(message="resource is not in a valid state for this transition"):
    return ApiError("ERR_INVALID_STATE", message, 409)


def conflict(error_id, message):
    return ApiError(error_id, message, 409)


# ---------------------------------------------------------------------------
# Time (logical clock for domain timestamps, wall clock for meta timestamps)
# ---------------------------------------------------------------------------

def now():
    return store.clock


def _iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def iso(dt):
    if dt is None:
        return None
    return _iso(dt)


def iso_wall_now():
    return _iso(datetime.now(timezone.utc))


def parse_dt(value):
    if not isinstance(value, str):
        raise validation_error("expected an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise validation_error("invalid ISO 8601 datetime: %r" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # datetimes are compared to the second
    return dt.astimezone(timezone.utc).replace(microsecond=0)


# ---------------------------------------------------------------------------
# Decimal helpers (money is integer cents; half-up rounding)
# ---------------------------------------------------------------------------

def dec(v):
    return Decimal(str(v))


def round_cents(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_2dp(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_1dp(d):
    return d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def ceil_int(d):
    return int(d.to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": iso_wall_now(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Auth (X-User-ID + X-User-Role)
# ---------------------------------------------------------------------------

def auth_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-Role must name a declared role and X-User-ID must be present", 401)
    return uid, role


def require_roles(*roles):
    uid, role = auth_context()
    if role not in roles:
        raise forbidden("role %s is not permitted on this endpoint" % role)
    return uid, role


# ---------------------------------------------------------------------------
# Request body & field validators
# ---------------------------------------------------------------------------

def get_body():
    data = request.get_json(silent=True, force=True)
    if not isinstance(data, dict):
        return {}
    return data


def req_present(body, name):
    if name not in body or body[name] is None:
        raise validation_error("missing required field: %s" % name)
    return body[name]


def req_str(body, name):
    v = req_present(body, name)
    if not isinstance(v, str):
        raise validation_error("field %s must be a string" % name)
    return v


def req_nonempty_str(body, name):
    v = req_str(body, name)
    if not v.strip():
        raise validation_error("field %s must be a non-empty string" % name)
    return v


def _as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise validation_error("field %s must be an integer" % name)
    return v


def req_int(body, name, minimum=None):
    v = _as_int(req_present(body, name), name)
    if minimum is not None and v < minimum:
        raise validation_error("field %s must be >= %d" % (name, minimum))
    return v


def req_pos_int(body, name):
    v = _as_int(req_present(body, name), name)
    if v <= 0:
        raise validation_error("field %s must be positive" % name)
    return v


def _as_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise validation_error("field %s must be a number" % name)
    return v


def req_num(body, name):
    return _as_num(req_present(body, name), name)


def req_pos_num(body, name):
    v = _as_num(req_present(body, name), name)
    if v <= 0:
        raise validation_error("field %s must be positive" % name)
    return v


def req_nonneg_num(body, name):
    v = _as_num(req_present(body, name), name)
    if v < 0:
        raise validation_error("field %s must be >= 0" % name)
    return v


def req_bool(body, name):
    v = req_present(body, name)
    if not isinstance(v, bool):
        raise validation_error("field %s must be a boolean" % name)
    return v


def req_dt(body, name):
    return parse_dt(req_present(body, name))


def req_enum(body, name, allowed):
    v = req_present(body, name)
    if not isinstance(v, str) or v not in allowed:
        raise validation_error("field %s must be one of %s" % (name, sorted(allowed)))
    return v


def opt_str(body, name):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, str):
        raise validation_error("field %s must be a string" % name)
    return v


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise validation_error("field %s must be a boolean" % name)
    return v


# ---------------------------------------------------------------------------
# Pagination (limit default 10, min 1, max 100; offset default 0)
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise validation_error("limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise validation_error("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise validation_error("offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise validation_error("offset must be >= 0")
    return limit, offset


def paginate(serialized_items):
    limit, offset = pagination_params()
    total = len(serialized_items)
    page = serialized_items[offset:offset + limit]
    return ok_list(page, total, limit, offset)
