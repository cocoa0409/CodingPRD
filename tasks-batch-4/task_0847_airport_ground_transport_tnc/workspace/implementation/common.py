"""Request pipeline helpers: envelope, auth, body/field validation, pagination."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError
from store import db

ROLES = {"AirportAuthority", "Operator", "CurbCoordinator"}


# --------------------------------------------------------------------------- #
# Response envelope (SCAFFOLD 1.0 / PRD 2.2)
# --------------------------------------------------------------------------- #
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(db.clock),
    }
    if extra:
        m.update(extra)
    return m


def respond(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------- #
# Auth (SCAFFOLD 1.4 priority 1-2 / PRD 2.1)
# --------------------------------------------------------------------------- #
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


# --------------------------------------------------------------------------- #
# Body / field validation (SCAFFOLD 1.4 priority 3 -> ERR_VALIDATION)
# --------------------------------------------------------------------------- #
def body_json():
    raw = request.get_data()
    if raw and raw.strip():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
        return data
    return {}


def _bad(msg):
    raise ApiError("ERR_VALIDATION", 400, msg)


def require_present(body, name):
    if name not in body or body[name] is None:
        _bad(f"Missing required field: {name}")
    return body[name]


def as_str(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            _bad(f"Missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, str) or v == "":
        _bad(f"Field {name} must be a non-empty string")
    return v


def as_int(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            _bad(f"Missing required field: {name}")
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(f"Field {name} must be an integer")
    return v


def as_number(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            _bad(f"Missing required field: {name}")
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(f"Field {name} must be a number")
    return float(v)


def as_bool(body, name, required=False, default=False):
    if name not in body or body[name] is None:
        if required:
            _bad(f"Missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, bool):
        _bad(f"Field {name} must be a boolean")
    return v


def as_enum(body, name, choices, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            _bad(f"Missing required field: {name}")
        return default
    v = body[name]
    if v not in choices:
        _bad(f"Field {name} must be one of {sorted(choices)}")
    return v


def parse_dt(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            _bad(f"Missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, str):
        _bad(f"Field {name} must be an ISO8601 datetime string")
    return parse_iso(v)


def parse_iso(value):
    try:
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except Exception:
        _bad(f"Invalid ISO8601 datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# Existence (SCAFFOLD 1.4 priority 4 -> ERR_NOT_FOUND)
# --------------------------------------------------------------------------- #
def must_exist(coll, _id):
    rec = coll.get(_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return rec


# --------------------------------------------------------------------------- #
# Pagination (SCAFFOLD 1.0 / PRD 2.3)
# --------------------------------------------------------------------------- #
def parse_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            _bad("limit must be an integer")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            _bad("offset must be an integer")
    if limit < 1 or limit > 100:
        _bad("limit must be between 1 and 100")
    if offset < 0:
        _bad("offset must be >= 0")
    return limit, offset


def list_response(records, serializer, limit, offset):
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset: offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return respond([serializer(r) for r in page], "array", 200, pagination)
