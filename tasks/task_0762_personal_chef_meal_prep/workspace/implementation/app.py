import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# Enums / constants
# =============================================================================
ROLES = {"PlatformAdmin", "Client", "Chef"}
BILLING_MODES = {"PER_WEEK", "PER_MEAL"}
EQUIPMENT = {"OVEN", "STOVETOP", "BLENDER", "GRILL", "SOUS_VIDE"}
RESTRICTIONS = {"VEGAN", "VEGETARIAN", "GLUTEN_FREE", "KETO", "PALEO", "OMNIVORE"}
ALLERGENS = {"NUTS", "DAIRY", "SHELLFISH", "EGGS", "SOY", "GLUTEN"}
MEAL_SLOTS = {"BREAKFAST", "LUNCH", "DINNER"}
INGREDIENT_STATUSES = {"INCLUDED", "ADDED", "SUBSTITUTED_OUT"}

STRIKE_LIMIT = 3
CHEF_BUFFER = timedelta(minutes=60)

TIER1_MAX_EXCL = 15000
TIER2_MAX_EXCL = 30000
TIER1_PCT = 15
TIER2_PCT = 12
TIER3_PCT = 10
PER_HEAD_SURCHARGE_CENTS = 500
SURCHARGE_FREE_HEADS = 2
PER_MEAL_MARKUP_PCT = 20

# =============================================================================
# Error catalog
# =============================================================================
ERR_HTTP = {
    "ERR_MISSING_USER_CONTEXT": 400,
    "ERR_VALIDATION": 400,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_CHEF_NOT_FOUND": 404,
    "ERR_DIETARY_PLAN_NOT_FOUND": 404,
    "ERR_WEEKLY_MENU_NOT_FOUND": 404,
    "ERR_MENU_MEAL_NOT_FOUND": 404,
    "ERR_COOK_SESSION_NOT_FOUND": 404,
    "ERR_CONTAINER_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_STALE_CLIENT_VERSION": 412,
    "ERR_INVALID_MENU_STATE": 409,
    "ERR_INVALID_SESSION_STATE": 409,
    "ERR_INVALID_INVOICE_STATE": 409,
    "ERR_MENU_HAS_NO_MEALS": 409,
    "ERR_WEEK_ALREADY_STARTED": 409,
    "ERR_MEAL_NOT_COOKED": 409,
    "ERR_DIETARY_PLAN_NOT_ACTIVE": 409,
    "ERR_MENU_NOT_APPROVED": 409,
    "ERR_CHEF_SUSPENDED": 409,
    "ERR_INVALID_RATING": 422,
    "ERR_ALLERGEN_CONFLICT": 422,
    "ERR_EQUIPMENT_UNAVAILABLE": 422,
    "ERR_CHEF_SCHEDULE_CONFLICT": 409,
    "ERR_CLIENT_KITCHEN_DOUBLE_BOOKED": 409,
    "ERR_OUTSIDE_KITCHEN_HOURS": 422,
    "ERR_GROCERY_BUDGET_EXCEEDED": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=""):
        super().__init__(error_id)
        self.error_id = error_id
        self.http = ERR_HTTP[error_id]
        self.message = message or error_id


# =============================================================================
# In-memory store (wiped on every process boot)
# =============================================================================
DB = {
    "clients": {},
    "chefs": {},
    "plans": {},
    "menus": {},
    "meals": {},
    "sessions": {},
    "containers": {},
    "invoices": {},
}
_SEQ = {"n": 0}


def _next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# =============================================================================
# Time helpers
# =============================================================================
def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_ms(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_wall():
    return datetime.now(timezone.utc)


CLOCK = {"now": parse_iso("2026-03-01T00:00:00Z")}


def clock_now():
    return CLOCK["now"]


# =============================================================================
# Money helpers
# =============================================================================
def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =============================================================================
# Envelope helpers
# =============================================================================
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": iso_ms(now_wall())}
    if extra:
        m.update(extra)
    return m


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize(data) if data is not None else {}}
    return jsonify(body), code


def ok_raw(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, pag):
    body = {
        "meta": _meta(pag),
        "response_type": "array",
        "data": [serialize(i) for i in items],
    }
    return jsonify(body), 200


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http


# =============================================================================
# Entity base + mutation helpers
# =============================================================================
def new_entity(bucket, fields):
    now = iso_ms(now_wall())
    e = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    e.update(fields)
    DB[bucket][e["id"]] = e
    return e


def touch(entity):
    entity["updated_at"] = iso_ms(now_wall())
    entity["version"] += 1


# =============================================================================
# Auth
# =============================================================================
def auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or str(uid).strip() == "" or str(role).strip() == "":
        raise ApiError("ERR_MISSING_USER_CONTEXT", "Missing or malformed user context headers")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s may not invoke this operation" % role)
    return uid, role


# =============================================================================
# Existence helpers
# =============================================================================
def get_client(cid):
    c = DB["clients"].get(cid)
    if c is None:
        raise ApiError("ERR_CLIENT_NOT_FOUND", "Client not found")
    return c


def get_chef(cid):
    c = DB["chefs"].get(cid)
    if c is None:
        raise ApiError("ERR_CHEF_NOT_FOUND", "Chef not found")
    return c


def get_plan(pid):
    p = DB["plans"].get(pid)
    if p is None:
        raise ApiError("ERR_DIETARY_PLAN_NOT_FOUND", "Dietary plan not found")
    return p


def get_menu(mid):
    m = DB["menus"].get(mid)
    if m is None:
        raise ApiError("ERR_WEEKLY_MENU_NOT_FOUND", "Weekly menu not found")
    return m


def get_meal(mid):
    m = DB["meals"].get(mid)
    if m is None:
        raise ApiError("ERR_MENU_MEAL_NOT_FOUND", "Menu meal not found")
    return m


def get_session(sid):
    s = DB["sessions"].get(sid)
    if s is None:
        raise ApiError("ERR_COOK_SESSION_NOT_FOUND", "Cook session not found")
    return s


def get_container(cid):
    c = DB["containers"].get(cid)
    if c is None:
        raise ApiError("ERR_CONTAINER_NOT_FOUND", "Container not found")
    return c


def get_invoice(iid):
    inv = DB["invoices"].get(iid)
    if inv is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", "Invoice not found")
    return inv


# =============================================================================
# Body / validation helpers
# =============================================================================
def body():
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def bad(msg="Invalid request body"):
    raise ApiError("ERR_VALIDATION", msg)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def req_int(d, key, minimum=None):
    v = d.get(key)
    if not is_int(v):
        bad("Field %s must be an integer" % key)
    if minimum is not None and v < minimum:
        bad("Field %s must be >= %s" % (key, minimum))
    return v


def req_str(d, key):
    v = d.get(key)
    if not isinstance(v, str) or v.strip() == "":
        bad("Field %s is required" % key)
    return v


def req_enum(d, key, allowed):
    v = req_str(d, key)
    if v not in allowed:
        bad("Field %s must be one of %s" % (key, sorted(allowed)))
    return v


def req_number(d, key, minimum=None):
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad("Field %s must be a number" % key)
    if minimum is not None and v < minimum:
        bad("Field %s must be >= %s" % (key, minimum))
    return v


def validate_tag_array(d, key, allowed, required=True):
    v = d.get(key)
    if v is None:
        if required:
            bad("Field %s is required" % key)
        return []
    if not isinstance(v, list):
        bad("Field %s must be an array" % key)
    for item in v:
        if item not in allowed:
            bad("Field %s contains invalid value %r" % (key, item))
    return list(v)


# =============================================================================
# Ownership helpers
# =============================================================================
def client_owns(role, uid, client_id):
    if role == "Client" and client_id is not None and uid != client_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Caller does not own this resource")


def chef_owns(role, uid, chef_id):
    if role == "Chef" and chef_id is not None and uid != chef_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Caller does not own this resource")


# =============================================================================
# Calculations
# =============================================================================
def compute_meal_cost(meal):
    total = 0
    for ing in meal["ingredients"]:
        if ing.get("status") in ("INCLUDED", "ADDED"):
            q = Decimal(str(ing["quantity"]))
            c = Decimal(str(ing["unit_cost_cents"]))
            total += round_half_up(q * c)
    return total


def recompute_meal_cost(meal):
    meal["meal_grocery_cost_cents"] = compute_meal_cost(meal)


def compute_menu_grocery(menu):
    total = 0
    for meal in DB["meals"].values():
        if meal["weekly_menu_id"] == menu["id"] and meal["status"] in ("PLANNED", "COOKED"):
            total += meal["meal_grocery_cost_cents"]
    return total


def markup_tier(grocery):
    if grocery < TIER1_MAX_EXCL:
        return TIER1_PCT
    if grocery < TIER2_MAX_EXCL:
        return TIER2_PCT
    return TIER3_PCT


def payout(start_dt, end_dt, rate_cents):
    seconds = Decimal((end_dt - start_dt).total_seconds())
    hours = seconds / Decimal(3600)
    return round_half_up(hours * Decimal(rate_cents))


def add_wallet(client, delta):
    client["wallet_credit_cents"] = max(0, client["wallet_credit_cents"] + delta)


def active_allergens_conflict(meal, plan_allergens):
    for ing in meal["ingredients"]:
        if ing.get("status") in ("INCLUDED", "ADDED"):
            for tag in ing.get("allergen_tags", []) or []:
                if tag in plan_allergens:
                    return True
    return False


# =============================================================================
# Health
# =============================================================================
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# =============================================================================
# Clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(["PlatformAdmin"])
    d = body()
    to = d.get("to_iso8601")
    try:
        dt = parse_iso(to)
    except Exception:
        bad("to_iso8601 must be a valid ISO8601 instant")
    CLOCK["now"] = dt
    return ok_raw({})


# =============================================================================
# Clients
# =============================================================================
@app.route("/clients", methods=["POST"])
def create_client():
    auth(["PlatformAdmin"])
    d = body()
    full_name = req_str(d, "full_name")
    email = req_str(d, "email")
    household_size = req_int(d, "household_size", minimum=1)
    billing_mode = req_enum(d, "billing_mode", BILLING_MODES)
    weekly_base_fee_cents = req_int(d, "weekly_base_fee_cents", minimum=0)
    per_meal_fee_cents = req_int(d, "per_meal_fee_cents", minimum=0)
    weekly_grocery_budget_cents = req_int(d, "weekly_grocery_budget_cents", minimum=0)
    available_equipment = validate_tag_array(d, "available_equipment", EQUIPMENT, required=False)
    kitchen_open_hour = req_int(d, "kitchen_open_hour")
    kitchen_close_hour = req_int(d, "kitchen_close_hour")
    if not (0 <= kitchen_open_hour <= 23):
        bad("kitchen_open_hour must be 0..23")
    if not (0 <= kitchen_close_hour <= 24):
        bad("kitchen_close_hour must be 0..24")
    if not (kitchen_close_hour > kitchen_open_hour):
        bad("kitchen_close_hour must be strictly greater than kitchen_open_hour")

    c = new_entity("clients", {
        "full_name": full_name,
        "email": email,
        "household_size": household_size,
        "billing_mode": billing_mode,
        "weekly_base_fee_cents": weekly_base_fee_cents,
        "per_meal_fee_cents": per_meal_fee_cents,
        "weekly_grocery_budget_cents": weekly_grocery_budget_cents,
        "available_equipment": available_equipment,
        "kitchen_open_hour": kitchen_open_hour,
        "kitchen_close_hour": kitchen_close_hour,
        "wallet_credit_cents": 0,
        "status": "ACTIVE",
    })
    return ok_object(c, 201)


@app.route("/clients/<cid>", methods=["GET"])
def fetch_client(cid):
    auth(["PlatformAdmin", "Client", "Chef"])
    c = get_client(cid)
    return ok_object(c)


@app.route("/clients/<cid>/cancel", methods=["POST"])
def cancel_client(cid):
    auth(["PlatformAdmin"])
    client = get_client(cid)

    client["status"] = "CANCELLED"
    for menu in DB["menus"].values():
        if menu["client_id"] != cid:
            continue
        if menu["status"] not in ("DRAFT", "PROPOSED", "APPROVED", "SKIPPED"):
            continue
        was_skipped = menu["status"] == "SKIPPED"
        menu["status"] = "CANCELLED"
        touch(menu)
        if was_skipped:
            add_wallet(client, -client["weekly_base_fee_cents"])
        for meal in DB["meals"].values():
            if meal["weekly_menu_id"] == menu["id"] and meal["status"] == "PLANNED":
                meal["status"] = "CANCELLED"
                touch(meal)
        for sess in DB["sessions"].values():
            if sess["weekly_menu_id"] == menu["id"] and sess["status"] in ("SCHEDULED", "IN_PROGRESS"):
                sess["status"] = "CANCELLED"
                touch(sess)
    touch(client)
    return ok_object(client)


# =============================================================================
# Chefs
# =============================================================================
@app.route("/chefs", methods=["POST"])
def create_chef():
    auth(["PlatformAdmin"])
    d = body()
    full_name = req_str(d, "full_name")
    email = req_str(d, "email")
    hourly_rate_cents = req_int(d, "hourly_rate_cents", minimum=0)
    c = new_entity("chefs", {
        "full_name": full_name,
        "email": email,
        "hourly_rate_cents": hourly_rate_cents,
        "no_show_strikes": 0,
        "status": "ACTIVE",
    })
    return ok_object(c, 201)


# =============================================================================
# Dietary plans
# =============================================================================
@app.route("/dietary-plans", methods=["POST"])
def create_plan():
    uid, role = auth(["Client"])
    d = body()
    client_id = d.get("client_id")
    # ownership (priority 3) — compare caller to the body FK
    client_owns(role, uid, client_id)
    # existence (priority 4)
    if not isinstance(client_id, str) or client_id.strip() == "":
        bad("client_id is required")
    client = get_client(client_id)
    # OCC (priority 5)
    expected = d.get("expected_client_version")
    if not is_int(expected):
        bad("expected_client_version is required")
    if expected != client["version"]:
        raise ApiError("ERR_STALE_CLIENT_VERSION", "Client version is stale")
    # body validation (priority 6)
    restriction_tags = validate_tag_array(d, "restriction_tags", RESTRICTIONS, required=True)
    allergen_tags = validate_tag_array(d, "allergen_tags", ALLERGENS, required=True)
    daily_calorie_target = req_int(d, "daily_calorie_target", minimum=1)

    # supersede prior ACTIVE plan
    for p in DB["plans"].values():
        if p["client_id"] == client_id and p["status"] == "ACTIVE":
            p["status"] = "SUPERSEDED"
            touch(p)

    plan = new_entity("plans", {
        "client_id": client_id,
        "restriction_tags": restriction_tags,
        "allergen_tags": allergen_tags,
        "daily_calorie_target": daily_calorie_target,
        "status": "ACTIVE",
    })
    touch(client)  # advance client.version
    return ok_object(plan, 201)


@app.route("/dietary-plans/<pid>", methods=["GET"])
def fetch_plan(pid):
    auth(["PlatformAdmin", "Client", "Chef"])
    return ok_object(get_plan(pid))


@app.route("/dietary-plans", methods=["GET"])
def list_plans():
    auth(["PlatformAdmin", "Client", "Chef"])
    client_id = request.args.get("client_id")
    items = [p for p in DB["plans"].values() if client_id is None or p["client_id"] == client_id]
    items.sort(key=lambda e: e["_seq"])
    page, pag = paginate(items)
    return ok_list(page, pag)


# =============================================================================
# Weekly menus
# =============================================================================
@app.route("/weekly-menus", methods=["POST"])
def create_menu():
    uid, role = auth(["Chef"])
    d = body()
    chef_id = d.get("chef_id")
    # ownership (chef authors/owns the menu)
    chef_owns(role, uid, chef_id)
    # existence left-to-right: client_id, dietary_plan_id, chef_id
    client_id = d.get("client_id")
    if not isinstance(client_id, str) or client_id.strip() == "":
        bad("client_id is required")
    get_client(client_id)
    dietary_plan_id = d.get("dietary_plan_id")
    if not isinstance(dietary_plan_id, str) or dietary_plan_id.strip() == "":
        bad("dietary_plan_id is required")
    get_plan(dietary_plan_id)
    if not isinstance(chef_id, str) or chef_id.strip() == "":
        bad("chef_id is required")
    get_chef(chef_id)
    # body validation
    wsd = d.get("week_start_date")
    try:
        week_dt = parse_iso(wsd)
    except Exception:
        bad("week_start_date must be a valid ISO8601 instant")

    menu = new_entity("menus", {
        "client_id": client_id,
        "dietary_plan_id": dietary_plan_id,
        "chef_id": chef_id,
        "week_start_date": wsd,
        "grocery_cost_cents": 0,
        "pinned_plan_version": None,
        "billing_mode_snapshot": None,
        "markup_pct_snapshot": None,
        "billed_amount_cents": None,
        "status": "DRAFT",
        "_week_dt": week_dt,
    })
    return ok_object(menu, 201)


@app.route("/weekly-menus/<mid>", methods=["GET"])
def fetch_menu(mid):
    auth(["PlatformAdmin", "Client", "Chef"])
    return ok_object(get_menu(mid))


@app.route("/weekly-menus", methods=["GET"])
def list_menus():
    auth(["PlatformAdmin", "Client", "Chef"])
    client_id = request.args.get("client_id")
    dietary_plan_id = request.args.get("dietary_plan_id")
    chef_id = request.args.get("chef_id")
    items = []
    for m in DB["menus"].values():
        if client_id is not None and m["client_id"] != client_id:
            continue
        if dietary_plan_id is not None and m["dietary_plan_id"] != dietary_plan_id:
            continue
        if chef_id is not None and m["chef_id"] != chef_id:
            continue
        items.append(m)
    items.sort(key=lambda e: e["_seq"])
    page, pag = paginate(items)
    return ok_list(page, pag)


@app.route("/weekly-menus/<mid>/propose", methods=["POST"])
def propose_menu(mid):
    uid, role = auth(["Chef"])
    menu = get_menu(mid)
    chef_owns(role, uid, menu["chef_id"])
    if menu["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_MENU_STATE", "Menu is not DRAFT")
    has_meal = any(
        meal["weekly_menu_id"] == mid and meal["status"] != "CANCELLED"
        for meal in DB["meals"].values()
    )
    if not has_meal:
        raise ApiError("ERR_MENU_HAS_NO_MEALS", "Menu has no meals")
    menu["status"] = "PROPOSED"
    touch(menu)
    return ok_object(menu)


@app.route("/weekly-menus/<mid>/reject", methods=["POST"])
def reject_menu(mid):
    uid, role = auth(["Client"])
    menu = get_menu(mid)
    client_owns(role, uid, menu["client_id"])
    if menu["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_MENU_STATE", "Menu is not PROPOSED")
    menu["status"] = "DRAFT"
    touch(menu)
    return ok_object(menu)


@app.route("/weekly-menus/<mid>/approve", methods=["POST"])
def approve_menu(mid):
    uid, role = auth(["Client"])
    menu = get_menu(mid)
    client_owns(role, uid, menu["client_id"])
    if menu["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_MENU_STATE", "Menu is not PROPOSED")

    client = get_client(menu["client_id"])
    plan = get_plan(menu["dietary_plan_id"])

    # gate 1: dietary plan ACTIVE
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_DIETARY_PLAN_NOT_ACTIVE", "Referenced dietary plan is not ACTIVE")

    meals = [m for m in DB["meals"].values()
             if m["weekly_menu_id"] == mid and m["status"] != "CANCELLED"]

    # gate 2: allergen conflict
    plan_allergens = set(plan["allergen_tags"])
    for meal in meals:
        if active_allergens_conflict(meal, plan_allergens):
            raise ApiError("ERR_ALLERGEN_CONFLICT", "An active ingredient carries a forbidden allergen")

    # gate 3: equipment subset
    available = set(client["available_equipment"])
    for meal in meals:
        if not set(meal["required_equipment"]).issubset(available):
            raise ApiError("ERR_EQUIPMENT_UNAVAILABLE", "Required equipment not available in kitchen")

    # gate 4: grocery budget
    grocery = compute_menu_grocery(menu)
    if grocery > client["weekly_grocery_budget_cents"]:
        raise ApiError("ERR_GROCERY_BUDGET_EXCEEDED", "Grocery cost exceeds weekly budget")

    # freeze snapshot
    menu["grocery_cost_cents"] = grocery
    menu["pinned_plan_version"] = plan["version"]
    menu["billing_mode_snapshot"] = client["billing_mode"]
    if client["billing_mode"] == "PER_WEEK":
        menu["markup_pct_snapshot"] = markup_tier(grocery)
    else:
        menu["markup_pct_snapshot"] = None
    menu["status"] = "APPROVED"
    touch(menu)
    return ok_object(menu)


@app.route("/weekly-menus/<mid>/skip", methods=["POST"])
def skip_menu(mid):
    uid, role = auth(["Client"])
    menu = get_menu(mid)
    client_owns(role, uid, menu["client_id"])
    if menu["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_MENU_STATE", "Menu is not APPROVED")
    if not (clock_now() < menu["_week_dt"]):
        raise ApiError("ERR_WEEK_ALREADY_STARTED", "Service week has already started")
    client = get_client(menu["client_id"])
    menu["status"] = "SKIPPED"
    touch(menu)
    add_wallet(client, client["weekly_base_fee_cents"])
    touch(client)
    return ok_object(menu)


@app.route("/weekly-menus/<mid>/resume", methods=["POST"])
def resume_menu(mid):
    uid, role = auth(["Client"])
    menu = get_menu(mid)
    client_owns(role, uid, menu["client_id"])
    if menu["status"] != "SKIPPED":
        raise ApiError("ERR_INVALID_MENU_STATE", "Menu is not SKIPPED")
    if not (clock_now() < menu["_week_dt"]):
        raise ApiError("ERR_WEEK_ALREADY_STARTED", "Service week has already started")
    client = get_client(menu["client_id"])
    menu["status"] = "APPROVED"
    touch(menu)
    add_wallet(client, -client["weekly_base_fee_cents"])
    touch(client)
    return ok_object(menu)


# =============================================================================
# Menu meals
# =============================================================================
@app.route("/menu-meals", methods=["POST"])
def create_meal():
    uid, role = auth(["Chef"])
    d = body()
    weekly_menu_id = d.get("weekly_menu_id")
    if not isinstance(weekly_menu_id, str) or weekly_menu_id.strip() == "":
        bad("weekly_menu_id is required")
    menu = get_menu(weekly_menu_id)
    chef_owns(role, uid, menu["chef_id"])

    meal_name = req_str(d, "meal_name")
    meal_slot = req_enum(d, "meal_slot", MEAL_SLOTS)
    servings = req_int(d, "servings", minimum=1)
    is_perishable = d.get("is_perishable", True)
    if not isinstance(is_perishable, bool):
        bad("is_perishable must be a boolean")
    required_equipment = validate_tag_array(d, "required_equipment", EQUIPMENT, required=False)

    raw_ings = d.get("ingredients")
    if not isinstance(raw_ings, list) or len(raw_ings) == 0:
        bad("ingredients must be a non-empty array")
    ingredients = []
    for ing in raw_ings:
        if not isinstance(ing, dict):
            bad("each ingredient must be an object")
        name = req_str(ing, "name")
        quantity = req_number(ing, "quantity", minimum=0)
        unit = req_str(ing, "unit")
        unit_cost_cents = req_int(ing, "unit_cost_cents", minimum=0)
        atags = validate_tag_array(ing, "allergen_tags", ALLERGENS, required=False)
        ingredients.append({
            "name": name,
            "quantity": quantity,
            "unit": unit,
            "unit_cost_cents": unit_cost_cents,
            "allergen_tags": atags,
            "status": "INCLUDED",
        })

    meal = new_entity("meals", {
        "weekly_menu_id": weekly_menu_id,
        "meal_name": meal_name,
        "meal_slot": meal_slot,
        "servings": servings,
        "is_perishable": is_perishable,
        "required_equipment": required_equipment,
        "ingredients": ingredients,
        "meal_grocery_cost_cents": 0,
        "client_rating": None,
        "status": "PLANNED",
    })
    recompute_meal_cost(meal)
    # recompute parent menu grocery (mutation of menu)
    menu["grocery_cost_cents"] = compute_menu_grocery(menu)
    touch(menu)
    return ok_object(meal, 201)


@app.route("/menu-meals/<mid>", methods=["GET"])
def fetch_meal(mid):
    auth(["PlatformAdmin", "Client", "Chef"])
    return ok_object(get_meal(mid))


@app.route("/menu-meals", methods=["GET"])
def list_meals():
    auth(["PlatformAdmin", "Client", "Chef"])
    weekly_menu_id = request.args.get("weekly_menu_id")
    items = [m for m in DB["meals"].values()
             if weekly_menu_id is None or m["weekly_menu_id"] == weekly_menu_id]
    items.sort(key=lambda e: e["_seq"])
    page, pag = paginate(items)
    return ok_list(page, pag)


@app.route("/menu-meals/<mid>/substitute", methods=["POST"])
def substitute_meal(mid):
    uid, role = auth(["Chef"])
    meal = get_meal(mid)
    menu = get_menu(meal["weekly_menu_id"])
    chef_owns(role, uid, menu["chef_id"])

    d = body()
    target = req_str(d, "target_ingredient_name")
    replacement_name = req_str(d, "replacement_name")
    replacement_quantity = req_number(d, "replacement_quantity", minimum=0)
    replacement_unit = req_str(d, "replacement_unit")
    replacement_unit_cost_cents = req_int(d, "replacement_unit_cost_cents", minimum=0)
    replacement_allergen_tags = validate_tag_array(d, "replacement_allergen_tags", ALLERGENS, required=False)

    # mark matching active ingredient SUBSTITUTED_OUT
    for ing in meal["ingredients"]:
        if ing["name"] == target and ing["status"] in ("INCLUDED", "ADDED"):
            ing["status"] = "SUBSTITUTED_OUT"
            break
    meal["ingredients"].append({
        "name": replacement_name,
        "quantity": replacement_quantity,
        "unit": replacement_unit,
        "unit_cost_cents": replacement_unit_cost_cents,
        "allergen_tags": replacement_allergen_tags,
        "status": "ADDED",
    })

    # allergen safety against the menu's dietary plan
    plan = get_plan(menu["dietary_plan_id"])
    if active_allergens_conflict(meal, set(plan["allergen_tags"])):
        raise ApiError("ERR_ALLERGEN_CONFLICT", "Substitution introduces a forbidden allergen")

    recompute_meal_cost(meal)
    touch(meal)
    menu["grocery_cost_cents"] = compute_menu_grocery(menu)
    touch(menu)
    return ok_object(meal)


@app.route("/menu-meals/<mid>/feedback", methods=["POST"])
def feedback_meal(mid):
    uid, role = auth(["Client"])
    meal = get_meal(mid)
    menu = get_menu(meal["weekly_menu_id"])
    client_owns(role, uid, menu["client_id"])

    d = body()
    rating = d.get("rating")
    if not is_int(rating):
        bad("rating is required")
    if rating < 1 or rating > 5:
        raise ApiError("ERR_INVALID_RATING", "rating must be within 1..5")
    if meal["status"] != "COOKED":
        raise ApiError("ERR_MEAL_NOT_COOKED", "Meal has not been cooked")
    meal["client_rating"] = rating
    touch(meal)
    return ok_object(meal)


# =============================================================================
# Cook sessions
# =============================================================================
def _intervals_overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


@app.route("/cook-sessions", methods=["POST"])
def create_session():
    uid, role = auth(["Chef"])
    d = body()
    chef_id = d.get("chef_id")
    chef_owns(role, uid, chef_id)

    weekly_menu_id = d.get("weekly_menu_id")
    if not isinstance(weekly_menu_id, str) or weekly_menu_id.strip() == "":
        bad("weekly_menu_id is required")
    menu = get_menu(weekly_menu_id)
    if not isinstance(chef_id, str) or chef_id.strip() == "":
        bad("chef_id is required")
    chef = get_chef(chef_id)

    ss = d.get("scheduled_start")
    se = d.get("scheduled_end")
    try:
        ss_dt = parse_iso(ss)
    except Exception:
        bad("scheduled_start must be a valid ISO8601 instant")
    try:
        se_dt = parse_iso(se)
    except Exception:
        bad("scheduled_end must be a valid ISO8601 instant")
    if not (se_dt > ss_dt):
        bad("scheduled_end must be strictly after scheduled_start")

    # chef active
    if chef["status"] != "ACTIVE":
        raise ApiError("ERR_CHEF_SUSPENDED", "Chef is suspended")

    # chef separation (>= 60 min buffer)
    for other in DB["sessions"].values():
        if other["chef_id"] != chef_id or other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        os_, oe = other["_ss_dt"], other["_se_dt"]
        if _intervals_overlap(ss_dt, se_dt, os_, oe):
            raise ApiError("ERR_CHEF_SCHEDULE_CONFLICT", "Chef schedule conflict")
        gap = (os_ - se_dt) if os_ >= se_dt else (ss_dt - oe)
        if gap < CHEF_BUFFER:
            raise ApiError("ERR_CHEF_SCHEDULE_CONFLICT", "Chef schedule conflict")

    # kitchen occupancy (overlap only, no buffer) — same client's kitchen
    for other in DB["sessions"].values():
        if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        other_menu = DB["menus"].get(other["weekly_menu_id"])
        if other_menu is None or other_menu["client_id"] != menu["client_id"]:
            continue
        if _intervals_overlap(ss_dt, se_dt, other["_ss_dt"], other["_se_dt"]):
            raise ApiError("ERR_CLIENT_KITCHEN_DOUBLE_BOOKED", "Client kitchen double-booked")

    # kitchen hours
    client = get_client(menu["client_id"])
    if ss_dt.hour < client["kitchen_open_hour"] or se_dt.hour > client["kitchen_close_hour"]:
        raise ApiError("ERR_OUTSIDE_KITCHEN_HOURS", "Session outside kitchen hours")

    provisional = payout(ss_dt, se_dt, chef["hourly_rate_cents"])
    sess = new_entity("sessions", {
        "weekly_menu_id": weekly_menu_id,
        "chef_id": chef_id,
        "scheduled_start": ss,
        "scheduled_end": se,
        "actual_start": None,
        "actual_end": None,
        "provisional_payout_cents": provisional,
        "final_payout_cents": None,
        "status": "SCHEDULED",
        "_ss_dt": ss_dt,
        "_se_dt": se_dt,
    })
    return ok_object(sess, 201)


@app.route("/cook-sessions/<sid>", methods=["GET"])
def fetch_session(sid):
    auth(["PlatformAdmin", "Client", "Chef"])
    return ok_object(get_session(sid))


@app.route("/cook-sessions", methods=["GET"])
def list_sessions():
    auth(["PlatformAdmin", "Client", "Chef"])
    weekly_menu_id = request.args.get("weekly_menu_id")
    chef_id = request.args.get("chef_id")
    items = []
    for s in DB["sessions"].values():
        if weekly_menu_id is not None and s["weekly_menu_id"] != weekly_menu_id:
            continue
        if chef_id is not None and s["chef_id"] != chef_id:
            continue
        items.append(s)
    items.sort(key=lambda e: e["_seq"])
    page, pag = paginate(items)
    return ok_list(page, pag)


@app.route("/cook-sessions/<sid>/start", methods=["POST"])
def start_session(sid):
    uid, role = auth(["Chef"])
    sess = get_session(sid)
    chef_owns(role, uid, sess["chef_id"])
    if sess["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_SESSION_STATE", "Session is not SCHEDULED")
    menu = get_menu(sess["weekly_menu_id"])
    if menu["status"] != "APPROVED":
        raise ApiError("ERR_MENU_NOT_APPROVED", "Parent menu is not APPROVED")
    chef = get_chef(sess["chef_id"])
    if chef["status"] != "ACTIVE":
        raise ApiError("ERR_CHEF_SUSPENDED", "Chef is suspended")
    sess["actual_start"] = iso_ms(clock_now())
    sess["_as_dt"] = clock_now()
    sess["status"] = "IN_PROGRESS"
    touch(sess)
    return ok_object(sess)


@app.route("/cook-sessions/<sid>/complete", methods=["POST"])
def complete_session(sid):
    uid, role = auth(["Chef"])
    sess = get_session(sid)
    chef_owns(role, uid, sess["chef_id"])
    if sess["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_SESSION_STATE", "Session is not IN_PROGRESS")

    chef = get_chef(sess["chef_id"])
    now = clock_now()
    sess["actual_end"] = iso_ms(now)
    sess["final_payout_cents"] = payout(sess["_as_dt"], now, chef["hourly_rate_cents"])
    sess["status"] = "COMPLETED"
    touch(sess)

    # ---- production cascade ----
    menu = get_menu(sess["weekly_menu_id"])
    client = get_client(menu["client_id"])
    menu["status"] = "COOKED"

    cooked_meals = []
    for meal in DB["meals"].values():
        if meal["weekly_menu_id"] == menu["id"] and meal["status"] == "PLANNED":
            meal["status"] = "COOKED"
            touch(meal)
            cooked_meals.append(meal)
            # synthesize container
            shelf_days = 3 if meal["is_perishable"] else 5
            prep = now
            use_by = prep + timedelta(days=shelf_days)
            prep_iso = iso_ms(prep)
            use_by_iso = iso_ms(use_by)
            new_entity("containers", {
                "menu_meal_id": meal["id"],
                "label_prep_date": prep_iso,
                "label_use_by_date": use_by_iso,
                "portion_count": meal["servings"],
                "label_text": "%s — prep %s — use by %s" % (meal["meal_name"], prep_iso, use_by_iso),
                "status": "FILLED",
            })

    # ---- invoice issuance ----
    mode = menu["billing_mode_snapshot"]
    if mode == "PER_WEEK":
        grocery = menu["grocery_cost_cents"]
        pct = menu["markup_pct_snapshot"]
        if pct is None:
            pct = markup_tier(grocery)
        grocery_markup = round_half_up(Decimal(grocery) * Decimal(pct) / Decimal(100))
        household_surch = max(0, client["household_size"] - SURCHARGE_FREE_HEADS) * PER_HEAD_SURCHARGE_CENTS
        gross = client["weekly_base_fee_cents"] + grocery_markup + household_surch
    else:  # PER_MEAL
        gross = 0
        cooked = [m for m in DB["meals"].values()
                  if m["weekly_menu_id"] == menu["id"] and m["status"] == "COOKED"]
        for meal in cooked:
            meal_charge = round_half_up(
                Decimal(meal["meal_grocery_cost_cents"]) * Decimal(100 + PER_MEAL_MARKUP_PCT) / Decimal(100)
            ) + client["per_meal_fee_cents"]
            gross += meal_charge

    invoice = new_entity("invoices", {
        "client_id": menu["client_id"],
        "weekly_menu_id": menu["id"],
        "billing_mode": mode,
        "gross_amount_cents": gross,
        "credit_applied_cents": 0,
        "net_amount_cents": None,
        "status": "ISSUED",
    })
    menu["billed_amount_cents"] = gross
    touch(menu)
    return ok_object(sess)


@app.route("/cook-sessions/<sid>/no-show", methods=["POST"])
def no_show_session(sid):
    uid, role = auth(["Client", "PlatformAdmin"])
    sess = get_session(sid)
    menu = get_menu(sess["weekly_menu_id"])
    if role == "Client":
        client_owns(role, uid, menu["client_id"])
    if sess["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_SESSION_STATE", "Session is not SCHEDULED")

    client = get_client(menu["client_id"])
    chef = get_chef(sess["chef_id"])
    sess["status"] = "NO_SHOW"
    touch(sess)
    add_wallet(client, client["weekly_base_fee_cents"])
    touch(client)
    chef["no_show_strikes"] += 1
    if chef["no_show_strikes"] >= STRIKE_LIMIT and chef["status"] == "ACTIVE":
        chef["status"] = "SUSPENDED"
    touch(chef)
    return ok_object(sess)


# =============================================================================
# Containers
# =============================================================================
@app.route("/containers/<cid>", methods=["GET"])
def fetch_container(cid):
    auth(["PlatformAdmin", "Client", "Chef"])
    return ok_object(get_container(cid))


@app.route("/containers", methods=["GET"])
def list_containers():
    auth(["PlatformAdmin", "Client", "Chef"])
    menu_meal_id = request.args.get("menu_meal_id")
    items = [c for c in DB["containers"].values()
             if menu_meal_id is None or c["menu_meal_id"] == menu_meal_id]
    items.sort(key=lambda e: e["_seq"])
    page, pag = paginate(items)
    return ok_list(page, pag)


# =============================================================================
# Billing invoices
# =============================================================================
@app.route("/billing-invoices/<iid>", methods=["GET"])
def fetch_invoice(iid):
    auth(["PlatformAdmin", "Client", "Chef"])
    return ok_object(get_invoice(iid))


@app.route("/billing-invoices", methods=["GET"])
def list_invoices():
    auth(["PlatformAdmin", "Client", "Chef"])
    client_id = request.args.get("client_id")
    weekly_menu_id = request.args.get("weekly_menu_id")
    items = []
    for inv in DB["invoices"].values():
        if client_id is not None and inv["client_id"] != client_id:
            continue
        if weekly_menu_id is not None and inv["weekly_menu_id"] != weekly_menu_id:
            continue
        items.append(inv)
    items.sort(key=lambda e: e["_seq"])
    page, pag = paginate(items)
    return ok_list(page, pag)


@app.route("/billing-invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    uid, role = auth(["Client"])
    invoice = get_invoice(iid)
    client_owns(role, uid, invoice["client_id"])
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_INVOICE_STATE", "Invoice is not ISSUED")
    client = get_client(invoice["client_id"])
    credit_applied = min(client["wallet_credit_cents"], invoice["gross_amount_cents"])
    invoice["credit_applied_cents"] = credit_applied
    invoice["net_amount_cents"] = invoice["gross_amount_cents"] - credit_applied
    invoice["status"] = "PAID"
    touch(invoice)
    add_wallet(client, -credit_applied)
    touch(client)
    return ok_object(invoice)


# =============================================================================
# Pagination
# =============================================================================
def paginate(items):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
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
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, pag


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
