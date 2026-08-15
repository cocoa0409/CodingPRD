"""Core infrastructure: in-memory store, logical clock, envelope, errors, helpers."""
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process start — no persistence)
# ---------------------------------------------------------------------------
DB = {
    "shops": {},
    "clients": {},
    "design_packages": {},
    "takeoffs": {},
    "takeoff_lines": {},
    "bids": {},
    "productions": {},
    "engineering_reviews": {},
    "finish_samples": {},
    "change_orders": {},
    "bay_reservations": {},
    "stock_items": {},
    "transport_plans": {},
}

# Logical clock: server default is normatively 2026-08-01T00:00:00Z
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}
SEQ = {"n": 0}

ROLES = [
    "ShopAdmin", "Estimator", "ShopForeman", "StaffEngineer",
    "PaintCharge", "ClientPM", "TransportCoordinator",
]
ALL_ROLES = set(ROLES)

COND_FACTOR_BP = {"A": 6000, "B": 4000, "C": 2500}
ROM_RATE_CENTS_PER_SQFT = {"A_SIMPLE": 9000, "B_STANDARD": 14000, "C_COMPLEX": 22000}
URGENCY_WINDOW_DAYS = 28
URGENCY_MULTIPLIER_BP = 12500
VOLUME_TIER_MIN_CENTS = 500000
VOLUME_TIER_DISCOUNT_BP = 500
RUSH_PER_DAY_BP = 500
RUSH_CAP_BP = 3000
REWORK_BP = 12000
SF_STATIC_MIN = Decimal("1.50")
SF_DYNAMIC_MIN = Decimal("2.00")
COMMITTED_STATUSES = ("SCHEDULED", "IN_BUILD", "ON_HOLD")
OUTSTANDING_STATUSES = ("SCHEDULED", "IN_BUILD", "ON_HOLD", "BUILT", "LOADED_IN", "STRUCK")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def verr(message):
    return ApiError("ERR_VALIDATION", 400, message)


def not_found(message="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, message)


def invalid_state(message="Invalid state for requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now():
    return CLOCK["now"]


def parse_dt(value, name):
    if not isinstance(value, str):
        raise verr(f"{name} must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        raise verr(f"{name} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Rounding helpers (round half-up, per PRD §2.10)
# ---------------------------------------------------------------------------
def rhu_cents(x):
    """Round a Decimal to integer cents, half-up."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(x):
    """Round a Decimal to two decimal places, half-up."""
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------
def mint():
    SEQ["n"] += 1
    return {
        "id": str(uuid.uuid4()),
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": SEQ["n"],
    }


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now()


def pub(value):
    """Public serializer: strip internal fields, convert datetimes/Decimals."""
    if isinstance(value, dict):
        return {k: pub(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [pub(v) for v in value]
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def get_or_404(collection, entity_id, message="Resource not found"):
    entity = DB[collection].get(entity_id)
    if entity is None:
        raise not_found(message)
    return entity


# ---------------------------------------------------------------------------
# Response envelope (§1.0 / PRD §2.2)
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": iso(now()),
    }


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": pub(data)}
    return jsonify(body), code


def ok_list(items, pagination):
    body = {"meta": _meta(), "response_type": "array", "data": [pub(i) for i in items]}
    body["meta"].update(pagination)
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# Auth (PRD §2.1)
# ---------------------------------------------------------------------------
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED", 401,
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return uid, role


def need_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role is not permitted for this endpoint")


def not_own(message="Resource belongs to a different client"):
    return ApiError("ERR_NOT_OWN_RESOURCE", 403, message)


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------
def body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    try:
        data = json.loads(raw, parse_float=Decimal)
    except Exception:
        raise verr("Request body is not valid JSON")
    if not isinstance(data, dict):
        raise verr("Request body must be a JSON object")
    return data


def check_unknown(data, allowed):
    for key in data:
        if key not in allowed:
            raise verr(f"Unknown field: {key}")


def req(data, name):
    if name not in data or data[name] is None:
        raise verr(f"Missing required field: {name}")
    return data[name]


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise verr(f"{name} must be an integer")
    return value


def as_str(value, name):
    if not isinstance(value, str):
        raise verr(f"{name} must be a string")
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise verr(f"{name} must be a boolean")
    return value


def as_enum(value, name, choices):
    if not isinstance(value, str) or value not in choices:
        raise verr(f"{name} must be one of {sorted(choices)}")
    return value


def as_load(value, name):
    """Positive number with up to two decimal places (engineering loads)."""
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise verr(f"{name} must be a number")
    d = Decimal(value)
    if d <= 0:
        raise verr(f"{name} must be greater than 0")
    if -d.as_tuple().exponent > 2:
        raise verr(f"{name} supports up to two decimal places")
    return d


def opt_int(data, name):
    if name in data and data[name] is not None:
        return as_int(data[name], name)
    return None


def opt_str(data, name):
    if name in data and data[name] is not None:
        return as_str(data[name], name)
    return None


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit/offset, defaults 10/0, min 1, max 100
# ---------------------------------------------------------------------------
def paginate(items):
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise verr("limit must be an integer")
        if limit < 1 or limit > 100:
            raise verr("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise verr("offset must be an integer")
        if offset < 0:
            raise verr("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


def list_response(items):
    page, meta_fields = paginate(items)
    return ok_list(page, meta_fields)


# ---------------------------------------------------------------------------
# Aggregate recomputation (touch only when a value actually changes)
# ---------------------------------------------------------------------------
def recompute_capacity(shop):
    committed = sum(
        p["committed_crew_hours"]
        for p in DB["productions"].values()
        if p["shop_id"] == shop["id"] and p["status"] in COMMITTED_STATUSES
    )
    denom = shop["weekly_crew_hours_capacity"] * shop["horizon_weeks"]
    ratio = rhu_cents(Decimal(committed) * 10000 / Decimal(denom))
    if ratio >= 10000:
        posture = "SATURATED"
    elif ratio >= 8000:
        posture = "TIGHT"
    else:
        posture = "OPEN"
    if (shop["committed_crew_hours"] != committed
            or shop["capacity_ratio_bp"] != ratio
            or shop["posture"] != posture):
        shop["committed_crew_hours"] = committed
        shop["capacity_ratio_bp"] = ratio
        shop["posture"] = posture
        touch(shop)


def recompute_inventory(shop):
    inv = sum(
        item["reuse_value_cents"]
        for item in DB["stock_items"].values()
        if item["shop_id"] == shop["id"]
    )
    if shop["inventory_value_cents"] != inv:
        shop["inventory_value_cents"] = inv
        touch(shop)


def recompute_client(client):
    outstanding = sum(
        p["current_price_cents"]
        for p in DB["productions"].values()
        if p["client_id"] == client["id"] and p["status"] in OUTSTANDING_STATUSES
    )
    if client["outstanding_cents"] != outstanding:
        client["outstanding_cents"] = outstanding
        touch(client)


def stock_refresh(item):
    item["reuse_unit_cost_cents"] = rhu_cents(
        Decimal(item["replacement_cost_cents"]) * COND_FACTOR_BP[item["condition_grade"]] / 10000
    )
    item["reuse_value_cents"] = item["quantity_on_hand"] * item["reuse_unit_cost_cents"]
    item["replacement_value_cents"] = item["quantity_on_hand"] * item["replacement_cost_cents"]
    item["status"] = "ACTIVE" if item["quantity_on_hand"] > 0 else "DEPLETED"


def recompute_takeoff_subtotal(takeoff):
    takeoff["materials_subtotal_cents"] = sum(
        line["line_total_cents"]
        for line in DB["takeoff_lines"].values()
        if line["takeoff_id"] == takeoff["id"]
    )


# ---------------------------------------------------------------------------
# Calculations (§1.3)
# ---------------------------------------------------------------------------
def compute_sf(scope, design_load, member_capacity, impact_factor_bp):
    sf_static = rhu2(member_capacity / design_load)
    sf_dynamic = None
    if scope == "AUTOMATION":
        effective_load = rhu2(design_load * impact_factor_bp / 10000)
        sf_dynamic = rhu2(member_capacity / effective_load)
    return sf_static, sf_dynamic


def price_bid_detailed(shop, takeoff):
    lines = [l for l in DB["takeoff_lines"].values() if l["takeoff_id"] == takeoff["id"]]
    gross = sum(l["line_total_cents"] for l in lines)
    tier_bp = VOLUME_TIER_DISCOUNT_BP if gross >= VOLUME_TIER_MIN_CENTS else 0
    discounted = rhu_cents(Decimal(gross) * (10000 - tier_bp) / 10000)
    labor = takeoff["labor_hours_est"] * shop["labor_rate_cents_per_hour"]
    base = discounted + labor
    overhead = rhu_cents(Decimal(base) * shop["overhead_pct_bp"] / 10000)
    margin = rhu_cents(Decimal(base + overhead) * shop["margin_pct_bp"] / 10000)
    return base + overhead + margin


def price_bid_rom(package, floor_area_sqft, complexity_class):
    days_until_load_in = (package["load_in_at"] - now()).days
    urgency_bp = URGENCY_MULTIPLIER_BP if days_until_load_in <= URGENCY_WINDOW_DAYS else 10000
    return rhu_cents(
        Decimal(floor_area_sqft) * ROM_RATE_CENTS_PER_SQFT[complexity_class] * urgency_bp / 10000
    )


def price_change_order(shop, production, delta_materials, delta_hours, delta_days):
    mult_bp = (shop["overtime_multiplier_bp"]
               if shop["posture"] in ("TIGHT", "SATURATED") else 10000)
    labor_magnitude = rhu_cents(
        Decimal(abs(delta_hours)) * shop["labor_rate_cents_per_hour"] * mult_bp / 10000
    )
    labor_component = labor_magnitude if delta_hours >= 0 else -labor_magnitude
    rush_component = 0
    if delta_days < 0:
        rush_bp = min(RUSH_CAP_BP, RUSH_PER_DAY_BP * abs(delta_days))
        if labor_component > 0:
            rush_component = rhu_cents(Decimal(labor_component) * rush_bp / 10000)
    rework_bp = REWORK_BP if production["status"] in ("BUILT", "LOADED_IN") else 10000
    materials_component = rhu_cents(
        Decimal(delta_materials) * (10000 + shop["overhead_pct_bp"]) * rework_bp
        / Decimal(100000000)
    )
    return materials_component + labor_component + rush_component


# ---------------------------------------------------------------------------
# Shared lookups
# ---------------------------------------------------------------------------
def client_of(bid_or_production):
    return DB["clients"].get(bid_or_production["client_id"])


def shop_of_client(client):
    return DB["shops"].get(client["shop_id"])


def current_package_for(client_id, show_title):
    for pkg in DB["design_packages"].values():
        if (pkg["client_id"] == client_id and pkg["show_title"] == show_title
                and pkg["status"] == "CURRENT"):
            return pkg
    return None


def find_stock_item(shop_id, material_code, condition_grade):
    for item in DB["stock_items"].values():
        if (item["shop_id"] == shop_id and item["material_code"] == material_code
                and item["condition_grade"] == condition_grade):
            return item
    return None


def overlaps(start_a, end_a, start_b, end_b):
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end)."""
    return start_a < end_b and start_b < end_a
