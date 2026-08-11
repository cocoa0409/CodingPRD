"""Response envelope, auth/role guard, field validators, dates, pagination."""
import random
import string
from datetime import datetime, timezone, date
from functools import wraps

from flask import request, g, jsonify

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
)

ALL_ROLES = [
    "PlatformAdmin", "PlantManager", "BatchOperator", "QATechnician",
    "QAManager", "TechServiceEngineer", "CommercialManager",
    "LogisticsCoordinator", "Distributor",
]

# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def now_iso():
    """Wall-clock timestamp, ISO 8601 UTC with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {"api_request_id": _req_id(), "api_request_timestamp": now_iso()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

def require_roles(*roles):
    allowed = set(roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ALL_ROLES:
                raise ApiError(
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-ID and X-User-Role headers are required and the role must be declared",
                    400,
                )
            if role not in allowed:
                raise ApiError(
                    ERR_INSUFFICIENT_PERMISSIONS,
                    f"Role {role} is not permitted for this endpoint",
                    403,
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def require_owner(owner_id):
    """Distributor-ownership check: resource FK must equal the caller's id."""
    if g.user_role == "Distributor" and owner_id != g.user_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Distributor may only act on its own resources",
            403,
        )


# ---------------------------------------------------------------------------
# Body + field validators (malformed -> ERR_INVALID_REQUEST 400)
# ---------------------------------------------------------------------------

def body_json():
    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data(cache=False)
        if raw and raw.strip():
            raise ApiError(ERR_INVALID_REQUEST, "Request body must be valid JSON", 400)
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def _bad(msg):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def f_str(b, name, required=True):
    v = b.get(name)
    if v is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return None
    if not isinstance(v, str) or v == "":
        raise _bad(f"Field {name} must be a non-empty string")
    return v


def f_int(b, name, required=True, lo=None, hi=None):
    v = b.get(name)
    if v is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise _bad(f"Field {name} must be an integer")
    if lo is not None and v < lo:
        raise _bad(f"Field {name} must be >= {lo}")
    if hi is not None and v > hi:
        raise _bad(f"Field {name} must be <= {hi}")
    return v


def f_num(b, name, required=True, lo=None, hi=None):
    v = b.get(name)
    if v is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _bad(f"Field {name} must be a number")
    v = float(v)
    if lo is not None and v < lo:
        raise _bad(f"Field {name} must be >= {lo}")
    if hi is not None and v > hi:
        raise _bad(f"Field {name} must be <= {hi}")
    return v


def f_bool(b, name, required=True):
    v = b.get(name)
    if v is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return None
    if not isinstance(v, bool):
        raise _bad(f"Field {name} must be a boolean")
    return v


def f_enum(b, name, allowed, required=True):
    v = b.get(name)
    if v is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return None
    if not isinstance(v, str) or v not in allowed:
        raise _bad(f"Field {name} must be one of {sorted(allowed)}")
    return v


def f_list(b, name, required=True):
    v = b.get(name)
    if v is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return None
    if not isinstance(v, list):
        raise _bad(f"Field {name} must be an array")
    return v


# ---------------------------------------------------------------------------
# Datetime / date parsing and formatting
# ---------------------------------------------------------------------------

def parse_dt(s):
    """Parse an ISO 8601 datetime (Z or offset) into an aware UTC datetime."""
    if not isinstance(s, str):
        return None
    try:
        if "T" in s or " " in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        d = date.fromisoformat(s)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    except ValueError:
        return None


def f_dt(b, name, required=True):
    v = b.get(name)
    if v is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return None
    dt = parse_dt(v)
    if dt is None:
        raise _bad(f"Field {name} must be a valid ISO 8601 datetime")
    return dt


def fmt_dt(dt):
    if dt is None:
        return None
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += f".{dt.microsecond:06d}"
    return base + "Z"


def parse_date(s):
    """Parse a strict YYYY-MM-DD date."""
    if not isinstance(s, str):
        return None
    try:
        if "T" in s or " " in s:
            return None
        return date.fromisoformat(s)
    except ValueError:
        return None


def f_date(b, name, required=True):
    v = b.get(name)
    if v is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return None
    d = parse_date(v)
    if d is None:
        raise _bad(f"Field {name} must be a valid YYYY-MM-DD date")
    return d


def fmt_date(d):
    return None if d is None else d.isoformat()


# ---------------------------------------------------------------------------
# Pagination (limit/offset; defaults 10/0; limit 1..100)
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
            raise _bad("Query parameter limit must be an integer")
        if limit < 1 or limit > 100:
            raise _bad("Query parameter limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise _bad("Query parameter offset must be an integer")
        if offset < 0:
            raise _bad("Query parameter offset must be >= 0")
    return limit, offset
