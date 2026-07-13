"""Core: in-memory store, logical clock, envelope, errors, auth, calculations."""
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = ("PropertyManager", "CorporateAdmin", "Employee")
DAYS_PER_MONTH = 30
MIN_LEASE_TERM_DAYS = 30
TAX_EXEMPT_THRESHOLD_DAYS = 30
TURNOVER_BUFFER_DAYS = 1

CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "corporate_accounts",
    "rate_plans",
    "units",
    "master_leases",
    "employees",
    "stays",
    "housekeeping_visits",
    "damage_charges",
    "invoices",
    "turnovers",
)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.clock = CLOCK_DEFAULT
        self.seq = 0
        self.data = {c: {} for c in COLLECTIONS}

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def now_iso():
    return fmt_ts(db.clock)


def parse_dt(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_days(start_dt, end_dt):
    return int((end_dt - start_dt).total_seconds() // 86400)


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def gen_id():
    return str(uuid.uuid4())


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def create(collection, fields):
    ts = now_iso()
    entity = dict(fields)
    entity["id"] = gen_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    db.data[collection][entity["id"]] = entity
    return entity


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def get(collection, entity_id):
    return db.data[collection].get(entity_id)


def all_of(collection):
    return sorted(db.data[collection].values(), key=lambda e: e["_seq"])


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def error_body(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def auth(allowed_roles):
    uid, role = authenticate()
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return uid, role


# ---------------------------------------------------------------------------
# Body / pagination
# ---------------------------------------------------------------------------
def get_body():
    if request.data:
        body = request.get_json(silent=True)
        if body is None:
            raise err("ERR_VALIDATION", 400, "Malformed JSON body")
        if not isinstance(body, dict):
            raise err("ERR_VALIDATION", 400, "Body must be a JSON object")
        return body
    return {}


def require_fields(body, names):
    for name in names:
        if body.get(name) is None:
            raise err("ERR_VALIDATION", 400, "Missing required field: {}".format(name))


def require_int(body, name, minimum=None, gt=None):
    val = body.get(name)
    if not isinstance(val, int) or isinstance(val, bool):
        raise err("ERR_VALIDATION", 400, "Field {} must be an integer".format(name))
    if minimum is not None and val < minimum:
        raise err("ERR_VALIDATION", 400, "Field {} must be >= {}".format(name, minimum))
    if gt is not None and val <= gt:
        raise err("ERR_VALIDATION", 400, "Field {} must be > {}".format(name, gt))
    return val


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_PAGINATION_INVALID", 400, "limit out of range [1,100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", 400, "offset must be an integer")
        if offset < 0:
            raise err("ERR_PAGINATION_INVALID", 400, "offset must be >= 0")
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset: offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


# ---------------------------------------------------------------------------
# Rounding / calculations
# ---------------------------------------------------------------------------
def rhu(numerator, denominator=1):
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate_subtotal_cents(rate_plan, nights):
    full_months = nights // DAYS_PER_MONTH
    remainder = nights % DAYS_PER_MONTH
    line_rent_full = rhu(rate_plan["monthly_rate_cents"] * full_months)
    line_util_full = rhu(rate_plan["utility_monthly_cents"] * full_months)
    line_rent_partial = rhu(rate_plan["monthly_rate_cents"] * remainder, DAYS_PER_MONTH)
    line_util_partial = rhu(rate_plan["utility_monthly_cents"] * remainder, DAYS_PER_MONTH)
    return line_rent_full + line_util_full + line_rent_partial + line_util_partial


def occupancy_tax_cents(rate_plan, nights, subtotal):
    if nights >= TAX_EXEMPT_THRESHOLD_DAYS:
        return 0
    return rhu(subtotal * rate_plan["occupancy_tax_rate_bps"], 10000)


# ---------------------------------------------------------------------------
# Derived-field computation (master lease capacity, stay deposit ledger)
# ---------------------------------------------------------------------------
def lease_capacity(lease):
    consumed = sum(
        1
        for s in db.data["stays"].values()
        if s["master_lease_id"] == lease["id"] and s["status"] in ("RESERVED", "ACTIVE")
    )
    free = max(0, lease["committed_units"] - consumed)
    return consumed, free


def recompute_lease(lease):
    consumed, free = lease_capacity(lease)
    if lease.get("units_consumed") != consumed or lease.get("units_free") != free:
        lease["units_consumed"] = consumed
        lease["units_free"] = free
        touch(lease)


def stay_deposit(stay):
    charged = sum(
        dc["amount_cents"]
        for dc in db.data["damage_charges"].values()
        if dc["stay_id"] == stay["id"] and dc["status"] == "CHARGED"
    )
    refundable = max(0, stay["deposit_held_cents"] - charged)
    return charged, refundable


def find_invoice_for_stay(stay_id):
    for inv in all_of("invoices"):
        if inv["stay_id"] == stay_id:
            return inv
    return None


def recompute_invoice_settlement(stay):
    inv = find_invoice_for_stay(stay["id"])
    if inv is not None and inv["invoice_kind"] == "FINAL":
        inv["damage_total_cents"] = stay["deposit_charged_cents"]
        inv["total_settlement_cents"] = inv["amount_due_cents"] + inv["damage_total_cents"]
        inv["deposit_refund_cents"] = max(0, stay["deposit_held_cents"] - inv["damage_total_cents"])
        touch(inv)


def recompute_stay_deposit(stay):
    charged, refundable = stay_deposit(stay)
    if stay.get("deposit_charged_cents") != charged or stay.get("deposit_refundable_cents") != refundable:
        stay["deposit_charged_cents"] = charged
        stay["deposit_refundable_cents"] = refundable
        touch(stay)
    recompute_invoice_settlement(stay)


# ---------------------------------------------------------------------------
# Serialization with live-computed derived fields
# ---------------------------------------------------------------------------
def serialize(collection, entity):
    data = public(entity)
    if collection == "master_leases":
        consumed, free = lease_capacity(entity)
        data["units_consumed"] = consumed
        data["units_free"] = free
    elif collection == "stays":
        charged, refundable = stay_deposit(entity)
        data["deposit_charged_cents"] = charged
        data["deposit_refundable_cents"] = refundable
    return data
