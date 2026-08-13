"""Shared primitives: errors, envelope, datetime/decimal helpers, validators, auth, pagination."""
import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import g, jsonify, request

from store import current_time

CENT = Decimal("1")
TWO_DP = Decimal("0.01")


def D(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def rhu(x, quantum):
    return D(x).quantize(quantum, rounding=ROUND_HALF_UP)


def num_out(v):
    """Serialize an internal numeric (Decimal/int/float) to a JSON-friendly value."""
    if isinstance(v, Decimal):
        if v == v.to_integral_value():
            return int(v)
        return float(v)
    return v


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err400(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def err404(msg="Resource not found"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


def err409(error_id, msg):
    raise ApiError(error_id, 409, msg)


# ---------------------------------------------------------------- datetimes

def parse_dt(v):
    """Parse an ISO-8601 string (or date) into an aware UTC datetime. None if invalid."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """ISO-8601 UTC with exactly three fractional digits (audit/request timestamps)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    """Domain datetime fields: whole-second Z form unless a fraction is present."""
    if dt is None:
        return None
    if dt.microsecond:
        return fmt_ts(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- envelope

def meta_base():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_ts(current_time()),
    }


def obj_response(data, code=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return jsonify(body), code


def list_response(page, limit, offset, total, code=200):
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), code


def error_response(error_id, http_status, message):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def paginate(items):
    """Sort by creation order; validate limit/offset; return (page, limit, offset, total)."""
    items = sorted(items, key=lambda e: e["_seq"])
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit, 10)
        except (ValueError, TypeError):
            err400("limit must be an integer")
        if limit < 1 or limit > 100:
            err400("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset, 10)
        except (ValueError, TypeError):
            err400("offset must be an integer")
        if offset < 0:
            err400("offset must be >= 0")
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


# ---------------------------------------------------------------- body validators

def body_json(required=True):
    data = request.get_json(silent=True)
    if data is None:
        if required:
            err400("Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        err400("Request body must be a JSON object")
    return data


def need(body, name):
    if name not in body or body[name] is None:
        err400(f"Missing required field: {name}")
    return body[name]


def v_str(v, name):
    if not isinstance(v, str):
        err400(f"Field {name} must be a string")
    return v


def v_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        err400(f"Field {name} must be an integer")
    return v


def v_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err400(f"Field {name} must be a number")
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        err400(f"Field {name} must be a finite number")
    return v


def v_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        err400(f"Field {name} must be one of {sorted(allowed)}")
    return v


def v_dt(v, name):
    dt = parse_dt(v)
    if dt is None:
        err400(f"Field {name} must be an ISO-8601 datetime")
    return dt


# ---------------------------------------------------------------- auth

ROLES = {
    "DealerRep",
    "PlantEngineer",
    "ProductionLead",
    "ShippingCoordinator",
    "WarrantyAdjuster",
    "PlantManager",
}

ANY_ROLE = tuple(sorted(ROLES))


def require_roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED", 401,
                               "Missing or unrecognized X-User-ID / X-User-Role headers")
            if role not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                               f"Role {role} is not permitted on this endpoint")
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def check_ownership(dealer_id):
    """DealerRep may only touch resources whose dealer chain equals X-User-ID."""
    if g.role == "DealerRep" and dealer_id != g.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "DealerRep may only act on their own dealership's resources")
