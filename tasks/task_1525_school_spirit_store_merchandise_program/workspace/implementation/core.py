"""Core plumbing: in-memory store, errors, envelope, auth, logical clock.

PRD §2: envelope (meta/response_type/data), pagination (limit/offset,
total_count/has_more), common fields (id/created_at/updated_at/version),
logical clock defaulting to 2026-08-01T00:00:00Z, money as integer cents
with round-half-up.
"""
import random
import string
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from flask import jsonify, request

# ------------------------------------------------------------- error ids ----
ERR_AUTH = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_ROLE = "ERR_UNAUTHORIZED_ROLE"
ERR_PROGRAM_NF = "ERR_PROGRAM_NOT_FOUND"
ERR_VENDOR_NF = "ERR_VENDOR_NOT_FOUND"
ERR_DESIGN_NF = "ERR_DESIGN_NOT_FOUND"
ERR_VARIANT_NF = "ERR_VARIANT_NOT_FOUND"
ERR_DROP_NF = "ERR_DROP_NOT_FOUND"
ERR_PO_NF = "ERR_PO_NOT_FOUND"
ERR_CAMPAIGN_NF = "ERR_CAMPAIGN_NOT_FOUND"
ERR_PREORDER_NF = "ERR_PREORDER_NOT_FOUND"
ERR_EVENT_NF = "ERR_EVENT_NOT_FOUND"
ERR_ORDER_NF = "ERR_ORDER_NOT_FOUND"
ERR_EXCHANGE_NF = "ERR_EXCHANGE_NOT_FOUND"
ERR_ACCOUNT_NF = "ERR_ACCOUNT_NOT_FOUND"
ERR_RUN_NF = "ERR_ALLOCATION_RUN_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_PROGRAM_NOT_ACTIVE = "ERR_PROGRAM_NOT_ACTIVE"
ERR_PROGRAM_NOT_CLOSED = "ERR_PROGRAM_NOT_CLOSED"
ERR_INVALID_STATE = "ERR_INVALID_STATE_TRANSITION"
ERR_DESIGN_NOT_LICENSED = "ERR_DESIGN_NOT_LICENSED"
ERR_LICENSE_REVOKED = "ERR_LICENSE_REVOKED"
ERR_DROP_NOT_OPEN = "ERR_DROP_NOT_OPEN"
ERR_DROP_NOT_STARTED = "ERR_DROP_WINDOW_NOT_STARTED"
ERR_DROP_OVERLAP = "ERR_DROP_WINDOW_OVERLAP"
ERR_REGISTER_CONFLICT = "ERR_EVENT_REGISTER_CONFLICT"
ERR_EVENT_WINDOW_PASSED = "ERR_EVENT_WINDOW_PASSED"
ERR_DRAWER_NOT_OPEN = "ERR_DRAWER_NOT_OPEN"
ERR_VENDOR_NOT_APPROVED = "ERR_VENDOR_NOT_APPROVED"
ERR_CAMPAIGN_NOT_OPEN = "ERR_CAMPAIGN_NOT_OPEN"
ERR_CAMPAIGN_WINDOW_OPEN = "ERR_CAMPAIGN_WINDOW_STILL_OPEN"
ERR_DUP_CAMPAIGN = "ERR_DUPLICATE_ACTIVE_CAMPAIGN"
ERR_DUP_VARIANT = "ERR_DUPLICATE_VARIANT"
ERR_VARIANT_DESIGN_MISMATCH = "ERR_VARIANT_DESIGN_MISMATCH"
ERR_PREORDER_NOT_PAYABLE = "ERR_PREORDER_NOT_PAYABLE"
ERR_PREORDER_NOT_CANCELLABLE = "ERR_PREORDER_NOT_CANCELLABLE"
ERR_PICKUP_NOT_READY = "ERR_PICKUP_NOT_READY"
ERR_PICKUP_EXPIRED = "ERR_PICKUP_EXPIRED"
ERR_INSUFFICIENT_STOCK = "ERR_INSUFFICIENT_STOCK"
ERR_MIN_ORDER_QTY = "ERR_MIN_ORDER_QTY"
ERR_NO_ELIGIBLE_VENDOR = "ERR_NO_ELIGIBLE_VENDOR"
ERR_EXCHANGE_MISMATCH = "ERR_EXCHANGE_VARIANT_MISMATCH"
ERR_EXCHANGE_WINDOW_CLOSED = "ERR_EXCHANGE_WINDOW_CLOSED"
ERR_REFUND_EXCEEDS = "ERR_REFUND_EXCEEDS_PAID"
ERR_DEPOSIT_SHORTFALL = "ERR_DEPOSIT_SHORTFALL"
ERR_PAYMENT_MISMATCH = "ERR_PAYMENT_AMOUNT_MISMATCH"
ERR_ALLOCATION_EXCEEDS = "ERR_ALLOCATION_EXCEEDS_PROFIT"
ERR_UNRESOLVED = "ERR_UNRESOLVED_OPERATIONS"
ERR_PROFIT_NOT_ALLOCATED = "ERR_PROFIT_NOT_FULLY_ALLOCATED"
ERR_SEGREGATION = "ERR_SEGREGATION_OF_DUTIES"
ERR_STALE = "ERR_STALE_VERSION"

ROLES = ("ActivitiesDirector", "StoreManager", "LicensingCoordinator",
         "Treasurer", "StudentCashier", "Customer")
AD, SM, LC, TRE, SC, CUST = ROLES


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# ----------------------------------------------------------- in-memory db ---
# The store starts completely empty on every boot; nothing is seeded.
DB = {
    "programs": {},
    "vendors": {},
    "designs": {},
    "variants": {},
    "drops": {},
    "pos": {},
    "campaigns": {},
    "preorders": {},
    "events": {},
    "orders": {},
    "exchanges": {},
    "accounts": {},
    "runs": {},
}

# Logical clock (PRD §2.5): defaults to exactly 2026-08-01T00:00:00Z and
# never falls back to wall-clock time.
CLOCK = {"dt": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

_SEQ = [0]
_LAST_MS = [0]


def now_logical():
    return CLOCK["dt"]


def new_ts():
    """Monotonic ISO-8601 UTC timestamp with three fractional digits."""
    ms = time.time_ns() // 1_000_000
    if ms <= _LAST_MS[0]:
        ms = _LAST_MS[0] + 1
    _LAST_MS[0] = ms
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (ms % 1000)


def req_id():
    return "req_" + "".join(random.choice(string.ascii_letters + string.digits)
                            for _ in range(20))


def parse_dt(value):
    """Parse an ISO-8601 datetime; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ser_dt(dt):
    if dt is None:
        return None
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def rhu_decimal(dec):
    """Round-half-up a Decimal to integer cents."""
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu(num, den=1):
    """Round-half-up of num/den using exact decimal arithmetic."""
    return rhu_decimal(Decimal(str(num)) / Decimal(str(den)))


def floor_div_dec(num, den):
    return int((Decimal(str(num)) / Decimal(str(den))).to_integral_value(
        rounding=ROUND_FLOOR))


def dec(v):
    return Decimal(str(v))


# ------------------------------------------------------------ entity base ---
def new_entity(fields):
    _SEQ[0] += 1
    ts = new_ts()
    entity = dict(fields)
    entity["id"] = str(uuid.uuid4())
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = _SEQ[0]
    return entity


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = new_ts()


def pub(entity):
    out = {}
    for key, value in entity.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = ser_dt(value)
        elif isinstance(value, list):
            cleaned = []
            for item in value:
                if isinstance(item, dict):
                    cleaned.append({k: (ser_dt(v) if isinstance(v, datetime) else v)
                                    for k, v in item.items() if not k.startswith("_")})
                else:
                    cleaned.append(item)
            out[key] = cleaned
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------- envelope --
def success(data, code=200, rtype="object", pagination=None):
    meta = {"api_request_id": req_id(), "api_request_timestamp": new_ts()}
    if pagination:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": rtype, "data": data}), code


def error_response(error_id, status, message):
    body = {"meta": {"api_request_id": req_id(),
                     "api_request_timestamp": new_ts()},
            "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), status


def paginate(items):
    """limit/offset per PRD §2.3: default 10, min 1, max 100, offset >= 0."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "limit and offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    return page, {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": offset + len(page) < total}


def list_response(items, serializer):
    page, pagination = paginate(items)
    return success([serializer(e) for e in page], rtype="array",
                   pagination=pagination)


# -------------------------------------------------------------------- auth --
def auth():
    """Pipeline step 1: X-User-ID and X-User-Role present, role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_AUTH, 400,
                       "X-User-ID and X-User-Role headers are required and "
                       "the role must be recognized")
    return uid, role


def need_role(role, *allowed):
    """Pipeline step 2: role permitted for the endpoint."""
    if role not in allowed:
        raise ApiError(ERR_ROLE, 403,
                       "role %s is not permitted for this endpoint" % role)


# ------------------------------------------------------------------ bodies --
def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_fields(data, *names):
    for name in names:
        if data.get(name) is None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "missing required field: %s" % name)


def req_int(data, name, minimum=None):
    v = data.get(name)
    if not is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "field %s must be >= %d" % (name, minimum))
    return v


def req_pct(data, name):
    v = data.get(name)
    if not is_num(v) or v < 0 or v > 1:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "field %s must be a fraction between 0 and 1" % name)
    return v


def req_dt(data, name):
    v = data.get(name)
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "missing required field: %s" % name)
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "field %s must be an ISO-8601 datetime" % name)


def opt_int(data, name, default, minimum=None):
    v = data.get(name)
    if v is None:
        return default
    if not is_int(v) or (minimum is not None and v < minimum):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "field %s must be an integer >= %s" % (name, minimum))
    return v


# ------------------------------------------------------------ fetch helpers --
def fetch(store, key, err_id):
    entity = DB[store].get(key)
    if entity is None:
        raise ApiError(err_id, 404, "%s not found" % err_id)
    return entity


def fetch_scoped(store, key, err_id, program_id):
    """Body-FK rule (pipeline step 4): must exist and belong to the program."""
    entity = fetch(store, key, err_id)
    if program_id is not None and entity["program_id"] != program_id:
        raise ApiError(err_id, 404, "%s not found in this program" % err_id)
    return entity


def gate_active(program):
    if program["status"] != "ACTIVE":
        raise ApiError(ERR_PROGRAM_NOT_ACTIVE, 409,
                       "program must be ACTIVE for this write")


def gate_closed(program):
    if program["status"] != "CLOSED":
        raise ApiError(ERR_PROGRAM_NOT_CLOSED, 409,
                       "program must be CLOSED for this write")


# ------------------------------------------------------- computed helpers ---
def variant_sellable(v):
    program = DB["programs"].get(v["program_id"])
    design = DB["designs"].get(v["design_id"])
    if not program or program["status"] != "ACTIVE":
        return False
    if not design or design["status"] != "APPROVED":
        return False
    if v["drop_id"]:
        drop = DB["drops"].get(v["drop_id"])
        if not drop or drop["status"] != "OPEN":
            return False
    return True


def pub_variant(v):
    data = pub(v)
    available = v["on_hand_qty"] - v["reserved_online_qty"]
    data["available_qty"] = available
    data["low_stock"] = available <= v["reorder_point"]
    data["sellable"] = variant_sellable(v)
    return data


def campaign_units(campaign):
    """placed_units: PLACED/PAID/FULFILLED; paid_units: PAID/FULFILLED only."""
    placed = 0
    paid = 0
    for p in DB["preorders"].values():
        if p["campaign_id"] != campaign["id"]:
            continue
        if p["status"] in ("PLACED", "PAID", "FULFILLED"):
            placed += p["qty"]
        if p["status"] in ("PAID", "FULFILLED"):
            paid += p["qty"]
    return placed, paid


def pub_campaign(c):
    data = pub(c)
    placed, paid = campaign_units(c)
    data["placed_units"] = placed
    data["paid_units"] = paid
    return data


def cascade_campaign_cancel(campaign):
    """PAID preorders -> REFUNDED (full collected); PLACED -> CANCELLED."""
    for p in DB["preorders"].values():
        if p["campaign_id"] != campaign["id"]:
            continue
        if p["status"] == "PAID":
            p["status"] = "REFUNDED"
            p["refunded_cents"] = p["deposit_paid_cents"] + p["balance_paid_cents"]
            touch(p)
        elif p["status"] == "PLACED":
            p["status"] = "CANCELLED"
            touch(p)
