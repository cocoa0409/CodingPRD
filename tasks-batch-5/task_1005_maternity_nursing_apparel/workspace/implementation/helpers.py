"""Shared helpers: response envelope, error type, auth, datetime, rounding."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

ROLES = {"Shopper", "FulfillmentAgent", "PlatformAdmin", "Guest"}


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------- datetime
def now_wall():
    return datetime.now(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 422, "invalid datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------- rounding
def round_half_up(cents, rate):
    """round_half_up(cents * rate) -> int cents."""
    return int((Decimal(cents) * Decimal(str(rate))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- envelope
def _rand_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _rand_id(), "api_request_timestamp": fmt_dt(now_wall())}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def err_response(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------- auth
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this endpoint")


# ---------------------------------------------------------------- body / validation
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 422, "body must be an object")
    return data


def require_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_VALIDATION", 422, f"missing required field: {name}")
    return body[name]


def as_str(v, name):
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be a non-empty string")
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be an integer")
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be a boolean")
    return v


def as_number(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be a number")
    return v


def as_enum(v, name, members):
    if v not in members:
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be one of {sorted(members)}")
    return v


def paginate_params():
    args = request.args

    def parse_int(nm, default):
        raw = args.get(nm)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, f"{nm} must be an integer")

    limit = parse_int("limit", 10)
    offset = parse_int("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    """items: full filtered list already sorted. Returns (page, pagination_meta)."""
    limit, offset = paginate_params()
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
