import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Manager", "Baker", "Cashier", "Driver", "WholesaleClient"}
CATEGORY = {"BREAD", "PASTRY", "CAKE", "SANDWICH", "OTHER"}
ALLERGENS = {"GLUTEN", "DAIRY", "EGG", "NUT", "SOY", "SESAME"}
CONTRACT_TIER = {"STANDARD", "PREMIUM", "BULK"}
WEEKDAY = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}

# markdown calc constants
MARKDOWN_WINDOW_HOURS = 8
MID_TIER_HOURS = 4
MID_DISCOUNT = Decimal("0.25")
LATE_DISCOUNT = Decimal("0.50")
SURPLUS_BONUS = Decimal("0.15")
MAX_DISCOUNT = Decimal("0.60")

# wholesale pricing constants
TIER_DISCOUNT = {"STANDARD": Decimal("0.10"), "PREMIUM": Decimal("0.15"), "BULK": Decimal("0.20")}
BULK_DISCOUNT = Decimal("0.20")
BULK_MIN_QTY = 24

CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store (empty on every boot; nothing is seeded)
# ---------------------------------------------------------------------------
DB = {
    "products": {},
    "ovens": {},
    "bake_plans": {},
    "bake_plan_lines": {},
    "bake_lots": {},
    "retail_sales": {},
    "wholesale_accounts": {},
    "standing_orders": {},
    "delivery_orders": {},
    "delivery_routes": {},
    "route_stops": {},
}
CLOCK = {"now": CLOCK_DEFAULT}
_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def now_dt():
    return CLOCK["now"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    raise ApiError(error_id, http_status, message)


def bad(message="invalid request"):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def format_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def base_meta():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": format_dt(now_dt())}


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = format_dt(v)
        else:
            out[k] = v
    return out


def ok(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = base_meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "missing or invalid authentication headers")
    return {"user_id": uid, "role": role}


def endpoint(roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(**kwargs):
            ctx = authenticate()
            if ctx["role"] not in roles:
                err("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")
            return fn(ctx, **kwargs)
        return wrapper
    return deco


def require_owner(ctx, account_id):
    if ctx["role"] == "WholesaleClient" and ctx["user_id"] != account_id:
        err("ERR_UNAUTHORIZED", 403, "not owner of this resource")


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        bad("request body must be a JSON object")
    return body


def req_str(body, field, allow_empty=False):
    v = body.get(field)
    if not isinstance(v, str):
        bad("field '%s' must be a string" % field)
    if not allow_empty and v == "":
        bad("field '%s' must be non-empty" % field)
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        bad("field '%s' must be a string" % field)
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        bad("field '%s' must be an integer" % field)
    if minimum is not None and v < minimum:
        bad("field '%s' must be >= %s" % (field, minimum))
    return v


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        bad("field '%s' must be an integer" % field)
    if minimum is not None and v < minimum:
        bad("field '%s' must be >= %s" % (field, minimum))
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        bad("field '%s' has invalid value" % field)
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        bad("field '%s' has invalid value" % field)
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        bad("field '%s' must be a boolean" % field)
    return v


def req_allergen_list(body, field, default=None):
    if field not in body or body[field] is None:
        return list(default) if default is not None else []
    v = body[field]
    if not isinstance(v, list):
        bad("field '%s' must be an array" % field)
    for item in v:
        if not isinstance(item, str) or item not in ALLERGENS:
            bad("field '%s' has invalid allergen value" % field)
    return list(v)


def req_dt(body, field):
    v = body.get(field)
    try:
        return parse_dt(v)
    except Exception:
        bad("field '%s' must be a valid ISO 8601 timestamp" % field)


# ---------------------------------------------------------------------------
# Entity lifecycle helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def create_entity(store, fields, common=True):
    ts = now_dt()
    ent = {"id": new_id(), "created_at": ts}
    if common:
        ent["updated_at"] = ts
        ent["version"] = 1
    ent.update(fields)
    ent["_seq"] = next_seq()
    store[ent["id"]] = ent
    return ent


def touch(entity):
    entity["updated_at"] = now_dt()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Existence lookups
# ---------------------------------------------------------------------------
def get_or_404(store, oid, error_id):
    ent = store.get(oid)
    if ent is None:
        err(error_id, 404, "resource not found")
    return ent


# ---------------------------------------------------------------------------
# Derived-field recomputation
# ---------------------------------------------------------------------------
def refresh_line(line, bump):
    lid = line["id"]
    reserved = 0
    delivered = 0
    for o in DB["delivery_orders"].values():
        if o["bake_plan_line_id"] == lid and o["fulfillment_status"] != "CANCELLED":
            reserved += o["qty"]
        if o["bake_plan_line_id"] == lid and o["fulfillment_status"] == "DELIVERED":
            delivered += o["qty"]
    baked = 0
    lot_ids = set()
    for lot in DB["bake_lots"].values():
        if lot["bake_plan_line_id"] == lid:
            baked += lot["baked_qty"]
            lot_ids.add(lot["id"])
    sold = 0
    for s in DB["retail_sales"].values():
        if s["bake_lot_id"] in lot_ids:
            sold += s["qty"]
    line["reserved_qty"] = reserved
    line["available_qty"] = line["par_qty"] - reserved
    line["baked_qty"] = baked
    line["sold_qty"] = sold
    line["delivered_qty"] = delivered
    if bump:
        touch(line)


def refresh_route(route, bump):
    rid = route["id"]
    count = 0
    load = 0
    for s in DB["route_stops"].values():
        if s["route_id"] == rid and s["status"] != "CANCELLED":
            count += 1
            o = DB["delivery_orders"].get(s["delivery_order_id"])
            if o is not None:
                load += o["qty"]
    route["stop_count"] = count
    route["total_load_qty"] = load
    if bump:
        touch(route)


def refresh_account(account, bump):
    aid = account["id"]
    bal = 0
    for o in DB["delivery_orders"].values():
        if o["wholesale_account_id"] == aid and o["fulfillment_status"] == "DELIVERED":
            bal += (o["line_total_cents"] - o["amount_paid_cents"])
    account["credit_balance_cents"] = bal
    if bump:
        touch(account)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def round_half_up(dec_value):
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_markdown_price(lot, product):
    best_by = lot["best_by"]
    h = (best_by - now_dt()).total_seconds() / 3600.0
    if h > MID_TIER_HOURS:
        base_d = MID_DISCOUNT
    else:
        base_d = LATE_DISCOUNT
    # surplus bonus when remaining_qty / baked_qty >= 0.5
    surplus = SURPLUS_BONUS if (2 * lot["remaining_qty"] >= lot["baked_qty"]) else Decimal("0")
    discount = base_d + surplus
    if discount > MAX_DISCOUNT:
        discount = MAX_DISCOUNT
    base = product["base_price_cents"]
    return round_half_up(Decimal(base) * (Decimal(1) - discount))


def compute_wholesale_price(product, account, qty):
    base = product["base_price_cents"]
    discount = TIER_DISCOUNT[account["contract_tier"]]
    if qty >= BULK_MIN_QTY and BULK_DISCOUNT > discount:
        discount = BULK_DISCOUNT
    unit_price = round_half_up(Decimal(base) * (Decimal(1) - discount))
    line_total = round_half_up(Decimal(qty) * Decimal(base) * (Decimal(1) - discount))
    list_total = qty * base
    return unit_price, line_total, list_total


# ---------------------------------------------------------------------------
# Pagination / listing
# ---------------------------------------------------------------------------
def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            bad("limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            bad("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(entities, serializer=serialize):
    limit, offset = get_pagination()
    ordered = sorted(entities, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serializer(e) for e in page], limit, offset, total


# ---------------------------------------------------------------------------
# Serializers that refresh live derived fields (no version bump on read)
# ---------------------------------------------------------------------------
def line_public(line):
    refresh_line(line, bump=False)
    return serialize(line)


def route_public(route):
    refresh_route(route, bump=False)
    return serialize(route)


def account_public(account):
    refresh_account(account, bump=False)
    return serialize(account)


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
@endpoint({"Manager"})
def set_clock(ctx):
    body = get_body()
    ts = req_dt(body, "to_iso8601")
    CLOCK["now"] = ts
    return ok({})


# ===========================================================================
# Products
# ===========================================================================
@app.route("/products", methods=["POST"])
@endpoint({"Manager"})
def create_product(ctx):
    body = get_body()
    sku = req_str(body, "sku")
    name = req_str(body, "name")
    category = req_enum(body, "category", CATEGORY)
    base_price = req_int(body, "base_price_cents", minimum=0)
    shelf = req_int(body, "shelf_life_hours", minimum=1)
    allergens = req_allergen_list(body, "allergens", default=[])
    is_custom = opt_bool(body, "is_custom", default=False)
    ent = create_entity(DB["products"], {
        "sku": sku,
        "name": name,
        "category": category,
        "allergens": allergens,
        "shelf_life_hours": shelf,
        "base_price_cents": base_price,
        "is_custom": is_custom,
        "status": "ACTIVE",
    })
    return ok(serialize(ent), 201)


@app.route("/products", methods=["GET"])
@endpoint(ROLES)
def list_products(ctx):
    items = list(DB["products"].values())
    cat = request.args.get("category")
    if cat is not None:
        items = [p for p in items if p["category"] == cat]
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.route("/products/<pid>", methods=["GET"])
@endpoint(ROLES)
def get_product(ctx, pid):
    ent = get_or_404(DB["products"], pid, "ERR_PRODUCT_NOT_FOUND")
    return ok(serialize(ent))


@app.route("/products/<pid>/discontinue", methods=["POST"])
@endpoint({"Manager"})
def discontinue_product(ctx, pid):
    ent = get_or_404(DB["products"], pid, "ERR_PRODUCT_NOT_FOUND")
    if ent["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "product is not ACTIVE")
    ent["status"] = "DISCONTINUED"
    touch(ent)
    return ok(serialize(ent))


# ===========================================================================
# Ovens
# ===========================================================================
@app.route("/ovens", methods=["POST"])
@endpoint({"Manager"})
def create_oven(ctx):
    body = get_body()
    name = req_str(body, "name")
    capacity = req_int(body, "capacity_trays", minimum=1)
    buffer_min = opt_int(body, "clean_buffer_minutes", default=15, minimum=0)
    ent = create_entity(DB["ovens"], {
        "name": name,
        "capacity_trays": capacity,
        "clean_buffer_minutes": buffer_min,
        "status": "ACTIVE",
    })
    return ok(serialize(ent), 201)


@app.route("/ovens", methods=["GET"])
@endpoint({"Manager", "Baker"})
def list_ovens(ctx):
    items = list(DB["ovens"].values())
    st = request.args.get("status")
    if st is not None:
        items = [o for o in items if o["status"] == st]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


# ===========================================================================
# Bake plans
# ===========================================================================
@app.route("/bake-plans", methods=["POST"])
@endpoint({"Manager"})
def create_bake_plan(ctx):
    body = get_body()
    production_date = req_dt(body, "production_date")
    notes = opt_str(body, "notes", default=None)
    ent = create_entity(DB["bake_plans"], {
        "production_date": production_date,
        "notes": notes,
        "status": "DRAFT",
        "total_theoretical_waste_units": 0,
        "total_actual_waste_units": 0,
        "total_waste_value_cents": 0,
    })
    return ok(serialize(ent), 201)


@app.route("/bake-plans/<plan_id>", methods=["GET"])
@endpoint({"Manager", "Baker"})
def get_bake_plan(ctx, plan_id):
    ent = get_or_404(DB["bake_plans"], plan_id, "ERR_BAKE_PLAN_NOT_FOUND")
    return ok(serialize(ent))


@app.route("/bake-plans/<plan_id>/lines", methods=["POST"])
@endpoint({"Manager"})
def add_bake_plan_line(ctx, plan_id):
    plan = get_or_404(DB["bake_plans"], plan_id, "ERR_BAKE_PLAN_NOT_FOUND")
    body = get_body()
    product_id = req_str(body, "product_id")
    par_qty = req_int(body, "par_qty", minimum=1)
    product = get_or_404(DB["products"], product_id, "ERR_PRODUCT_NOT_FOUND")
    if plan["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "plan is not DRAFT")
    if product["status"] != "ACTIVE":
        err("ERR_PRODUCT_DISCONTINUED", 409, "product is discontinued")
    ent = create_entity(DB["bake_plan_lines"], {
        "bake_plan_id": plan_id,
        "product_id": product_id,
        "par_qty": par_qty,
        "reserved_qty": 0,
        "available_qty": par_qty,
        "baked_qty": 0,
        "sold_qty": 0,
        "delivered_qty": 0,
        "theoretical_waste_units": 0,
        "actual_waste_units": 0,
    })
    return ok(serialize(ent), 201)


@app.route("/bake-plans/<plan_id>/lines", methods=["GET"])
@endpoint({"Manager", "Baker"})
def list_plan_lines(ctx, plan_id):
    get_or_404(DB["bake_plans"], plan_id, "ERR_BAKE_PLAN_NOT_FOUND")
    items = [l for l in DB["bake_plan_lines"].values() if l["bake_plan_id"] == plan_id]
    page, limit, offset, total = paginate(items, serializer=line_public)
    return ok_list(page, limit, offset, total)


@app.route("/bake-plans/<plan_id>/commit", methods=["POST"])
@endpoint({"Manager"})
def commit_bake_plan(ctx, plan_id):
    plan = get_or_404(DB["bake_plans"], plan_id, "ERR_BAKE_PLAN_NOT_FOUND")
    if plan["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "plan is not DRAFT")
    has_line = any(l["bake_plan_id"] == plan_id for l in DB["bake_plan_lines"].values())
    if not has_line:
        err("ERR_INVALID_STATE", 409, "plan has no par lines")
    plan["status"] = "COMMITTED"
    touch(plan)
    return ok(serialize(plan))


@app.route("/bake-plans/<plan_id>/reconcile", methods=["POST"])
@endpoint({"Manager"})
def reconcile_bake_plan(ctx, plan_id):
    plan = get_or_404(DB["bake_plans"], plan_id, "ERR_BAKE_PLAN_NOT_FOUND")
    if plan["status"] != "BAKED":
        err("ERR_INVALID_STATE", 409, "plan is not BAKED")
    total_theo = 0
    total_actual = 0
    total_value = 0
    for line in DB["bake_plan_lines"].values():
        if line["bake_plan_id"] != plan_id:
            continue
        refresh_line(line, bump=False)
        baked = line["baked_qty"]
        sold = line["sold_qty"]
        delivered = line["delivered_qty"]
        theo = max(0, baked - line["par_qty"])
        actual = max(0, baked - sold - delivered)
        line["theoretical_waste_units"] = theo
        line["actual_waste_units"] = actual
        touch(line)
        product = DB["products"].get(line["product_id"])
        base = product["base_price_cents"] if product else 0
        total_theo += theo
        total_actual += actual
        total_value += actual * base
    plan["total_theoretical_waste_units"] = total_theo
    plan["total_actual_waste_units"] = total_actual
    plan["total_waste_value_cents"] = total_value
    plan["status"] = "RECONCILED"
    touch(plan)
    return ok(serialize(plan))


@app.route("/bake-plans/<plan_id>/close", methods=["POST"])
@endpoint({"Manager"})
def close_bake_plan(ctx, plan_id):
    plan = get_or_404(DB["bake_plans"], plan_id, "ERR_BAKE_PLAN_NOT_FOUND")
    if plan["status"] != "RECONCILED":
        err("ERR_INVALID_STATE", 409, "plan is not RECONCILED")
    plan["status"] = "CLOSED"
    touch(plan)
    line_ids = {l["id"] for l in DB["bake_plan_lines"].values() if l["bake_plan_id"] == plan_id}
    for lot in DB["bake_lots"].values():
        if lot["bake_plan_line_id"] in line_ids and lot["status"] in ("FRESH", "MARKED_DOWN"):
            lot["status"] = "EXPIRED"
            touch(lot)
    return ok(serialize(plan))


@app.route("/bake-plan-lines/<line_id>", methods=["GET"])
@endpoint({"Manager", "Baker"})
def get_bake_plan_line(ctx, line_id):
    ent = get_or_404(DB["bake_plan_lines"], line_id, "ERR_BAKE_PLAN_LINE_NOT_FOUND")
    return ok(line_public(ent))


@app.route("/bake-plan-lines", methods=["GET"])
@endpoint({"Manager", "Baker"})
def list_bake_plan_lines(ctx):
    items = list(DB["bake_plan_lines"].values())
    bpid = request.args.get("bake_plan_id")
    if bpid is not None:
        items = [l for l in items if l["bake_plan_id"] == bpid]
    pid = request.args.get("product_id")
    if pid is not None:
        items = [l for l in items if l["product_id"] == pid]
    page, limit, offset, total = paginate(items, serializer=line_public)
    return ok_list(page, limit, offset, total)


# ===========================================================================
# Bake lots
# ===========================================================================
def slots_conflict(a_start, a_end, b_start, b_end, buffer_minutes):
    buf = timedelta(minutes=buffer_minutes)
    if a_start <= b_start:
        earlier_end, later_start = a_end, b_start
    else:
        earlier_end, later_start = b_end, a_start
    gap = later_start - earlier_end
    if gap <= timedelta(0):
        return True
    if gap < buf:
        return True
    return False


@app.route("/bake-lots", methods=["POST"])
@endpoint({"Manager", "Baker"})
def create_bake_lot(ctx):
    body = get_body()
    line_id = req_str(body, "bake_plan_line_id")
    oven_id = req_str(body, "oven_id")
    baked_qty = req_int(body, "baked_qty", minimum=1)
    produced_at = req_dt(body, "produced_at")
    slot_start = req_dt(body, "slot_start")
    slot_end = req_dt(body, "slot_end")
    line = get_or_404(DB["bake_plan_lines"], line_id, "ERR_BAKE_PLAN_LINE_NOT_FOUND")
    oven = get_or_404(DB["ovens"], oven_id, "ERR_OVEN_NOT_FOUND")
    # tier 7: oven slot conflict
    for lot in DB["bake_lots"].values():
        if lot["oven_id"] != oven_id:
            continue
        if slots_conflict(slot_start, slot_end, lot["slot_start"], lot["slot_end"],
                          oven["clean_buffer_minutes"]):
            err("ERR_OVEN_SLOT_CONFLICT", 409, "bake slot conflicts with another lot on this oven")
    # tier 8: interval validity
    if not (slot_end > slot_start):
        err("ERR_INVALID_WINDOW", 422, "slot_end must be after slot_start")
    product = DB["products"].get(line["product_id"])
    best_by = produced_at + timedelta(hours=product["shelf_life_hours"])
    ent = create_entity(DB["bake_lots"], {
        "bake_plan_line_id": line_id,
        "oven_id": oven_id,
        "baked_qty": baked_qty,
        "remaining_qty": baked_qty,
        "produced_at": produced_at,
        "best_by": best_by,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "status": "FRESH",
        "markdown_price_cents": None,
        "current_unit_price_cents": product["base_price_cents"],
    })
    refresh_line(line, bump=True)
    plan = DB["bake_plans"].get(line["bake_plan_id"])
    if plan is not None and plan["status"] == "COMMITTED":
        plan["status"] = "BAKED"
        touch(plan)
    return ok(serialize(ent), 201)


@app.route("/bake-lots/<lot_id>", methods=["GET"])
@endpoint({"Manager", "Baker", "Cashier"})
def get_bake_lot(ctx, lot_id):
    ent = get_or_404(DB["bake_lots"], lot_id, "ERR_BAKE_LOT_NOT_FOUND")
    return ok(serialize(ent))


@app.route("/bake-lots", methods=["GET"])
@endpoint({"Manager", "Baker", "Cashier"})
def list_bake_lots(ctx):
    items = list(DB["bake_lots"].values())
    lid = request.args.get("bake_plan_line_id")
    if lid is not None:
        items = [l for l in items if l["bake_plan_line_id"] == lid]
    oid = request.args.get("oven_id")
    if oid is not None:
        items = [l for l in items if l["oven_id"] == oid]
    st = request.args.get("status")
    if st is not None:
        items = [l for l in items if l["status"] == st]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.route("/bake-lots/<lot_id>/retail-sales", methods=["GET"])
@endpoint({"Manager", "Baker", "Cashier"})
def list_lot_sales(ctx, lot_id):
    get_or_404(DB["bake_lots"], lot_id, "ERR_BAKE_LOT_NOT_FOUND")
    items = [s for s in DB["retail_sales"].values() if s["bake_lot_id"] == lot_id]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.route("/bake-lots/<lot_id>/markdown", methods=["POST"])
@endpoint({"Manager", "Baker"})
def markdown_lot(ctx, lot_id):
    lot = get_or_404(DB["bake_lots"], lot_id, "ERR_BAKE_LOT_NOT_FOUND")
    body = get_body()
    expected = req_int(body, "expected_bake_lot_version")
    opt_str(body, "reason", default=None)
    # tier 4 state
    if lot["status"] == "EXPIRED":
        err("ERR_LOT_EXPIRED", 409, "lot is expired")
    if lot["status"] not in ("FRESH", "MARKED_DOWN"):
        err("ERR_INVALID_STATE", 409, "lot cannot be marked down from its current state")
    # tier 8 eligibility
    h = (lot["best_by"] - now_dt()).total_seconds() / 3600.0
    if not (0 < h <= MARKDOWN_WINDOW_HOURS):
        err("ERR_MARKDOWN_NOT_ELIGIBLE", 422, "lot is not eligible for markdown")
    # tier 10 OCC
    if expected != lot["version"]:
        err("ERR_STALE_LOT_VERSION", 412, "stale bake lot version")
    line = DB["bake_plan_lines"][lot["bake_plan_line_id"]]
    product = DB["products"][line["product_id"]]
    price = compute_markdown_price(lot, product)
    lot["markdown_price_cents"] = price
    lot["current_unit_price_cents"] = price
    lot["status"] = "MARKED_DOWN"
    touch(lot)
    return ok(serialize(lot))


@app.route("/bake-lots/<lot_id>/expire", methods=["POST"])
@endpoint({"Manager", "Baker"})
def expire_lot(ctx, lot_id):
    lot = get_or_404(DB["bake_lots"], lot_id, "ERR_BAKE_LOT_NOT_FOUND")
    if lot["status"] not in ("FRESH", "MARKED_DOWN"):
        err("ERR_INVALID_STATE", 409, "lot cannot be expired from its current state")
    lot["status"] = "EXPIRED"
    touch(lot)
    return ok(serialize(lot))


# ===========================================================================
# Retail sales
# ===========================================================================
@app.route("/retail-sales", methods=["POST"])
@endpoint({"Cashier", "Manager"})
def create_retail_sale(ctx):
    body = get_body()
    lot_id = req_str(body, "bake_lot_id")
    qty = req_int(body, "qty", minimum=1)
    lot = get_or_404(DB["bake_lots"], lot_id, "ERR_BAKE_LOT_NOT_FOUND")
    if lot["status"] == "EXPIRED":
        err("ERR_LOT_EXPIRED", 409, "lot is expired")
    if qty > lot["remaining_qty"]:
        err("ERR_INSUFFICIENT_INVENTORY", 409, "sale quantity exceeds remaining inventory")
    unit_price = lot["current_unit_price_cents"]
    ent = create_entity(DB["retail_sales"], {
        "bake_lot_id": lot_id,
        "qty": qty,
        "unit_price_cents": unit_price,
        "total_cents": qty * unit_price,
        "sold_at": now_dt(),
    }, common=False)
    lot["remaining_qty"] -= qty
    if lot["remaining_qty"] == 0 and lot["status"] in ("FRESH", "MARKED_DOWN"):
        lot["status"] = "SOLD_OUT"
    touch(lot)
    line = DB["bake_plan_lines"].get(lot["bake_plan_line_id"])
    if line is not None:
        refresh_line(line, bump=True)
    return ok(serialize(ent), 201)


# ===========================================================================
# Wholesale accounts
# ===========================================================================
@app.route("/wholesale-accounts", methods=["POST"])
@endpoint({"Manager"})
def create_account(ctx):
    body = get_body()
    name = req_str(body, "name")
    credit_limit = req_int(body, "credit_limit_cents", minimum=0)
    tier = opt_enum(body, "contract_tier", CONTRACT_TIER, default="STANDARD")
    restrictions = req_allergen_list(body, "allergen_restrictions", default=[])
    ent = create_entity(DB["wholesale_accounts"], {
        "name": name,
        "contract_tier": tier,
        "credit_limit_cents": credit_limit,
        "credit_balance_cents": 0,
        "allergen_restrictions": restrictions,
        "status": "ACTIVE",
    })
    return ok(serialize(ent), 201)


@app.route("/wholesale-accounts/<acct_id>", methods=["GET"])
@endpoint({"Manager", "WholesaleClient"})
def get_account(ctx, acct_id):
    require_owner(ctx, acct_id)
    ent = get_or_404(DB["wholesale_accounts"], acct_id, "ERR_ACCOUNT_NOT_FOUND")
    return ok(account_public(ent))


@app.route("/wholesale-accounts/<acct_id>/suspend", methods=["POST"])
@endpoint({"Manager"})
def suspend_account(ctx, acct_id):
    acct = get_or_404(DB["wholesale_accounts"], acct_id, "ERR_ACCOUNT_NOT_FOUND")
    if acct["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "account is not ACTIVE")
    acct["status"] = "SUSPENDED"
    touch(acct)
    return ok(account_public(acct))


@app.route("/wholesale-accounts/<acct_id>/close", methods=["POST"])
@endpoint({"Manager"})
def close_account(ctx, acct_id):
    acct = get_or_404(DB["wholesale_accounts"], acct_id, "ERR_ACCOUNT_NOT_FOUND")
    if acct["status"] not in ("ACTIVE", "SUSPENDED"):
        err("ERR_INVALID_STATE", 409, "account cannot be closed from its current state")
    refresh_account(acct, bump=False)
    if acct["credit_balance_cents"] != 0:
        err("ERR_INVALID_STATE", 409, "account has an outstanding credit balance")
    acct["status"] = "CLOSED"
    touch(acct)
    # cascade: ACTIVE/PAUSED standing orders -> CANCELLED; their open orders -> CANCELLED
    for so in DB["standing_orders"].values():
        if so["wholesale_account_id"] == acct_id and so["status"] in ("ACTIVE", "PAUSED"):
            so["status"] = "CANCELLED"
            touch(so)
            for o in list(DB["delivery_orders"].values()):
                if o["standing_order_id"] == so["id"] and o["fulfillment_status"] in (
                        "PENDING", "PACKED", "OUT_FOR_DELIVERY"):
                    do_cancel_order(o)
    return ok(account_public(acct))


@app.route("/wholesale-accounts/<acct_id>/statement", methods=["GET"])
@endpoint({"Manager", "WholesaleClient"})
def account_statement(ctx, acct_id):
    require_owner(ctx, acct_id)
    acct = get_or_404(DB["wholesale_accounts"], acct_id, "ERR_ACCOUNT_NOT_FOUND")
    dd_raw = request.args.get("delivery_date")
    if dd_raw is None:
        bad("delivery_date query parameter is required")
    try:
        dd = parse_dt(dd_raw)
    except Exception:
        bad("delivery_date must be a valid ISO 8601 timestamp")
    invoice_total = 0
    list_total = 0
    order_count = 0
    for o in DB["delivery_orders"].values():
        if o["wholesale_account_id"] != acct_id:
            continue
        if o["fulfillment_status"] != "DELIVERED":
            continue
        if o["delivery_date"] != dd:
            continue
        invoice_total += o["line_total_cents"]
        list_total += o["list_total_cents"]
        order_count += 1
    return ok({
        "invoice_total_cents": invoice_total,
        "list_total_cents": list_total,
        "order_count": order_count,
    })


# ===========================================================================
# Standing orders
# ===========================================================================
@app.route("/standing-orders", methods=["POST"])
@endpoint({"Manager"})
def create_standing_order(ctx):
    body = get_body()
    account_id = req_str(body, "wholesale_account_id")
    product_id = req_str(body, "product_id")
    qty = req_int(body, "qty_per_delivery", minimum=1)
    mask = body.get("weekday_mask")
    if not isinstance(mask, list) or len(mask) == 0:
        bad("weekday_mask must be a non-empty array")
    for d in mask:
        if not isinstance(d, str) or d not in WEEKDAY:
            bad("weekday_mask has invalid value")
    cutoff = opt_int(body, "cutoff_hours", default=24, minimum=0)
    account = get_or_404(DB["wholesale_accounts"], account_id, "ERR_ACCOUNT_NOT_FOUND")
    product = get_or_404(DB["products"], product_id, "ERR_PRODUCT_NOT_FOUND")
    # tier 5 allergen
    if set(product["allergens"]) & set(account["allergen_restrictions"]):
        err("ERR_ALLERGEN_CONFLICT", 422, "product allergens conflict with account restrictions")
    # tier 6 discontinued
    if product["status"] != "ACTIVE":
        err("ERR_PRODUCT_DISCONTINUED", 409, "product is discontinued")
    ent = create_entity(DB["standing_orders"], {
        "wholesale_account_id": account_id,
        "product_id": product_id,
        "qty_per_delivery": qty,
        "weekday_mask": list(mask),
        "cutoff_hours": cutoff,
        "status": "ACTIVE",
    })
    return ok(serialize(ent), 201)


@app.route("/standing-orders/<so_id>", methods=["GET"])
@endpoint({"Manager", "WholesaleClient"})
def get_standing_order(ctx, so_id):
    ent = get_or_404(DB["standing_orders"], so_id, "ERR_STANDING_ORDER_NOT_FOUND")
    require_owner(ctx, ent["wholesale_account_id"])
    return ok(serialize(ent))


@app.route("/standing-orders", methods=["GET"])
@endpoint({"Manager", "WholesaleClient"})
def list_standing_orders(ctx):
    items = list(DB["standing_orders"].values())
    if ctx["role"] == "WholesaleClient":
        items = [s for s in items if s["wholesale_account_id"] == ctx["user_id"]]
    aid = request.args.get("wholesale_account_id")
    if aid is not None:
        items = [s for s in items if s["wholesale_account_id"] == aid]
    pid = request.args.get("product_id")
    if pid is not None:
        items = [s for s in items if s["product_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [s for s in items if s["status"] == st]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.route("/standing-orders/<so_id>/pause", methods=["POST"])
@endpoint({"Manager"})
def pause_standing_order(ctx, so_id):
    so = get_or_404(DB["standing_orders"], so_id, "ERR_STANDING_ORDER_NOT_FOUND")
    if so["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "standing order is not ACTIVE")
    so["status"] = "PAUSED"
    touch(so)
    return ok(serialize(so))


@app.route("/standing-orders/<so_id>/resume", methods=["POST"])
@endpoint({"Manager"})
def resume_standing_order(ctx, so_id):
    so = get_or_404(DB["standing_orders"], so_id, "ERR_STANDING_ORDER_NOT_FOUND")
    if so["status"] != "PAUSED":
        err("ERR_INVALID_STATE", 409, "standing order is not PAUSED")
    so["status"] = "ACTIVE"
    touch(so)
    return ok(serialize(so))


@app.route("/standing-orders/<so_id>/cancel", methods=["POST"])
@endpoint({"Manager"})
def cancel_standing_order(ctx, so_id):
    so = get_or_404(DB["standing_orders"], so_id, "ERR_STANDING_ORDER_NOT_FOUND")
    if so["status"] not in ("ACTIVE", "PAUSED"):
        err("ERR_INVALID_STATE", 409, "standing order cannot be cancelled from its current state")
    so["status"] = "CANCELLED"
    touch(so)
    for o in list(DB["delivery_orders"].values()):
        if o["standing_order_id"] == so_id and o["fulfillment_status"] in (
                "PENDING", "PACKED", "OUT_FOR_DELIVERY"):
            do_cancel_order(o)
    return ok(serialize(so))


# ===========================================================================
# Delivery orders
# ===========================================================================
def do_cancel_order(order):
    """Cancel or void a delivery order and cascade side effects."""
    prev = order["fulfillment_status"]
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    line = DB["bake_plan_lines"].get(order["bake_plan_line_id"])
    if line is not None:
        refresh_line(line, bump=True)
    if prev == "DELIVERED":
        # void: reverse credit only
        account = DB["wholesale_accounts"].get(order["wholesale_account_id"])
        if account is not None:
            refresh_account(account, bump=True)
    else:
        # cancel any non-cancelled route stop referencing this order
        for s in DB["route_stops"].values():
            if s["delivery_order_id"] == order["id"] and s["status"] != "CANCELLED":
                s["status"] = "CANCELLED"
                touch(s)
                route = DB["delivery_routes"].get(s["route_id"])
                if route is not None:
                    refresh_route(route, bump=True)


def deliver_order(order, check_credit):
    account = DB["wholesale_accounts"].get(order["wholesale_account_id"])
    if check_credit:
        refresh_account(account, bump=False)
        outstanding = order["line_total_cents"] - order["amount_paid_cents"]
        if account["credit_balance_cents"] + outstanding > account["credit_limit_cents"]:
            err("ERR_CREDIT_LIMIT_EXCEEDED", 402, "delivery would exceed the account credit limit")
    order["fulfillment_status"] = "DELIVERED"
    touch(order)
    if account is not None:
        refresh_account(account, bump=True)
    line = DB["bake_plan_lines"].get(order["bake_plan_line_id"])
    if line is not None:
        refresh_line(line, bump=True)


@app.route("/delivery-orders", methods=["POST"])
@endpoint({"Manager", "WholesaleClient"})
def create_delivery_order(ctx):
    body_peek = request.get_json(silent=True)
    if ctx["role"] == "WholesaleClient":
        acct_in_body = body_peek.get("wholesale_account_id") if isinstance(body_peek, dict) else None
        if acct_in_body != ctx["user_id"]:
            err("ERR_UNAUTHORIZED", 403, "not owner of this account")
    body = get_body()
    account_id = req_str(body, "wholesale_account_id")
    product_id = req_str(body, "product_id")
    line_id = req_str(body, "bake_plan_line_id")
    delivery_date = req_dt(body, "delivery_date")
    qty = req_int(body, "qty", minimum=1)
    standing_order_id = opt_str(body, "standing_order_id", default=None)
    # tier 3 existence (declared FK order)
    account = get_or_404(DB["wholesale_accounts"], account_id, "ERR_ACCOUNT_NOT_FOUND")
    product = get_or_404(DB["products"], product_id, "ERR_PRODUCT_NOT_FOUND")
    line = get_or_404(DB["bake_plan_lines"], line_id, "ERR_BAKE_PLAN_LINE_NOT_FOUND")
    standing = None
    if standing_order_id is not None:
        standing = get_or_404(DB["standing_orders"], standing_order_id, "ERR_STANDING_ORDER_NOT_FOUND")
    # tier 5 allergen
    if set(product["allergens"]) & set(account["allergen_restrictions"]):
        err("ERR_ALLERGEN_CONFLICT", 422, "product allergens conflict with account restrictions")
    # tier 6 discontinued
    if product["status"] != "ACTIVE":
        err("ERR_PRODUCT_DISCONTINUED", 409, "product is discontinued")
    # tier 6 mismatch
    if line["product_id"] != product_id:
        err("ERR_ACCOUNT_MISMATCH", 409, "bake plan line product does not match order product")
    if standing is not None:
        if standing["wholesale_account_id"] != account_id or standing["status"] != "ACTIVE":
            err("ERR_ACCOUNT_MISMATCH", 409, "standing order does not match the account or is not active")
    # tier 7 par reservation
    refresh_line(line, bump=False)
    if qty > line["available_qty"]:
        err("ERR_INSUFFICIENT_PAR", 409, "quantity exceeds available par")
    # tier 8 cutoff (only for standing-order orders)
    if standing is not None:
        if (delivery_date - now_dt()) < timedelta(hours=standing["cutoff_hours"]):
            err("ERR_PAST_CUTOFF", 422, "order created inside the standing order cutoff window")
    # pricing
    unit_price, line_total, list_total = compute_wholesale_price(product, account, qty)
    # tier 9 credit ceiling at booking
    refresh_account(account, bump=False)
    if account["credit_balance_cents"] + line_total > account["credit_limit_cents"]:
        err("ERR_CREDIT_LIMIT_EXCEEDED", 402, "order would exceed the account credit limit")
    ent = create_entity(DB["delivery_orders"], {
        "wholesale_account_id": account_id,
        "standing_order_id": standing_order_id,
        "product_id": product_id,
        "bake_plan_line_id": line_id,
        "delivery_date": delivery_date,
        "qty": qty,
        "unit_price_cents": unit_price,
        "line_total_cents": line_total,
        "list_total_cents": list_total,
        "amount_paid_cents": 0,
        "payment_status": "UNPAID",
        "fulfillment_status": "PENDING",
    })
    refresh_line(line, bump=True)
    return ok(serialize(ent), 201)


@app.route("/delivery-orders/<order_id>", methods=["GET"])
@endpoint({"Manager", "WholesaleClient"})
def get_delivery_order(ctx, order_id):
    ent = get_or_404(DB["delivery_orders"], order_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    require_owner(ctx, ent["wholesale_account_id"])
    return ok(serialize(ent))


@app.route("/delivery-orders", methods=["GET"])
@endpoint({"Manager", "WholesaleClient"})
def list_delivery_orders(ctx):
    items = list(DB["delivery_orders"].values())
    if ctx["role"] == "WholesaleClient":
        items = [o for o in items if o["wholesale_account_id"] == ctx["user_id"]]
    aid = request.args.get("wholesale_account_id")
    if aid is not None:
        items = [o for o in items if o["wholesale_account_id"] == aid]
    sid = request.args.get("standing_order_id")
    if sid is not None:
        items = [o for o in items if o["standing_order_id"] == sid]
    lid = request.args.get("bake_plan_line_id")
    if lid is not None:
        items = [o for o in items if o["bake_plan_line_id"] == lid]
    pid = request.args.get("product_id")
    if pid is not None:
        items = [o for o in items if o["product_id"] == pid]
    fs = request.args.get("fulfillment_status")
    if fs is not None:
        items = [o for o in items if o["fulfillment_status"] == fs]
    dd_raw = request.args.get("delivery_date")
    if dd_raw is not None:
        try:
            dd = parse_dt(dd_raw)
        except Exception:
            bad("delivery_date must be a valid ISO 8601 timestamp")
        items = [o for o in items if o["delivery_date"] == dd]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.route("/delivery-orders/<order_id>/pack", methods=["POST"])
@endpoint({"Manager"})
def pack_delivery_order(ctx, order_id):
    order = get_or_404(DB["delivery_orders"], order_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    if order["fulfillment_status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "order is not PENDING")
    account = DB["wholesale_accounts"].get(order["wholesale_account_id"])
    if account is None or account["status"] != "ACTIVE":
        err("ERR_ACCOUNT_SUSPENDED", 409, "account is not ACTIVE")
    order["fulfillment_status"] = "PACKED"
    touch(order)
    return ok(serialize(order))


@app.route("/delivery-orders/<order_id>/deliver", methods=["POST"])
@endpoint({"Manager", "Driver"})
def deliver_delivery_order(ctx, order_id):
    order = get_or_404(DB["delivery_orders"], order_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    status = order["fulfillment_status"]
    if status == "PACKED":
        deliver_order(order, check_credit=True)
    elif status == "OUT_FOR_DELIVERY":
        deliver_order(order, check_credit=False)
    else:
        err("ERR_INVALID_STATE", 409, "order cannot be delivered from its current state")
    return ok(serialize(order))


@app.route("/delivery-orders/<order_id>/payments", methods=["POST"])
@endpoint({"Manager", "WholesaleClient"})
def pay_delivery_order(ctx, order_id):
    order = get_or_404(DB["delivery_orders"], order_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    require_owner(ctx, order["wholesale_account_id"])
    body = get_body()
    amount = req_int(body, "amount_cents", minimum=1)
    if order["fulfillment_status"] == "CANCELLED":
        err("ERR_INVALID_STATE", 409, "order is cancelled")
    ps = order["payment_status"]
    lt = order["line_total_cents"]
    ap = order["amount_paid_cents"]
    outstanding = lt - ap
    if ps == "PAID":
        err("ERR_INVALID_STATE", 409, "order is already fully paid")
    if ps == "UNPAID" and amount == lt:
        new_ap, new_ps = lt, "PAID"
    elif ps == "UNPAID" and 0 < amount < lt:
        new_ap, new_ps = ap + amount, "PARTIALLY_PAID"
    elif ps == "PARTIALLY_PAID" and amount == outstanding:
        new_ap, new_ps = lt, "PAID"
    else:
        err("ERR_INVALID_STATE", 409, "payment amount does not match a valid transition")
    order["amount_paid_cents"] = new_ap
    order["payment_status"] = new_ps
    touch(order)
    if order["fulfillment_status"] == "DELIVERED":
        account = DB["wholesale_accounts"].get(order["wholesale_account_id"])
        if account is not None:
            refresh_account(account, bump=True)
    return ok(serialize(order))


@app.route("/delivery-orders/<order_id>/cancel", methods=["POST"])
@endpoint({"Manager"})
def cancel_delivery_order(ctx, order_id):
    order = get_or_404(DB["delivery_orders"], order_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    if order["fulfillment_status"] == "CANCELLED":
        err("ERR_INVALID_STATE", 409, "order is already cancelled")
    do_cancel_order(order)
    return ok(serialize(order))


# ===========================================================================
# Delivery routes
# ===========================================================================
@app.route("/delivery-routes", methods=["POST"])
@endpoint({"Manager"})
def create_route(ctx):
    body = get_body()
    route_date = req_dt(body, "route_date")
    driver_name = req_str(body, "driver_name")
    window_start = req_dt(body, "window_start")
    window_end = req_dt(body, "window_end")
    if not (window_end > window_start):
        err("ERR_INVALID_WINDOW", 422, "window_end must be after window_start")
    ent = create_entity(DB["delivery_routes"], {
        "route_date": route_date,
        "driver_name": driver_name,
        "window_start": window_start,
        "window_end": window_end,
        "status": "PLANNED",
        "stop_count": 0,
        "total_load_qty": 0,
    })
    return ok(serialize(ent), 201)


@app.route("/delivery-routes/<route_id>", methods=["GET"])
@endpoint({"Manager", "Driver"})
def get_route(ctx, route_id):
    ent = get_or_404(DB["delivery_routes"], route_id, "ERR_ROUTE_NOT_FOUND")
    return ok(route_public(ent))


@app.route("/delivery-routes/<route_id>/dispatch", methods=["POST"])
@endpoint({"Manager"})
def dispatch_route(ctx, route_id):
    route = get_or_404(DB["delivery_routes"], route_id, "ERR_ROUTE_NOT_FOUND")
    if route["status"] != "PLANNED":
        err("ERR_INVALID_STATE", 409, "route is not PLANNED")
    refresh_route(route, bump=False)
    if route["stop_count"] < 1:
        err("ERR_INVALID_STATE", 409, "route has no stops")
    route["status"] = "DISPATCHED"
    touch(route)
    for s in DB["route_stops"].values():
        if s["route_id"] == route_id and s["status"] != "CANCELLED":
            o = DB["delivery_orders"].get(s["delivery_order_id"])
            if o is not None and o["fulfillment_status"] == "PACKED":
                o["fulfillment_status"] = "OUT_FOR_DELIVERY"
                touch(o)
    return ok(route_public(route))


@app.route("/delivery-routes/<route_id>/cancel", methods=["POST"])
@endpoint({"Manager"})
def cancel_route(ctx, route_id):
    route = get_or_404(DB["delivery_routes"], route_id, "ERR_ROUTE_NOT_FOUND")
    if route["status"] != "PLANNED":
        err("ERR_INVALID_STATE", 409, "route is not PLANNED")
    route["status"] = "CANCELLED"
    touch(route)
    for s in DB["route_stops"].values():
        if s["route_id"] == route_id and s["status"] == "PENDING":
            s["status"] = "CANCELLED"
            touch(s)
    refresh_route(route, bump=True)
    return ok(route_public(route))


@app.route("/delivery-routes/<route_id>/stops", methods=["POST"])
@endpoint({"Manager"})
def add_route_stop(ctx, route_id):
    route = get_or_404(DB["delivery_routes"], route_id, "ERR_ROUTE_NOT_FOUND")
    body = get_body()
    order_id = req_str(body, "delivery_order_id")
    sequence = req_int(body, "sequence", minimum=1)
    aws = req_dt(body, "arrival_window_start")
    awe = req_dt(body, "arrival_window_end")
    get_or_404(DB["delivery_orders"], order_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    # tier 7: window overlap with other non-cancelled stops on same route (half-open)
    for s in DB["route_stops"].values():
        if s["route_id"] != route_id or s["status"] == "CANCELLED":
            continue
        if aws < s["arrival_window_end"] and s["arrival_window_start"] < awe:
            err("ERR_STOP_WINDOW_OVERLAP", 409, "stop window overlaps another stop on this route")
    # tier 7: duplicate stop referencing same order
    for s in DB["route_stops"].values():
        if s["delivery_order_id"] == order_id and s["status"] != "CANCELLED":
            err("ERR_DUPLICATE_STOP", 409, "a non-cancelled stop already references this order")
    # tier 8: window validity and containment in route window
    if not (awe > aws):
        err("ERR_INVALID_WINDOW", 422, "arrival_window_end must be after arrival_window_start")
    if aws < route["window_start"] or awe > route["window_end"]:
        err("ERR_INVALID_WINDOW", 422, "stop window must fall within the route window")
    ent = create_entity(DB["route_stops"], {
        "route_id": route_id,
        "delivery_order_id": order_id,
        "sequence": sequence,
        "arrival_window_start": aws,
        "arrival_window_end": awe,
        "status": "PENDING",
    })
    refresh_route(route, bump=True)
    return ok(serialize(ent), 201)


@app.route("/delivery-routes/<route_id>/stops", methods=["GET"])
@endpoint({"Manager", "Driver"})
def list_route_stops(ctx, route_id):
    get_or_404(DB["delivery_routes"], route_id, "ERR_ROUTE_NOT_FOUND")
    items = [s for s in DB["route_stops"].values() if s["route_id"] == route_id]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.route("/route-stops/<stop_id>", methods=["GET"])
@endpoint({"Manager", "Driver"})
def get_route_stop(ctx, stop_id):
    ent = get_or_404(DB["route_stops"], stop_id, "ERR_ROUTE_STOP_NOT_FOUND")
    return ok(serialize(ent))


@app.route("/route-stops", methods=["GET"])
@endpoint({"Manager", "Driver"})
def list_route_stops_flat(ctx):
    items = list(DB["route_stops"].values())
    rid = request.args.get("route_id")
    if rid is not None:
        items = [s for s in items if s["route_id"] == rid]
    oid = request.args.get("delivery_order_id")
    if oid is not None:
        items = [s for s in items if s["delivery_order_id"] == oid]
    st = request.args.get("status")
    if st is not None:
        items = [s for s in items if s["status"] == st]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.route("/route-stops/<stop_id>/complete", methods=["POST"])
@endpoint({"Manager", "Driver"})
def complete_route_stop(ctx, stop_id):
    stop = get_or_404(DB["route_stops"], stop_id, "ERR_ROUTE_STOP_NOT_FOUND")
    if stop["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "stop is not PENDING")
    route = DB["delivery_routes"].get(stop["route_id"])
    if route is None or route["status"] != "DISPATCHED":
        err("ERR_ROUTE_NOT_DISPATCHED", 409, "route is not dispatched")
    stop["status"] = "DELIVERED"
    touch(stop)
    order = DB["delivery_orders"].get(stop["delivery_order_id"])
    if order is not None and order["fulfillment_status"] == "OUT_FOR_DELIVERY":
        deliver_order(order, check_credit=False)
    # if all non-cancelled stops are DELIVERED, complete the route
    live_stops = [s for s in DB["route_stops"].values()
                  if s["route_id"] == route["id"] and s["status"] != "CANCELLED"]
    if live_stops and all(s["status"] == "DELIVERED" for s in live_stops):
        route["status"] = "COMPLETED"
        touch(route)
    return ok(serialize(stop))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
