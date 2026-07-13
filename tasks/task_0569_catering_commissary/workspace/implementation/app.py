import os
import math
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Admin", "KitchenManager", "SalesManager", "EventCaptain"}

UNIT_ENUM = {"GRAM", "ML", "EACH"}
CATEGORY_ENUM = {"ENTREE", "SIDE", "BEVERAGE", "DESSERT"}
ASSET_TYPE_ENUM = {"CHAFER", "LINEN", "TABLE", "GLASSWARE"}
STAFF_ROLE_ENUM = {"SERVER", "BARTENDER", "CHEF"}

OT_THRESHOLD_HOURS = Decimal("8")
OT_MULTIPLIER = Decimal("1.5")
# Not fixed numerically anywhere in the PRD/scaffold; chosen default (minutes).
STAFF_REST_BUFFER_MIN = 60

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_QUANTITY_NOT_POSITIVE": 422,
    "ERR_INVALID_GUEST_COUNT": 422,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_EVENT_ORDER_NOT_FOUND": 404,
    "ERR_MENU_ITEM_NOT_FOUND": 404,
    "ERR_INGREDIENT_NOT_FOUND": 404,
    "ERR_STATION_NOT_FOUND": 404,
    "ERR_EQUIPMENT_NOT_FOUND": 404,
    "ERR_STAFF_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ORDER_NOT_DRAFT": 409,
    "ERR_PRODUCTION_NOT_COMPLETE": 409,
    "ERR_NO_ORDER_LINES": 422,
    "ERR_STAFF_ROLE_MISMATCH": 422,
    "ERR_NO_STAFF_CONFIRMED": 422,
    "ERR_STAFF_DOUBLE_BOOKED": 409,
    "ERR_STATION_OVERBOOKED": 409,
    "ERR_INSUFFICIENT_INVENTORY": 422,
    "ERR_EQUIPMENT_UNAVAILABLE": 409,
    "ERR_STALE_ORDER_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory data store (starts empty on every boot; no seeding)
# ---------------------------------------------------------------------------
db = {
    "ingredients": {},
    "menu_items": {},
    "recipe_lines": {},
    "stations": {},
    "equipment_items": {},
    "staff_members": {},
    "event_orders": {},
    "order_lines": {},
    "quotes": {},
    "production_runs": {},
    "rental_reservations": {},
    "staff_assignments": {},
}

_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def base_record(with_version=True):
    ts = now_iso()
    rec = {"id": new_id(), "created_at": ts, "_seq": next_seq()}
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Serialization / responses
# ---------------------------------------------------------------------------
def conv(v):
    if isinstance(v, Decimal):
        if v == v.to_integral_value():
            return int(v)
        return float(v)
    return v


def serialize(rec):
    return {k: conv(v) for k, v in rec.items() if not k.startswith("_")}


def meta(pagination=None):
    m = {"api_request_id": req_id(), "api_request_timestamp": now_iso()}
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unrecognized auth headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this operation")
    return role


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------
def get_body(optional=False):
    data = request.get_json(silent=True)
    if data is None:
        if optional:
            return {}
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def req_str(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_VALIDATION", f"Missing required field: {name}")
    v = body[name]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be a string")
    return v


def opt_str(body, name):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be a string")
    return v


def req_int(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_VALIDATION", f"Missing required field: {name}")
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be an integer")
    return v


def req_num(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_VALIDATION", f"Missing required field: {name}")
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be a number")
    return Decimal(str(v))


def req_dt(body, name):
    s = req_str(body, name)
    parse_dt(s)  # validate parseability -> ERR_VALIDATION on failure
    return s


def opt_dt(body, name):
    if name not in body or body[name] is None:
        return None
    s = opt_str(body, name)
    parse_dt(s)
    return s


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", "Invalid datetime")
    try:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        raise ApiError("ERR_VALIDATION", "Invalid datetime format")


# ---------------------------------------------------------------------------
# Calculation helpers
# ---------------------------------------------------------------------------
def round_half_up(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_portion_food_cost(menu_item):
    raw = Decimal(0)
    for rl in db["recipe_lines"].values():
        if rl["menu_item_id"] == menu_item["id"]:
            ing = db["ingredients"][rl["ingredient_id"]]
            raw += rl["qty_per_portion"] * Decimal(ing["unit_cost_cents"])
    menu_item["portion_food_cost_cents"] = round_half_up(raw)


def active_order_lines(order_id):
    return [
        ol for ol in db["order_lines"].values()
        if ol["event_order_id"] == order_id and ol["status"] == "ACTIVE"
    ]


def compute_food(order_id, headcount):
    rev = 0
    cost = 0
    for ol in active_order_lines(order_id):
        mi = db["menu_items"][ol["menu_item_id"]]
        p = math.ceil(ol["portions_per_guest"] * Decimal(headcount))
        rev += p * mi["sell_price_cents_per_portion"]
        cost += p * mi["portion_food_cost_cents"]
    return rev, cost


def compute_labor(start_s, end_s, rate):
    start = parse_dt(start_s)
    end = parse_dt(end_s)
    delta = end - start
    total_secs = (
        Decimal(delta.days) * 86400
        + Decimal(delta.seconds)
        + Decimal(delta.microseconds) / Decimal(1000000)
    )
    hours = total_secs / Decimal(3600)
    reg = min(hours, OT_THRESHOLD_HOURS)
    ot = max(hours - OT_THRESHOLD_HOURS, Decimal(0))
    raw = reg * Decimal(rate) + ot * Decimal(rate) * OT_MULTIPLIER
    return round_half_up(raw)


def recipe_needs(menu_item_id, portions):
    needs = []
    for rl in db["recipe_lines"].values():
        if rl["menu_item_id"] == menu_item_id:
            need = rl["qty_per_portion"] * Decimal(portions)
            needs.append((rl["ingredient_id"], need))
    return needs


def commit_ingredients(menu_item_id, portions):
    needs = recipe_needs(menu_item_id, portions)
    # atomic: verify all first
    for ing_id, need in needs:
        ing = db["ingredients"][ing_id]
        if ing["on_hand_qty"] < need:
            raise ApiError("ERR_INSUFFICIENT_INVENTORY", "Insufficient ingredient inventory")
    for ing_id, need in needs:
        ing = db["ingredients"][ing_id]
        ing["on_hand_qty"] = ing["on_hand_qty"] - need
        ing["committed_qty"] = ing["committed_qty"] + need
        touch(ing)


def release_ingredients(menu_item_id, portions):
    for ing_id, need in recipe_needs(menu_item_id, portions):
        ing = db["ingredients"][ing_id]
        ing["on_hand_qty"] = ing["on_hand_qty"] + need
        ing["committed_qty"] = ing["committed_qty"] - need
        touch(ing)


def consume_ingredients(menu_item_id, portions):
    for ing_id, need in recipe_needs(menu_item_id, portions):
        ing = db["ingredients"][ing_id]
        ing["committed_qty"] = ing["committed_qty"] - need
        touch(ing)


def check_station_capacity(station_id, start_s, end_s, capacity, exclude_id=None):
    start = parse_dt(start_s)
    end = parse_dt(end_s)
    runs = [
        r for r in db["production_runs"].values()
        if r["station_id"] == station_id
        and r["status"] in ("SCHEDULED", "IN_PROGRESS")
        and r["id"] != exclude_id
    ]
    overlapping = [
        r for r in runs
        if parse_dt(r["scheduled_start"]) < end and start < parse_dt(r["scheduled_end"])
    ]
    instants = [start] + [max(parse_dt(r["scheduled_start"]), start) for r in overlapping]
    peak = 0
    for t in instants:
        if not (start <= t < end):
            continue
        c = sum(
            1 for r in overlapping
            if parse_dt(r["scheduled_start"]) <= t < parse_dt(r["scheduled_end"])
        )
        peak = max(peak, c)
    if peak + 1 > capacity:
        raise ApiError("ERR_STATION_OVERBOOKED", "Station capacity exceeded")


def equipment_peak(equipment_id, wstart, wend, exclude_id=None):
    res = [
        r for r in db["rental_reservations"].values()
        if r["equipment_item_id"] == equipment_id
        and r["status"] == "ACTIVE"
        and r["id"] != exclude_id
    ]
    if wstart is not None and wend is not None:
        overlapping = [
            r for r in res
            if parse_dt(r["out_time"]) < wend and wstart < parse_dt(r["return_time"])
        ]
        instants = [wstart] + [max(parse_dt(r["out_time"]), wstart) for r in overlapping]
        instants = [t for t in instants if wstart <= t < wend]
    else:
        overlapping = res
        instants = [parse_dt(r["out_time"]) for r in overlapping]
    peak = 0
    for t in instants:
        s = sum(
            r["qty"] for r in overlapping
            if parse_dt(r["out_time"]) <= t < parse_dt(r["return_time"])
        )
        peak = max(peak, s)
    return peak


def check_double_book(staff_member_id, start_s, end_s, exclude_id=None):
    buf = timedelta(minutes=STAFF_REST_BUFFER_MIN)
    start = parse_dt(start_s)
    end = parse_dt(end_s)
    for a in db["staff_assignments"].values():
        if a["staff_member_id"] != staff_member_id:
            continue
        if a["status"] == "CANCELLED":
            continue
        if a["id"] == exclude_id:
            continue
        astart = parse_dt(a["shift_start"])
        aend = parse_dt(a["shift_end"])
        if (start - buf) < aend and astart < (end + buf):
            raise ApiError("ERR_STAFF_DOUBLE_BOOKED", "Staff member double-booked")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_PAGINATION", "limit out of range")
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION", "offset must be >= 0")
    return limit, offset


def paginate_list(items):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda r: r["_seq"])
    total = len(items)
    window = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    data = [serialize(r) for r in window]
    return ok(data, 200, "array", pagination)


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(collection, _id, error_id):
    rec = db[collection].get(_id)
    if rec is None:
        raise ApiError(error_id, "Resource not found")
    return rec


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ===========================================================================
# Ingredient
# ===========================================================================
@app.route("/ingredients", methods=["POST"])
def create_ingredient():
    authenticate({"Admin"})
    body = get_body()
    name = req_str(body, "name")
    unit = req_str(body, "unit")
    unit_cost = req_int(body, "unit_cost_cents")
    on_hand = req_num(body, "on_hand_qty")
    if unit not in UNIT_ENUM:
        raise ApiError("ERR_INVALID_ENUM", "Invalid unit")
    if unit_cost <= 0:
        raise ApiError("ERR_QUANTITY_NOT_POSITIVE", "unit_cost_cents must be > 0")
    rec = base_record()
    rec.update({
        "name": name,
        "unit": unit,
        "unit_cost_cents": unit_cost,
        "on_hand_qty": on_hand,
        "committed_qty": Decimal(0),
    })
    db["ingredients"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/ingredients/<_id>", methods=["GET"])
def get_ingredient(_id):
    authenticate(ROLES)
    rec = get_or_404("ingredients", _id, "ERR_INGREDIENT_NOT_FOUND")
    return ok(serialize(rec), 200)


# ===========================================================================
# MenuItem
# ===========================================================================
@app.route("/menu-items", methods=["POST"])
def create_menu_item():
    authenticate({"KitchenManager"})
    body = get_body()
    name = req_str(body, "name")
    category = req_str(body, "category")
    sell_price = req_int(body, "sell_price_cents_per_portion")
    if category not in CATEGORY_ENUM:
        raise ApiError("ERR_INVALID_ENUM", "Invalid category")
    if sell_price <= 0:
        raise ApiError("ERR_QUANTITY_NOT_POSITIVE", "sell_price_cents_per_portion must be > 0")
    rec = base_record()
    rec.update({
        "name": name,
        "category": category,
        "sell_price_cents_per_portion": sell_price,
        "portion_food_cost_cents": 0,
    })
    db["menu_items"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/menu-items/<_id>", methods=["GET"])
def get_menu_item(_id):
    authenticate(ROLES)
    rec = get_or_404("menu_items", _id, "ERR_MENU_ITEM_NOT_FOUND")
    return ok(serialize(rec), 200)


# ===========================================================================
# RecipeLine
# ===========================================================================
@app.route("/recipe-lines", methods=["POST"])
def create_recipe_line():
    authenticate({"KitchenManager"})
    body = get_body()
    menu_item_id = req_str(body, "menu_item_id")
    ingredient_id = req_str(body, "ingredient_id")
    qty_per_portion = req_num(body, "qty_per_portion")
    if qty_per_portion <= 0:
        raise ApiError("ERR_QUANTITY_NOT_POSITIVE", "qty_per_portion must be > 0")
    mi = get_or_404("menu_items", menu_item_id, "ERR_MENU_ITEM_NOT_FOUND")
    get_or_404("ingredients", ingredient_id, "ERR_INGREDIENT_NOT_FOUND")
    rec = base_record(with_version=False)
    rec.update({
        "menu_item_id": menu_item_id,
        "ingredient_id": ingredient_id,
        "qty_per_portion": qty_per_portion,
    })
    db["recipe_lines"][rec["id"]] = rec
    recompute_portion_food_cost(mi)
    touch(mi)
    return ok(serialize(rec), 201)


@app.route("/recipe-lines/<_id>", methods=["GET"])
def get_recipe_line(_id):
    authenticate(ROLES)
    rec = get_or_404("recipe_lines", _id, "ERR_RESOURCE_NOT_FOUND")
    return ok(serialize(rec), 200)


@app.route("/recipe-lines", methods=["GET"])
def list_recipe_lines():
    authenticate(ROLES)
    menu_item_id = request.args.get("menu_item_id")
    ingredient_id = request.args.get("ingredient_id")
    items = list(db["recipe_lines"].values())
    if menu_item_id is not None:
        items = [r for r in items if r["menu_item_id"] == menu_item_id]
    if ingredient_id is not None:
        items = [r for r in items if r["ingredient_id"] == ingredient_id]
    return paginate_list(items)


# ===========================================================================
# Station
# ===========================================================================
@app.route("/stations", methods=["POST"])
def create_station():
    authenticate({"Admin"})
    body = get_body()
    name = req_str(body, "name")
    capacity = req_int(body, "concurrent_capacity")
    if capacity <= 0:
        raise ApiError("ERR_QUANTITY_NOT_POSITIVE", "concurrent_capacity must be >= 1")
    rec = base_record()
    rec.update({"name": name, "concurrent_capacity": capacity})
    db["stations"][rec["id"]] = rec
    return ok(serialize(rec), 201)


# ===========================================================================
# EquipmentItem
# ===========================================================================
@app.route("/equipment-items", methods=["POST"])
def create_equipment_item():
    authenticate({"Admin"})
    body = get_body()
    name = req_str(body, "name")
    asset_type = req_str(body, "asset_type")
    total_units = req_int(body, "total_units")
    rental_price = req_int(body, "rental_price_cents")
    if asset_type not in ASSET_TYPE_ENUM:
        raise ApiError("ERR_INVALID_ENUM", "Invalid asset_type")
    if total_units <= 0:
        raise ApiError("ERR_QUANTITY_NOT_POSITIVE", "total_units must be > 0")
    if rental_price <= 0:
        raise ApiError("ERR_QUANTITY_NOT_POSITIVE", "rental_price_cents must be > 0")
    rec = base_record()
    rec.update({
        "name": name,
        "asset_type": asset_type,
        "total_units": total_units,
        "rental_price_cents": rental_price,
    })
    db["equipment_items"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/equipment-items/<_id>", methods=["GET"])
def get_equipment_item(_id):
    authenticate(ROLES)
    rec = get_or_404("equipment_items", _id, "ERR_EQUIPMENT_NOT_FOUND")
    return ok(serialize(rec), 200)


@app.route("/equipment-items/<_id>/availability", methods=["GET"])
def get_equipment_availability(_id):
    authenticate(ROLES)
    rec = get_or_404("equipment_items", _id, "ERR_EQUIPMENT_NOT_FOUND")
    out_raw = request.args.get("out_time")
    ret_raw = request.args.get("return_time")
    wstart = wend = None
    if out_raw is not None or ret_raw is not None:
        if out_raw is None or ret_raw is None:
            raise ApiError("ERR_VALIDATION", "Both out_time and return_time required")
        wstart = parse_dt(out_raw)
        wend = parse_dt(ret_raw)
        if not (wend > wstart):
            raise ApiError("ERR_INVALID_TIME_WINDOW", "return_time must be after out_time")
    peak = equipment_peak(_id, wstart, wend)
    available = rec["total_units"] - peak
    return ok({"available_units": available, "total_units": rec["total_units"]}, 200)


# ===========================================================================
# StaffMember
# ===========================================================================
@app.route("/staff-members", methods=["POST"])
def create_staff_member():
    authenticate({"Admin"})
    body = get_body()
    name = req_str(body, "name")
    staff_role = req_str(body, "staff_role")
    hourly_rate = req_int(body, "hourly_rate_cents")
    if staff_role not in STAFF_ROLE_ENUM:
        raise ApiError("ERR_INVALID_ENUM", "Invalid staff_role")
    if hourly_rate <= 0:
        raise ApiError("ERR_QUANTITY_NOT_POSITIVE", "hourly_rate_cents must be > 0")
    rec = base_record()
    rec.update({"name": name, "staff_role": staff_role, "hourly_rate_cents": hourly_rate})
    db["staff_members"][rec["id"]] = rec
    return ok(serialize(rec), 201)


# ===========================================================================
# EventOrder
# ===========================================================================
def new_event_order_record():
    rec = base_record()
    rec.update({
        "guest_count": None,
        "event_start": None,
        "event_end": None,
        "venue_address": None,
        "service_charge_pct": None,
        "gratuity_pct": None,
        "delivery_vehicle": None,
        "delivery_depart_time": None,
        "status": "DRAFT",
        "actual_guest_count": None,
        "actual_labor_total_cents": 0,
        "actual_food_revenue_cents": None,
        "actual_food_cost_cents": None,
        "actual_rental_cents": None,
        "actual_service_charge_cents": None,
        "actual_gratuity_cents": None,
        "actual_grand_total_cents": None,
    })
    return rec


@app.route("/event-orders", methods=["POST"])
def create_event_order():
    authenticate({"SalesManager"})
    body = get_body()
    guest_count = req_int(body, "guest_count")
    event_start = req_dt(body, "event_start")
    event_end = req_dt(body, "event_end")
    venue_address = req_str(body, "venue_address")
    service_charge_pct = req_num(body, "service_charge_pct")
    gratuity_pct = req_num(body, "gratuity_pct")
    delivery_vehicle = opt_str(body, "delivery_vehicle")
    delivery_depart_time = opt_dt(body, "delivery_depart_time")
    if guest_count <= 0:
        raise ApiError("ERR_INVALID_GUEST_COUNT", "guest_count must be > 0")
    if not (parse_dt(event_end) > parse_dt(event_start)):
        raise ApiError("ERR_INVALID_TIME_WINDOW", "event_end must be after event_start")
    rec = new_event_order_record()
    rec.update({
        "guest_count": guest_count,
        "event_start": event_start,
        "event_end": event_end,
        "venue_address": venue_address,
        "service_charge_pct": conv(service_charge_pct),
        "gratuity_pct": conv(gratuity_pct),
        "delivery_vehicle": delivery_vehicle,
        "delivery_depart_time": delivery_depart_time,
    })
    db["event_orders"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/event-orders/<_id>", methods=["GET"])
def get_event_order(_id):
    authenticate(ROLES)
    rec = get_or_404("event_orders", _id, "ERR_EVENT_ORDER_NOT_FOUND")
    return ok(serialize(rec), 200)


@app.route("/event-orders", methods=["GET"])
def list_event_orders():
    authenticate(ROLES)
    status = request.args.get("status")
    items = list(db["event_orders"].values())
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate_list(items)


@app.route("/event-orders/<_id>/quotes", methods=["POST"])
def generate_quote(_id):
    authenticate({"SalesManager"})
    body = get_body()
    expected_version = req_int(body, "expected_event_order_version")
    order = get_or_404("event_orders", _id, "ERR_EVENT_ORDER_NOT_FOUND")
    if order["status"] not in ("DRAFT", "QUOTED"):
        raise ApiError("ERR_INVALID_STATE", "Quote not allowed from current state")
    if len(active_order_lines(_id)) < 1:
        raise ApiError("ERR_NO_ORDER_LINES", "Order has no active order lines")
    if expected_version != order["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION", "Stale event order version")
    # supersede prior active quote
    for q in db["quotes"].values():
        if q["event_order_id"] == _id and q["status"] == "ACTIVE":
            q["status"] = "SUPERSEDED"
            touch(q)
    rev, cost = compute_food(_id, order["guest_count"])
    quote = base_record()
    quote.update({
        "event_order_id": _id,
        "status": "ACTIVE",
        "guest_count_snapshot": order["guest_count"],
        "food_revenue_cents": rev,
        "food_cost_cents": cost,
    })
    db["quotes"][quote["id"]] = quote
    order["status"] = "QUOTED"
    touch(order)
    return ok(serialize(quote), 201)


@app.route("/event-orders/<_id>/revise", methods=["POST"])
def revise_event_order(_id):
    authenticate({"SalesManager"})
    get_body(optional=True)
    order = get_or_404("event_orders", _id, "ERR_EVENT_ORDER_NOT_FOUND")
    if order["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Revise only allowed from QUOTED")
    for q in db["quotes"].values():
        if q["event_order_id"] == _id and q["status"] == "ACTIVE":
            q["status"] = "SUPERSEDED"
            touch(q)
    order["status"] = "DRAFT"
    touch(order)
    return ok(serialize(order), 200)


@app.route("/event-orders/<_id>/confirm", methods=["POST"])
def confirm_event_order(_id):
    authenticate({"SalesManager"})
    get_body(optional=True)
    order = get_or_404("event_orders", _id, "ERR_EVENT_ORDER_NOT_FOUND")
    if order["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Confirm only allowed from QUOTED")
    order["status"] = "CONFIRMED"
    touch(order)
    return ok(serialize(order), 200)


@app.route("/event-orders/<_id>/start-production", methods=["POST"])
def start_production(_id):
    authenticate({"KitchenManager"})
    get_body(optional=True)
    order = get_or_404("event_orders", _id, "ERR_EVENT_ORDER_NOT_FOUND")
    if order["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "start-production requires CONFIRMED")
    runs = [r for r in db["production_runs"].values() if r["event_order_id"] == _id]
    non_cancelled = [r for r in runs if r["status"] != "CANCELLED"]
    if len(non_cancelled) < 1 or any(r["status"] != "SCHEDULED" for r in non_cancelled):
        raise ApiError("ERR_INVALID_STATE", "All runs must be SCHEDULED to start production")
    order["status"] = "IN_PRODUCTION"
    touch(order)
    return ok(serialize(order), 200)


@app.route("/event-orders/<_id>/pack", methods=["POST"])
def pack_event_order(_id):
    authenticate({"KitchenManager"})
    get_body(optional=True)
    order = get_or_404("event_orders", _id, "ERR_EVENT_ORDER_NOT_FOUND")
    if order["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE", "pack requires IN_PRODUCTION")
    runs = [r for r in db["production_runs"].values() if r["event_order_id"] == _id]
    non_cancelled = [r for r in runs if r["status"] != "CANCELLED"]
    if any(r["status"] != "DONE" for r in non_cancelled):
        raise ApiError("ERR_PRODUCTION_NOT_COMPLETE", "All runs must be DONE to pack")
    order["status"] = "PACKED"
    touch(order)
    return ok(serialize(order), 200)


@app.route("/event-orders/<_id>/dispatch", methods=["POST"])
def dispatch_event_order(_id):
    authenticate({"EventCaptain"})
    body = get_body(optional=True)
    delivery_vehicle = opt_str(body, "delivery_vehicle")
    delivery_depart_time = opt_dt(body, "delivery_depart_time")
    order = get_or_404("event_orders", _id, "ERR_EVENT_ORDER_NOT_FOUND")
    if order["status"] != "PACKED":
        raise ApiError("ERR_INVALID_STATE", "dispatch requires PACKED")
    confirmed = [
        a for a in db["staff_assignments"].values()
        if a["event_order_id"] == _id
        and a["status"] in ("CONFIRMED", "CHECKED_IN", "CHECKED_OUT")
    ]
    if len(confirmed) < 1:
        raise ApiError("ERR_NO_STAFF_CONFIRMED", "No confirmed staff assignment")
    if delivery_vehicle is not None:
        order["delivery_vehicle"] = delivery_vehicle
    if delivery_depart_time is not None:
        order["delivery_depart_time"] = delivery_depart_time
    order["status"] = "DISPATCHED"
    touch(order)
    return ok(serialize(order), 200)


@app.route("/event-orders/<_id>/complete", methods=["POST"])
def complete_event_order(_id):
    authenticate({"EventCaptain"})
    get_body(optional=True)
    order = get_or_404("event_orders", _id, "ERR_EVENT_ORDER_NOT_FOUND")
    if order["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", "complete requires DISPATCHED")
    order["status"] = "COMPLETED"
    touch(order)
    return ok(serialize(order), 200)


@app.route("/event-orders/<_id>/actualize", methods=["POST"])
def actualize_event_order(_id):
    authenticate({"SalesManager"})
    body = get_body(optional=True)
    agc = body.get("actual_guest_count")
    if agc is None or isinstance(agc, bool) or not isinstance(agc, int) or agc <= 0:
        raise ApiError("ERR_INVALID_GUEST_COUNT", "actual_guest_count must be present and > 0")
    order = get_or_404("event_orders", _id, "ERR_EVENT_ORDER_NOT_FOUND")
    if order["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "actualize requires COMPLETED")
    rev, cost = compute_food(_id, agc)
    rental = 0
    for r in db["rental_reservations"].values():
        if r["event_order_id"] == _id and r["status"] == "ACTIVE":
            eq = db["equipment_items"][r["equipment_item_id"]]
            rental += r["qty"] * eq["rental_price_cents"]
    labor = order["actual_labor_total_cents"]
    service = round_half_up(Decimal(str(order["service_charge_pct"])) * (Decimal(rev) + Decimal(labor)))
    gratuity = round_half_up(Decimal(str(order["gratuity_pct"])) * Decimal(rev))
    grand = rev + labor + rental + service + gratuity
    order["actual_guest_count"] = agc
    order["actual_food_revenue_cents"] = rev
    order["actual_food_cost_cents"] = cost
    order["actual_rental_cents"] = rental
    order["actual_service_charge_cents"] = service
    order["actual_gratuity_cents"] = gratuity
    order["actual_grand_total_cents"] = grand
    order["status"] = "ACTUALIZED"
    touch(order)
    return ok(serialize(order), 200)


@app.route("/event-orders/<_id>/cancel", methods=["POST"])
def cancel_event_order(_id):
    authenticate({"SalesManager"})
    get_body(optional=True)
    order = get_or_404("event_orders", _id, "ERR_EVENT_ORDER_NOT_FOUND")
    if order["status"] not in ("DRAFT", "QUOTED", "CONFIRMED", "IN_PRODUCTION"):
        raise ApiError("ERR_INVALID_STATE", "Order cannot be cancelled from current state")
    if order["status"] == "QUOTED":
        for q in db["quotes"].values():
            if q["event_order_id"] == _id and q["status"] == "ACTIVE":
                q["status"] = "SUPERSEDED"
                touch(q)
    # cascade production runs
    for r in db["production_runs"].values():
        if r["event_order_id"] == _id and r["status"] in ("SCHEDULED", "IN_PROGRESS"):
            release_ingredients(r["menu_item_id"], r["portions"])
            r["status"] = "CANCELLED"
            touch(r)
    # cascade rental reservations
    for res in db["rental_reservations"].values():
        if res["event_order_id"] == _id and res["status"] == "ACTIVE":
            res["status"] = "CANCELLED"
            touch(res)
    # cascade staff assignments
    for a in db["staff_assignments"].values():
        if a["event_order_id"] == _id and a["status"] not in ("CHECKED_OUT", "CANCELLED"):
            a["status"] = "CANCELLED"
            touch(a)
    order["status"] = "CANCELLED"
    touch(order)
    return ok(serialize(order), 200)


# ===========================================================================
# OrderLine
# ===========================================================================
@app.route("/order-lines", methods=["POST"])
def create_order_line():
    authenticate({"SalesManager"})
    body = get_body()
    event_order_id = req_str(body, "event_order_id")
    menu_item_id = req_str(body, "menu_item_id")
    portions_per_guest = req_num(body, "portions_per_guest")
    if portions_per_guest <= 0:
        raise ApiError("ERR_QUANTITY_NOT_POSITIVE", "portions_per_guest must be > 0")
    order = get_or_404("event_orders", event_order_id, "ERR_EVENT_ORDER_NOT_FOUND")
    get_or_404("menu_items", menu_item_id, "ERR_MENU_ITEM_NOT_FOUND")
    if order["status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT", "Order must be DRAFT to add lines")
    rec = base_record()
    rec.update({
        "event_order_id": event_order_id,
        "menu_item_id": menu_item_id,
        "portions_per_guest": portions_per_guest,
        "status": "ACTIVE",
    })
    db["order_lines"][rec["id"]] = rec
    touch(order)
    return ok(serialize(rec), 201)


@app.route("/order-lines/<_id>", methods=["GET"])
def get_order_line(_id):
    authenticate(ROLES)
    rec = get_or_404("order_lines", _id, "ERR_RESOURCE_NOT_FOUND")
    return ok(serialize(rec), 200)


@app.route("/order-lines", methods=["GET"])
def list_order_lines():
    authenticate(ROLES)
    event_order_id = request.args.get("event_order_id")
    menu_item_id = request.args.get("menu_item_id")
    include_removed = request.args.get("include_removed")
    include = str(include_removed).lower() == "true" if include_removed is not None else False
    items = list(db["order_lines"].values())
    if event_order_id is not None:
        items = [r for r in items if r["event_order_id"] == event_order_id]
    if menu_item_id is not None:
        items = [r for r in items if r["menu_item_id"] == menu_item_id]
    if not include:
        items = [r for r in items if r["status"] != "REMOVED"]
    return paginate_list(items)


@app.route("/order-lines/<_id>", methods=["DELETE"])
def delete_order_line(_id):
    authenticate({"SalesManager"})
    rec = get_or_404("order_lines", _id, "ERR_RESOURCE_NOT_FOUND")
    order = db["event_orders"][rec["event_order_id"]]
    if order["status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT", "Order must be DRAFT to remove lines")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Order line already removed")
    rec["status"] = "REMOVED"
    touch(rec)
    touch(order)
    return ok(serialize(rec), 200)


# ===========================================================================
# Quote
# ===========================================================================
@app.route("/quotes/<_id>", methods=["GET"])
def get_quote(_id):
    authenticate(ROLES)
    rec = get_or_404("quotes", _id, "ERR_RESOURCE_NOT_FOUND")
    return ok(serialize(rec), 200)


@app.route("/quotes", methods=["GET"])
def list_quotes():
    authenticate(ROLES)
    event_order_id = request.args.get("event_order_id")
    status = request.args.get("status")
    items = list(db["quotes"].values())
    if event_order_id is not None:
        items = [r for r in items if r["event_order_id"] == event_order_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate_list(items)


# ===========================================================================
# ProductionRun
# ===========================================================================
@app.route("/production-runs", methods=["POST"])
def create_production_run():
    authenticate({"KitchenManager"})
    body = get_body()
    event_order_id = req_str(body, "event_order_id")
    station_id = req_str(body, "station_id")
    menu_item_id = req_str(body, "menu_item_id")
    portions = req_int(body, "portions")
    scheduled_start = req_dt(body, "scheduled_start")
    scheduled_end = req_dt(body, "scheduled_end")
    if portions <= 0:
        raise ApiError("ERR_QUANTITY_NOT_POSITIVE", "portions must be > 0")
    if not (parse_dt(scheduled_end) > parse_dt(scheduled_start)):
        raise ApiError("ERR_INVALID_TIME_WINDOW", "scheduled_end must be after scheduled_start")
    order = get_or_404("event_orders", event_order_id, "ERR_EVENT_ORDER_NOT_FOUND")
    station = get_or_404("stations", station_id, "ERR_STATION_NOT_FOUND")
    get_or_404("menu_items", menu_item_id, "ERR_MENU_ITEM_NOT_FOUND")
    if order["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Production run requires CONFIRMED order")
    check_station_capacity(station_id, scheduled_start, scheduled_end, station["concurrent_capacity"])
    commit_ingredients(menu_item_id, portions)
    rec = base_record()
    rec.update({
        "event_order_id": event_order_id,
        "station_id": station_id,
        "menu_item_id": menu_item_id,
        "portions": portions,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
    })
    db["production_runs"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/production-runs/<_id>", methods=["GET"])
def get_production_run(_id):
    authenticate(ROLES)
    rec = get_or_404("production_runs", _id, "ERR_RESOURCE_NOT_FOUND")
    return ok(serialize(rec), 200)


@app.route("/production-runs", methods=["GET"])
def list_production_runs():
    authenticate(ROLES)
    event_order_id = request.args.get("event_order_id")
    station_id = request.args.get("station_id")
    menu_item_id = request.args.get("menu_item_id")
    items = list(db["production_runs"].values())
    if event_order_id is not None:
        items = [r for r in items if r["event_order_id"] == event_order_id]
    if station_id is not None:
        items = [r for r in items if r["station_id"] == station_id]
    if menu_item_id is not None:
        items = [r for r in items if r["menu_item_id"] == menu_item_id]
    return paginate_list(items)


@app.route("/production-runs/<_id>/start", methods=["POST"])
def start_production_run(_id):
    authenticate({"KitchenManager"})
    get_body(optional=True)
    rec = get_or_404("production_runs", _id, "ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Run must be SCHEDULED to start")
    order = db["event_orders"][rec["event_order_id"]]
    if order["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE", "Parent order must be IN_PRODUCTION")
    rec["status"] = "IN_PROGRESS"
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/production-runs/<_id>/complete", methods=["POST"])
def complete_production_run(_id):
    authenticate({"KitchenManager"})
    get_body(optional=True)
    rec = get_or_404("production_runs", _id, "ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Run must be IN_PROGRESS to complete")
    consume_ingredients(rec["menu_item_id"], rec["portions"])
    rec["status"] = "DONE"
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/production-runs/<_id>/reschedule", methods=["POST"])
def reschedule_production_run(_id):
    authenticate({"KitchenManager"})
    body = get_body(optional=True)
    rec = get_or_404("production_runs", _id, "ERR_RESOURCE_NOT_FOUND")
    new_start = body.get("scheduled_start")
    new_end = body.get("scheduled_end")
    supplied = new_start is not None or new_end is not None
    if supplied:
        new_start = req_dt(body, "scheduled_start")
        new_end = req_dt(body, "scheduled_end")
        if not (parse_dt(new_end) > parse_dt(new_start)):
            raise ApiError("ERR_INVALID_TIME_WINDOW", "scheduled_end must be after scheduled_start")
    if rec["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Run must be IN_PROGRESS to reschedule")
    if supplied:
        station = db["stations"][rec["station_id"]]
        check_station_capacity(rec["station_id"], new_start, new_end,
                               station["concurrent_capacity"], exclude_id=rec["id"])
        rec["scheduled_start"] = new_start
        rec["scheduled_end"] = new_end
    rec["status"] = "SCHEDULED"
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/production-runs/<_id>/cancel", methods=["POST"])
def cancel_production_run(_id):
    authenticate({"KitchenManager"})
    get_body(optional=True)
    rec = get_or_404("production_runs", _id, "ERR_RESOURCE_NOT_FOUND")
    if rec["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "Run cannot be cancelled from current state")
    release_ingredients(rec["menu_item_id"], rec["portions"])
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok(serialize(rec), 200)


# ===========================================================================
# RentalReservation
# ===========================================================================
@app.route("/rental-reservations", methods=["POST"])
def create_rental_reservation():
    authenticate({"EventCaptain"})
    body = get_body()
    event_order_id = req_str(body, "event_order_id")
    equipment_item_id = req_str(body, "equipment_item_id")
    qty = req_int(body, "qty")
    out_time = req_dt(body, "out_time")
    return_time = req_dt(body, "return_time")
    if qty <= 0:
        raise ApiError("ERR_QUANTITY_NOT_POSITIVE", "qty must be > 0")
    if not (parse_dt(return_time) > parse_dt(out_time)):
        raise ApiError("ERR_INVALID_TIME_WINDOW", "return_time must be after out_time")
    order = get_or_404("event_orders", event_order_id, "ERR_EVENT_ORDER_NOT_FOUND")
    equipment = get_or_404("equipment_items", equipment_item_id, "ERR_EQUIPMENT_NOT_FOUND")
    if order["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Reservation requires CONFIRMED order")
    peak = equipment_peak(equipment_item_id, parse_dt(out_time), parse_dt(return_time))
    if peak + qty > equipment["total_units"]:
        raise ApiError("ERR_EQUIPMENT_UNAVAILABLE", "Equipment not available for window")
    rec = base_record()
    rec.update({
        "event_order_id": event_order_id,
        "equipment_item_id": equipment_item_id,
        "qty": qty,
        "out_time": out_time,
        "return_time": return_time,
        "status": "ACTIVE",
    })
    db["rental_reservations"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/rental-reservations/<_id>", methods=["GET"])
def get_rental_reservation(_id):
    authenticate(ROLES)
    rec = get_or_404("rental_reservations", _id, "ERR_RESOURCE_NOT_FOUND")
    return ok(serialize(rec), 200)


@app.route("/rental-reservations", methods=["GET"])
def list_rental_reservations():
    authenticate(ROLES)
    event_order_id = request.args.get("event_order_id")
    equipment_item_id = request.args.get("equipment_item_id")
    items = list(db["rental_reservations"].values())
    if event_order_id is not None:
        items = [r for r in items if r["event_order_id"] == event_order_id]
    if equipment_item_id is not None:
        items = [r for r in items if r["equipment_item_id"] == equipment_item_id]
    return paginate_list(items)


@app.route("/rental-reservations/<_id>/cancel", methods=["POST"])
def cancel_rental_reservation(_id):
    authenticate({"EventCaptain"})
    get_body(optional=True)
    rec = get_or_404("rental_reservations", _id, "ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Reservation cannot be cancelled from current state")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok(serialize(rec), 200)


# ===========================================================================
# StaffAssignment
# ===========================================================================
@app.route("/staff-assignments", methods=["POST"])
def create_staff_assignment():
    authenticate({"EventCaptain"})
    body = get_body()
    event_order_id = req_str(body, "event_order_id")
    staff_member_id = req_str(body, "staff_member_id")
    staff_role = req_str(body, "staff_role")
    shift_start = req_dt(body, "shift_start")
    shift_end = req_dt(body, "shift_end")
    if staff_role not in STAFF_ROLE_ENUM:
        raise ApiError("ERR_INVALID_ENUM", "Invalid staff_role")
    if not (parse_dt(shift_end) > parse_dt(shift_start)):
        raise ApiError("ERR_INVALID_TIME_WINDOW", "shift_end must be after shift_start")
    order = get_or_404("event_orders", event_order_id, "ERR_EVENT_ORDER_NOT_FOUND")
    staff = get_or_404("staff_members", staff_member_id, "ERR_STAFF_NOT_FOUND")
    if order["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Assignment requires CONFIRMED order")
    if staff_role != staff["staff_role"]:
        raise ApiError("ERR_STAFF_ROLE_MISMATCH", "Assignment role does not match staff role")
    check_double_book(staff_member_id, shift_start, shift_end)
    scheduled_labor = compute_labor(shift_start, shift_end, staff["hourly_rate_cents"])
    rec = base_record()
    rec.update({
        "event_order_id": event_order_id,
        "staff_member_id": staff_member_id,
        "staff_role": staff_role,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "actual_start": None,
        "actual_end": None,
        "scheduled_labor_cents": scheduled_labor,
        "actual_labor_cents": None,
        "status": "OFFERED",
    })
    db["staff_assignments"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/staff-assignments/<_id>", methods=["GET"])
def get_staff_assignment(_id):
    authenticate(ROLES)
    rec = get_or_404("staff_assignments", _id, "ERR_RESOURCE_NOT_FOUND")
    return ok(serialize(rec), 200)


@app.route("/staff-assignments", methods=["GET"])
def list_staff_assignments():
    authenticate(ROLES)
    event_order_id = request.args.get("event_order_id")
    staff_member_id = request.args.get("staff_member_id")
    items = list(db["staff_assignments"].values())
    if event_order_id is not None:
        items = [r for r in items if r["event_order_id"] == event_order_id]
    if staff_member_id is not None:
        items = [r for r in items if r["staff_member_id"] == staff_member_id]
    return paginate_list(items)


@app.route("/staff-assignments/<_id>/confirm", methods=["POST"])
def confirm_staff_assignment(_id):
    authenticate({"EventCaptain"})
    get_body(optional=True)
    rec = get_or_404("staff_assignments", _id, "ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "Assignment must be OFFERED to confirm")
    rec["status"] = "CONFIRMED"
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/staff-assignments/<_id>/check-in", methods=["POST"])
def check_in_staff_assignment(_id):
    authenticate({"EventCaptain"})
    body = get_body(optional=True)
    actual_start = req_dt(body, "actual_start")
    rec = get_or_404("staff_assignments", _id, "ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Assignment must be CONFIRMED to check in")
    rec["actual_start"] = actual_start
    rec["status"] = "CHECKED_IN"
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/staff-assignments/<_id>/check-out", methods=["POST"])
def check_out_staff_assignment(_id):
    authenticate({"EventCaptain"})
    body = get_body(optional=True)
    actual_end = req_dt(body, "actual_end")
    rec = get_or_404("staff_assignments", _id, "ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", "Assignment must be CHECKED_IN to check out")
    if not (parse_dt(actual_end) > parse_dt(rec["actual_start"])):
        raise ApiError("ERR_INVALID_TIME_WINDOW", "actual_end must be after actual_start")
    staff = db["staff_members"][rec["staff_member_id"]]
    actual_labor = compute_labor(rec["actual_start"], actual_end, staff["hourly_rate_cents"])
    rec["actual_end"] = actual_end
    rec["actual_labor_cents"] = actual_labor
    rec["status"] = "CHECKED_OUT"
    touch(rec)
    order = db["event_orders"][rec["event_order_id"]]
    order["actual_labor_total_cents"] = order["actual_labor_total_cents"] + actual_labor
    touch(order)
    return ok(serialize(rec), 200)


@app.route("/staff-assignments/<_id>/cancel", methods=["POST"])
def cancel_staff_assignment(_id):
    authenticate({"EventCaptain"})
    get_body(optional=True)
    rec = get_or_404("staff_assignments", _id, "ERR_RESOURCE_NOT_FOUND")
    if rec["status"] not in ("OFFERED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "Assignment cannot be cancelled from current state")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok(serialize(rec), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
