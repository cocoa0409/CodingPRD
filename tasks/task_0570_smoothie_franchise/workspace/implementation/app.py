"""Smoothie & Juice Bar Franchise API — Flask reference implementation.

In-memory only. No seeding at startup. All state is built via the API.
"""
import math
import os
import random
import string
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_ROLES = {"PlatformAdmin", "Franchisee", "StoreStaff", "Customer", "Anonymous"}

SIZE_UPCHARGE_CENTS = {"SMALL": 0, "MEDIUM": 100, "LARGE": 200}
SIZE_QTY_FACTOR = {"SMALL": Decimal("1.0"), "MEDIUM": Decimal("1.5"), "LARGE": Decimal("2.0")}
TIER_DISCOUNT_PCT = {"BRONZE": Decimal("0"), "SILVER": Decimal("0.05"), "GOLD": Decimal("0.10")}
TAX_RATE = Decimal("0.08")
CATERING_SERVICE_FEE_PER_HEAD_CENTS = 200
SILVER_THRESHOLD = 500
GOLD_THRESHOLD = 1500
REBATE_THRESHOLD_CENTS = 50000
REBATE_RATE = Decimal("0.05")

SIZES = {"SMALL", "MEDIUM", "LARGE"}
MENU_CATEGORIES = {"SMOOTHIE", "JUICE", "BOWL", "WELLNESS_PACK"}
INGREDIENT_UNITS = {"GRAM", "ML", "UNIT"}
SUB_TIERS = {"BASIC", "PREMIUM"}
FULFILLMENT_TYPES = {"PICKUP", "DELIVERY"}
ROYALTY_BASES = {"NET", "GROSS"}
VEHICLE_STATUSES = {"AVAILABLE", "MAINTENANCE"}
STORE_STATUSES = {"SETUP", "OPEN", "SUSPENDED", "CLOSED"}
PAYMENT_OUTCOMES = {"SUCCESS", "FAIL"}

STORE_TRANSITIONS = {
    ("SETUP", "OPEN"),
    ("OPEN", "SUSPENDED"),
    ("SUSPENDED", "OPEN"),
    ("OPEN", "CLOSED"),
    ("SUSPENDED", "CLOSED"),
}

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.franchisees = {}
        self.stores = {}
        self.vehicles = {}
        self.ingredients = {}
        self.lots = {}
        self.menu_items = {}
        self.boosts = {}
        self.customers = {}
        self.subscriptions = {}
        self.orders = {}
        self.points_txns = {}
        self.bookings = {}
        self.reconciliations = {}


db = DB()
CLOCK = {"now": DEFAULT_CLOCK}
_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def clock_now():
    return CLOCK["now"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    raise ApiError(error_id, http_status, message)


def unauthenticated(msg="Missing or malformed authentication headers"):
    err("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized(msg="Role not permitted for this operation"):
    err("ERR_UNAUTHORIZED", 403, msg)


def bad_request(msg="Malformed request"):
    err("ERR_INVALID_REQUEST", 400, msg)


def not_found(msg="Resource not found"):
    err("ERR_NOT_FOUND", 404, msg)


def not_owner(msg="Caller does not own the target resource"):
    err("ERR_NOT_RESOURCE_OWNER", 403, msg)


def invalid_state(msg="Invalid state for transition"):
    err("ERR_INVALID_STATE", 409, msg)


def store_not_open(msg="Store is not OPEN"):
    err("ERR_STORE_NOT_OPEN", 409, msg)


def stale_version(msg="Stale version"):
    err("ERR_STALE_VERSION", 412, msg)


def validation_error(msg="Semantically invalid request"):
    err("ERR_VALIDATION", 422, msg)


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def now_str():
    return fmt_dt(clock_now())


def parse_dt(value):
    if not isinstance(value, str):
        return None
    t = value.strip()
    if not t:
        return None
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        # Fallback for a few common layouts
        for fmtstr in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                       "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
            try:
                dt = datetime.strptime(value.strip().rstrip("Zz"), fmtstr)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_business_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def rhu(dec_value):
    """Round half up to an integer."""
    if not isinstance(dec_value, Decimal):
        dec_value = Decimal(str(dec_value))
    return int(dec_value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def base_meta():
    return {"api_request_id": request_id(), "api_request_timestamp": now_str()}


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def success(data, response_type="object", code=200, pagination=None):
    meta = base_meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return body, code


def error_body(e):
    meta = base_meta()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return body, e.http_status


@app.errorhandler(ApiError)
def handle_api_error(e):
    from flask import jsonify
    body, code = error_body(e)
    return jsonify(body), code


@app.errorhandler(404)
def handle_404(e):
    from flask import jsonify
    body, code = error_body(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))
    return jsonify(body), code


@app.errorhandler(405)
def handle_405(e):
    from flask import jsonify
    body, code = error_body(ApiError("ERR_INVALID_REQUEST", 400, "Method not allowed"))
    return jsonify(body), 400


@app.errorhandler(Exception)
def handle_uncaught(e):
    from flask import jsonify
    if isinstance(e, ApiError):
        body, code = error_body(e)
        return jsonify(body), code
    # Defensive: never leak a 500 stack; treat as validation issue.
    body, code = error_body(ApiError("ERR_INVALID_REQUEST", 400, "Malformed request: %s" % str(e)))
    return jsonify(body), 400


def respond(data, response_type="object", code=200, pagination=None):
    from flask import jsonify
    body, c = success(data, response_type, code, pagination)
    return jsonify(body), c


# ---------------------------------------------------------------------------
# Request body / query helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("GET", "DELETE"):
        return {}
    raw = request.get_data()
    if not raw:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        bad_request("Request body is not valid JSON")
    if not isinstance(data, dict):
        bad_request("Request body must be a JSON object")
    return data


def require_present(body, field):
    if field not in body or body[field] is None:
        bad_request("Missing required field: %s" % field)
    return body[field]


def check_int(value, field, min_value=None):
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field %s must be an integer" % field)
    if value < 0:
        bad_request("Field %s must not be negative" % field)
    if min_value is not None and value < min_value:
        validation_error("Field %s must be >= %d" % (field, min_value))
    return value


def check_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad_request("Field %s must be a number" % field)
    if value < 0:
        bad_request("Field %s must not be negative" % field)
    return value


def check_rate(value, field, hi):
    check_number(value, field)
    if value > hi:
        validation_error("Field %s must be between 0 and %s" % (field, hi))
    return value


def check_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        bad_request("Field %s must be one of %s" % (field, sorted(allowed)))
    return value


def check_bool(value, field):
    if not isinstance(value, bool):
        bad_request("Field %s must be a boolean" % field)
    return value


def check_str(value, field):
    if not isinstance(value, str) or value == "":
        bad_request("Field %s must be a non-empty string" % field)
    return value


def check_allergen_tags(value, field):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(t, str) for t in value):
        bad_request("Field %s must be a list of strings" % field)
    return list(value)


def get_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            bad_request("limit must be an integer")
        if limit_v < 1 or limit_v > 100:
            bad_request("limit must be between 1 and 100")
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            bad_request("offset must be an integer")
        if offset_v < 0:
            bad_request("offset must be >= 0")
    return limit_v, offset_v


def sort_key(entity):
    return (entity["_created_dt"], entity["_seq"])


def paginate_and_respond(items, code=200):
    limit, offset = get_pagination()
    items = sorted(items, key=sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    data = [serialize(i) for i in page]
    return respond(data, "array", code, pagination)


# ---------------------------------------------------------------------------
# Entity creation base
# ---------------------------------------------------------------------------
def base_common(with_version=True):
    now = now_str()
    d = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "_created_dt": clock_now(),
        "_seq": next_seq(),
    }
    if with_version:
        d["updated_at"] = now
        d["version"] = 1
    return d


def touch(entity):
    if "version" in entity:
        entity["version"] += 1
        entity["updated_at"] = now_str()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or uid is None or role == "" or uid == "":
        unauthenticated()
    if role not in VALID_ROLES:
        unauthenticated("Unknown role: %s" % role)
    g.role = role
    g.uid = uid
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        unauthorized("Role %s may not perform this operation" % role)


def auth_and_authorize(allowed):
    uid, role = authenticate()
    authorize(role, allowed)
    return uid, role


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def get_or_404(collection, rid, label):
    if not isinstance(rid, str):
        not_found("%s not found" % label)
    entity = collection.get(rid)
    if entity is None:
        not_found("%s not found: %s" % (label, rid))
    return entity


def get_customer_active_subscription(customer_id):
    for sub in db.subscriptions.values():
        if sub["customer_id"] == customer_id and sub["status"] == "ACTIVE":
            return sub
    return None


def get_customer_non_cancelled_subscription(customer_id):
    for sub in db.subscriptions.values():
        if sub["customer_id"] == customer_id and sub["status"] != "CANCELLED":
            return sub
    return None


def recompute_loyalty_tier(customer):
    lp = customer["lifetime_points_earned"]
    if lp >= GOLD_THRESHOLD:
        customer["loyalty_tier"] = "GOLD"
    elif lp >= SILVER_THRESHOLD:
        customer["loyalty_tier"] = "SILVER"
    else:
        customer["loyalty_tier"] = "BRONZE"


def add_points_txn(customer, reason, delta, order_id=None):
    customer["points_balance"] += delta
    if reason != "REDEEM":
        customer["lifetime_points_earned"] += delta
    recompute_loyalty_tier(customer)
    touch(customer)
    txn = base_common(with_version=False)
    txn.update({
        "customer_id": customer["id"],
        "order_id": order_id,
        "reason": reason,
        "delta": delta,
        "balance_after": customer["points_balance"],
    })
    db.points_txns[txn["id"]] = txn
    return txn


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------
def store_of(entity_store_id):
    return db.stores.get(entity_store_id)


def owns_store(uid, role, store):
    if role == "PlatformAdmin":
        return True
    if role == "Franchisee":
        return store["franchisee_id"] == uid
    if role == "StoreStaff":
        return store["id"] == uid
    return False


# ---------------------------------------------------------------------------
# Pricing / nutrition
# ---------------------------------------------------------------------------
def compute_required_units(lines):
    """Aggregate required whole ingredient units across all lines."""
    req = {}
    for line in lines:
        mi = db.menu_items[line["menu_item_id"]]
        factor = SIZE_QTY_FACTOR[line["size"]]
        for entry in mi["recipe"]:
            ing_id = entry["ingredient_id"]
            base_qty = entry["base_qty"]
            needed = int(math.ceil(Decimal(base_qty) * factor))
            req[ing_id] = req.get(ing_id, 0) + needed
    return req


def compute_line_allergens(line):
    mi = db.menu_items[line["menu_item_id"]]
    tags = set(mi.get("allergen_tags") or [])
    for b in line["boost_ids"]:
        tags |= set(db.boosts[b].get("allergen_tags") or [])
    return sorted(tags)


def compute_pricing(lines_input, customer, active_sub, redeem_points, use_credit):
    """Return the fully computed order pricing/nutrition dict."""
    tier_pct = TIER_DISCOUNT_PCT[customer["loyalty_tier"]]
    credits_avail = 0
    if use_credit and active_sub is not None:
        credits_avail = active_sub["credits_remaining"]

    out_lines = []
    credits_used = 0
    subtotal = 0
    gross_merch = 0
    total_calories = 0
    allergen_summary = set()

    for line in lines_input:
        mi = db.menu_items[line["menu_item_id"]]
        size = line["size"]
        boost_ids = line["boost_ids"]
        size_base = mi["base_price_cents"] + SIZE_UPCHARGE_CENTS[size]
        boosts_total = sum(db.boosts[b]["price_cents"] for b in boost_ids)
        line_gross = size_base + boosts_total

        credit_applied = (use_credit and mi["category"] == "SMOOTHIE" and credits_avail > 0)
        if credit_applied:
            covered = size_base
            credits_avail -= 1
            credits_used += 1
        else:
            covered = 0
        subsidized = line_gross - covered
        tier_discount = rhu(Decimal(subsidized) * tier_pct)
        line_net = subsidized - tier_discount

        # nutrition
        factor = SIZE_QTY_FACTOR[size]
        line_calories = rhu(Decimal(mi["base_calories"]) * factor)
        line_calories += sum(db.boosts[b]["calories"] for b in boost_ids)
        line_allergens = compute_line_allergens(line)

        subtotal += line_net
        gross_merch += line_gross
        total_calories += line_calories
        allergen_summary |= set(line_allergens)

        out_lines.append({
            "menu_item_id": line["menu_item_id"],
            "size": size,
            "boost_ids": list(boost_ids),
            "line_gross_cents": line_gross,
            "tier_discount_cents": tier_discount,
            "credit_applied": credit_applied,
            "line_net_cents": line_net,
            "line_calories": line_calories,
            "line_allergens": line_allergens,
        })

    redeem_discount = min(redeem_points, subtotal)
    discounted_subtotal = subtotal - redeem_discount
    tax = rhu(Decimal(discounted_subtotal) * TAX_RATE)
    total = discounted_subtotal + tax

    return {
        "lines": out_lines,
        "subtotal_cents": subtotal,
        "redeem_discount_cents": redeem_discount,
        "discounted_subtotal_cents": discounted_subtotal,
        "tax_cents": tax,
        "total_cents": total,
        "gross_merch_cents": gross_merch,
        "credits_used": credits_used,
        "total_calories": total_calories,
        "allergen_summary": sorted(allergen_summary),
    }


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
def available_lots(store_id, ingredient_id):
    lots = [lot for lot in db.lots.values()
            if lot["store_id"] == store_id and lot["ingredient_id"] == ingredient_id
            and lot["status"] == "AVAILABLE"]
    lots.sort(key=lambda l: (l["_dt_received_at"], l["_created_dt"], l["_seq"]))
    return lots


def available_qty(store_id, ingredient_id):
    return sum(lot["remaining_qty"] for lot in db.lots.values()
               if lot["store_id"] == store_id and lot["ingredient_id"] == ingredient_id
               and lot["status"] == "AVAILABLE")


def inventory_sufficient(store_id, required):
    for ing_id, need in required.items():
        if available_qty(store_id, ing_id) < need:
            return False
    return True


def consume_inventory(store_id, required):
    """Draw units FIFO. Returns list of {lot_id, qty, unit_cost_cents}."""
    consumption = []
    for ing_id, need in required.items():
        remaining_need = need
        for lot in available_lots(store_id, ing_id):
            if remaining_need <= 0:
                break
            draw = min(lot["remaining_qty"], remaining_need)
            if draw <= 0:
                continue
            lot["remaining_qty"] -= draw
            lot["consumed_qty"] += draw
            if lot["remaining_qty"] == 0:
                lot["status"] = "DEPLETED"
            touch(lot)
            consumption.append({"lot_id": lot["id"], "qty": draw,
                                "unit_cost_cents": lot["unit_cost_cents"]})
            remaining_need -= draw
    return consumption


def restore_inventory(consumption):
    for c in consumption:
        lot = db.lots.get(c["lot_id"])
        if lot is None:
            continue
        lot["remaining_qty"] += c["qty"]
        lot["consumed_qty"] -= c["qty"]
        if lot["status"] == "DEPLETED" and lot["remaining_qty"] > 0:
            lot["status"] = "AVAILABLE"
        touch(lot)


# ===========================================================================
# Endpoints
# ===========================================================================

# --- Franchisees --------------------------------------------------------
@app.route("/franchisees", methods=["POST"])
def create_franchisee():
    uid, role = auth_and_authorize({"PlatformAdmin"})
    body = get_body()
    legal_name = check_str(require_present(body, "legal_name"), "legal_name")
    contact_email = check_str(require_present(body, "contact_email"), "contact_email")
    base_royalty_rate = check_rate(require_present(body, "base_royalty_rate"), "base_royalty_rate", 0.5)
    marketing_fee_rate = check_rate(require_present(body, "marketing_fee_rate"), "marketing_fee_rate", 0.2)

    ent = base_common()
    ent.update({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "base_royalty_rate": base_royalty_rate,
        "marketing_fee_rate": marketing_fee_rate,
        "lifetime_royalty_cents": 0,
    })
    db.franchisees[ent["id"]] = ent
    return respond(serialize(ent), "object", 201)


@app.route("/franchisees/<fid>", methods=["GET"])
def get_franchisee(fid):
    uid, role = auth_and_authorize({"PlatformAdmin", "Franchisee"})
    ent = get_or_404(db.franchisees, fid, "Franchisee")
    if role == "Franchisee" and ent["id"] != uid:
        not_owner()
    return respond(serialize(ent), "object", 200)


@app.route("/franchisees/<fid>/stores", methods=["GET"])
def list_franchisee_stores(fid):
    uid, role = auth_and_authorize({"PlatformAdmin", "Franchisee"})
    ent = get_or_404(db.franchisees, fid, "Franchisee")
    if role == "Franchisee" and ent["id"] != uid:
        not_owner()
    status = request.args.get("status")
    if status is not None and status not in STORE_STATUSES:
        bad_request("Invalid status filter")
    items = [s for s in db.stores.values() if s["franchisee_id"] == fid]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paginate_and_respond(items)


@app.route("/franchisees/<fid>/stores", methods=["POST"])
def create_store(fid):
    uid, role = auth_and_authorize({"PlatformAdmin", "Franchisee"})
    body = get_body()
    name = check_str(require_present(body, "name"), "name")
    catering_capacity = check_int(require_present(body, "catering_capacity"), "catering_capacity", min_value=1)
    royalty_override = body.get("royalty_rate_override")
    if royalty_override is not None:
        check_rate(royalty_override, "royalty_rate_override", 0.5)
    ent = get_or_404(db.franchisees, fid, "Franchisee")
    if role == "Franchisee" and ent["id"] != uid:
        not_owner()

    store = base_common()
    store.update({
        "franchisee_id": fid,
        "name": name,
        "status": "SETUP",
        "catering_capacity": catering_capacity,
        "royalty_rate_override": royalty_override,
        "mtd_spoilage_cents": 0,
    })
    db.stores[store["id"]] = store
    return respond(serialize(store), "object", 201)


@app.route("/stores/<sid>", methods=["GET"])
def get_store(sid):
    uid, role = auth_and_authorize({"PlatformAdmin", "Franchisee", "StoreStaff"})
    store = get_or_404(db.stores, sid, "Store")
    if not owns_store(uid, role, store):
        not_owner()
    return respond(serialize(store), "object", 200)


@app.route("/stores/<sid>", methods=["PATCH"])
def patch_store(sid):
    uid, role = auth_and_authorize({"PlatformAdmin", "Franchisee"})
    body = get_body()
    expected = require_present(body, "expected_store_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        bad_request("expected_store_version must be an integer")
    new_status = body.get("status")
    if new_status is not None:
        check_enum(new_status, "status", STORE_STATUSES)
    new_capacity = body.get("catering_capacity")
    if new_capacity is not None:
        check_int(new_capacity, "catering_capacity", min_value=1)
    if "royalty_rate_override" in body and body["royalty_rate_override"] is not None:
        check_rate(body["royalty_rate_override"], "royalty_rate_override", 0.5)

    store = get_or_404(db.stores, sid, "Store")
    if role == "Franchisee" and store["franchisee_id"] != uid:
        not_owner()

    # State precondition (only when the status actually changes)
    if new_status is not None and new_status != store["status"]:
        if (store["status"], new_status) not in STORE_TRANSITIONS:
            invalid_state("Cannot transition store from %s to %s" % (store["status"], new_status))

    # OCC
    if expected != store["version"]:
        stale_version("expected_store_version %s != current %s" % (expected, store["version"]))

    if new_status is not None:
        store["status"] = new_status
    if new_capacity is not None:
        store["catering_capacity"] = new_capacity
    if "royalty_rate_override" in body:
        store["royalty_rate_override"] = body["royalty_rate_override"]
    touch(store)
    return respond(serialize(store), "object", 200)


# --- Delivery vehicles --------------------------------------------------
@app.route("/stores/<sid>/delivery-vehicles", methods=["POST"])
def create_vehicle(sid):
    uid, role = auth_and_authorize({"Franchisee"})
    body = get_body()
    label = check_str(require_present(body, "label"), "label")
    headcount_capacity = check_int(require_present(body, "headcount_capacity"), "headcount_capacity", min_value=1)
    store = get_or_404(db.stores, sid, "Store")
    if store["franchisee_id"] != uid:
        not_owner()
    veh = base_common()
    veh.update({
        "store_id": sid,
        "label": label,
        "headcount_capacity": headcount_capacity,
        "status": "AVAILABLE",
    })
    db.vehicles[veh["id"]] = veh
    return respond(serialize(veh), "object", 201)


@app.route("/stores/<sid>/delivery-vehicles", methods=["GET"])
def list_vehicles(sid):
    uid, role = auth_and_authorize({"Franchisee", "StoreStaff"})
    store = get_or_404(db.stores, sid, "Store")
    if not owns_store(uid, role, store):
        not_owner()
    status = request.args.get("status")
    if status is not None and status not in VEHICLE_STATUSES:
        bad_request("Invalid status filter")
    items = [v for v in db.vehicles.values() if v["store_id"] == sid]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    return paginate_and_respond(items)


@app.route("/delivery-vehicles/<vid>", methods=["PATCH"])
def patch_vehicle(vid):
    uid, role = auth_and_authorize({"Franchisee"})
    body = get_body()
    new_status = check_enum(require_present(body, "status"), "status", VEHICLE_STATUSES)
    veh = get_or_404(db.vehicles, vid, "DeliveryVehicle")
    store = store_of(veh["store_id"])
    if store is None or store["franchisee_id"] != uid:
        not_owner()
    veh["status"] = new_status
    touch(veh)
    return respond(serialize(veh), "object", 200)


# --- Ingredients --------------------------------------------------------
@app.route("/ingredients", methods=["POST"])
def create_ingredient():
    uid, role = auth_and_authorize({"PlatformAdmin"})
    body = get_body()
    name = check_str(require_present(body, "name"), "name")
    unit = check_enum(require_present(body, "unit"), "unit", INGREDIENT_UNITS)
    std_cost = check_int(require_present(body, "standard_cost_cents_per_unit"), "standard_cost_cents_per_unit")
    allergen_tags = check_allergen_tags(body.get("allergen_tags"), "allergen_tags")
    ent = base_common()
    ent.update({
        "name": name,
        "unit": unit,
        "standard_cost_cents_per_unit": std_cost,
        "allergen_tags": allergen_tags,
    })
    db.ingredients[ent["id"]] = ent
    return respond(serialize(ent), "object", 201)


@app.route("/ingredients", methods=["GET"])
def list_ingredients():
    auth_and_authorize({"PlatformAdmin", "Franchisee", "StoreStaff", "Customer"})
    return paginate_and_respond(list(db.ingredients.values()))


# --- Inventory lots -----------------------------------------------------
@app.route("/stores/<sid>/inventory-lots", methods=["POST"])
def receive_lot(sid):
    uid, role = auth_and_authorize({"StoreStaff"})
    body = get_body()
    ingredient_id = require_present(body, "ingredient_id")
    if not isinstance(ingredient_id, str):
        bad_request("ingredient_id must be a string")
    qty_received = check_int(require_present(body, "qty_received"), "qty_received", min_value=1)
    unit_cost_cents = check_int(require_present(body, "unit_cost_cents"), "unit_cost_cents")
    received_at_raw = require_present(body, "received_at")
    expiry_raw = require_present(body, "expiry_date")
    received_dt = parse_dt(received_at_raw)
    expiry_dt = parse_dt(expiry_raw)
    if received_dt is None:
        bad_request("received_at is not a valid datetime")
    if expiry_dt is None:
        bad_request("expiry_date is not a valid datetime")

    store = get_or_404(db.stores, sid, "Store")
    get_or_404(db.ingredients, ingredient_id, "Ingredient")
    if store["id"] != uid:
        not_owner()

    lot = base_common()
    lot.update({
        "store_id": sid,
        "ingredient_id": ingredient_id,
        "qty_received": qty_received,
        "remaining_qty": qty_received,
        "consumed_qty": 0,
        "spoiled_qty": 0,
        "unit_cost_cents": unit_cost_cents,
        "received_at": received_at_raw,
        "expiry_date": expiry_raw,
        "status": "AVAILABLE",
        "_dt_received_at": received_dt,
        "_dt_expiry": expiry_dt,
    })
    db.lots[lot["id"]] = lot
    return respond(serialize(lot), "object", 201)


@app.route("/inventory-lots/<lid>", methods=["GET"])
def get_lot(lid):
    uid, role = auth_and_authorize({"StoreStaff", "Franchisee"})
    lot = get_or_404(db.lots, lid, "InventoryLot")
    store = store_of(lot["store_id"])
    if role == "StoreStaff" and lot["store_id"] != uid:
        not_owner()
    if role == "Franchisee" and (store is None or store["franchisee_id"] != uid):
        not_owner()
    return respond(serialize(lot), "object", 200)


@app.route("/inventory-lots", methods=["GET"])
def list_lots():
    uid, role = auth_and_authorize({"StoreStaff", "Franchisee"})
    q_store = request.args.get("store_id")
    q_ing = request.args.get("ingredient_id")
    status = request.args.get("status")
    if status is not None and status not in {"AVAILABLE", "DEPLETED", "SPOILED"}:
        bad_request("Invalid status filter")
    items = list(db.lots.values())
    if role == "StoreStaff":
        items = [l for l in items if l["store_id"] == uid]
    elif role == "Franchisee":
        items = [l for l in items
                 if store_of(l["store_id"]) is not None
                 and store_of(l["store_id"])["franchisee_id"] == uid]
    if q_store is not None:
        items = [l for l in items if l["store_id"] == q_store]
    if q_ing is not None:
        items = [l for l in items if l["ingredient_id"] == q_ing]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return paginate_and_respond(items)


@app.route("/stores/<sid>/spoilage-sweep", methods=["POST"])
def spoilage_sweep(sid):
    uid, role = auth_and_authorize({"StoreStaff", "PlatformAdmin"})
    store = get_or_404(db.stores, sid, "Store")
    if role == "StoreStaff" and store["id"] != uid:
        not_owner()
    now = clock_now()
    spoiled = []
    total_writeoff = 0
    lots = [l for l in db.lots.values() if l["store_id"] == sid and l["status"] == "AVAILABLE"]
    lots.sort(key=sort_key)
    for lot in lots:
        if lot["_dt_expiry"] <= now:
            lot["spoiled_qty"] = lot["remaining_qty"]
            writeoff = lot["spoiled_qty"] * lot["unit_cost_cents"]
            lot["remaining_qty"] = 0
            lot["status"] = "SPOILED"
            touch(lot)
            total_writeoff += writeoff
            spoiled.append(lot)
    if total_writeoff > 0:
        store["mtd_spoilage_cents"] += total_writeoff
        touch(store)
    data = [serialize(l) for l in spoiled]
    return respond(data, "array", 200,
                   {"limit": len(data), "offset": 0, "total_count": len(data), "has_more": False})


# --- Menu items ---------------------------------------------------------
@app.route("/menu-items", methods=["POST"])
def create_menu_item():
    uid, role = auth_and_authorize({"PlatformAdmin"})
    body = get_body()
    name = check_str(require_present(body, "name"), "name")
    category = check_enum(require_present(body, "category"), "category", MENU_CATEGORIES)
    base_price = check_int(require_present(body, "base_price_cents"), "base_price_cents")
    base_calories = check_int(require_present(body, "base_calories"), "base_calories")
    recipe_raw = require_present(body, "recipe")
    if not isinstance(recipe_raw, list):
        bad_request("recipe must be a list")
    recipe = []
    for entry in recipe_raw:
        if not isinstance(entry, dict):
            bad_request("recipe entries must be objects")
        ing_id = entry.get("ingredient_id")
        base_qty = entry.get("base_qty")
        if not isinstance(ing_id, str):
            bad_request("recipe.ingredient_id must be a string")
        if isinstance(base_qty, bool) or not isinstance(base_qty, int):
            bad_request("recipe.base_qty must be an integer")
        if base_qty < 0:
            bad_request("recipe.base_qty must not be negative")
        recipe.append({"ingredient_id": ing_id, "base_qty": base_qty})
    allergen_tags = check_allergen_tags(body.get("allergen_tags"), "allergen_tags")
    # existence of recipe ingredients
    for entry in recipe:
        get_or_404(db.ingredients, entry["ingredient_id"], "Ingredient")

    ent = base_common()
    ent.update({
        "name": name,
        "category": category,
        "base_price_cents": base_price,
        "recipe": recipe,
        "base_calories": base_calories,
        "allergen_tags": allergen_tags,
    })
    db.menu_items[ent["id"]] = ent
    return respond(serialize(ent), "object", 201)


@app.route("/menu-items", methods=["GET"])
def list_menu_items():
    auth_and_authorize({"PlatformAdmin", "Franchisee", "StoreStaff", "Customer"})
    category = request.args.get("category")
    if category is not None and category not in MENU_CATEGORIES:
        bad_request("Invalid category filter")
    items = list(db.menu_items.values())
    if category is not None:
        items = [m for m in items if m["category"] == category]
    return paginate_and_respond(items)


@app.route("/menu-items/<mid>", methods=["GET"])
def get_menu_item(mid):
    auth_and_authorize({"PlatformAdmin", "Franchisee", "StoreStaff", "Customer"})
    ent = get_or_404(db.menu_items, mid, "MenuItem")
    return respond(serialize(ent), "object", 200)


# --- Boosts -------------------------------------------------------------
@app.route("/boosts", methods=["POST"])
def create_boost():
    uid, role = auth_and_authorize({"PlatformAdmin"})
    body = get_body()
    name = check_str(require_present(body, "name"), "name")
    price_cents = check_int(require_present(body, "price_cents"), "price_cents")
    calories = check_int(require_present(body, "calories"), "calories")
    allergen_tags = check_allergen_tags(body.get("allergen_tags"), "allergen_tags")
    ent = base_common()
    ent.update({
        "name": name,
        "price_cents": price_cents,
        "calories": calories,
        "allergen_tags": allergen_tags,
    })
    db.boosts[ent["id"]] = ent
    return respond(serialize(ent), "object", 201)


@app.route("/boosts", methods=["GET"])
def list_boosts():
    auth_and_authorize({"PlatformAdmin", "Franchisee", "StoreStaff", "Customer"})
    return paginate_and_respond(list(db.boosts.values()))


# --- Customers ----------------------------------------------------------
@app.route("/customers", methods=["POST"])
def create_customer():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None and uid is None:
        pass  # unauthenticated visitor may self-register
    elif role is None or uid is None or role == "" or uid == "":
        unauthenticated()
    elif role not in VALID_ROLES:
        unauthenticated("Unknown role: %s" % role)
    elif role not in {"Anonymous", "PlatformAdmin"}:
        unauthorized("Role %s may not register a customer" % role)

    body = get_body()
    email = check_str(require_present(body, "email"), "email")
    full_name = check_str(require_present(body, "full_name"), "full_name")
    allergen_avoid = check_allergen_tags(body.get("allergen_avoid"), "allergen_avoid")

    ent = base_common()
    ent.update({
        "email": email,
        "full_name": full_name,
        "allergen_avoid": allergen_avoid,
        "points_balance": 0,
        "lifetime_points_earned": 0,
        "loyalty_tier": "BRONZE",
    })
    db.customers[ent["id"]] = ent
    return respond(serialize(ent), "object", 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    uid, role = auth_and_authorize({"Customer", "PlatformAdmin"})
    ent = get_or_404(db.customers, cid, "Customer")
    if role == "Customer" and ent["id"] != uid:
        not_owner()
    return respond(serialize(ent), "object", 200)


# --- Subscriptions ------------------------------------------------------
@app.route("/customers/<cid>/subscriptions", methods=["POST"])
def create_subscription(cid):
    uid, role = auth_and_authorize({"Customer"})
    body = get_body()
    tier = check_enum(require_present(body, "tier"), "tier", SUB_TIERS)
    monthly_fee = check_int(require_present(body, "monthly_fee_cents"), "monthly_fee_cents")
    included_credits = check_int(require_present(body, "included_smoothie_credits"), "included_smoothie_credits")
    renewal_bonus = body.get("renewal_bonus_points", 0)
    if renewal_bonus is None:
        renewal_bonus = 0
    check_int(renewal_bonus, "renewal_bonus_points")

    customer = get_or_404(db.customers, cid, "Customer")
    if customer["id"] != uid:
        not_owner()
    if get_customer_non_cancelled_subscription(cid) is not None:
        err("ERR_SUBSCRIPTION_EXISTS", 409, "Customer already has a non-cancelled subscription")

    sub = base_common()
    sub.update({
        "customer_id": cid,
        "tier": tier,
        "monthly_fee_cents": monthly_fee,
        "included_smoothie_credits": included_credits,
        "credits_remaining": included_credits,
        "renewal_bonus_points": renewal_bonus,
        "cycle_index": 1,
        "status": "ACTIVE",
    })
    db.subscriptions[sub["id"]] = sub
    return respond(serialize(sub), "object", 201)


@app.route("/customers/<cid>/subscriptions", methods=["GET"])
def list_subscriptions(cid):
    uid, role = auth_and_authorize({"Customer", "PlatformAdmin"})
    customer = get_or_404(db.customers, cid, "Customer")
    if role == "Customer" and customer["id"] != uid:
        not_owner()
    status = request.args.get("status")
    if status is not None and status not in {"ACTIVE", "PAST_DUE", "CANCELLED"}:
        bad_request("Invalid status filter")
    items = [s for s in db.subscriptions.values() if s["customer_id"] == cid]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paginate_and_respond(items)


@app.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    uid, role = auth_and_authorize({"Customer", "PlatformAdmin"})
    sub = get_or_404(db.subscriptions, sid, "Subscription")
    if role == "Customer" and sub["customer_id"] != uid:
        not_owner()
    return respond(serialize(sub), "object", 200)


@app.route("/subscriptions/<sid>/renew", methods=["POST"])
def renew_subscription(sid):
    uid, role = auth_and_authorize({"PlatformAdmin"})
    body = get_body()
    outcome = check_enum(require_present(body, "payment_outcome"), "payment_outcome", PAYMENT_OUTCOMES)
    sub = get_or_404(db.subscriptions, sid, "Subscription")
    status = sub["status"]
    if status not in {"ACTIVE", "PAST_DUE"}:
        invalid_state("Cannot renew a %s subscription" % status)

    customer = db.customers[sub["customer_id"]]
    if outcome == "SUCCESS":
        # ACTIVE->ACTIVE or PAST_DUE->ACTIVE : same effects
        sub["status"] = "ACTIVE"
        sub["cycle_index"] += 1
        sub["credits_remaining"] = sub["included_smoothie_credits"]
        touch(sub)
        if sub["renewal_bonus_points"] > 0:
            add_points_txn(customer, "SUBSCRIPTION_BONUS", sub["renewal_bonus_points"], None)
    else:  # FAIL
        if status == "ACTIVE":
            sub["status"] = "PAST_DUE"
            touch(sub)
        else:  # PAST_DUE -> CANCELLED
            sub["status"] = "CANCELLED"
            sub["credits_remaining"] = 0
            touch(sub)
    return respond(serialize(sub), "object", 200)


@app.route("/subscriptions/<sid>/change-plan", methods=["POST"])
def change_plan(sid):
    uid, role = auth_and_authorize({"Customer"})
    body = get_body()
    expected = require_present(body, "expected_subscription_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        bad_request("expected_subscription_version must be an integer")
    tier = check_enum(require_present(body, "tier"), "tier", SUB_TIERS)
    monthly_fee = check_int(require_present(body, "monthly_fee_cents"), "monthly_fee_cents")
    included_credits = check_int(require_present(body, "included_smoothie_credits"), "included_smoothie_credits")
    renewal_bonus = body.get("renewal_bonus_points", 0)
    if renewal_bonus is None:
        renewal_bonus = 0
    check_int(renewal_bonus, "renewal_bonus_points")

    sub = get_or_404(db.subscriptions, sid, "Subscription")
    if sub["customer_id"] != uid:
        not_owner()
    if sub["status"] != "ACTIVE":
        invalid_state("Cannot change plan on a %s subscription" % sub["status"])
    if expected != sub["version"]:
        stale_version("expected_subscription_version %s != current %s" % (expected, sub["version"]))

    sub["tier"] = tier
    sub["monthly_fee_cents"] = monthly_fee
    sub["included_smoothie_credits"] = included_credits
    sub["renewal_bonus_points"] = renewal_bonus
    sub["credits_remaining"] = included_credits
    touch(sub)
    return respond(serialize(sub), "object", 200)


@app.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    uid, role = auth_and_authorize({"Customer"})
    sub = get_or_404(db.subscriptions, sid, "Subscription")
    if sub["customer_id"] != uid:
        not_owner()
    if sub["status"] not in {"ACTIVE", "PAST_DUE"}:
        invalid_state("Cannot cancel a %s subscription" % sub["status"])
    sub["status"] = "CANCELLED"
    sub["credits_remaining"] = 0
    touch(sub)
    return respond(serialize(sub), "object", 200)


# --- Points transactions ------------------------------------------------
@app.route("/customers/<cid>/points-transactions", methods=["GET"])
def list_customer_points(cid):
    uid, role = auth_and_authorize({"Customer", "PlatformAdmin"})
    customer = get_or_404(db.customers, cid, "Customer")
    if role == "Customer" and customer["id"] != uid:
        not_owner()
    reason = request.args.get("reason")
    if reason is not None and reason not in {"EARN", "REDEEM", "CLAWBACK", "SUBSCRIPTION_BONUS"}:
        bad_request("Invalid reason filter")
    items = [t for t in db.points_txns.values() if t["customer_id"] == cid]
    if reason is not None:
        items = [t for t in items if t["reason"] == reason]
    return paginate_and_respond(items)


@app.route("/orders/<oid>/points-transactions", methods=["GET"])
def list_order_points(oid):
    uid, role = auth_and_authorize({"Customer", "StoreStaff", "PlatformAdmin"})
    order = get_or_404(db.orders, oid, "Order")
    if role == "Customer" and order["customer_id"] != uid:
        not_owner()
    if role == "StoreStaff" and order["store_id"] != uid:
        not_owner()
    items = [t for t in db.points_txns.values() if t["order_id"] == oid]
    return paginate_and_respond(items)


# --- Orders -------------------------------------------------------------
def validate_order_lines(lines_raw):
    if not isinstance(lines_raw, list) or len(lines_raw) == 0:
        bad_request("lines must be a non-empty list")
    lines = []
    for line in lines_raw:
        if not isinstance(line, dict):
            bad_request("each line must be an object")
        menu_item_id = line.get("menu_item_id")
        if not isinstance(menu_item_id, str):
            bad_request("line.menu_item_id must be a string")
        size = check_enum(line.get("size"), "size", SIZES)
        boost_ids = line.get("boost_ids", [])
        if boost_ids is None:
            boost_ids = []
        if not isinstance(boost_ids, list) or any(not isinstance(b, str) for b in boost_ids):
            bad_request("line.boost_ids must be a list of strings")
        lines.append({"menu_item_id": menu_item_id, "size": size, "boost_ids": list(boost_ids)})
    return lines


@app.route("/orders", methods=["POST"])
def place_order():
    uid, role = auth_and_authorize({"Customer"})
    body = get_body()
    store_id = require_present(body, "store_id")
    if not isinstance(store_id, str):
        bad_request("store_id must be a string")
    lines = validate_order_lines(require_present(body, "lines"))
    redeem_points = body.get("redeem_points", 0)
    if redeem_points is None:
        redeem_points = 0
    check_int(redeem_points, "redeem_points")
    use_credit = body.get("use_subscription_credit", False)
    if use_credit is None:
        use_credit = False
    check_bool(use_credit, "use_subscription_credit")

    # existence
    store = get_or_404(db.stores, store_id, "Store")
    for line in lines:
        get_or_404(db.menu_items, line["menu_item_id"], "MenuItem")
        for b in line["boost_ids"]:
            get_or_404(db.boosts, b, "BoostAddIn")

    # ownership (acting customer)
    customer = db.customers.get(uid)
    if customer is None:
        not_owner("Acting customer does not exist")

    # store open
    if store["status"] != "OPEN":
        store_not_open()

    # allergen safety (per line)
    avoid = set(customer["allergen_avoid"] or [])
    for line in lines:
        if set(compute_line_allergens(line)) & avoid:
            err("ERR_ALLERGEN_CONFLICT", 422, "Line allergens conflict with customer's avoid list")

    # subscription credit requirement
    active_sub = get_customer_active_subscription(uid)
    if use_credit and active_sub is None:
        err("ERR_NO_ACTIVE_SUBSCRIPTION", 409, "No active subscription for credit application")

    # pricing / nutrition
    pricing = compute_pricing(lines, customer, active_sub, redeem_points, use_credit)

    # inventory availability (does not consume at placement)
    required = compute_required_units(lines)
    if not inventory_sufficient(store_id, required):
        err("ERR_INSUFFICIENT_INVENTORY", 409, "Insufficient ingredient inventory")

    # points sufficiency
    if redeem_points > customer["points_balance"]:
        err("ERR_INSUFFICIENT_POINTS", 422, "redeem_points exceeds points balance")

    order = base_common()
    order.update({
        "store_id": store_id,
        "customer_id": uid,
        "lines": pricing["lines"],
        "redeem_points": redeem_points,
        "use_subscription_credit": use_credit,
        "fulfillment_status": "PLACED",
        "payment_status": "PENDING",
        "subtotal_cents": pricing["subtotal_cents"],
        "redeem_discount_cents": pricing["redeem_discount_cents"],
        "discounted_subtotal_cents": pricing["discounted_subtotal_cents"],
        "tax_cents": pricing["tax_cents"],
        "total_cents": pricing["total_cents"],
        "gross_merch_cents": pricing["gross_merch_cents"],
        "cogs_provisional_cents": 0,
        "cogs_final_cents": 0,
        "credits_used": pricing["credits_used"],
        "points_earned": 0,
        "total_calories": pricing["total_calories"],
        "allergen_summary": pricing["allergen_summary"],
        "paid_at": None,
        "completed_at": None,
        "cancelled_at": None,
        "_consumption": [],
        "_subscription_id": None,
    })
    db.orders[order["id"]] = order

    # Redemption debit at placement (points validated above).
    if pricing["redeem_discount_cents"] > 0:
        add_points_txn(customer, "REDEEM", -pricing["redeem_discount_cents"], order["id"])

    return respond(serialize(order), "object", 201)


@app.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    uid, role = auth_and_authorize({"Customer", "StoreStaff", "PlatformAdmin"})
    order = get_or_404(db.orders, oid, "Order")
    if role == "Customer" and order["customer_id"] != uid:
        not_owner()
    if role == "StoreStaff" and order["store_id"] != uid:
        not_owner()
    return respond(serialize(order), "object", 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    uid, role = auth_and_authorize({"Customer", "StoreStaff", "PlatformAdmin"})
    q_store = request.args.get("store_id")
    q_customer = request.args.get("customer_id")
    status = request.args.get("status")
    items = list(db.orders.values())
    if role == "Customer":
        items = [o for o in items if o["customer_id"] == uid]
    elif role == "StoreStaff":
        items = [o for o in items if o["store_id"] == uid]
    if q_store is not None:
        items = [o for o in items if o["store_id"] == q_store]
    if q_customer is not None:
        items = [o for o in items if o["customer_id"] == q_customer]
    if status is not None:
        items = [o for o in items
                 if o["fulfillment_status"] == status or o["payment_status"] == status]
    return paginate_and_respond(items)


@app.route("/orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    uid, role = auth_and_authorize({"Customer"})
    order = get_or_404(db.orders, oid, "Order")
    if order["customer_id"] != uid:
        not_owner()
    if not (order["fulfillment_status"] == "PLACED" and order["payment_status"] == "PENDING"):
        invalid_state("Order is not in a payable state")
    store = db.stores.get(order["store_id"])
    if store is None or store["status"] != "OPEN":
        store_not_open()

    customer = db.customers[order["customer_id"]]
    use_credit = order["use_subscription_credit"]
    active_sub = get_customer_active_subscription(order["customer_id"])
    if use_credit and active_sub is None:
        err("ERR_NO_ACTIVE_SUBSCRIPTION", 409, "No active subscription for credit application")

    # re-lock pricing at current tier/credits
    lines_input = [{"menu_item_id": l["menu_item_id"], "size": l["size"],
                    "boost_ids": l["boost_ids"]} for l in order["lines"]]
    pricing = compute_pricing(lines_input, customer, active_sub,
                              order["redeem_points"], use_credit)

    required = compute_required_units(lines_input)
    if not inventory_sufficient(order["store_id"], required):
        err("ERR_INSUFFICIENT_INVENTORY", 409, "Insufficient ingredient inventory")
    consumption = consume_inventory(order["store_id"], required)

    # provisional COGS (standard cost)
    cogs_prov = 0
    for ing_id, units in required.items():
        ing = db.ingredients[ing_id]
        cogs_prov += units * ing["standard_cost_cents_per_unit"]

    points_earned = pricing["discounted_subtotal_cents"] // 100

    # apply computed order fields
    order["lines"] = pricing["lines"]
    order["subtotal_cents"] = pricing["subtotal_cents"]
    order["redeem_discount_cents"] = pricing["redeem_discount_cents"]
    order["discounted_subtotal_cents"] = pricing["discounted_subtotal_cents"]
    order["tax_cents"] = pricing["tax_cents"]
    order["total_cents"] = pricing["total_cents"]
    order["gross_merch_cents"] = pricing["gross_merch_cents"]
    order["total_calories"] = pricing["total_calories"]
    order["allergen_summary"] = pricing["allergen_summary"]
    order["credits_used"] = pricing["credits_used"]
    order["cogs_provisional_cents"] = cogs_prov
    order["points_earned"] = points_earned
    order["_consumption"] = consumption

    # decrement subscription credits
    if use_credit and pricing["credits_used"] > 0 and active_sub is not None:
        active_sub["credits_remaining"] -= pricing["credits_used"]
        touch(active_sub)
        order["_subscription_id"] = active_sub["id"]

    # earn points
    if points_earned > 0:
        add_points_txn(customer, "EARN", points_earned, order["id"])

    order["payment_status"] = "PAID"
    order["fulfillment_status"] = "PREPARING"
    order["paid_at"] = now_str()
    touch(order)
    return respond(serialize(order), "object", 200)


@app.route("/orders/<oid>/ready", methods=["POST"])
def ready_order(oid):
    uid, role = auth_and_authorize({"StoreStaff"})
    order = get_or_404(db.orders, oid, "Order")
    if order["store_id"] != uid:
        not_owner()
    if order["fulfillment_status"] != "PREPARING":
        invalid_state("Order is not PREPARING")
    order["fulfillment_status"] = "READY"
    touch(order)
    return respond(serialize(order), "object", 200)


@app.route("/orders/<oid>/complete", methods=["POST"])
def complete_order(oid):
    uid, role = auth_and_authorize({"StoreStaff"})
    order = get_or_404(db.orders, oid, "Order")
    if order["store_id"] != uid:
        not_owner()
    if order["fulfillment_status"] != "READY":
        invalid_state("Order is not READY")
    cogs_final = sum(c["qty"] * c["unit_cost_cents"] for c in order["_consumption"])
    order["cogs_final_cents"] = cogs_final
    order["fulfillment_status"] = "PICKED_UP"
    order["completed_at"] = now_str()
    touch(order)
    return respond(serialize(order), "object", 200)


@app.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    uid, role = auth_and_authorize({"Customer", "StoreStaff"})
    order = get_or_404(db.orders, oid, "Order")
    if role == "Customer" and order["customer_id"] != uid:
        not_owner()
    if role == "StoreStaff" and order["store_id"] != uid:
        not_owner()
    if order["fulfillment_status"] not in {"PLACED", "PREPARING", "READY"}:
        invalid_state("Order cannot be cancelled from %s" % order["fulfillment_status"])

    if order["payment_status"] == "PAID":
        # restore inventory
        restore_inventory(order["_consumption"])
        order["payment_status"] = "REFUNDED"
        # clawback earned points
        if order["points_earned"] > 0:
            customer = db.customers[order["customer_id"]]
            add_points_txn(customer, "CLAWBACK", -order["points_earned"], order["id"])
        # restore credits
        if order["credits_used"] > 0 and order["_subscription_id"]:
            sub = db.subscriptions.get(order["_subscription_id"])
            if sub is not None:
                sub["credits_remaining"] += order["credits_used"]
                touch(sub)
    order["fulfillment_status"] = "CANCELLED"
    order["cancelled_at"] = now_str()
    touch(order)
    return respond(serialize(order), "object", 200)


# --- Catering bookings --------------------------------------------------
def windows_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@app.route("/stores/<sid>/catering-bookings", methods=["POST"])
def create_booking(sid):
    uid, role = auth_and_authorize({"Customer"})
    body = get_body()
    customer_id = require_present(body, "customer_id")
    if not isinstance(customer_id, str):
        bad_request("customer_id must be a string")
    fulfillment_type = check_enum(require_present(body, "fulfillment_type"), "fulfillment_type", FULFILLMENT_TYPES)
    headcount = check_int(require_present(body, "headcount"), "headcount", min_value=1)
    items_raw = require_present(body, "items")
    if not isinstance(items_raw, list) or len(items_raw) == 0:
        bad_request("items must be a non-empty list")
    items = []
    for it in items_raw:
        if not isinstance(it, dict):
            bad_request("each item must be an object")
        mi_id = it.get("menu_item_id")
        qty = it.get("qty")
        if not isinstance(mi_id, str):
            bad_request("item.menu_item_id must be a string")
        check_int(qty, "item.qty", min_value=1)
        items.append({"menu_item_id": mi_id, "qty": qty})
    prep_start_raw = require_present(body, "prep_window_start")
    prep_end_raw = require_present(body, "prep_window_end")
    prep_start = parse_dt(prep_start_raw)
    prep_end = parse_dt(prep_end_raw)
    if prep_start is None or prep_end is None:
        bad_request("prep window must be valid datetimes")

    delivery_vehicle_id = body.get("delivery_vehicle_id")
    del_start_raw = body.get("delivery_window_start")
    del_end_raw = body.get("delivery_window_end")
    del_start = del_end = None
    if fulfillment_type == "DELIVERY":
        if delivery_vehicle_id is None or not isinstance(delivery_vehicle_id, str):
            bad_request("delivery_vehicle_id required for DELIVERY")
        if del_start_raw is None or del_end_raw is None:
            bad_request("delivery window required for DELIVERY")
        del_start = parse_dt(del_start_raw)
        del_end = parse_dt(del_end_raw)
        if del_start is None or del_end is None:
            bad_request("delivery window must be valid datetimes")

    # existence
    store = get_or_404(db.stores, sid, "Store")
    customer = get_or_404(db.customers, customer_id, "Customer")
    for it in items:
        get_or_404(db.menu_items, it["menu_item_id"], "MenuItem")
    vehicle = None
    if fulfillment_type == "DELIVERY":
        vehicle = get_or_404(db.vehicles, delivery_vehicle_id, "DeliveryVehicle")

    # ownership
    if customer["id"] != uid:
        not_owner()

    now = clock_now()
    # window validity
    if not (prep_start < prep_end):
        err("ERR_INVALID_WINDOW", 422, "prep_window_start must be before prep_window_end")
    if prep_start < now:
        err("ERR_INVALID_WINDOW", 422, "prep window may not be in the past")
    if fulfillment_type == "DELIVERY":
        if not (del_start < del_end):
            err("ERR_INVALID_WINDOW", 422, "delivery_window_start must be before delivery_window_end")
        if del_start < now:
            err("ERR_INVALID_WINDOW", 422, "delivery window may not be in the past")

    # vehicle availability
    if fulfillment_type == "DELIVERY":
        if vehicle["status"] != "AVAILABLE":
            err("ERR_VEHICLE_UNAVAILABLE", 409, "Vehicle is not AVAILABLE")
        # double-book
        for b in db.bookings.values():
            if b["delivery_vehicle_id"] == delivery_vehicle_id and b["status"] != "CANCELLED":
                if windows_overlap(del_start, del_end, b["_dt_del_start"], b["_dt_del_end"]):
                    err("ERR_VEHICLE_DOUBLE_BOOKED", 409, "Delivery window overlaps another booking")

    # catering capacity (overlapping prep windows, non-cancelled)
    overlap_headcount = 0
    for b in db.bookings.values():
        if b["store_id"] == sid and b["status"] != "CANCELLED":
            if windows_overlap(prep_start, prep_end, b["_dt_prep_start"], b["_dt_prep_end"]):
                overlap_headcount += b["headcount"]
    if overlap_headcount + headcount > store["catering_capacity"]:
        err("ERR_CATERING_CAPACITY_EXCEEDED", 409, "Catering capacity exceeded")

    # quote
    items_total = sum(db.menu_items[it["menu_item_id"]]["base_price_cents"] * it["qty"] for it in items)
    service_fee = headcount * CATERING_SERVICE_FEE_PER_HEAD_CENTS
    tax = rhu(Decimal(items_total + service_fee) * TAX_RATE)
    quoted = items_total + service_fee + tax

    booking = base_common()
    booking.update({
        "store_id": sid,
        "customer_id": customer_id,
        "delivery_vehicle_id": delivery_vehicle_id if fulfillment_type == "DELIVERY" else None,
        "fulfillment_type": fulfillment_type,
        "headcount": headcount,
        "items": items,
        "prep_window_start": prep_start_raw,
        "prep_window_end": prep_end_raw,
        "delivery_window_start": del_start_raw if fulfillment_type == "DELIVERY" else None,
        "delivery_window_end": del_end_raw if fulfillment_type == "DELIVERY" else None,
        "quoted_price_cents": quoted,
        "status": "REQUESTED",
        "_dt_prep_start": prep_start,
        "_dt_prep_end": prep_end,
        "_dt_del_start": del_start,
        "_dt_del_end": del_end,
    })
    db.bookings[booking["id"]] = booking
    return respond(serialize(booking), "object", 201)


@app.route("/catering-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    uid, role = auth_and_authorize({"Customer", "StoreStaff", "PlatformAdmin"})
    booking = get_or_404(db.bookings, bid, "CateringBooking")
    if role == "Customer" and booking["customer_id"] != uid:
        not_owner()
    if role == "StoreStaff" and booking["store_id"] != uid:
        not_owner()
    return respond(serialize(booking), "object", 200)


@app.route("/catering-bookings", methods=["GET"])
def list_bookings():
    uid, role = auth_and_authorize({"Customer", "StoreStaff", "PlatformAdmin"})
    q_store = request.args.get("store_id")
    q_customer = request.args.get("customer_id")
    q_vehicle = request.args.get("delivery_vehicle_id")
    status = request.args.get("status")
    items = list(db.bookings.values())
    if role == "Customer":
        items = [b for b in items if b["customer_id"] == uid]
    elif role == "StoreStaff":
        items = [b for b in items if b["store_id"] == uid]
    if q_store is not None:
        items = [b for b in items if b["store_id"] == q_store]
    if q_customer is not None:
        items = [b for b in items if b["customer_id"] == q_customer]
    if q_vehicle is not None:
        items = [b for b in items if b["delivery_vehicle_id"] == q_vehicle]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginate_and_respond(items)


@app.route("/catering-bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    uid, role = auth_and_authorize({"StoreStaff"})
    booking = get_or_404(db.bookings, bid, "CateringBooking")
    if booking["store_id"] != uid:
        not_owner()
    if booking["status"] != "REQUESTED":
        invalid_state("Booking is not REQUESTED")
    store = db.stores.get(booking["store_id"])
    if store is None or store["status"] != "OPEN":
        store_not_open()
    booking["status"] = "CONFIRMED"
    touch(booking)
    return respond(serialize(booking), "object", 200)


@app.route("/catering-bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    uid, role = auth_and_authorize({"StoreStaff"})
    booking = get_or_404(db.bookings, bid, "CateringBooking")
    if booking["store_id"] != uid:
        not_owner()
    if booking["status"] not in {"REQUESTED", "CONFIRMED"}:
        invalid_state("Booking cannot be completed from %s" % booking["status"])
    if clock_now() < booking["_dt_prep_start"]:
        invalid_state("Cannot complete before prep_window_start")
    booking["status"] = "COMPLETED"
    touch(booking)
    return respond(serialize(booking), "object", 200)


@app.route("/catering-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    uid, role = auth_and_authorize({"Customer", "StoreStaff"})
    booking = get_or_404(db.bookings, bid, "CateringBooking")
    if role == "Customer" and booking["customer_id"] != uid:
        not_owner()
    if role == "StoreStaff" and booking["store_id"] != uid:
        not_owner()
    if booking["status"] not in {"REQUESTED", "CONFIRMED"}:
        invalid_state("Booking cannot be cancelled from %s" % booking["status"])
    booking["status"] = "CANCELLED"
    touch(booking)
    return respond(serialize(booking), "object", 200)


# --- Reconciliations ----------------------------------------------------
def reconciliation_order_set(store_id, business_date):
    result = []
    for o in db.orders.values():
        if o["store_id"] != store_id:
            continue
        if o["fulfillment_status"] != "PICKED_UP":
            continue
        if not o["completed_at"]:
            continue
        if o["completed_at"][:10] == business_date:
            result.append(o)
    return result


@app.route("/stores/<sid>/reconciliations", methods=["POST"])
def open_reconciliation(sid):
    uid, role = auth_and_authorize({"StoreStaff"})
    body = get_body()
    business_date_raw = require_present(body, "business_date")
    bdate = parse_business_date(business_date_raw)
    if bdate is None:
        bad_request("business_date must be an ISO date YYYY-MM-DD")
    business_date = bdate.isoformat()

    store = get_or_404(db.stores, sid, "Store")
    if store["id"] != uid:
        not_owner()

    for r in db.reconciliations.values():
        if r["store_id"] == sid and r["business_date"] == business_date and r["status"] != "POSTED":
            err("ERR_RECONCILIATION_EXISTS", 409, "A non-posted reconciliation already exists")

    order_set = reconciliation_order_set(sid, business_date)
    expected = sum(o["total_cents"] for o in order_set)
    gross = sum(o["gross_merch_cents"] for o in order_set)
    net = sum(o["discounted_subtotal_cents"] for o in order_set)

    recon = base_common()
    recon.update({
        "store_id": sid,
        "business_date": business_date,
        "status": "OPEN",
        "expected_sales_cents": expected,
        "gross_sales_cents": gross,
        "net_sales_cents": net,
        "counted_cash_cents": 0,
        "variance_cents": 0,
        "royalty_basis": "NET",
        "royalty_rate_applied": 0,
        "royalty_due_cents": 0,
        "marketing_fee_cents": 0,
        "total_franchise_due_cents": 0,
    })
    db.reconciliations[recon["id"]] = recon
    return respond(serialize(recon), "object", 201)


@app.route("/stores/<sid>/reconciliations", methods=["GET"])
def list_reconciliations(sid):
    uid, role = auth_and_authorize({"StoreStaff", "Franchisee"})
    store = get_or_404(db.stores, sid, "Store")
    if role == "StoreStaff" and store["id"] != uid:
        not_owner()
    if role == "Franchisee" and store["franchisee_id"] != uid:
        not_owner()
    business_date = request.args.get("business_date")
    status = request.args.get("status")
    if status is not None and status not in {"OPEN", "COUNTED", "POSTED"}:
        bad_request("Invalid status filter")
    items = [r for r in db.reconciliations.values() if r["store_id"] == sid]
    if business_date is not None:
        items = [r for r in items if r["business_date"] == business_date]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate_and_respond(items)


@app.route("/reconciliations/<rid>", methods=["GET"])
def get_reconciliation(rid):
    uid, role = auth_and_authorize({"StoreStaff", "Franchisee", "PlatformAdmin"})
    recon = get_or_404(db.reconciliations, rid, "DailyReconciliation")
    store = db.stores.get(recon["store_id"])
    if role == "StoreStaff" and recon["store_id"] != uid:
        not_owner()
    if role == "Franchisee" and (store is None or store["franchisee_id"] != uid):
        not_owner()
    return respond(serialize(recon), "object", 200)


@app.route("/reconciliations/<rid>/count", methods=["POST"])
def count_reconciliation(rid):
    uid, role = auth_and_authorize({"StoreStaff"})
    body = get_body()
    counted = check_int(require_present(body, "counted_cash_cents"), "counted_cash_cents")
    recon = get_or_404(db.reconciliations, rid, "DailyReconciliation")
    if recon["store_id"] != uid:
        not_owner()
    if recon["status"] != "OPEN":
        invalid_state("Reconciliation is not OPEN")
    recon["counted_cash_cents"] = counted
    recon["variance_cents"] = counted - recon["expected_sales_cents"]
    recon["status"] = "COUNTED"
    touch(recon)
    return respond(serialize(recon), "object", 200)


@app.route("/reconciliations/<rid>/post", methods=["POST"])
def post_reconciliation(rid):
    uid, role = auth_and_authorize({"Franchisee", "PlatformAdmin"})
    body = get_body()
    royalty_basis = body.get("royalty_basis", "NET")
    if royalty_basis is None:
        royalty_basis = "NET"
    check_enum(royalty_basis, "royalty_basis", ROYALTY_BASES)

    recon = get_or_404(db.reconciliations, rid, "DailyReconciliation")
    store = db.stores.get(recon["store_id"])
    if role == "Franchisee" and (store is None or store["franchisee_id"] != uid):
        not_owner()
    if recon["status"] != "COUNTED":
        invalid_state("Reconciliation is not COUNTED")

    franchisee = db.franchisees[store["franchisee_id"]]
    net = recon["net_sales_cents"]
    gross = recon["gross_sales_cents"]
    basis_sales = net if royalty_basis == "NET" else gross

    if store["royalty_rate_override"] is not None:
        effective_rate = store["royalty_rate_override"]
    else:
        effective_rate = franchisee["base_royalty_rate"]

    if net >= REBATE_THRESHOLD_CENTS:
        rate_applied = float(REBATE_RATE)
    else:
        rate_applied = effective_rate

    royalty_due = rhu(Decimal(basis_sales) * Decimal(str(rate_applied)))
    marketing_fee = rhu(Decimal(basis_sales) * Decimal(str(franchisee["marketing_fee_rate"])))
    total_due = royalty_due + marketing_fee

    recon["royalty_basis"] = royalty_basis
    recon["royalty_rate_applied"] = rate_applied
    recon["royalty_due_cents"] = royalty_due
    recon["marketing_fee_cents"] = marketing_fee
    recon["total_franchise_due_cents"] = total_due
    recon["status"] = "POSTED"
    touch(recon)

    franchisee["lifetime_royalty_cents"] += total_due
    touch(franchisee)
    return respond(serialize(recon), "object", 200)


# --- Logical clock ------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = auth_and_authorize({"PlatformAdmin"})
    body = get_body()
    to_iso = require_present(body, "to_iso8601")
    dt = parse_dt(to_iso)
    if dt is None:
        bad_request("to_iso8601 must be a valid ISO 8601 datetime")
    CLOCK["now"] = dt
    return respond({}, "object", 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
