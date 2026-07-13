"""Cross-cutting concerns: error catalog, response envelope, auth, validation,
datetime parsing, and pagination — all read from the PRD/scaffold, not assumed.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify
from store import request_id, now_iso

# ---------------------------------------------------------------------------
# Error catalog (PRD 5 / scaffold 1.6). error_id -> http status.
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_PARTICIPANT_NOT_FOUND": 404,
    "ERR_GRANT_NOT_FOUND": 404,
    "ERR_DONATION_NOT_FOUND": 404,
    "ERR_FUNDED_SERVICE_NOT_FOUND": 404,
    "ERR_ROOM_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_SIGNUP_NOT_FOUND": 404,
    "ERR_VEHICLE_NOT_FOUND": 404,
    "ERR_TRANSPORT_NOT_FOUND": 404,
    "ERR_SERVICE_DAY_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_GRANT_NOT_ACTIVE": 409,
    "ERR_SERVICE_DAY_CLOSED": 409,
    "ERR_SESSION_NOT_SCHEDULED": 409,
    "ERR_PARTICIPANT_INACTIVE": 409,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_SIGNUP_CLOSED": 422,
    "ERR_ROOM_DOUBLE_BOOKED": 409,
    "ERR_VEHICLE_UNAVAILABLE": 409,
    "ERR_SESSION_FULL": 409,
    "ERR_DUPLICATE_SIGNUP": 409,
    "ERR_GRANT_CATEGORY_MISMATCH": 422,
    "ERR_DONATION_CATEGORY_MISMATCH": 422,
    "ERR_MEAL_CAPACITY_EXCEEDED": 409,
    "ERR_DUPLICATE_RESERVATION": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


def err(error_id, message=None):
    return ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2 / scaffold response_envelope).
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_array(items, page, status=200):
    meta_extra = {
        "limit": page["limit"],
        "offset": page["offset"],
        "total_count": page["total_count"],
        "has_more": page["has_more"],
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(e: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Authentication + authorization (PRD 2.1).
# ---------------------------------------------------------------------------
KNOWN_ROLES = {"CenterAdmin", "Coordinator", "Participant", "Auditor"}


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_actor():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unknown authentication headers")
    return Actor(uid, role)


def authorize(actor, allowed_roles):
    if actor.role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")


def check_ownership(actor, participant_id):
    """Participant self-service writes: X-User-ID must equal target participant_id."""
    if actor.role == "Participant" and actor.user_id != participant_id:
        raise err("ERR_UNAUTHORIZED", "Participant may only act on their own resources")


# ---------------------------------------------------------------------------
# Body / field validation (ERR_VALIDATION, 400).
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        if request.data:
            body = request.get_json(silent=True)
            if body is None:
                raise err("ERR_VALIDATION", "Malformed JSON body")
            if not isinstance(body, dict):
                raise err("ERR_VALIDATION", "Body must be a JSON object")
            return body
        return {}
    return {}


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_VALIDATION", f"Missing or invalid '{field}'")
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise err("ERR_VALIDATION", f"'{field}' must be one of {sorted(allowed)}")
    return v


def opt_enum(body, field, allowed, default):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_VALIDATION", f"'{field}' must be one of {sorted(allowed)}")
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"Missing or invalid integer '{field}'")
    if minimum is not None and v < minimum:
        raise err("ERR_VALIDATION", f"'{field}' must be >= {minimum}")
    return v


def opt_int(body, field, default, minimum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum)


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", f"Missing or invalid boolean '{field}'")
    return v


def req_number(body, field, gt=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION", f"Missing or invalid number '{field}'")
    if gt is not None and not (v > gt):
        raise err("ERR_VALIDATION", f"'{field}' must be > {gt}")
    return v


def req_datetime(body, field):
    raw = req_str(body, field)
    return raw, parse_dt(raw, field)


def parse_dt(value, field="datetime"):
    if not isinstance(value, str) or value == "":
        raise err("ERR_VALIDATION", f"Invalid datetime '{field}'")
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise err("ERR_VALIDATION", f"Invalid ISO 8601 value for '{field}'")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Money helper: round half up to whole cents.
# ---------------------------------------------------------------------------
def round_half_up(numer, denom=1):
    q = Decimal(numer) / Decimal(denom)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10 [1,100], offset default 0 [0,).
# ---------------------------------------------------------------------------
def read_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION", "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paginate(rows):
    """rows: list of records. Sort by insertion order (created_at asc)."""
    limit, offset = read_pagination()
    ordered = sorted(rows, key=lambda r: r["_seq"])
    total = len(ordered)
    window = ordered[offset:offset + limit]
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, page
