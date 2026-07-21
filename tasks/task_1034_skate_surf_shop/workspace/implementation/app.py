"""Skate & Surf Shop API — Python + Flask, in-memory only.

Every route traces to a PRD sentence. Storage is Python dicts keyed by id.
The store starts empty on every boot; no seeding.
"""
import os
import uuid
import random
import string
import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_ROLES = {"ShopManager", "BenchTech", "SalesAssociate", "Customer"}
ALL_ROLES = ["ShopManager", "BenchTech", "SalesAssociate", "Customer"]

PRODUCT_CATEGORIES = {
    "DECK", "TRUCKS", "WHEELS", "GRIP", "WAX",
    "COMPLETE", "SURFBOARD", "WETSUIT", "ACCESSORY",
}
DISCIPLINES = {"SURF", "SKATE"}
CONDITIONS = {"GOOD", "FAIR", "NEEDS_SERVICE"}
TRADE_MODES = {"TRADE_IN", "CONSIGNMENT"}
PAYOUT_CHOICES = {"CASH", "STORE_CREDIT"}
ENTRY_ROLES = {"TEAM_RIDER", "PUBLIC"}
LESSON_OUTCOMES = {"COMPLETED", "NO_SHOW"}

TIER_MULTIPLIER = {"BRONZE": Decimal("1.0"), "SILVER": Decimal("1.25"), "GOLD": Decimal("1.5")}
EVENT_MULTIPLIER = Decimal("2.0")
SILVER_THRESHOLD_CENTS = 50000
GOLD_THRESHOLD_CENTS = 100000

CASH_RATE = Decimal("0.50")
STORE_CREDIT_RATE = Decimal("0.70")
CONSIGNMENT_RATE = Decimal("0.60")
BUILD_LABOR_CENTS = 2500
BUILD_BUNDLE_FACTOR = Decimal("0.90")   # 1 - 0.10
TAX_RATE_FACTOR = Decimal("1.0725")     # 1 + 0.0725
LATE_FEE_PER_DAY_CENTS = 1000
SETUP_BUFFER = timedelta(minutes=15)

DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

ERR_HTTP = {
    "ERR_MISSING_AUTH_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_VALIDATION": 400,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_COACH_NOT_FOUND": 404,
    "ERR_RENTAL_ASSET_NOT_FOUND": 404,
    "ERR_LESSON_NOT_FOUND": 404,
    "ERR_RENTAL_NOT_FOUND": 404,
    "ERR_BOARD_BUILD_NOT_FOUND": 404,
    "ERR_SERVICE_TICKET_NOT_FOUND": 404,
    "ERR_TRADE_IN_NOT_FOUND": 404,
    "ERR_SPECIAL_ORDER_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_EVENT_ENTRY_NOT_FOUND": 404,
    "ERR_DUPLICATE_SKU": 409,
    "ERR_DUPLICATE_ASSET_TAG": 409,
    "ERR_LESSON_INVALID_STATE": 409,
    "ERR_RENTAL_INVALID_STATE": 409,
    "ERR_BUILD_INVALID_STATE": 409,
    "ERR_SERVICE_INVALID_STATE": 409,
    "ERR_TRADE_IN_INVALID_STATE": 409,
    "ERR_ORDER_INVALID_STATE": 409,
    "ERR_EVENT_INVALID_STATE": 409,
    "ERR_ENTRY_INVALID_STATE": 409,
    "ERR_COMPONENT_INCOMPATIBLE": 422,
    "ERR_COACH_UNAVAILABLE": 409,
    "ERR_ASSET_UNAVAILABLE": 409,
    "ERR_LESSON_NOT_SCHEDULED": 409,
    "ERR_EVENT_NOT_OPEN": 409,
    "ERR_EVENT_FULL": 409,
    "ERR_INSUFFICIENT_STOCK": 402,
    "ERR_INSUFFICIENT_POINTS": 402,
    "ERR_STALE_VERSION": 412,
}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "products": {},
    "customers": {},
    "coaches": {},
    "rental_assets": {},
    "lessons": {},
    "rentals": {},
    "board_builds": {},
    "service_tickets": {},
    "trade_ins": {},
    "special_orders": {},
    "events": {},
    "event_entries": {},
}
_STATE = {"clock": DEFAULT_CLOCK, "seq": 0}


def next_seq():
    _STATE["seq"] += 1
    return _STATE["seq"]


def clock_now():
    return _STATE["clock"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http = ERR_HTTP[error_id]
        self.message = message or error_id


@app.errorhandler(ApiError)
def handle_api_error(exc):
    body = {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.http


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    if not isinstance(value, str) or not value:
        raise ApiError("ERR_VALIDATION", "invalid datetime")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def build_meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def ser(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": build_meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_AUTH_CONTEXT", "missing or invalid auth context")
    return uid, role


def authz(allowed_roles):
    uid, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "role not permitted for this operation")
    return uid, role


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_entity(extra):
    now = clock_now()
    e = {
        "id": str(uuid.uuid4()),
        "created_at": fmt_ts(now),
        "updated_at": fmt_ts(now),
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(extra)
    return e


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = fmt_ts(clock_now())


def check_fk(collection, value, err_id):
    """Existence check for a present FK string. No-op when value absent."""
    if isinstance(value, str) and value:
        if value not in DB[collection]:
            raise ApiError(err_id)


def get_or_404(collection, ident, err_id):
    e = DB[collection].get(ident)
    if e is None:
        raise ApiError(err_id)
    return e


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------
def get_body():
    return request.get_json(silent=True) or {}


def v_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", "missing or invalid field: %s" % key)
    return v


def v_int(body, key, minv=None):
    v = body.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", "missing or invalid integer: %s" % key)
    if minv is not None and v < minv:
        raise ApiError("ERR_VALIDATION", "value out of range: %s" % key)
    return v


def v_opt_int(body, key, default, minv=None):
    if key not in body or body.get(key) is None:
        return default
    return v_int(body, key, minv)


def v_enum(body, key, choices):
    v = body.get(key)
    if v not in choices:
        raise ApiError("ERR_VALIDATION", "invalid enum: %s" % key)
    return v


def v_opt_enum(body, key, choices, default):
    if key not in body or body.get(key) is None:
        return default
    return v_enum(body, key, choices)


def v_opt_bool(body, key, default):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", "invalid boolean: %s" % key)
    return v


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def rhu(dec_value):
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_availability(product):
    product["available_qty"] = product["on_hand_qty"] - product["reserved_qty"]


def reconcile_tier(customer):
    ls = customer["lifetime_spend_cents"]
    if ls >= GOLD_THRESHOLD_CENTS:
        customer["tier"] = "GOLD"
    elif ls >= SILVER_THRESHOLD_CENTS:
        customer["tier"] = "SILVER"
    else:
        customer["tier"] = "BRONZE"


def accrue_loyalty(customer, amount_cents, is_event_bonus=False):
    """Tier snapshot is read BEFORE this txn's spend is applied. Single floor."""
    tier_at_time = customer["tier"]
    base_points = amount_cents // 100
    mult = TIER_MULTIPLIER[tier_at_time]
    if is_event_bonus:
        mult = mult * EVENT_MULTIPLIER
    earned = int((Decimal(base_points) * mult).to_integral_value(rounding=ROUND_FLOOR))
    customer["loyalty_points"] += earned
    customer["lifetime_spend_cents"] += amount_cents
    reconcile_tier(customer)
    return earned


def window_days(start_dt, end_dt):
    secs = (end_dt - start_dt).total_seconds()
    return int(math.ceil(secs / 86400.0))


# ---------------------------------------------------------------------------
# Pagination + listing
# ---------------------------------------------------------------------------
def paginate(items):
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
    has_more = (offset + len(page)) < total
    pagination = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return page, pagination


def list_collection(collection, filters=None):
    authz(ALL_ROLES)
    items = list(DB[collection].values())
    if filters:
        for field, value in filters.items():
            if value is not None:
                items = [e for e in items if e.get(field) == value]
    items.sort(key=lambda e: e["_seq"])
    page, pagination = paginate(items)
    return ok([ser(e) for e in page], 200, "array", pagination)


# ===========================================================================
# Health / root (readiness)
# ===========================================================================
@app.route("/", methods=["GET"])
def root():
    return ok({}, 200)


# ===========================================================================
# Products
# ===========================================================================
@app.route("/products", methods=["POST"])
def create_product():
    authz(["ShopManager"])
    b = get_body()
    sku = v_str(b, "sku")
    name = v_str(b, "name")
    category = v_enum(b, "category", PRODUCT_CATEGORIES)
    unit_price = v_int(b, "unit_price_cents", minv=0)
    rental_rate = v_opt_int(b, "rental_day_rate_cents", 0, minv=0)
    is_rentable = v_opt_bool(b, "is_rentable", False)
    for p in DB["products"].values():
        if p["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_SKU")
    e = new_entity({
        "sku": sku, "name": name, "category": category,
        "unit_price_cents": unit_price, "rental_day_rate_cents": rental_rate,
        "is_rentable": is_rentable, "on_hand_qty": 0, "reserved_qty": 0,
        "available_qty": 0, "status": "ACTIVE",
    })
    DB["products"][e["id"]] = e
    return ok(ser(e), 201)


@app.route("/products", methods=["GET"])
def list_products():
    return list_collection("products")


@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    authz(ALL_ROLES)
    return ok(ser(get_or_404("products", pid, "ERR_PRODUCT_NOT_FOUND")))


@app.route("/products/<pid>/inventory-adjustments", methods=["POST"])
def adjust_inventory(pid):
    authz(["ShopManager"])
    product = get_or_404("products", pid, "ERR_PRODUCT_NOT_FOUND")
    b = get_body()
    delta = v_int(b, "delta_on_hand")
    product["on_hand_qty"] += delta
    recompute_availability(product)
    touch(product)
    return ok(ser(product))


@app.route("/products/<pid>/discontinue", methods=["POST"])
def discontinue_product(pid):
    authz(["ShopManager"])
    product = get_or_404("products", pid, "ERR_PRODUCT_NOT_FOUND")
    if product["status"] != "ACTIVE":
        # No dedicated product-state error is defined in the catalogue.
        raise ApiError("ERR_VALIDATION", "product is not ACTIVE")
    product["status"] = "DISCONTINUED"
    touch(product)
    return ok(ser(product))


# ===========================================================================
# Customers
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    authz(["ShopManager", "SalesAssociate"])
    b = get_body()
    email = v_str(b, "email")
    full_name = v_str(b, "full_name")
    e = new_entity({
        "email": email, "full_name": full_name,
        "loyalty_points": 0, "lifetime_spend_cents": 0,
        "store_credit_cents": 0, "tier": "BRONZE", "status": "ACTIVE",
    })
    DB["customers"][e["id"]] = e
    return ok(ser(e), 201)


@app.route("/customers", methods=["GET"])
def list_customers():
    return list_collection("customers")


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    authz(ALL_ROLES)
    return ok(ser(get_or_404("customers", cid, "ERR_CUSTOMER_NOT_FOUND")))


@app.route("/customers/<cid>/loyalty-adjustments", methods=["POST"])
def loyalty_adjustment(cid):
    authz(["ShopManager", "SalesAssociate"])
    customer = get_or_404("customers", cid, "ERR_CUSTOMER_NOT_FOUND")
    b = get_body()
    kind = v_enum(b, "kind", {"EARN", "REDEEM"})
    if kind == "EARN":
        spend = v_int(b, "spend_cents", minv=0)
        accrue_loyalty(customer, spend, is_event_bonus=False)
    else:
        points = v_int(b, "points", minv=1)
        if points > customer["loyalty_points"]:
            raise ApiError("ERR_INSUFFICIENT_POINTS")
        customer["loyalty_points"] -= points
    touch(customer)
    return ok(ser(customer))


# ===========================================================================
# Coaches
# ===========================================================================
@app.route("/coaches", methods=["POST"])
def create_coach():
    authz(["ShopManager"])
    b = get_body()
    name = v_str(b, "name")
    discipline = v_enum(b, "discipline", DISCIPLINES)
    e = new_entity({"name": name, "discipline": discipline, "status": "ACTIVE"})
    DB["coaches"][e["id"]] = e
    return ok(ser(e), 201)


@app.route("/coaches", methods=["GET"])
def list_coaches():
    return list_collection("coaches")


@app.route("/coaches/<coid>", methods=["GET"])
def get_coach(coid):
    authz(ALL_ROLES)
    return ok(ser(get_or_404("coaches", coid, "ERR_COACH_NOT_FOUND")))


# ===========================================================================
# Rental Assets
# ===========================================================================
@app.route("/rental-assets", methods=["POST"])
def create_rental_asset():
    authz(["ShopManager"])
    b = get_body()
    check_fk("products", b.get("product_id"), "ERR_PRODUCT_NOT_FOUND")
    product_id = v_str(b, "product_id")
    asset_tag = v_str(b, "asset_tag")
    condition = v_opt_enum(b, "condition", CONDITIONS, "GOOD")
    for a in DB["rental_assets"].values():
        if a["asset_tag"] == asset_tag:
            raise ApiError("ERR_DUPLICATE_ASSET_TAG")
    e = new_entity({
        "product_id": product_id, "asset_tag": asset_tag,
        "condition": condition, "status": "AVAILABLE",
    })
    DB["rental_assets"][e["id"]] = e
    return ok(ser(e), 201)


@app.route("/rental-assets", methods=["GET"])
def list_rental_assets():
    return list_collection("rental_assets", {"product_id": request.args.get("product_id")})


@app.route("/rental-assets/<aid>", methods=["GET"])
def get_rental_asset(aid):
    authz(ALL_ROLES)
    return ok(ser(get_or_404("rental_assets", aid, "ERR_RENTAL_ASSET_NOT_FOUND")))


# ===========================================================================
# Lessons
# ===========================================================================
@app.route("/lessons", methods=["POST"])
def create_lesson():
    authz(["SalesAssociate", "ShopManager"])
    b = get_body()
    check_fk("coaches", b.get("coach_id"), "ERR_COACH_NOT_FOUND")
    check_fk("customers", b.get("customer_id"), "ERR_CUSTOMER_NOT_FOUND")
    coach_id = v_str(b, "coach_id")
    customer_id = v_str(b, "customer_id")
    discipline = v_enum(b, "discipline", DISCIPLINES)
    start_dt = parse_dt(b.get("start_at"))
    end_dt = parse_dt(b.get("end_at"))
    if end_dt <= start_dt:
        raise ApiError("ERR_VALIDATION", "end_at must be after start_at")
    coach = DB["coaches"][coach_id]
    if discipline != coach["discipline"]:
        raise ApiError("ERR_VALIDATION", "lesson discipline must match coach")
    # Coach availability: overlap OR separation < 15 min buffer against SCHEDULED.
    for les in DB["lessons"].values():
        if les["coach_id"] != coach_id or les["status"] != "SCHEDULED":
            continue
        es = parse_dt(les["start_at"])
        ee = parse_dt(les["end_at"])
        if start_dt < ee + SETUP_BUFFER and es < end_dt + SETUP_BUFFER:
            raise ApiError("ERR_COACH_UNAVAILABLE")
    e = new_entity({
        "coach_id": coach_id, "customer_id": customer_id, "discipline": discipline,
        "start_at": fmt_ts(start_dt), "end_at": fmt_ts(end_dt), "status": "SCHEDULED",
    })
    DB["lessons"][e["id"]] = e
    return ok(ser(e), 201)


@app.route("/lessons", methods=["GET"])
def list_lessons():
    return list_collection("lessons", {
        "coach_id": request.args.get("coach_id"),
        "customer_id": request.args.get("customer_id"),
    })


@app.route("/lessons/<lid>", methods=["GET"])
def get_lesson(lid):
    authz(ALL_ROLES)
    return ok(ser(get_or_404("lessons", lid, "ERR_LESSON_NOT_FOUND")))


@app.route("/lessons/<lid>/complete", methods=["POST"])
def complete_lesson(lid):
    authz(["SalesAssociate", "ShopManager"])
    lesson = get_or_404("lessons", lid, "ERR_LESSON_NOT_FOUND")
    b = get_body()
    outcome = v_opt_enum(b, "outcome", LESSON_OUTCOMES, "COMPLETED")
    if lesson["status"] != "SCHEDULED":
        raise ApiError("ERR_LESSON_INVALID_STATE")
    lesson["status"] = outcome
    touch(lesson)
    return ok(ser(lesson))


@app.route("/lessons/<lid>/cancel", methods=["POST"])
def cancel_lesson(lid):
    authz(["SalesAssociate", "ShopManager"])
    lesson = get_or_404("lessons", lid, "ERR_LESSON_NOT_FOUND")
    if lesson["status"] != "SCHEDULED":
        raise ApiError("ERR_LESSON_INVALID_STATE")
    lesson["status"] = "CANCELLED"
    touch(lesson)
    # Cascade: release linked RESERVED rentals.
    for rental in DB["rentals"].values():
        if rental["lesson_id"] == lid and rental["fulfillment_status"] == "RESERVED":
            rental["fulfillment_status"] = "RELEASED"
            rental["payment_status"] = "DEPOSIT_REFUNDED"
            asset = DB["rental_assets"].get(rental["rental_asset_id"])
            if asset is not None:
                asset["status"] = "AVAILABLE"
                touch(asset)
            touch(rental)
    return ok(ser(lesson))


# ===========================================================================
# Rentals
# ===========================================================================
def rental_asset_overlap(asset_id, start_dt, end_dt, ignore_id=None):
    for r in DB["rentals"].values():
        if r["rental_asset_id"] != asset_id:
            continue
        if ignore_id is not None and r["id"] == ignore_id:
            continue
        if r["fulfillment_status"] not in ("RESERVED", "PICKED_UP"):
            continue
        es = parse_dt(r["start_at"])
        ee = parse_dt(r["end_at"])
        # half-open overlap, adjacency allowed
        if start_dt < ee and es < end_dt:
            return True
    return False


@app.route("/rentals", methods=["POST"])
def create_rental():
    authz(["SalesAssociate", "ShopManager"])
    b = get_body()
    check_fk("customers", b.get("customer_id"), "ERR_CUSTOMER_NOT_FOUND")
    check_fk("rental_assets", b.get("rental_asset_id"), "ERR_RENTAL_ASSET_NOT_FOUND")
    if b.get("lesson_id") is not None:
        check_fk("lessons", b.get("lesson_id"), "ERR_LESSON_NOT_FOUND")
    customer_id = v_str(b, "customer_id")
    asset_id = v_str(b, "rental_asset_id")
    lesson_id = b.get("lesson_id") if b.get("lesson_id") not in ("", None) else None
    start_dt = parse_dt(b.get("start_at"))
    end_dt = parse_dt(b.get("end_at"))
    if end_dt <= start_dt:
        raise ApiError("ERR_VALIDATION", "end_at must be after start_at")
    deposit = v_int(b, "deposit_cents", minv=0)
    if rental_asset_overlap(asset_id, start_dt, end_dt):
        raise ApiError("ERR_ASSET_UNAVAILABLE")
    asset = DB["rental_assets"][asset_id]
    product = DB["products"][asset["product_id"]]
    fee = window_days(start_dt, end_dt) * product["rental_day_rate_cents"]
    e = new_entity({
        "customer_id": customer_id, "rental_asset_id": asset_id, "lesson_id": lesson_id,
        "start_at": fmt_ts(start_dt), "end_at": fmt_ts(end_dt), "deposit_cents": deposit,
        "rental_fee_cents": fee, "late_fee_cents": 0, "returned_at": None,
        "fulfillment_status": "RESERVED", "payment_status": "DEPOSIT_HELD",
    })
    DB["rentals"][e["id"]] = e
    asset["status"] = "RESERVED"
    touch(asset)
    return ok(ser(e), 201)


@app.route("/rentals", methods=["GET"])
def list_rentals():
    return list_collection("rentals", {
        "customer_id": request.args.get("customer_id"),
        "rental_asset_id": request.args.get("rental_asset_id"),
        "lesson_id": request.args.get("lesson_id"),
    })


@app.route("/rentals/<rid>", methods=["GET"])
def get_rental(rid):
    authz(ALL_ROLES)
    return ok(ser(get_or_404("rentals", rid, "ERR_RENTAL_NOT_FOUND")))


@app.route("/rentals/<rid>/checkout", methods=["POST"])
def checkout_rental(rid):
    authz(["SalesAssociate", "ShopManager"])
    rental = get_or_404("rentals", rid, "ERR_RENTAL_NOT_FOUND")
    if rental["fulfillment_status"] != "RESERVED":
        raise ApiError("ERR_RENTAL_INVALID_STATE")
    if rental["lesson_id"]:
        lesson = DB["lessons"].get(rental["lesson_id"])
        if lesson is None or lesson["status"] != "SCHEDULED":
            raise ApiError("ERR_LESSON_NOT_SCHEDULED")
    rental["fulfillment_status"] = "PICKED_UP"
    asset = DB["rental_assets"].get(rental["rental_asset_id"])
    if asset is not None:
        asset["status"] = "OUT"
        touch(asset)
    touch(rental)
    return ok(ser(rental))


@app.route("/rentals/<rid>/return", methods=["POST"])
def return_rental(rid):
    authz(["SalesAssociate", "ShopManager"])
    rental = get_or_404("rentals", rid, "ERR_RENTAL_NOT_FOUND")
    if rental["fulfillment_status"] != "PICKED_UP":
        raise ApiError("ERR_RENTAL_INVALID_STATE")
    now = clock_now()
    end_dt = parse_dt(rental["end_at"])
    if now <= end_dt:
        late_fee = 0
    else:
        late_days = int(math.ceil((now - end_dt).total_seconds() / 86400.0))
        late_fee = late_days * LATE_FEE_PER_DAY_CENTS
    rental["returned_at"] = fmt_ts(now)
    rental["late_fee_cents"] = late_fee
    rental["fulfillment_status"] = "RETURNED"
    rental["payment_status"] = "DEPOSIT_CAPTURED" if late_fee > 0 else "DEPOSIT_REFUNDED"
    asset = DB["rental_assets"].get(rental["rental_asset_id"])
    if asset is not None:
        asset["status"] = "AVAILABLE"
        touch(asset)
    customer = DB["customers"].get(rental["customer_id"])
    if customer is not None:
        accrue_loyalty(customer, rental["rental_fee_cents"] + late_fee, is_event_bonus=False)
        touch(customer)
    touch(rental)
    return ok(ser(rental))


@app.route("/rentals/<rid>/release", methods=["POST"])
def release_rental(rid):
    authz(["SalesAssociate", "ShopManager"])
    rental = get_or_404("rentals", rid, "ERR_RENTAL_NOT_FOUND")
    if rental["fulfillment_status"] != "RESERVED":
        raise ApiError("ERR_RENTAL_INVALID_STATE")
    rental["fulfillment_status"] = "RELEASED"
    rental["payment_status"] = "DEPOSIT_REFUNDED"
    asset = DB["rental_assets"].get(rental["rental_asset_id"])
    if asset is not None:
        asset["status"] = "AVAILABLE"
        touch(asset)
    touch(rental)
    return ok(ser(rental))


# ===========================================================================
# Board Builds
# ===========================================================================
def parse_components(b):
    comps = b.get("components")
    if not isinstance(comps, list) or len(comps) == 0:
        raise ApiError("ERR_VALIDATION", "components required")
    parsed = []
    for c in comps:
        if not isinstance(c, dict):
            raise ApiError("ERR_VALIDATION", "invalid component")
        pid = c.get("product_id")
        qty = c.get("qty")
        if not isinstance(pid, str) or not pid:
            raise ApiError("ERR_VALIDATION", "invalid component product_id")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise ApiError("ERR_VALIDATION", "invalid component qty")
        parsed.append({"product_id": pid, "qty": qty})
    return parsed


@app.route("/board-builds", methods=["POST"])
def create_board_build():
    authz(["BenchTech", "ShopManager"])
    b = get_body()
    check_fk("customers", b.get("customer_id"), "ERR_CUSTOMER_NOT_FOUND")
    comps_raw = b.get("components")
    if isinstance(comps_raw, list):
        for c in comps_raw:
            if isinstance(c, dict) and isinstance(c.get("product_id"), str) and c.get("product_id"):
                check_fk("products", c.get("product_id"), "ERR_PRODUCT_NOT_FOUND")
    customer_id = v_str(b, "customer_id")
    components = parse_components(b)
    e = new_entity({
        "customer_id": customer_id, "components": components,
        "provisional_cost_cents": 0, "final_cost_cents": 0, "status": "DRAFT",
    })
    DB["board_builds"][e["id"]] = e
    return ok(ser(e), 201)


@app.route("/board-builds", methods=["GET"])
def list_board_builds():
    return list_collection("board_builds", {"customer_id": request.args.get("customer_id")})


@app.route("/board-builds/<bid>", methods=["GET"])
def get_board_build(bid):
    authz(ALL_ROLES)
    return ok(ser(get_or_404("board_builds", bid, "ERR_BOARD_BUILD_NOT_FOUND")))


@app.route("/board-builds/<bid>/reserve", methods=["POST"])
def reserve_board_build(bid):
    authz(["BenchTech", "ShopManager"])
    build = get_or_404("board_builds", bid, "ERR_BOARD_BUILD_NOT_FOUND")
    if build["status"] != "DRAFT":
        raise ApiError("ERR_BUILD_INVALID_STATE")
    # business_safety (priority 6) before business_fiscal (priority 13)
    for comp in build["components"]:
        product = DB["products"][comp["product_id"]]
        if product["status"] == "DISCONTINUED":
            raise ApiError("ERR_COMPONENT_INCOMPATIBLE")
    for comp in build["components"]:
        product = DB["products"][comp["product_id"]]
        if product["available_qty"] < comp["qty"]:
            raise ApiError("ERR_INSUFFICIENT_STOCK")
    # provisional cost = list-price sum + labor
    total = 0
    for comp in build["components"]:
        product = DB["products"][comp["product_id"]]
        total += product["unit_price_cents"] * comp["qty"]
    build["provisional_cost_cents"] = total + BUILD_LABOR_CENTS
    for comp in build["components"]:
        product = DB["products"][comp["product_id"]]
        product["reserved_qty"] += comp["qty"]
        recompute_availability(product)
        touch(product)
    build["status"] = "RESERVED"
    touch(build)
    return ok(ser(build))


@app.route("/board-builds/<bid>/complete", methods=["POST"])
def complete_board_build(bid):
    authz(["BenchTech", "ShopManager"])
    build = get_or_404("board_builds", bid, "ERR_BOARD_BUILD_NOT_FOUND")
    if build["status"] != "RESERVED":
        raise ApiError("ERR_BUILD_INVALID_STATE")
    # final cost = per-line round_half_up(price*qty*0.90) summed + labor
    total = 0
    for comp in build["components"]:
        product = DB["products"][comp["product_id"]]
        line = Decimal(product["unit_price_cents"]) * Decimal(comp["qty"]) * BUILD_BUNDLE_FACTOR
        total += rhu(line)
    build["final_cost_cents"] = total + BUILD_LABOR_CENTS
    for comp in build["components"]:
        product = DB["products"][comp["product_id"]]
        product["reserved_qty"] -= comp["qty"]
        product["on_hand_qty"] -= comp["qty"]
        recompute_availability(product)
        touch(product)
    customer = DB["customers"].get(build["customer_id"])
    if customer is not None:
        accrue_loyalty(customer, build["final_cost_cents"], is_event_bonus=False)
        touch(customer)
    build["status"] = "COMPLETED"
    touch(build)
    return ok(ser(build))


@app.route("/board-builds/<bid>/cancel", methods=["POST"])
def cancel_board_build(bid):
    authz(["BenchTech", "ShopManager"])
    build = get_or_404("board_builds", bid, "ERR_BOARD_BUILD_NOT_FOUND")
    if build["status"] not in ("DRAFT", "RESERVED"):
        raise ApiError("ERR_BUILD_INVALID_STATE")
    if build["status"] == "RESERVED":
        for comp in build["components"]:
            product = DB["products"][comp["product_id"]]
            product["reserved_qty"] -= comp["qty"]
            recompute_availability(product)
            touch(product)
    build["status"] = "CANCELLED"
    touch(build)
    return ok(ser(build))


# ===========================================================================
# Service Tickets
# ===========================================================================
def parse_parts(b):
    parts = b.get("parts")
    if not isinstance(parts, list):
        raise ApiError("ERR_VALIDATION", "parts required")
    parsed = []
    for p in parts:
        if not isinstance(p, dict):
            raise ApiError("ERR_VALIDATION", "invalid part")
        pid = p.get("product_id")
        qty = p.get("qty")
        price = p.get("unit_price_cents")
        if not isinstance(pid, str) or not pid:
            raise ApiError("ERR_VALIDATION", "invalid part product_id")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise ApiError("ERR_VALIDATION", "invalid part qty")
        if not isinstance(price, int) or isinstance(price, bool) or price < 0:
            raise ApiError("ERR_VALIDATION", "invalid part unit_price_cents")
        parsed.append({"product_id": pid, "qty": qty, "unit_price_cents": price})
    return parsed


@app.route("/service-tickets", methods=["POST"])
def create_service_ticket():
    authz(["BenchTech", "ShopManager"])
    b = get_body()
    check_fk("customers", b.get("customer_id"), "ERR_CUSTOMER_NOT_FOUND")
    parts_raw = b.get("parts")
    if isinstance(parts_raw, list):
        for p in parts_raw:
            if isinstance(p, dict) and isinstance(p.get("product_id"), str) and p.get("product_id"):
                check_fk("products", p.get("product_id"), "ERR_PRODUCT_NOT_FOUND")
    customer_id = v_str(b, "customer_id")
    board_description = v_str(b, "board_description")
    parts = parse_parts(b)
    labor = v_int(b, "labor_cents", minv=0)
    e = new_entity({
        "customer_id": customer_id, "board_description": board_description,
        "parts": parts, "labor_cents": labor, "total_cents": 0, "status": "INTAKE",
    })
    DB["service_tickets"][e["id"]] = e
    return ok(ser(e), 201)


@app.route("/service-tickets", methods=["GET"])
def list_service_tickets():
    return list_collection("service_tickets", {"customer_id": request.args.get("customer_id")})


@app.route("/service-tickets/<sid>", methods=["GET"])
def get_service_ticket(sid):
    authz(ALL_ROLES)
    return ok(ser(get_or_404("service_tickets", sid, "ERR_SERVICE_TICKET_NOT_FOUND")))


@app.route("/service-tickets/<sid>/ready", methods=["POST"])
def ready_service_ticket(sid):
    authz(["BenchTech", "ShopManager"])
    ticket = get_or_404("service_tickets", sid, "ERR_SERVICE_TICKET_NOT_FOUND")
    if ticket["status"] != "INTAKE":
        raise ApiError("ERR_SERVICE_INVALID_STATE")
    part_total = 0
    for part in ticket["parts"]:
        line = Decimal(part["unit_price_cents"]) * Decimal(part["qty"]) * TAX_RATE_FACTOR
        part_total += rhu(line)
    labor_line = rhu(Decimal(ticket["labor_cents"]) * TAX_RATE_FACTOR)
    ticket["total_cents"] = part_total + labor_line
    ticket["status"] = "READY"
    touch(ticket)
    return ok(ser(ticket))


@app.route("/service-tickets/<sid>/pickup", methods=["POST"])
def pickup_service_ticket(sid):
    authz(["BenchTech", "ShopManager"])
    ticket = get_or_404("service_tickets", sid, "ERR_SERVICE_TICKET_NOT_FOUND")
    if ticket["status"] != "READY":
        raise ApiError("ERR_SERVICE_INVALID_STATE")
    ticket["status"] = "PICKED_UP"
    customer = DB["customers"].get(ticket["customer_id"])
    if customer is not None:
        accrue_loyalty(customer, ticket["total_cents"], is_event_bonus=False)
        touch(customer)
    touch(ticket)
    return ok(ser(ticket))


@app.route("/service-tickets/<sid>/cancel", methods=["POST"])
def cancel_service_ticket(sid):
    authz(["BenchTech", "ShopManager"])
    ticket = get_or_404("service_tickets", sid, "ERR_SERVICE_TICKET_NOT_FOUND")
    if ticket["status"] not in ("INTAKE", "READY"):
        raise ApiError("ERR_SERVICE_INVALID_STATE")
    ticket["status"] = "CANCELLED"
    touch(ticket)
    return ok(ser(ticket))


# ===========================================================================
# Trade-Ins / Consignment
# ===========================================================================
@app.route("/trade-ins", methods=["POST"])
def create_trade_in():
    authz(["SalesAssociate", "ShopManager", "Customer"])
    b = get_body()
    check_fk("customers", b.get("customer_id"), "ERR_CUSTOMER_NOT_FOUND")
    customer_id = v_str(b, "customer_id")
    item_description = v_str(b, "item_description")
    mode = v_enum(b, "mode", TRADE_MODES)
    list_price = v_opt_int(b, "list_price_cents", 0, minv=0)
    e = new_entity({
        "customer_id": customer_id, "item_description": item_description, "mode": mode,
        "appraised_value_cents": 0, "cash_offer_cents": 0, "store_credit_offer_cents": 0,
        "payout_choice": None, "list_price_cents": list_price, "sold_price_cents": 0,
        "consignor_credit_cents": 0, "status": "RECEIVED",
    })
    DB["trade_ins"][e["id"]] = e
    return ok(ser(e), 201)


@app.route("/trade-ins", methods=["GET"])
def list_trade_ins():
    return list_collection("trade_ins", {"customer_id": request.args.get("customer_id")})


@app.route("/trade-ins/<tid>", methods=["GET"])
def get_trade_in(tid):
    authz(ALL_ROLES)
    return ok(ser(get_or_404("trade_ins", tid, "ERR_TRADE_IN_NOT_FOUND")))


@app.route("/trade-ins/<tid>/appraise", methods=["POST"])
def appraise_trade_in(tid):
    authz(["ShopManager"])
    trade = get_or_404("trade_ins", tid, "ERR_TRADE_IN_NOT_FOUND")
    b = get_body()
    appraised = v_int(b, "appraised_value_cents", minv=0)
    if trade["status"] != "RECEIVED":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    trade["appraised_value_cents"] = appraised
    trade["cash_offer_cents"] = rhu(Decimal(appraised) * CASH_RATE)
    trade["store_credit_offer_cents"] = rhu(Decimal(appraised) * STORE_CREDIT_RATE)
    trade["status"] = "APPRAISED"
    touch(trade)
    return ok(ser(trade))


@app.route("/trade-ins/<tid>/accept", methods=["POST"])
def accept_trade_in(tid):
    authz(["Customer", "SalesAssociate", "ShopManager"])
    trade = get_or_404("trade_ins", tid, "ERR_TRADE_IN_NOT_FOUND")
    b = get_body()
    if trade["status"] != "APPRAISED":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    if trade["mode"] == "TRADE_IN":
        payout = v_enum(b, "payout_choice", PAYOUT_CHOICES)
        trade["payout_choice"] = payout
        trade["status"] = "ACCEPTED"
        if payout == "STORE_CREDIT":
            customer = DB["customers"].get(trade["customer_id"])
            if customer is not None:
                customer["store_credit_cents"] += trade["store_credit_offer_cents"]
                touch(customer)
    else:  # CONSIGNMENT
        if trade["list_price_cents"] <= 0:
            raise ApiError("ERR_VALIDATION", "list_price_cents must be > 0")
        trade["status"] = "LISTED"
    touch(trade)
    return ok(ser(trade))


@app.route("/trade-ins/<tid>/reject", methods=["POST"])
def reject_trade_in(tid):
    authz(["Customer", "SalesAssociate", "ShopManager"])
    trade = get_or_404("trade_ins", tid, "ERR_TRADE_IN_NOT_FOUND")
    if trade["status"] != "APPRAISED":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    trade["status"] = "REJECTED"
    touch(trade)
    return ok(ser(trade))


@app.route("/trade-ins/<tid>/sell", methods=["POST"])
def sell_trade_in(tid):
    authz(["ShopManager"])
    trade = get_or_404("trade_ins", tid, "ERR_TRADE_IN_NOT_FOUND")
    b = get_body()
    sold = v_int(b, "sold_price_cents", minv=0)
    if trade["status"] != "LISTED":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    trade["sold_price_cents"] = sold
    trade["consignor_credit_cents"] = rhu(Decimal(sold) * CONSIGNMENT_RATE)
    trade["status"] = "SOLD"
    customer = DB["customers"].get(trade["customer_id"])
    if customer is not None:
        customer["store_credit_cents"] += trade["consignor_credit_cents"]
        touch(customer)
    touch(trade)
    return ok(ser(trade))


# ===========================================================================
# Special Orders
# ===========================================================================
@app.route("/special-orders", methods=["POST"])
def create_special_order():
    authz(["SalesAssociate", "ShopManager", "Customer"])
    b = get_body()
    check_fk("customers", b.get("customer_id"), "ERR_CUSTOMER_NOT_FOUND")
    check_fk("products", b.get("product_id"), "ERR_PRODUCT_NOT_FOUND")
    customer_id = v_str(b, "customer_id")
    product_id = v_str(b, "product_id")
    quantity = v_int(b, "quantity", minv=1)
    e = new_entity({
        "customer_id": customer_id, "product_id": product_id, "quantity": quantity,
        "quoted_price_cents": 0, "revision_count": 0, "status": "DRAFT",
    })
    DB["special_orders"][e["id"]] = e
    return ok(ser(e), 201)


@app.route("/special-orders", methods=["GET"])
def list_special_orders():
    return list_collection("special_orders", {
        "customer_id": request.args.get("customer_id"),
        "product_id": request.args.get("product_id"),
    })


@app.route("/special-orders/<oid>", methods=["GET"])
def get_special_order(oid):
    authz(ALL_ROLES)
    return ok(ser(get_or_404("special_orders", oid, "ERR_SPECIAL_ORDER_NOT_FOUND")))


@app.route("/special-orders/<oid>/quote", methods=["POST"])
def quote_special_order(oid):
    authz(["ShopManager"])
    order = get_or_404("special_orders", oid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    b = get_body()
    quoted = v_int(b, "quoted_price_cents", minv=0)
    if order["status"] not in ("DRAFT", "CUSTOMER_REVIEW"):
        raise ApiError("ERR_ORDER_INVALID_STATE")
    order["quoted_price_cents"] = quoted
    order["status"] = "QUOTED"
    touch(order)  # version += 1
    return ok(ser(order))


@app.route("/special-orders/<oid>/revise", methods=["POST"])
def revise_special_order(oid):
    authz(["SalesAssociate", "ShopManager"])
    order = get_or_404("special_orders", oid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    b = get_body()
    expected = v_int(b, "expected_special_order_version")
    if order["status"] != "QUOTED":
        raise ApiError("ERR_ORDER_INVALID_STATE")
    if expected != order["version"]:
        raise ApiError("ERR_STALE_VERSION")
    order["revision_count"] += 1
    order["status"] = "CUSTOMER_REVIEW"
    touch(order)  # version += 1
    return ok(ser(order))


@app.route("/special-orders/<oid>/approve", methods=["POST"])
def approve_special_order(oid):
    authz(["Customer", "SalesAssociate", "ShopManager"])
    order = get_or_404("special_orders", oid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if order["status"] != "QUOTED":
        raise ApiError("ERR_ORDER_INVALID_STATE")
    order["status"] = "APPROVED"
    touch(order)
    return ok(ser(order))


@app.route("/special-orders/<oid>/fulfill", methods=["POST"])
def fulfill_special_order(oid):
    authz(["ShopManager"])
    order = get_or_404("special_orders", oid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if order["status"] != "APPROVED":
        raise ApiError("ERR_ORDER_INVALID_STATE")
    product = DB["products"][order["product_id"]]
    if product["available_qty"] < order["quantity"]:
        raise ApiError("ERR_INSUFFICIENT_STOCK")
    product["on_hand_qty"] -= order["quantity"]
    recompute_availability(product)
    touch(product)
    order["status"] = "FULFILLED"
    customer = DB["customers"].get(order["customer_id"])
    if customer is not None:
        accrue_loyalty(customer, order["quoted_price_cents"], is_event_bonus=False)
        touch(customer)
    touch(order)
    return ok(ser(order))


@app.route("/special-orders/<oid>/cancel", methods=["POST"])
def cancel_special_order(oid):
    authz(["SalesAssociate", "ShopManager", "Customer"])
    order = get_or_404("special_orders", oid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if order["status"] not in ("DRAFT", "QUOTED", "CUSTOMER_REVIEW", "APPROVED"):
        raise ApiError("ERR_ORDER_INVALID_STATE")
    order["status"] = "CANCELLED"
    touch(order)
    return ok(ser(order))


# ===========================================================================
# Events
# ===========================================================================
@app.route("/events", methods=["POST"])
def create_event():
    authz(["ShopManager"])
    b = get_body()
    name = v_str(b, "name")
    sponsor = v_str(b, "sponsor")
    venue = v_str(b, "venue")
    start_dt = parse_dt(b.get("start_at"))
    capacity = v_int(b, "capacity", minv=1)
    entry_fee = v_int(b, "entry_fee_cents", minv=0)
    e = new_entity({
        "name": name, "sponsor": sponsor, "venue": venue,
        "start_at": fmt_ts(start_dt), "capacity": capacity, "entry_fee_cents": entry_fee,
        "entry_count": 0, "status": "DRAFT",
    })
    DB["events"][e["id"]] = e
    return ok(ser(e), 201)


@app.route("/events", methods=["GET"])
def list_events():
    return list_collection("events")


@app.route("/events/<eid>", methods=["GET"])
def get_event(eid):
    authz(ALL_ROLES)
    return ok(ser(get_or_404("events", eid, "ERR_EVENT_NOT_FOUND")))


@app.route("/events/<eid>/publish", methods=["POST"])
def publish_event(eid):
    authz(["ShopManager"])
    event = get_or_404("events", eid, "ERR_EVENT_NOT_FOUND")
    if event["status"] != "DRAFT":
        raise ApiError("ERR_EVENT_INVALID_STATE")
    event["status"] = "PUBLISHED"
    touch(event)
    return ok(ser(event))


@app.route("/events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    authz(["ShopManager"])
    event = get_or_404("events", eid, "ERR_EVENT_NOT_FOUND")
    if event["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError("ERR_EVENT_INVALID_STATE")
    event["status"] = "CANCELLED"
    touch(event)
    # Cascade: cancel REGISTERED entries, reverse loyalty, decrement count.
    for entry in DB["event_entries"].values():
        if entry["event_id"] == eid and entry["status"] == "REGISTERED":
            entry["status"] = "CANCELLED"
            event["entry_count"] -= 1
            customer = DB["customers"].get(entry["customer_id"])
            if customer is not None:
                customer["loyalty_points"] -= entry["points_awarded"]
                if customer["loyalty_points"] < 0:
                    customer["loyalty_points"] = 0
                touch(customer)
            touch(entry)
    return ok(ser(event))


# ===========================================================================
# Event Entries
# ===========================================================================
@app.route("/event-entries", methods=["POST"])
def create_event_entry():
    authz(["Customer", "SalesAssociate", "ShopManager"])
    b = get_body()
    check_fk("events", b.get("event_id"), "ERR_EVENT_NOT_FOUND")
    check_fk("customers", b.get("customer_id"), "ERR_CUSTOMER_NOT_FOUND")
    event_id = v_str(b, "event_id")
    customer_id = v_str(b, "customer_id")
    role = v_opt_enum(b, "role", ENTRY_ROLES, "PUBLIC")
    event = DB["events"][event_id]
    if event["status"] != "PUBLISHED":
        raise ApiError("ERR_EVENT_NOT_OPEN")
    if event["entry_count"] >= event["capacity"]:
        raise ApiError("ERR_EVENT_FULL")
    customer = DB["customers"][customer_id]
    awarded = accrue_loyalty(customer, event["entry_fee_cents"], is_event_bonus=True)
    touch(customer)
    e = new_entity({
        "event_id": event_id, "customer_id": customer_id, "role": role,
        "points_awarded": awarded, "status": "REGISTERED",
    })
    DB["event_entries"][e["id"]] = e
    event["entry_count"] += 1
    touch(event)
    return ok(ser(e), 201)


@app.route("/event-entries", methods=["GET"])
def list_event_entries():
    return list_collection("event_entries", {
        "event_id": request.args.get("event_id"),
        "customer_id": request.args.get("customer_id"),
    })


@app.route("/event-entries/<eeid>", methods=["GET"])
def get_event_entry(eeid):
    authz(ALL_ROLES)
    return ok(ser(get_or_404("event_entries", eeid, "ERR_EVENT_ENTRY_NOT_FOUND")))


@app.route("/event-entries/<eeid>/cancel", methods=["POST"])
def cancel_event_entry(eeid):
    authz(["Customer", "SalesAssociate", "ShopManager"])
    entry = get_or_404("event_entries", eeid, "ERR_EVENT_ENTRY_NOT_FOUND")
    if entry["status"] != "REGISTERED":
        raise ApiError("ERR_ENTRY_INVALID_STATE")
    entry["status"] = "CANCELLED"
    event = DB["events"].get(entry["event_id"])
    if event is not None:
        event["entry_count"] -= 1
        touch(event)
    customer = DB["customers"].get(entry["customer_id"])
    if customer is not None:
        customer["loyalty_points"] -= entry["points_awarded"]
        if customer["loyalty_points"] < 0:
            customer["loyalty_points"] = 0
        touch(customer)
    touch(entry)
    return ok(ser(entry))


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authz(["ShopManager"])
    b = get_body()
    target = parse_dt(b.get("to_iso8601"))
    _STATE["clock"] = target
    return ok({}, 200)


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
