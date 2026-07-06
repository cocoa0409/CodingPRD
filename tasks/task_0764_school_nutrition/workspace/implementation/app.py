"""School Nutrition & Cafeteria Operations API.

In-memory Flask implementation. Storage is process-local dicts keyed by id;
every boot starts empty (no seeding). See workspace/PRD.md for the contract.
"""
import json
import os
import re
import string
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import Flask, request, Response

app = Flask(__name__)

# --------------------------------------------------------------------------- #
# In-memory stores (start empty on every boot — never seeded)
# --------------------------------------------------------------------------- #
sites = {}
food_items = {}
rates = {}
menu_cycles = {}
inventory_lots = {}
production_records = {}
students = {}
meal_transactions = {}
claims = {}

_seq = 0
LOCK = threading.RLock()

# Logical service clock: startup default per PRD §2.10, never wall-clock.
CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = {"PlatformAdmin", "MenuPlanner", "NutritionDirector",
         "CafeteriaManager", "POSClerk"}

COMPONENTS = {"MEAT_MEAT_ALT", "GRAINS", "FRUIT", "VEGETABLE", "MILK"}
GRADES = {"GRADES_K_5", "GRADES_6_8", "GRADES_9_12"}
MEAL_TYPES = {"BREAKFAST", "LUNCH"}
FOOD_CATEGORIES = {"ENTREE", "GRAIN", "FRUIT", "VEGETABLE", "MILK", "SNACK", "BEVERAGE"}
UNITS = {"EACH", "OZ", "CASE"}
LOT_TYPES = {"COMMODITY_USDA_FOODS", "PURCHASED"}
PROGRAMS = {"NSLP", "SBP"}
CLAIM_CATEGORIES = {"FREE", "REDUCED", "PAID"}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


# --------------------------------------------------------------------------- #
# Errors & response envelope
# --------------------------------------------------------------------------- #
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _json_default(o):
    if isinstance(o, Decimal):
        i = int(o)
        return i if o == i else float(o)
    raise TypeError(f"not serializable: {type(o)}")


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _request_id():
    alphabet = string.ascii_letters + string.digits
    body = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + "".join(c for c in body if c in alphabet)[:20]


def _meta(pagination=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if pagination is not None:
        m.update(pagination)
    return m


def respond(data, status=200, response_type="object", pagination=None):
    payload = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return Response(json.dumps(payload, default=_json_default),
                    status=status, mimetype="application/json")


def error_response(error_id, http_status, message):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return Response(json.dumps(payload, default=_json_default),
                    status=http_status, mimetype="application/json")


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


# --------------------------------------------------------------------------- #
# Decimal / rounding helpers
# --------------------------------------------------------------------------- #
def D(x):
    return Decimal(str(x))


def rhu(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Record lifecycle helpers
# --------------------------------------------------------------------------- #
def stamp(rec):
    global _seq
    _seq += 1
    ts = now_iso()
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = _seq
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] = rec["version"] + 1


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# --------------------------------------------------------------------------- #
# Auth & body helpers
# --------------------------------------------------------------------------- #
def authn(allowed_roles):
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized role")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation")


def user_id():
    return request.headers.get("X-User-ID")


def endpoint(*allowed_roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with LOCK:
                authn(set(allowed_roles))
                return fn(*args, **kwargs)
        return wrapper
    return deco


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return body


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_str(x):
    return isinstance(x, str)


def vreq(cond, msg="Invalid request body"):
    if not cond:
        raise ApiError("ERR_VALIDATION", 400, msg)


def req_str(body, field):
    v = body.get(field)
    vreq(is_str(v) and v != "", f"{field} is required")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    vreq(is_str(v) and v in allowed, f"{field} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    vreq(is_str(v) and v in allowed, f"{field} must be one of {sorted(allowed)}")
    return v


def req_int(body, field):
    v = body.get(field)
    vreq(is_int(v), f"{field} must be an integer")
    return v


def opt_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    vreq(is_int(v), f"{field} must be an integer")
    return v


def req_num(body, field):
    v = body.get(field)
    vreq(is_num(v), f"{field} must be a number")
    return v


def opt_num(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    vreq(is_num(v), f"{field} must be a number")
    return v


def opt_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    vreq(isinstance(v, bool), f"{field} must be a boolean")
    return v


def req_date(body, field):
    v = req_str(body, field)
    vreq(bool(DATE_RE.match(v)), f"{field} must be YYYY-MM-DD")
    return v


def check_fk(body, field, store):
    """Existence check (priority 3): if a body FK reference is present and a
    string, it must resolve, else ERR_NOT_FOUND."""
    v = body.get(field)
    if v is not None and isinstance(v, str):
        if v not in store:
            raise ApiError("ERR_NOT_FOUND", 404, f"{field} does not resolve")


def fetch(store, rid, label="resource"):
    rec = store.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found")
    return rec


def parse_pagination():
    args = request.args
    lim_raw = args.get("limit")
    off_raw = args.get("offset")
    if lim_raw is None:
        limit = 10
    else:
        try:
            limit = int(lim_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
    vreq(1 <= limit <= 100, "limit must be within 1..100")
    if off_raw is None:
        offset = 0
    else:
        try:
            offset = int(off_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
    vreq(offset >= 0, "offset must be >= 0")
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [serialize(r) for r in page], pagination


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #
def clock_date_str():
    return CLOCK.strftime("%Y-%m-%d")


def parse_iso(s):
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# Calculations
# --------------------------------------------------------------------------- #
def compute_compliance(meal_type, components):
    total_meat = Decimal(0)
    total_grain = Decimal(0)
    total_fv = Decimal(0)
    milk_present = False
    grains_wgr = True
    for comp in components:
        fi = food_items[comp["food_item_id"]]
        ps = D(comp["planned_servings"])
        total_meat += ps * D(fi["meat_alt_oz_eq"])
        total_grain += ps * D(fi["grain_oz_eq"])
        total_fv += ps * (D(fi["fruit_cup"]) + D(fi["veg_cup"]))
        if comp["component"] == "MILK" and fi["category"] == "MILK":
            milk_present = True
        if comp["component"] == "GRAINS" and not fi["is_whole_grain_rich"]:
            grains_wgr = False
    total_meat = rhu(total_meat, 2)
    total_grain = rhu(total_grain, 2)
    total_fv = rhu(total_fv, 2)
    if meal_type == "LUNCH":
        ok = (total_meat >= D("1.0") and total_grain >= D("1.0")
              and total_fv >= D("0.75") and milk_present and grains_wgr)
    else:  # BREAKFAST
        ok = (total_grain >= D("1.0") and total_fv >= D("0.5")
              and milk_present and grains_wgr)
    return "COMPLIANT" if ok else "NONCOMPLIANT"


def smart_snack_ok(fi):
    cal = D(fi["calories"])
    if cal > D("200"):
        return False
    if D(fi["sodium_mg"]) > D("200"):
        return False
    # total fat at most 35% of calories (9 cal/g)
    if D(fi["total_fat_g"]) * D("9") > cal * D("0.35"):
        return False
    # saturated fat strictly less than 10% of calories (9 cal/g)
    if not (D(fi["sat_fat_g"]) * D("9") < cal * D("0.10")):
        return False
    # total sugar at most 35% of weight by weight
    if D(fi["total_sugar_g"]) > D(fi["weight_g"]) * D("0.35"):
        return False
    return True


def compute_account_status(student):
    bal = student["balance_cents"]
    thr = student["low_balance_threshold_cents"]
    if bal < 0:
        return "NEGATIVE"
    if bal <= thr:
        return "LOW_BALANCE"
    return "ACTIVE"


def apply_balance_change(student, delta):
    site = sites[student["site_id"]]
    old_status = student["account_status"]
    student["balance_cents"] = student["balance_cents"] + delta
    new_status = compute_account_status(student)
    student["account_status"] = new_status
    touch(student)
    if old_status != "NEGATIVE" and new_status == "NEGATIVE":
        site["negative_balance_count"] += 1
        touch(site)
    elif old_status == "NEGATIVE" and new_status != "NEGATIVE":
        site["negative_balance_count"] -= 1
        touch(site)


def recompute_leftover(pr):
    if pr["status"] == "PLANNED" or pr["prepared_qty"] is None:
        pr["leftover_qty"] = 0
    else:
        lv = D(pr["prepared_qty"]) - D(pr["served_qty"])
        pr["leftover_qty"] = lv if lv > 0 else 0


def month_reimbursable_meals(site_id, month):
    return [m for m in meal_transactions.values()
            if m["site_id"] == site_id
            and m["service_date"][:7] == month
            and m["meal_claim_status"] == "REIMBURSABLE"]


def recompute_claim_counts(claim):
    f = r = p = 0
    for m in month_reimbursable_meals(claim["site_id"], claim["claim_month"]):
        c = m["claim_category"]
        if c == "FREE":
            f += 1
        elif c == "REDUCED":
            r += 1
        else:
            p += 1
    claim["free_count"] = f
    claim["reduced_count"] = r
    claim["paid_count"] = p


def bump_draft_claim(site_id, month):
    for claim in claims.values():
        if (claim["site_id"] == site_id and claim["claim_month"] == month
                and claim["status"] == "DRAFT"):
            recompute_claim_counts(claim)
            touch(claim)


def applicable_rate(program, category, site, first_day):
    candidates = [r for r in rates.values()
                  if r["program"] == program and r["category"] == category
                  and r["effective_date"] <= first_day]
    if program == "SBP":
        candidates = [r for r in candidates
                      if r["severe_need"] == site["severe_need_breakfast"]]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["effective_date"], r["created_at"], r["_seq"]))
    return candidates[-1]


def compute_reimbursement(site, month):
    first_day = month + "-01"
    total = 0
    for m in month_reimbursable_meals(site["id"], month):
        program = "NSLP" if m["meal_type"] == "LUNCH" else "SBP"
        rate_row = applicable_rate(program, m["claim_category"], site, first_day)
        if rate_row is None:
            raise ApiError("ERR_RATE_NOT_FOUND", 409,
                           f"No applicable rate for {program}/{m['claim_category']}")
        addon = rate_row["performance_addon_cents"] if site["performance_based_certified"] else 0
        total += rate_row["rate_cents"] + addon
    return total


def deplete_for_prepare(pr, cycle, prepared_qty):
    """Commodity-first FIFO waterfall. Simulate across all components; raise on
    shortfall without mutating; then commit and return the list of per-lot draws."""
    working = {}
    draws = []
    for comp in cycle["components"]:
        fid = comp["food_item_id"]
        required = rhu(prepared_qty * D(comp["serving_amount"]), 3)
        lots = [l for l in inventory_lots.values()
                if l["site_id"] == pr["site_id"] and l["food_item_id"] == fid]
        lots.sort(key=lambda l: (0 if l["lot_type"] == "COMMODITY_USDA_FOODS" else 1,
                                 l["received_date"], l["_seq"]))
        remaining = required
        for l in lots:
            if remaining <= 0:
                break
            avail = working.get(l["id"], D(l["quantity_on_hand"]))
            if avail <= 0:
                continue
            take = avail if avail < remaining else remaining
            working[l["id"]] = avail - take
            draws.append((l["id"], take))
            remaining = remaining - take
        if remaining > 0:
            raise ApiError("ERR_INSUFFICIENT_INVENTORY", 409,
                           "Insufficient on-hand inventory to prepare")
    # Commit
    for lot_id, amt in draws:
        lot = inventory_lots[lot_id]
        new_qoh = rhu(D(lot["quantity_on_hand"]) - amt, 3)
        if new_qoh <= 0:
            new_qoh = Decimal("0")
            lot["quantity_on_hand"] = new_qoh
            lot["status"] = "DEPLETED"
        else:
            lot["quantity_on_hand"] = new_qoh
        touch(lot)
    return draws


def restore_inventory(pr):
    for lot_id, amt in pr.get("_depletions", []):
        lot = inventory_lots[lot_id]
        new_qoh = rhu(D(lot["quantity_on_hand"]) + amt, 3)
        lot["quantity_on_hand"] = new_qoh
        lot["status"] = "AVAILABLE" if new_qoh > 0 else "DEPLETED"
        touch(lot)
    pr["_depletions"] = []


# --------------------------------------------------------------------------- #
# Clock endpoint
# --------------------------------------------------------------------------- #
@app.route("/_clock/set_current_utc", methods=["POST"])
@endpoint("PlatformAdmin")
def set_clock():
    global CLOCK
    body = get_body()
    iso = req_str(body, "to_iso8601")
    try:
        dt = parse_iso(iso)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 is not a valid ISO 8601 instant")
    CLOCK = dt
    return respond({}, 200, "object")


# --------------------------------------------------------------------------- #
# SchoolSite
# --------------------------------------------------------------------------- #
@app.route("/nutrition/sites", methods=["POST"])
@endpoint("PlatformAdmin")
def create_site():
    body = get_body()
    name = req_str(body, "name")
    site_code = req_str(body, "site_code")
    rec = {
        "name": name,
        "site_code": site_code,
        "nslp_participating": opt_bool(body, "nslp_participating", True),
        "sbp_participating": opt_bool(body, "sbp_participating", True),
        "severe_need_breakfast": opt_bool(body, "severe_need_breakfast", False),
        "performance_based_certified": opt_bool(body, "performance_based_certified", False),
        "negative_balance_allowed": opt_bool(body, "negative_balance_allowed", False),
        "sales_tax_bps": opt_int(body, "sales_tax_bps", 0),
        "paid_lunch_price_cents": opt_int(body, "paid_lunch_price_cents", 300),
        "paid_breakfast_price_cents": opt_int(body, "paid_breakfast_price_cents", 200),
        "reduced_lunch_copay_cents": opt_int(body, "reduced_lunch_copay_cents", 40),
        "reduced_breakfast_copay_cents": opt_int(body, "reduced_breakfast_copay_cents", 30),
        "negative_balance_count": 0,
    }
    for s in sites.values():
        if s["site_code"] == site_code:
            raise ApiError("ERR_VALIDATION", 400, "site_code must be unique across sites")
    stamp(rec)
    sites[rec["id"]] = rec
    return respond(serialize(rec), 201, "object")


@app.route("/nutrition/sites/<rid>", methods=["GET"])
@endpoint("PlatformAdmin", "MenuPlanner", "NutritionDirector", "CafeteriaManager", "POSClerk")
def get_site(rid):
    return respond(serialize(fetch(sites, rid, "site")), 200, "object")


# --------------------------------------------------------------------------- #
# FoodItem
# --------------------------------------------------------------------------- #
@app.route("/nutrition/food-items", methods=["POST"])
@endpoint("PlatformAdmin")
def create_food_item():
    body = get_body()
    rec = {
        "name": req_str(body, "name"),
        "category": req_enum(body, "category", FOOD_CATEGORIES),
        "is_commodity": opt_bool(body, "is_commodity", False),
        "calories": opt_int(body, "calories", 0),
        "sat_fat_g": opt_num(body, "sat_fat_g", 0),
        "total_fat_g": opt_num(body, "total_fat_g", 0),
        "sodium_mg": opt_int(body, "sodium_mg", 0),
        "total_sugar_g": opt_num(body, "total_sugar_g", 0),
        "weight_g": opt_num(body, "weight_g", 1),
        "meat_alt_oz_eq": opt_num(body, "meat_alt_oz_eq", 0),
        "grain_oz_eq": opt_num(body, "grain_oz_eq", 0),
        "fruit_cup": opt_num(body, "fruit_cup", 0),
        "veg_cup": opt_num(body, "veg_cup", 0),
        "is_whole_grain_rich": opt_bool(body, "is_whole_grain_rich", False),
        "unit": opt_enum(body, "unit", UNITS, "EACH"),
    }
    stamp(rec)
    food_items[rec["id"]] = rec
    return respond(serialize(rec), 201, "object")


@app.route("/nutrition/food-items/<rid>", methods=["GET"])
@endpoint("PlatformAdmin", "MenuPlanner", "NutritionDirector", "CafeteriaManager", "POSClerk")
def get_food_item(rid):
    return respond(serialize(fetch(food_items, rid, "food item")), 200, "object")


# --------------------------------------------------------------------------- #
# ReimbursementRate
# --------------------------------------------------------------------------- #
@app.route("/nutrition/reimbursement-rates", methods=["POST"])
@endpoint("PlatformAdmin")
def create_rate():
    body = get_body()
    rec = {
        "program": req_enum(body, "program", PROGRAMS),
        "category": req_enum(body, "category", CLAIM_CATEGORIES),
        "severe_need": opt_bool(body, "severe_need", False),
        "rate_cents": req_int(body, "rate_cents"),
        "performance_addon_cents": opt_int(body, "performance_addon_cents", 0),
        "effective_date": req_date(body, "effective_date"),
    }
    stamp(rec)
    rates[rec["id"]] = rec
    return respond(serialize(rec), 201, "object")


# --------------------------------------------------------------------------- #
# MenuCycle
# --------------------------------------------------------------------------- #
def _validate_components(components):
    vreq(isinstance(components, list), "components must be an array")
    out = []
    for comp in components:
        vreq(isinstance(comp, dict), "each component must be an object")
        fid = comp.get("food_item_id")
        vreq(is_str(fid), "component.food_item_id is required")
        component = comp.get("component")
        vreq(is_str(component) and component in COMPONENTS,
             "component must be one of " + str(sorted(COMPONENTS)))
        vreq(is_num(comp.get("planned_servings")), "planned_servings must be a number")
        vreq(is_num(comp.get("serving_amount")), "serving_amount must be a number")
        out.append({
            "food_item_id": fid,
            "component": component,
            "planned_servings": comp["planned_servings"],
            "serving_amount": comp["serving_amount"],
        })
    return out


@app.route("/nutrition/menu-cycles", methods=["POST"])
@endpoint("MenuPlanner")
def create_menu_cycle():
    body = get_body()
    # Existence (priority 3), left-to-right: site_id then component food items
    check_fk(body, "site_id", sites)
    components_raw = body.get("components")
    if isinstance(components_raw, list):
        for comp in components_raw:
            if isinstance(comp, dict):
                fid = comp.get("food_item_id")
                if isinstance(fid, str) and fid not in food_items:
                    raise ApiError("ERR_NOT_FOUND", 404, "component food_item_id does not resolve")
    # Body shape (priority 4)
    site_id = req_str(body, "site_id")
    meal_type = req_enum(body, "meal_type", MEAL_TYPES)
    grade_group = req_enum(body, "grade_group", GRADES)
    effective_date = req_date(body, "effective_date")
    end_date = req_date(body, "end_date")
    vreq("components" in body, "components is required")
    components = _validate_components(components_raw)
    rec = {
        "site_id": site_id,
        "meal_type": meal_type,
        "grade_group": grade_group,
        "effective_date": effective_date,
        "end_date": end_date,
        "components": components,
        "status": "DRAFT",
        "compliance_status": compute_compliance(meal_type, components),
        "submitted_by_user_id": None,
        "rejection_note": None,
    }
    stamp(rec)
    menu_cycles[rec["id"]] = rec
    return respond(serialize(rec), 201, "object")


@app.route("/nutrition/menu-cycles/<rid>", methods=["GET"])
@endpoint("PlatformAdmin", "MenuPlanner", "NutritionDirector", "CafeteriaManager", "POSClerk")
def get_menu_cycle(rid):
    return respond(serialize(fetch(menu_cycles, rid, "menu cycle")), 200, "object")


@app.route("/nutrition/menu-cycles", methods=["GET"])
@endpoint("PlatformAdmin", "MenuPlanner", "NutritionDirector", "CafeteriaManager", "POSClerk")
def list_menu_cycles():
    args = request.args
    items = list(menu_cycles.values())
    for field in ("site_id", "meal_type", "grade_group", "status"):
        if args.get(field) is not None:
            items = [r for r in items if r[field] == args.get(field)]
    data, pagination = paginate(items)
    return respond(data, 200, "array", pagination)


@app.route("/nutrition/menu-cycles/<rid>/submit", methods=["POST"])
@endpoint("MenuPlanner")
def submit_menu_cycle(rid):
    cycle = fetch(menu_cycles, rid, "menu cycle")
    if cycle["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Menu cycle is not DRAFT")
    # re-check compliance from current components
    cycle["compliance_status"] = compute_compliance(cycle["meal_type"], cycle["components"])
    if cycle["compliance_status"] != "COMPLIANT":
        raise ApiError("ERR_MEAL_PATTERN_VIOLATION", 422, "Menu cycle is NONCOMPLIANT")
    if cycle["effective_date"] < clock_date_str():
        raise ApiError("ERR_MENU_EFFECTIVE_DATE_PAST", 422, "effective_date is in the past")
    cycle["status"] = "UNDER_REVIEW"
    cycle["submitted_by_user_id"] = user_id()
    cycle["rejection_note"] = None
    touch(cycle)
    return respond(serialize(cycle), 200, "object")


@app.route("/nutrition/menu-cycles/<rid>/approve", methods=["POST"])
@endpoint("NutritionDirector")
def approve_menu_cycle(rid):
    cycle = fetch(menu_cycles, rid, "menu cycle")
    # segregation of duties (priority 6) before generic state (priority 7)
    if user_id() == cycle["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Approver must differ from submitter")
    if cycle["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Menu cycle is not UNDER_REVIEW")
    for other in menu_cycles.values():
        if other["id"] == cycle["id"]:
            continue
        if (other["status"] == "APPROVED"
                and other["site_id"] == cycle["site_id"]
                and other["meal_type"] == cycle["meal_type"]
                and other["grade_group"] == cycle["grade_group"]
                and cycle["effective_date"] < other["end_date"]
                and other["effective_date"] < cycle["end_date"]):
            raise ApiError("ERR_MENU_PERIOD_OVERLAP", 409, "Overlapping approved menu cycle")
    cycle["status"] = "APPROVED"
    touch(cycle)
    return respond(serialize(cycle), 200, "object")


@app.route("/nutrition/menu-cycles/<rid>/reject", methods=["POST"])
@endpoint("NutritionDirector")
def reject_menu_cycle(rid):
    cycle = fetch(menu_cycles, rid, "menu cycle")
    body = get_body()
    rejection_note = req_str(body, "rejection_note")
    if user_id() == cycle["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Reviewer must differ from submitter")
    if cycle["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Menu cycle is not UNDER_REVIEW")
    cycle["status"] = "DRAFT"
    cycle["rejection_note"] = rejection_note
    touch(cycle)
    return respond(serialize(cycle), 200, "object")


# --------------------------------------------------------------------------- #
# InventoryLot
# --------------------------------------------------------------------------- #
@app.route("/nutrition/inventory-lots", methods=["POST"])
@endpoint("CafeteriaManager")
def create_inventory_lot():
    body = get_body()
    check_fk(body, "site_id", sites)
    check_fk(body, "food_item_id", food_items)
    site_id = req_str(body, "site_id")
    food_item_id = req_str(body, "food_item_id")
    lot_type = req_enum(body, "lot_type", LOT_TYPES)
    quantity_received = req_num(body, "quantity_received")
    received_date = req_date(body, "received_date")
    unit_cost_cents = opt_int(body, "unit_cost_cents", 0)
    qoh = rhu(D(quantity_received), 3)
    rec = {
        "site_id": site_id,
        "food_item_id": food_item_id,
        "lot_type": lot_type,
        "quantity_received": D(quantity_received),
        "quantity_on_hand": qoh,
        "unit_cost_cents": unit_cost_cents,
        "received_date": received_date,
        "status": "DEPLETED" if qoh <= 0 else "AVAILABLE",
    }
    stamp(rec)
    inventory_lots[rec["id"]] = rec
    return respond(serialize(rec), 201, "object")


@app.route("/nutrition/inventory-lots/<rid>", methods=["GET"])
@endpoint("PlatformAdmin", "CafeteriaManager", "NutritionDirector")
def get_inventory_lot(rid):
    return respond(serialize(fetch(inventory_lots, rid, "inventory lot")), 200, "object")


@app.route("/nutrition/inventory-lots", methods=["GET"])
@endpoint("PlatformAdmin", "CafeteriaManager", "NutritionDirector")
def list_inventory_lots():
    args = request.args
    items = list(inventory_lots.values())
    for field in ("site_id", "food_item_id", "lot_type", "status"):
        if args.get(field) is not None:
            items = [r for r in items if r[field] == args.get(field)]
    data, pagination = paginate(items)
    return respond(data, 200, "array", pagination)


# --------------------------------------------------------------------------- #
# ProductionRecord
# --------------------------------------------------------------------------- #
@app.route("/nutrition/production-records", methods=["POST"])
@endpoint("CafeteriaManager")
def create_production_record():
    body = get_body()
    check_fk(body, "site_id", sites)
    check_fk(body, "menu_cycle_id", menu_cycles)
    site_id = req_str(body, "site_id")
    menu_cycle_id = req_str(body, "menu_cycle_id")
    service_date = req_date(body, "service_date")
    meal_type = req_enum(body, "meal_type", MEAL_TYPES)
    planned_qty = req_num(body, "planned_qty")
    cycle = menu_cycles[menu_cycle_id]
    if cycle["status"] != "APPROVED" or cycle["compliance_status"] != "COMPLIANT":
        raise ApiError("ERR_MENU_NOT_APPROVED", 409, "Menu cycle is not APPROVED and COMPLIANT")
    vreq(meal_type == cycle["meal_type"], "meal_type must equal the menu cycle's meal_type")
    vreq(cycle["effective_date"] <= service_date < cycle["end_date"],
         "service_date must fall within the menu cycle period")
    for other in production_records.values():
        if (other["status"] != "CANCELLED"
                and other["site_id"] == site_id
                and other["service_date"] == service_date
                and other["meal_type"] == meal_type):
            raise ApiError("ERR_PRODUCTION_ALREADY_EXISTS", 409,
                           "Production record already exists for this site/date/meal")
    forecast = int(rhu(D(planned_qty) * D("0.9"), 0))
    rec = {
        "site_id": site_id,
        "menu_cycle_id": menu_cycle_id,
        "service_date": service_date,
        "meal_type": meal_type,
        "planned_qty": D(planned_qty),
        "forecast_par_qty": forecast,
        "prepared_qty": None,
        "served_qty": 0,
        "leftover_qty": 0,
        "status": "PLANNED",
        "_depletions": [],
    }
    stamp(rec)
    production_records[rec["id"]] = rec
    return respond(serialize(rec), 201, "object")


@app.route("/nutrition/production-records/<rid>", methods=["GET"])
@endpoint("PlatformAdmin", "CafeteriaManager", "NutritionDirector", "POSClerk")
def get_production_record(rid):
    return respond(serialize(fetch(production_records, rid, "production record")), 200, "object")


@app.route("/nutrition/production-records", methods=["GET"])
@endpoint("PlatformAdmin", "CafeteriaManager", "NutritionDirector", "POSClerk")
def list_production_records():
    args = request.args
    items = list(production_records.values())
    for field in ("site_id", "menu_cycle_id", "service_date", "meal_type", "status"):
        if args.get(field) is not None:
            items = [r for r in items if r[field] == args.get(field)]
    data, pagination = paginate(items)
    return respond(data, 200, "array", pagination)


@app.route("/nutrition/production-records/<rid>/prepare", methods=["POST"])
@endpoint("CafeteriaManager")
def prepare_production_record(rid):
    pr = fetch(production_records, rid, "production record")
    body = get_body()
    prepared_qty = req_num(body, "prepared_qty")
    if pr["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Production record is not PLANNED")
    pq = D(prepared_qty)
    cycle = menu_cycles[pr["menu_cycle_id"]]
    draws = deplete_for_prepare(pr, cycle, pq)
    pr["prepared_qty"] = pq
    pr["status"] = "PREPARED"
    pr["_depletions"] = draws
    recompute_leftover(pr)
    touch(pr)
    return respond(serialize(pr), 200, "object")


@app.route("/nutrition/production-records/<rid>/cancel", methods=["POST"])
@endpoint("CafeteriaManager")
def cancel_production_record(rid):
    pr = fetch(production_records, rid, "production record")
    if pr["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Production record already CANCELLED")
    if pr["status"] == "PREPARED" and pr["served_qty"] > 0:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Cannot cancel a prepared record with served meals")
    if pr["status"] == "PREPARED":
        restore_inventory(pr)
    pr["status"] = "CANCELLED"
    recompute_leftover(pr)
    touch(pr)
    return respond(serialize(pr), 200, "object")


# --------------------------------------------------------------------------- #
# Student
# --------------------------------------------------------------------------- #
@app.route("/nutrition/students", methods=["POST"])
@endpoint("PlatformAdmin")
def create_student():
    body = get_body()
    check_fk(body, "site_id", sites)
    site_id = req_str(body, "site_id")
    rec = {
        "site_id": site_id,
        "first_name": req_str(body, "first_name"),
        "last_name": req_str(body, "last_name"),
        "grade": req_enum(body, "grade", GRADES),
        "eligibility_category": opt_enum(body, "eligibility_category", CLAIM_CATEGORIES, "PAID"),
        "balance_cents": 0,
        "low_balance_threshold_cents": opt_int(body, "low_balance_threshold_cents", 500),
        "account_status": "ACTIVE",
    }
    rec["account_status"] = compute_account_status(rec)
    stamp(rec)
    students[rec["id"]] = rec
    return respond(serialize(rec), 201, "object")


@app.route("/nutrition/students/<rid>", methods=["GET"])
@endpoint("PlatformAdmin", "POSClerk", "NutritionDirector")
def get_student(rid):
    return respond(serialize(fetch(students, rid, "student")), 200, "object")


@app.route("/nutrition/students", methods=["GET"])
@endpoint("PlatformAdmin", "POSClerk", "NutritionDirector")
def list_students():
    args = request.args
    items = list(students.values())
    for field in ("site_id", "eligibility_category", "account_status"):
        if args.get(field) is not None:
            items = [r for r in items if r[field] == args.get(field)]
    data, pagination = paginate(items)
    return respond(data, 200, "array", pagination)


@app.route("/nutrition/students/<rid>/deposit", methods=["POST"])
@endpoint("POSClerk")
def deposit(rid):
    student = fetch(students, rid, "student")
    body = get_body()
    amount_cents = req_int(body, "amount_cents")
    apply_balance_change(student, amount_cents)
    return respond(serialize(student), 200, "object")


# --------------------------------------------------------------------------- #
# MealTransaction
# --------------------------------------------------------------------------- #
def _validate_alacarte(lines):
    vreq(isinstance(lines, list), "a_la_carte_lines must be an array")
    out = []
    for line in lines:
        vreq(isinstance(line, dict), "each a-la-carte line must be an object")
        fid = line.get("food_item_id")
        vreq(is_str(fid), "a-la-carte food_item_id is required")
        vreq(is_int(line.get("qty")), "a-la-carte qty must be an integer")
        vreq(is_int(line.get("unit_price_cents")), "a-la-carte unit_price_cents must be an integer")
        out.append({
            "food_item_id": fid,
            "qty": line["qty"],
            "unit_price_cents": line["unit_price_cents"],
        })
    return out


@app.route("/nutrition/meal-transactions", methods=["POST"])
@endpoint("POSClerk")
def create_meal_transaction():
    body = get_body()
    # Existence (priority 3), left-to-right
    check_fk(body, "site_id", sites)
    check_fk(body, "student_id", students)
    check_fk(body, "production_record_id", production_records)
    alc_raw = body.get("a_la_carte_lines")
    if isinstance(alc_raw, list):
        for line in alc_raw:
            if isinstance(line, dict):
                fid = line.get("food_item_id")
                if isinstance(fid, str) and fid not in food_items:
                    raise ApiError("ERR_NOT_FOUND", 404, "a-la-carte food_item_id does not resolve")
    # Body shape (priority 4)
    site_id = req_str(body, "site_id")
    student_id = req_str(body, "student_id")
    production_record_id = req_str(body, "production_record_id")
    service_date = req_date(body, "service_date")
    meal_type = req_enum(body, "meal_type", MEAL_TYPES)
    selected_raw = body.get("selected_components")
    vreq(isinstance(selected_raw, list), "selected_components must be an array")
    for c in selected_raw:
        vreq(is_str(c) and c in COMPONENTS, "selected_components has an invalid value")
    selected_components = list(selected_raw)
    alc = _validate_alacarte(alc_raw) if alc_raw is not None else []

    site = sites[site_id]
    student = students[student_id]
    pr = production_records[production_record_id]

    vreq(service_date == pr["service_date"],
         "service_date must equal the production record's service_date")

    # Guards in §2.5 order
    if pr["status"] != "PREPARED":
        raise ApiError("ERR_PRODUCTION_NOT_READY", 409, "Production record is not PREPARED")
    for line in alc:
        fi = food_items[line["food_item_id"]]
        if fi["category"] in ("SNACK", "BEVERAGE") and not smart_snack_ok(fi):
            raise ApiError("ERR_NOT_SMART_SNACK_COMPLIANT", 422,
                           "A-la-carte item fails Smart-Snacks standards")
    if student["site_id"] != site_id:
        raise ApiError("ERR_STUDENT_SITE_MISMATCH", 409, "Student belongs to a different site")
    cycle = menu_cycles[pr["menu_cycle_id"]]
    offered = set(c["component"] for c in cycle["components"])
    for comp in selected_components:
        if comp not in offered:
            raise ApiError("ERR_INVALID_COMPONENT", 422, "A selected component is not offered")

    # Snapshot & offer-vs-serve
    claim_category = student["eligibility_category"]
    taken = len(set(selected_components))
    has_fv = bool(set(selected_components) & {"FRUIT", "VEGETABLE"})
    reimbursable = taken >= 3 and has_fv
    meal_claim_status = "REIMBURSABLE" if reimbursable else "NON_REIMBURSABLE"

    if reimbursable:
        for m in meal_transactions.values():
            if (m["student_id"] == student_id
                    and m["service_date"] == service_date
                    and m["meal_type"] == meal_type
                    and m["meal_claim_status"] == "REIMBURSABLE"):
                raise ApiError("ERR_DUPLICATE_REIMBURSABLE_MEAL", 409,
                               "A reimbursable meal already exists for this student/date/meal")

    # A-la-carte total (round tax per line, then sum)
    alacarte_total = 0
    for line in alc:
        base = line["qty"] * line["unit_price_cents"]
        tax = int(rhu(D(base) * D(site["sales_tax_bps"]) / D("10000"), 0))
        alacarte_total += base + tax

    # Meal price/copay by category & meal_type
    if claim_category == "FREE":
        meal_price = 0
    elif claim_category == "REDUCED":
        meal_price = (site["reduced_lunch_copay_cents"] if meal_type == "LUNCH"
                      else site["reduced_breakfast_copay_cents"])
    else:  # PAID
        meal_price = (site["paid_lunch_price_cents"] if meal_type == "LUNCH"
                      else site["paid_breakfast_price_cents"])
    meal_charge_cents = meal_price + alacarte_total

    # Balance guard (last)
    prospective = student["balance_cents"] - meal_charge_cents
    if prospective < 0 and not site["negative_balance_allowed"]:
        raise ApiError("ERR_INSUFFICIENT_BALANCE", 402, "Charge would drive balance negative")

    payment_status = "PAID" if (meal_charge_cents == 0 or prospective >= 0) else "CHARGED"

    rec = {
        "site_id": site_id,
        "student_id": student_id,
        "production_record_id": production_record_id,
        "service_date": service_date,
        "meal_type": meal_type,
        "selected_components": selected_components,
        "claim_category": claim_category,
        "meal_claim_status": meal_claim_status,
        "a_la_carte_lines": alc,
        "alacarte_total_cents": alacarte_total,
        "meal_charge_cents": meal_charge_cents,
        "payment_status": payment_status,
    }
    stamp(rec)
    meal_transactions[rec["id"]] = rec

    # Cascade: charge student -> balance -> account_status -> site count
    apply_balance_change(student, -meal_charge_cents)
    # ProductionRecord served_qty++
    pr["served_qty"] += 1
    recompute_leftover(pr)
    touch(pr)
    # Draft claim recompute + version bump
    bump_draft_claim(site_id, service_date[:7])

    return respond(serialize(rec), 201, "object")


@app.route("/nutrition/meal-transactions/<rid>", methods=["GET"])
@endpoint("PlatformAdmin", "POSClerk", "NutritionDirector")
def get_meal_transaction(rid):
    return respond(serialize(fetch(meal_transactions, rid, "meal transaction")), 200, "object")


@app.route("/nutrition/meal-transactions", methods=["GET"])
@endpoint("PlatformAdmin", "POSClerk", "NutritionDirector")
def list_meal_transactions():
    args = request.args
    items = list(meal_transactions.values())
    for field in ("site_id", "student_id", "production_record_id",
                  "service_date", "meal_type", "meal_claim_status"):
        if args.get(field) is not None:
            items = [r for r in items if r[field] == args.get(field)]
    data, pagination = paginate(items)
    return respond(data, 200, "array", pagination)


@app.route("/nutrition/meal-transactions/<rid>/void", methods=["POST"])
@endpoint("POSClerk")
def void_meal_transaction(rid):
    meal = fetch(meal_transactions, rid, "meal transaction")
    if meal["meal_claim_status"] == "VOIDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Meal transaction is not RECORDED")
    meal["meal_claim_status"] = "VOIDED"
    meal["payment_status"] = "REFUNDED"
    student = students[meal["student_id"]]
    apply_balance_change(student, meal["meal_charge_cents"])
    pr = production_records[meal["production_record_id"]]
    pr["served_qty"] -= 1
    recompute_leftover(pr)
    touch(pr)
    touch(meal)
    bump_draft_claim(meal["site_id"], meal["service_date"][:7])
    return respond(serialize(meal), 200, "object")


# --------------------------------------------------------------------------- #
# ReimbursementClaim
# --------------------------------------------------------------------------- #
@app.route("/nutrition/reimbursement-claims", methods=["POST"])
@endpoint("NutritionDirector")
def create_claim():
    body = get_body()
    check_fk(body, "site_id", sites)
    site_id = req_str(body, "site_id")
    claim_month = req_str(body, "claim_month")
    vreq(bool(MONTH_RE.match(claim_month)), "claim_month must be YYYY-MM")
    for c in claims.values():
        if c["site_id"] == site_id and c["claim_month"] == claim_month:
            raise ApiError("ERR_CLAIM_ALREADY_EXISTS", 409,
                           "A claim already exists for this site/month")
    rec = {
        "site_id": site_id,
        "claim_month": claim_month,
        "status": "DRAFT",
        "free_count": 0,
        "reduced_count": 0,
        "paid_count": 0,
        "estimated_reimbursement_cents": None,
        "final_reimbursement_cents": None,
        "created_by_user_id": user_id(),
        "submitted_by_user_id": None,
    }
    stamp(rec)
    recompute_claim_counts(rec)
    claims[rec["id"]] = rec
    return respond(serialize(rec), 201, "object")


@app.route("/nutrition/reimbursement-claims/<rid>", methods=["GET"])
@endpoint("PlatformAdmin", "NutritionDirector")
def get_claim(rid):
    return respond(serialize(fetch(claims, rid, "reimbursement claim")), 200, "object")


@app.route("/nutrition/reimbursement-claims", methods=["GET"])
@endpoint("PlatformAdmin", "NutritionDirector")
def list_claims():
    args = request.args
    items = list(claims.values())
    for field in ("site_id", "claim_month", "status"):
        if args.get(field) is not None:
            items = [r for r in items if r[field] == args.get(field)]
    data, pagination = paginate(items)
    return respond(data, 200, "array", pagination)


@app.route("/nutrition/reimbursement-claims/<rid>/submit", methods=["POST"])
@endpoint("NutritionDirector")
def submit_claim(rid):
    claim = fetch(claims, rid, "reimbursement claim")
    body = get_body()
    expected = req_int(body, "expected_claim_version")
    # OCC (priority 5) -> seg (6) -> state (7) -> rate (13)
    if expected != claim["version"]:
        raise ApiError("ERR_STALE_CLAIM_VERSION", 412, "expected_claim_version is stale")
    if user_id() == claim["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Submitter must differ from creator")
    if claim["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not DRAFT")
    site = sites[claim["site_id"]]
    recompute_claim_counts(claim)
    estimated = compute_reimbursement(site, claim["claim_month"])
    claim["submitted_by_user_id"] = user_id()
    claim["estimated_reimbursement_cents"] = estimated
    claim["status"] = "SUBMITTED"
    touch(claim)
    return respond(serialize(claim), 200, "object")


@app.route("/nutrition/reimbursement-claims/<rid>/recall", methods=["POST"])
@endpoint("NutritionDirector")
def recall_claim(rid):
    claim = fetch(claims, rid, "reimbursement claim")
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not SUBMITTED")
    claim["submitted_by_user_id"] = None
    claim["status"] = "DRAFT"
    touch(claim)
    return respond(serialize(claim), 200, "object")


@app.route("/nutrition/reimbursement-claims/<rid>/mark-paid", methods=["POST"])
@endpoint("PlatformAdmin")
def mark_paid_claim(rid):
    claim = fetch(claims, rid, "reimbursement claim")
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not SUBMITTED")
    site = sites[claim["site_id"]]
    recompute_claim_counts(claim)
    final = compute_reimbursement(site, claim["claim_month"])
    claim["final_reimbursement_cents"] = final
    claim["status"] = "PAID"
    touch(claim)
    return respond(serialize(claim), 200, "object")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
