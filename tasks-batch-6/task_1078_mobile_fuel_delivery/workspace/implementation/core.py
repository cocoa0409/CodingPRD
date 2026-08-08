"""Cross-cutting helpers: error type, response envelope, auth, pagination,
datetime handling, rounding, price selection, and serializers."""
import random
import string
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

import store
from store import DB, UTC

# ---------------------------------------------------------------------------
# Error catalogue (error_id -> http status)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_VALIDATION": 400,
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_NOT_FOUND": 404,
    "ERR_FLEET_ACCOUNT_NOT_FOUND": 404,
    "ERR_VEHICLE_NOT_FOUND": 404,
    "ERR_TRUCK_NOT_FOUND": 404,
    "ERR_COMPARTMENT_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_VEHICLE_SUSPENDED": 409,
    "ERR_MEMBERSHIP_NOT_ACTIVE": 409,
    "ERR_INVALID_MEMBERSHIP_STATE": 409,
    "ERR_FLEET_ACCOUNT_SUSPENDED": 409,
    "ERR_TRUCK_UNAVAILABLE": 409,
    "ERR_INVALID_ORDER_STATE": 409,
    "ERR_INVALID_ROUTE_STATE": 409,
    "ERR_FLEET_ACCOUNT_HAS_ACTIVE_ORDERS": 409,
    "ERR_FUEL_TYPE_NOT_ALLOWED": 422,
    "ERR_ADDON_NOT_ALLOWED": 422,
    "ERR_NO_FUEL_PRICE_AVAILABLE": 422,
    "ERR_ROUTE_ZONE_MISMATCH": 422,
    "ERR_CUSTOMER_NOT_FLEET": 422,
    "ERR_EXCEEDS_TANK_CAPACITY": 422,
    "ERR_DISPENSE_EXCEEDS_REQUESTED": 422,
    "ERR_TRUCK_ROUTE_OVERLAP": 409,
    "ERR_VEHICLE_WINDOW_CONFLICT": 409,
    "ERR_ROUTE_AT_CAPACITY": 409,
    "ERR_INSUFFICIENT_COMPARTMENT_FUEL": 409,
    "ERR_COMPARTMENT_OVERFILL": 409,
    "ERR_VEHICLE_BUDGET_EXCEEDED": 402,
    "ERR_FLEET_BUDGET_EXCEEDED": 402,
    "ERR_STALE_FLEET_ACCOUNT_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    if not isinstance(value, str) or not value:
        raise ApiError("ERR_VALIDATION", "Invalid datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "Invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Rounding / money
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value to a whole integer, half away from zero."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money_mul(gallons, price_cents):
    """round_half_up(gallons * price_cents) -> int cents."""
    product = Decimal(str(gallons)) * Decimal(str(price_cents))
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def g1(x):
    """Round a gallon quantity to one decimal place (exact bookkeeping)."""
    return round(float(x) + 0.0, 1)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(UTC)),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, total, limit, offset):
    return ok(
        items,
        status=200,
        response_type="array",
        meta_extra={
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(items)) < total,
        },
    )


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
def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in store.ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "Missing or invalid user context header")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s not permitted" % role)


def deny():
    raise ApiError("ERR_UNAUTHORIZED", "Not permitted for this resource")


# ---------------------------------------------------------------------------
# Body / field parsing
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PATCH", "PUT"):
        if request.data:
            try:
                data = request.get_json(force=True, silent=True)
            except Exception:
                raise ApiError("ERR_VALIDATION", "Malformed JSON body")
            if data is None:
                raise ApiError("ERR_VALIDATION", "Malformed JSON body")
            if not isinstance(data, dict):
                raise ApiError("ERR_VALIDATION", "Body must be an object")
            return data
        return {}
    return {}


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise ApiError("ERR_VALIDATION", "Missing required field: %s" % n)


def check_enum(value, allowed, name):
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", "Invalid %s: %s" % (name, value))


def as_int(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", "%s must be >= %s" % (name, minimum))
    return value


def as_number(value, name, gt=None, ge=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_VALIDATION", "%s must be a number" % name)
    v = float(value)
    if gt is not None and not v > gt:
        raise ApiError("ERR_VALIDATION", "%s must be > %s" % (name, gt))
    if ge is not None and not v >= ge:
        raise ApiError("ERR_VALIDATION", "%s must be >= %s" % (name, ge))
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", "%s must be a boolean" % name)
    return value


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    """items: list already sorted. Returns (page, total, limit, offset)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, total, limit, offset


def sorted_records(collection):
    return sorted(collection.values(), key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Common entity scaffolding
# ---------------------------------------------------------------------------
def base_record(with_version=True):
    ts = store.now()
    rec = {"id": store.new_id(), "created_at": ts, "_seq": DB.next_seq()}
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump updated_at/version. Within a single request a given record is
    version-bumped at most once (a cascade that mutates one resource several
    times still counts as one logical mutation)."""
    from flask import g
    rec["updated_at"] = store.now()
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    key = id(rec)
    if key not in touched:
        touched.add(key)
        rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Fuel price selection (PRD §3.3)
# ---------------------------------------------------------------------------
def select_fuel_price(fuel_type, zone):
    clock = store.now()
    candidates = [
        p for p in DB.fuel_prices.values()
        if p["fuel_type"] == fuel_type and p["zone"] == zone
        and p["effective_date"] <= clock
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["effective_date"], p["_seq"]), reverse=True)
    return candidates[0]["price_per_gallon_cents"]
