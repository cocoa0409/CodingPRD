"""Core: in-memory store, response envelope, auth, errors, helpers, calculations.

All structural names (headers, envelope fields, error ids, pagination params)
are taken from PRD.md / SCAFFOLD.yaml for task_1032 (Outdoor & Camping Co-op).
"""
import math
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

# ---------------------------------------------------------------------------
# Constants (from PRD §3 / SCAFFOLD calculations)
# ---------------------------------------------------------------------------
MULTI_DAY_THRESHOLD = 7           # days
MULTI_DAY_DISCOUNT_PCT = Decimal("0.15")
MEMBER_DISCOUNT_PCT = {"BASIC": Decimal("0.00"), "PREMIER": Decimal("0.10")}
DAMAGE_WAIVER_PCT = Decimal("0.10")
LATE_FEE_MULTIPLIER = Decimal("1.5")
SERVICE_BUFFER_HOURS = 24
LOYALTY_CENTS_PER_POINT = 100
INSTANT_CREDIT_PCT = Decimal("0.40")
CONSIGNMENT_MEMBER_PCT = Decimal("0.65")
CHECKIN_LOYALTY_POINTS = 5

DEFAULT_CLOCK = "2026-07-01T00:00:00Z"

ROLES = ("Member", "StoreStaff", "Public")

# ---------------------------------------------------------------------------
# Error catalog (id -> http status) from PRD §5 / SCAFFOLD §1.6
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_GEAR_SKU_NOT_FOUND": 404,
    "ERR_GEAR_UNIT_NOT_FOUND": 404,
    "ERR_RENTAL_NOT_FOUND": 404,
    "ERR_SALES_ORDER_NOT_FOUND": 404,
    "ERR_TRADE_IN_NOT_FOUND": 404,
    "ERR_CLASS_TRIP_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_PERMIT_ALLOCATION_NOT_FOUND": 404,
    "ERR_PERMIT_PASS_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_MEMBERSHIP_INACTIVE": 403,
    "ERR_UNIT_NOT_READY": 409,
    "ERR_UNIT_UNAVAILABLE": 409,
    "ERR_UNIT_NOT_RENTABLE": 422,
    "ERR_TRIP_NOT_SCHEDULED": 409,
    "ERR_MEMBER_SCHEDULE_CONFLICT": 409,
    "ERR_OUTSIDE_SEASON": 422,
    "ERR_QUOTA_EXHAUSTED": 409,
    "ERR_INSUFFICIENT_STORE_CREDIT": 402,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_OFFER_RESPONSE": 409,
    "ERR_ORDER_NOT_PAID": 409,
}

NOT_FOUND_FOR = {
    "members": "ERR_MEMBER_NOT_FOUND",
    "gear_skus": "ERR_GEAR_SKU_NOT_FOUND",
    "gear_units": "ERR_GEAR_UNIT_NOT_FOUND",
    "rentals": "ERR_RENTAL_NOT_FOUND",
    "orders": "ERR_SALES_ORDER_NOT_FOUND",
    "trade_ins": "ERR_TRADE_IN_NOT_FOUND",
    "class_trips": "ERR_CLASS_TRIP_NOT_FOUND",
    "bookings": "ERR_BOOKING_NOT_FOUND",
    "permit_allocations": "ERR_PERMIT_ALLOCATION_NOT_FOUND",
    "permit_passes": "ERR_PERMIT_PASS_NOT_FOUND",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP[error_id]
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory store (fresh on every process boot; no seeding)
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.members = {}
        self.gear_skus = {}
        self.gear_units = {}
        self.rentals = {}
        self.orders = {}
        self.trade_ins = {}
        self.class_trips = {}
        self.bookings = {}
        self.permit_allocations = {}
        self.permit_passes = {}
        self._seq = 0
        self.clock = parse_iso(DEFAULT_CLOCK)

    def next_seq(self):
        self._seq += 1
        return self._seq


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str) or not value:
        raise ValueError("bad datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_from_dt(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Wall-clock ISO-8601 UTC timestamp with three fractional digits."""
    return iso_from_dt(datetime.now(timezone.utc))


def days_ceil(seconds):
    return math.ceil(seconds / 86400.0)


# Instantiate the store now that time helpers are defined.
db = DB()


# ---------------------------------------------------------------------------
# Rounding (round-half-up to whole cents)
# ---------------------------------------------------------------------------
def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Common fields / serialization
# ---------------------------------------------------------------------------
def new_common():
    return {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def _make_meta(pagination=None):
    rid = "req_" + "".join(
        random.choices(string.ascii_letters + string.digits, k=20)
    )
    meta = {"api_request_id": rid, "api_request_timestamp": now_iso()}
    if pagination:
        meta.update(pagination)
    return meta


def ok(data, status=200, is_array=False, pagination=None):
    body = {
        "meta": _make_meta(pagination),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, message):
    body = {
        "meta": _make_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), ERROR_HTTP[error_id]


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", f"'{field}' is required and must be a non-empty string")
    return v


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", f"'{field}' must be a non-empty string")
    return v


def req_int(data, field, min_value=None):
    v = data.get(field)
    if not _is_int(v):
        raise ApiError("ERR_VALIDATION", f"'{field}' is required and must be an integer")
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", f"'{field}' must be >= {min_value}")
    return v


def opt_int(data, field, default, min_value=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not _is_int(v):
        raise ApiError("ERR_VALIDATION", f"'{field}' must be an integer")
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", f"'{field}' must be >= {min_value}")
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", f"'{field}' is required and must be a boolean")
    return v


def opt_bool(data, field, default):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", f"'{field}' must be a boolean")
    return v


def req_enum(data, field, choices):
    v = data.get(field)
    if v not in choices:
        raise ApiError("ERR_VALIDATION", f"'{field}' must be one of {sorted(choices)}")
    return v


def opt_enum(data, field, choices, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if v not in choices:
        raise ApiError("ERR_VALIDATION", f"'{field}' must be one of {sorted(choices)}")
    return v


def req_datetime(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v:
        raise ApiError("ERR_VALIDATION", f"'{field}' is required and must be an ISO-8601 datetime")
    try:
        parse_iso(v)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", f"'{field}' must be a valid ISO-8601 datetime")
    return v


# ---------------------------------------------------------------------------
# Auth / RBAC (PRD §2.1, §2.10)
# ---------------------------------------------------------------------------
def authenticate():
    """Return (user_id, role) enforcing header presence/recognition."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unrecognized authentication headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this operation")


def require_owner(role, uid, member_id):
    """entity_backed Member may act only on resources whose member_id == uid."""
    if role == "Member" and member_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", "Members may act only on their own resources")


# ---------------------------------------------------------------------------
# Existence helpers (left-to-right, specific 404)
# ---------------------------------------------------------------------------
def fetch(collection_name, entity_id):
    coll = getattr(db, collection_name)
    ent = coll.get(entity_id)
    if ent is None:
        raise ApiError(NOT_FOUND_FOR[collection_name],
                       f"{collection_name[:-1]} '{entity_id}' not found")
    return ent


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def read_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "'limit' must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "'offset' must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    """items: full filtered+sorted list of entity dicts. Returns (page, meta)."""
    limit, offset = read_pagination()
    total = len(items)
    page = items[offset: offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [serialize(e) for e in page], meta


def sorted_by_created(entities):
    return sorted(entities, key=lambda e: (e["created_at"], e["_seq"]))


# ---------------------------------------------------------------------------
# Member balance helpers (never negative for wallet / loyalty)
# ---------------------------------------------------------------------------
def credit_wallet(member, amount):
    member["store_credit_cents"] = max(0, member["store_credit_cents"] + amount)
    touch(member)


def add_loyalty(member, amount):
    member["loyalty_points_balance"] = max(0, member["loyalty_points_balance"] + amount)
    touch(member)


def add_spend(member, amount):
    member["lifetime_eligible_spend_cents"] = member["lifetime_eligible_spend_cents"] + amount
    touch(member)


def reconcile_trip(trip):
    """Recompute derived seat counts from the trip's bookings (no version bump)."""
    bks = [b for b in db.bookings.values() if b["class_trip_id"] == trip["id"]]
    reserved = sum(1 for b in bks if b["status"] in ("BOOKED", "CHECKED_IN"))
    waitlist = sum(1 for b in bks if b["status"] == "WAITLISTED")
    trip["seats_reserved"] = reserved
    trip["seats_available"] = max(0, trip["capacity"] - reserved)
    trip["waitlist_count"] = waitlist
