"""Shared infrastructure: in-memory store, logical clock, errors, envelope, auth."""
import uuid
import random
import string
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

# ---------------------------------------------------------------------------
# Constants (from PRD §3 / SCAFFOLD calculations)
# ---------------------------------------------------------------------------
VETTING_VALID_DAYS = 365          # not numerically pinned in spec; driven by clock in tests
OFFER_TTL_HOURS = 24              # not numerically pinned in spec; driven by clock in tests
TRAVEL_BUFFER_MINUTES = 30
BUNDLE_MIN_ADDONS = 3
BUNDLE_DISCOUNT_BPS = 1000
MAX_BUNDLE_DISCOUNT_CENTS = 5000
AFTER_HOURS_FLAT_CENTS = 4000
AFTER_HOURS_BPS = 1500
STANDARD_START_HOUR_UTC = 8
STANDARD_END_HOUR_UTC = 18
PLATFORM_COMMISSION_BPS = 2500
REDO_PENALTY_CENTS = 3000

CATEGORIES = {"TV_MOUNT", "APPLIANCE", "SMART_DEVICE"}

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.current = _CLOCK_DEFAULT

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt


clock = Clock()

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.retailers = {}
        self.service_zones = {}
        self.customers = {}
        self.pros = {}
        self.applications = {}
        self.install_tasks = {}
        self.addons = {}
        self.work_orders = {}
        self.assignments = {}
        self.parts = {}
        self.payouts = {}
        self.settlement_entries = {}
        self.ratings = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso_ms(dt):
    """Format an aware datetime as ISO8601 UTC with 3 fractional digits + Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO8601 string into an aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str) or not value:
        raise ValueError("not a datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def rhu(numerator, denominator):
    """round_half_up(numerator / denominator) -> int."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def rhu2(numerator, denominator):
    """round_half_up to 2 decimals -> float."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_RETAILER_NOT_FOUND": 404,
    "ERR_SERVICE_ZONE_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_PRO_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_INSTALL_TASK_NOT_FOUND": 404,
    "ERR_ADDON_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_PAYOUT_NOT_FOUND": 404,
    "ERR_SETTLEMENT_ENTRY_NOT_FOUND": 404,
    "ERR_RATING_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_INVALID_APPOINTMENT_WINDOW": 422,
    "ERR_RETAILER_SUSPENDED": 409,
    "ERR_ZONE_COVERAGE_INACTIVE": 409,
    "ERR_ADDON_CATEGORY_MISMATCH": 422,
    "ERR_NO_ELIGIBLE_PRO": 409,
    "ERR_PRO_NOT_APPROVED": 409,
    "ERR_VETTING_EXPIRED": 409,
    "ERR_PRO_SCHEDULE_CONFLICT": 409,
    "ERR_ZONE_CAPACITY_EXCEEDED": 409,
    "ERR_APPOINTMENT_NOT_STARTED": 422,
    "ERR_WARRANTY_EXPIRED": 422,
    "ERR_DUPLICATE_RATING": 409,
    "ERR_RATING_NOT_ALLOWED": 409,
    "ERR_STALE_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


def err(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(pagination=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def serialize(obj):
    if isinstance(obj, datetime):
        return iso_ms(obj)
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [serialize(v) for v in obj]
    return obj


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": serialize(data),
    }
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
VALID_ROLES = {"PlatformAdmin", "Retailer", "Pro", "Customer"}


def authenticate(allowed_roles):
    """Check headers present (401) then role permitted (403). Returns (uid, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header.")
    if role not in allowed_roles:
        err("ERR_UNAUTHORIZED", "Role not permitted for this operation.")
    return uid, role


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_entity(common=True, **fields):
    now = clock.now()
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": now,
    }
    ent.update(fields)
    if common:
        ent["updated_at"] = now
        ent["version"] = 1
    ent["_seq"] = db.next_seq()
    return ent


def touch(entity):
    if "version" in entity:
        entity["version"] += 1
        entity["updated_at"] = clock.now()


def get_or_404(collection, ident, error_id):
    ent = collection.get(ident)
    if ent is None:
        err(error_id)
    return ent


# ---------------------------------------------------------------------------
# Body / pagination parsing
# ---------------------------------------------------------------------------
def get_body():
    if request.data:
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None
    else:
        data = None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        err("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def require_fields(body, names):
    for n in names:
        if body.get(n) is None:
            err("ERR_VALIDATION", f"Missing required field: {n}")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def parse_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", "limit must be an integer.")
        if limit_v < 1 or limit_v > 100:
            err("ERR_VALIDATION", "limit out of range (1..100).")
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", "offset must be an integer.")
        if offset_v < 0:
            err("ERR_VALIDATION", "offset must be >= 0.")
    return limit_v, offset_v


def paginate(rows):
    """rows: list of entity dicts. Sort by created_at asc then _seq, apply page."""
    limit, offset = parse_pagination()
    ordered = sorted(rows, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, pagination
