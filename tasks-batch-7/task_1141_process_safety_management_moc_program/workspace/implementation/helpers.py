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
    "PsmAdmin", "PsmManager", "Requester", "TechnicalReviewer", "OpsApprover",
    "PssrLead", "Investigator", "Auditor", "TrainingCoordinator",
]
# Entity-backed roles: X-User-ID is a Personnel id for these.
ENTITY_ROLES = [
    "Requester", "TechnicalReviewer", "OpsApprover", "PssrLead",
    "Investigator", "Auditor",
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


def f_num(b, name, required=True):
    v = b.get(name)
    if v is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _bad(f"Field {name} must be a number")
    return float(v)


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
# Calendar-day semantics: business datetimes are UTC midnights
# ---------------------------------------------------------------------------

def parse_day(s):
    """Parse a date or ISO datetime string into a datetime.date (UTC day)."""
    if not isinstance(s, str):
        return None
    try:
        if "T" in s or " " in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            return dt.date()
        return date.fromisoformat(s)
    except ValueError:
        return None


def f_day(b, name, required=True):
    v = b.get(name)
    if v is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return None
    d = parse_day(v)
    if d is None:
        raise _bad(f"Field {name} must be a valid ISO 8601 date")
    return d


def fmt_day(d):
    if d is None:
        return None
    return f"{d.isoformat()}T00:00:00Z"


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
