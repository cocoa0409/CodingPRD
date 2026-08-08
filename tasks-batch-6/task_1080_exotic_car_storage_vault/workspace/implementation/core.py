"""Core: in-memory store, logical clock, envelope, auth, validation helpers."""
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify, g

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLES = {"Member", "VaultManager", "ConciergeTech", "BillingAdmin"}

# ---------------------------------------------------------------------------
# Constants (from PRD §3.9 / SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
CLIMATE_SURCHARGE_CENTS = 5000
SHOWCASE_SURCHARGE_CENTS = 12000
MAX_DISCOUNT_CENTS = 20000
TIER_DISCOUNT_PCT = {"BRONZE": "0.00", "SILVER": "0.05", "GOLD": "0.10", "PLATINUM": "0.20"}
PRORATION_DAYS_IN_MONTH = 30
LABOR_RATE_CENTS = 12000
SERVICE_BASE_CENTS = {"DETAIL": 15000, "START_ENGINE": 3000, "CHECKOUT": 5000, "CHECKIN": 5000, "FUEL": 4000}
TAX_RATE = "0.08"
DELIVERY_FLAT_CENTS = 25000
BATTERY_MIN_VOLTAGE = 12.4
OFFER_TTL_HOURS = 48
INVOICE_DUE_DAYS = 15
SUSPEND_GRACE_DAYS = 30
TIER_RANK = {"PLATINUM": 4, "GOLD": 3, "SILVER": 2, "BRONZE": 1}

CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.facilities = {}
        self.units = {}
        self.members = {}
        self.vehicles = {}
        self.cois = {}
        self.agreements = {}
        self.monitorings = {}
        self.service_orders = {}
        self.transporters = {}
        self.delivery_jobs = {}
        self.waitlist = {}
        self.inspections = {}
        self.invoices = {}
        self.payments = []          # list of {member_id, amount_cents}
        self._seq = 0
        self.clock = parse_iso(CLOCK_DEFAULT)

    def next_seq(self):
        self._seq += 1
        return self._seq


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO 8601 UTC string into an aware datetime (UTC)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Render an aware datetime as ISO 8601 UTC with three fractional digits + Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_clock():
    return db.clock


def clock_iso():
    return iso(db.clock)


def wall_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Singleton store (instantiated after parse_iso is defined).
db = Store()


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------
def rhu(value):
    """Round half up to whole integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def base_record():
    ts = db.clock
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    rec["updated_at"] = db.clock
    rec["version"] += 1


def common_out(rec):
    return {
        "id": rec["id"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": wall_iso(),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def success(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC helpers
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    g.user_id = uid
    g.role = role
    return uid, role


def require(*allowed):
    uid, role = authenticate()
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return uid, role


def check_owner(role, uid, owner_member_id):
    """Entity-backed Member may act only on resources it owns."""
    if role == "Member" and uid != owner_member_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Member does not own this resource")


# ---------------------------------------------------------------------------
# Body / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ApiError("ERR_INVALID_REQUEST", 422, "Body must be a JSON object")
        return data
    return {}


def _invalid(msg):
    raise ApiError("ERR_INVALID_REQUEST", 422, msg)


def req_str(body, field, allow_empty=True):
    if field not in body:
        _invalid(f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str):
        _invalid(f"Field {field} must be a string")
    if not allow_empty and v == "":
        _invalid(f"Field {field} must not be empty")
    return v


def req_int(body, field, minimum=None):
    if field not in body:
        _invalid(f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        _invalid(f"Field {field} must be >= {minimum}")
    return v


def req_num(body, field, minimum=None):
    if field not in body:
        _invalid(f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _invalid(f"Field {field} must be a number")
    if minimum is not None and v < minimum:
        _invalid(f"Field {field} must be >= {minimum}")
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        _invalid(f"Field {field} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        _invalid(f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_bool(body, field):
    if field not in body:
        _invalid(f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, bool):
        _invalid(f"Field {field} must be a boolean")
    return v


def opt_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        _invalid(f"Field {field} must be a boolean")
    return v


def opt_str(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        _invalid(f"Field {field} must be a string")
    return v


def opt_int(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        _invalid(f"Field {field} must be >= {minimum}")
    return v


def req_dt(body, field):
    if field not in body:
        _invalid(f"Missing required field: {field}")
    v = body[field]
    try:
        return parse_iso(v)
    except Exception:
        _invalid(f"Field {field} must be an ISO 8601 UTC datetime")


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return rec


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------
def paginate(items):
    """items: already-sorted list of serialized dicts. Returns (page, pagination_meta)."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sort_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def list_response(records, serializer):
    ordered = sort_created(records)
    serialized = [serializer(r) for r in ordered]
    page, meta = paginate(serialized)
    return success(page, response_type="array", status=200, pagination=meta)
