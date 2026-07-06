"""
Corporate Catering & Cafeteria Management API.

In-memory Flask implementation. Every field, endpoint, side effect and error
traces to PRD.md. State is wiped on every process start (per-test-server
isolation); nothing is seeded at startup.
"""
import os
import re
import uuid
import random
import string
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4) — startup default 2026-03-01T00:00:00Z.
# ---------------------------------------------------------------------------
CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store (PRD 2.5). Empty on every boot.
# ---------------------------------------------------------------------------
DB = {
    "ClientSite": {},
    "Employee": {},
    "MenuCycle": {},
    "MenuItem": {},
    "CateringVenue": {},
    "ServiceSession": {},
    "BadgeTransaction": {},
    "Vendor": {},
    "PurchaseOrder": {},
    "InventoryLot": {},
    "WasteEvent": {},
    "CateringOrder": {},
    "VendorInvoice": {},
    "SatisfactionSurvey": {},
}
_SEQ = 0


def next_seq():
    global _SEQ
    _SEQ += 1
    return _SEQ


# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------
CURRENCIES = {"USD", "EUR", "GBP"}
ALLERGENS = {"PEANUTS", "TREE_NUTS", "DAIRY", "GLUTEN", "SOY", "SHELLFISH", "EGGS"}
MEAL_PERIODS = {"BREAKFAST", "LUNCH", "DINNER"}
ITEM_CATEGORIES = {"ENTREE", "SIDE", "BEVERAGE", "DESSERT", "HEALTHY"}
SUBSIDIZED_CATEGORIES = {"ENTREE", "HEALTHY"}
VENDOR_CATEGORIES = {"PRODUCE", "PROTEIN", "DRY_GOODS", "BEVERAGE", "DISPOSABLES"}
PAYMENT_METHODS = {"BADGE_PAYROLL", "WALLET"}
WASTE_REASONS = {"SPOILAGE", "OVERPRODUCTION", "PREP_ERROR", "EXPIRY"}

# Calculation constants (PRD 3.6 / scaffold calculations)
EVENT_OVERHEAD_FACTOR = Decimal("1.20")
SERVICE_FEE_PCT = Decimal("0.18")
MATCH_TOLERANCE_CENTS = 500

# Catering non-terminal states (overlap check) + terminal
CATERING_TERMINAL = {"INVOICED", "CANCELLED"}

# Roles
R_SITE_ADMIN = "SiteAdmin"
R_CAFE_MGR = "CafeteriaManager"
R_DINER = "Diner"
R_COORD = "CateringCoordinator"
R_APPROVER = "CateringApprover"
R_FINANCE = "FinanceController"


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


def verr(msg="validation error"):
    raise ApiError("ERR_VALIDATION", 400, msg)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def fmt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt(CLOCK)


def clock_date():
    return CLOCK.astimezone(timezone.utc).strftime("%Y-%m-%d")


def parse_iso(s):
    if not isinstance(s, str):
        verr("invalid datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except Exception:
        verr("invalid ISO 8601 datetime: %s" % s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Money / ratio helpers
# ---------------------------------------------------------------------------
def rhu_cents(dec):
    return int(dec.quantize(Decimal("1"), ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_common(rec):
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = now_iso()
    rec["updated_at"] = now_iso()
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def new_immutable(rec):
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = now_iso()
    rec["_seq"] = next_seq()
    return rec


def bump(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
def make_meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)
        ),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", meta_extra=None):
    body = {
        "meta": make_meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth (PRD 2.1)
# ---------------------------------------------------------------------------
def authorize(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        err("ERR_UNAUTHENTICATED", 401, "missing identity headers")
    if role not in allowed_roles:
        err("ERR_UNAUTHORIZED", 403, "role %s not permitted" % role)
    return uid, role


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def need(body, *fields):
    for f in fields:
        if body.get(f) is None:
            verr("missing required field: %s" % f)


def as_str(v, name, allow_empty=True):
    if not isinstance(v, str):
        verr("%s must be a string" % name)
    if not allow_empty and v == "":
        verr("%s must not be empty" % name)
    return v


def as_int(v, name, minv=None, maxv=None):
    if isinstance(v, bool) or not isinstance(v, int):
        verr("%s must be an integer" % name)
    if minv is not None and v < minv:
        verr("%s must be >= %s" % (name, minv))
    if maxv is not None and v > maxv:
        verr("%s must be <= %s" % (name, maxv))
    return v


def as_num(v, name, minv=None, maxv=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        verr("%s must be a number" % name)
    if minv is not None and v < minv:
        verr("%s must be >= %s" % (name, minv))
    if maxv is not None and v > maxv:
        verr("%s must be <= %s" % (name, maxv))
    return v


def as_enum(v, name, allowed):
    if v not in allowed:
        verr("%s must be one of %s" % (name, sorted(allowed)))
    return v


def as_allergens(v, name):
    if v is None:
        return []
    if not isinstance(v, list):
        verr("%s must be a list" % name)
    for a in v:
        as_enum(a, name, ALLERGENS)
    return list(v)


def parse_item_lines(v, name):
    """lines: [{menu_item_id, qty>=1}]"""
    if not isinstance(v, list):
        verr("%s must be a list" % name)
    out = []
    for el in v:
        if not isinstance(el, dict):
            verr("%s entries must be objects" % name)
        mid = el.get("menu_item_id")
        if not isinstance(mid, str) or not mid:
            verr("%s.menu_item_id must be a non-empty string" % name)
        as_int(el.get("qty"), "%s.qty" % name, minv=1)
        out.append({"menu_item_id": mid, "qty": el["qty"]})
    return out


def parse_ingredient_lines(v, name):
    """purchase order lines: [{ingredient, qty>=1, unit_cost_cents>=0}]"""
    if not isinstance(v, list):
        verr("%s must be a list" % name)
    out = []
    for el in v:
        if not isinstance(el, dict):
            verr("%s entries must be objects" % name)
        ing = el.get("ingredient")
        if not isinstance(ing, str) or not ing:
            verr("%s.ingredient must be a non-empty string" % name)
        as_int(el.get("qty"), "%s.qty" % name, minv=1)
        as_int(el.get("unit_cost_cents"), "%s.unit_cost_cents" % name, minv=0)
        out.append(
            {
                "ingredient": ing,
                "qty": el["qty"],
                "unit_cost_cents": el["unit_cost_cents"],
            }
        )
    return out


def parse_qty_ingredients(v, name):
    """consumed/reserved: [{ingredient, qty>=1}] -> aggregated dict ingredient->qty"""
    if not isinstance(v, list):
        verr("%s must be a list" % name)
    agg = {}
    for el in v:
        if not isinstance(el, dict):
            verr("%s entries must be objects" % name)
        ing = el.get("ingredient")
        if not isinstance(ing, str) or not ing:
            verr("%s.ingredient must be a non-empty string" % name)
        as_int(el.get("qty"), "%s.qty" % name, minv=1)
        agg[ing] = agg.get(ing, 0) + el["qty"]
    return agg


# ---------------------------------------------------------------------------
# Existence helpers (PRD 2.8)
# ---------------------------------------------------------------------------
def get_or_404(entity, rid):
    rec = DB[entity].get(rid)
    if rec is None:
        err("ERR_NOT_FOUND", 404, "%s %s not found" % (entity, rid))
    return rec


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def get_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            verr("limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            verr("offset must be an integer")
    if limit < 1 or limit > 100:
        verr("limit out of range (1..100)")
    if offset < 0:
        verr("offset out of range")
    return limit, offset


def paginate(items):
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset : offset + limit]
    has_more = (offset + len(page)) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta


def list_response(entity, filter_fields, serializer=pub):
    items = list(DB[entity].values())
    for f in filter_fields:
        val = request.args.get(f)
        if val is not None:
            items = [r for r in items if str(r.get(f)) == val]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, meta = paginate(items)
    data = [serializer(r) for r in page]
    return ok(data, 200, "array", meta)


# ---------------------------------------------------------------------------
# ClientSite derived fields (PRD 2.9)
# ---------------------------------------------------------------------------
def site_cost_status(site):
    food = site["period_food_cost_cents"]
    rev = site["period_revenue_cents"]
    if rev > 0:
        pct = (Decimal(food) / Decimal(rev)).quantize(
            Decimal("0.0001"), ROUND_HALF_UP
        )
    else:
        pct = None
    target = Decimal(str(site["food_cost_target_pct"]))
    status = "OVER_TARGET" if (pct is not None and pct > target) else "ON_TARGET"
    return pct, status


def site_inventory_value(site_id):
    return sum(
        l["qty_on_hand"] * l["unit_cost_cents"]
        for l in DB["InventoryLot"].values()
        if l["client_site_id"] == site_id and l["status"] == "AVAILABLE"
    )


def site_satisfaction_avg(site_id):
    ratings = [
        s["rating"]
        for s in DB["SatisfactionSurvey"].values()
        if s["client_site_id"] == site_id
    ]
    if not ratings:
        return None
    avg = (Decimal(sum(ratings)) / Decimal(len(ratings))).quantize(
        Decimal("0.01"), ROUND_HALF_UP
    )
    return float(avg)


def ser_site(site):
    d = pub(site)
    pct, status = site_cost_status(site)
    d["food_cost_pct"] = None if pct is None else float(pct)
    d["cost_status"] = status
    d["inventory_value_cents"] = site_inventory_value(site["id"])
    d["satisfaction_avg"] = site_satisfaction_avg(site["id"])
    return d


# ---------------------------------------------------------------------------
# Inventory / FIFO helpers (PRD 2.10)
# ---------------------------------------------------------------------------
def available_lots(site_id, ingredient):
    lots = [
        l
        for l in DB["InventoryLot"].values()
        if l["client_site_id"] == site_id
        and l["ingredient"] == ingredient
        and l["status"] == "AVAILABLE"
    ]
    lots.sort(key=lambda l: (l["received_at"], l["created_at"], l["_seq"]))
    return lots


def fifo_consume(site_id, needs):
    """FIFO-consume qty_on_hand for aggregated needs (ingredient->qty).
    Atomic: verify full feasibility before mutating. Returns cost in cents."""
    for ing, qty in needs.items():
        avail = sum(l["qty_on_hand"] for l in available_lots(site_id, ing))
        if avail < qty:
            err("ERR_INSUFFICIENT_INVENTORY", 409, "insufficient inventory for %s" % ing)
    cost = 0
    for ing, qty in needs.items():
        need_left = qty
        for lot in available_lots(site_id, ing):
            if need_left == 0:
                break
            take = min(need_left, lot["qty_on_hand"])
            if take <= 0:
                continue
            cost += take * lot["unit_cost_cents"]
            lot["qty_on_hand"] -= take
            if lot["qty_on_hand"] == 0:
                lot["status"] = "DEPLETED"
            bump(lot)
            need_left -= take
    return cost


def reserve_inventory(site_id, needs, order):
    """Reserve (qty_on_hand - qty_reserved) FIFO. Atomic feasibility first."""
    for ing, qty in needs.items():
        avail = sum(
            l["qty_on_hand"] - l["qty_reserved"] for l in available_lots(site_id, ing)
        )
        if avail < qty:
            err("ERR_INSUFFICIENT_INVENTORY", 409, "insufficient inventory for %s" % ing)
    for ing, qty in needs.items():
        need_left = qty
        for lot in available_lots(site_id, ing):
            if need_left == 0:
                break
            free = lot["qty_on_hand"] - lot["qty_reserved"]
            take = min(need_left, free)
            if take <= 0:
                continue
            lot["qty_reserved"] += take
            bump(lot)
            order["_reservations"].append({"lot_id": lot["id"], "qty": take})
            need_left -= take


def release_reservations(order):
    for r in order.get("_reservations", []):
        lot = DB["InventoryLot"].get(r["lot_id"])
        if lot:
            lot["qty_reserved"] -= r["qty"]
            bump(lot)
    order["_reservations"] = []


def rollup_after_close(site, added_food, added_revenue):
    site["period_food_cost_cents"] += added_food
    site["period_revenue_cents"] += added_revenue
    _, status = site_cost_status(site)
    if status == "OVER_TARGET":
        for co in DB["CateringOrder"].values():
            if co["client_site_id"] == site["id"] and co["status"] == "SUBMITTED":
                co["requires_finance_review"] = True
                bump(co)


# ===========================================================================
# Clock endpoint
# ===========================================================================
@app.route("/api/_clock/set_current_utc", methods=["POST"])
def clock_set():
    authorize([R_SITE_ADMIN])
    body = get_body()
    need(body, "to_iso8601")
    dt = parse_iso(body["to_iso8601"])
    global CLOCK
    CLOCK = dt
    return ok({"current_utc": fmt(CLOCK)})


# ===========================================================================
# ClientSite
# ===========================================================================
@app.route("/api/client-sites", methods=["POST"])
def client_site_create():
    authorize([R_SITE_ADMIN])
    body = get_body()
    need(body, "name", "client_name", "employer_subsidy_pct",
         "daily_subsidy_cap_cents", "food_cost_target_pct")
    as_str(body["name"], "name")
    as_str(body["client_name"], "client_name")
    currency = body.get("currency", "USD")
    as_enum(currency, "currency", CURRENCIES)
    as_num(body["employer_subsidy_pct"], "employer_subsidy_pct", 0, 1)
    as_int(body["daily_subsidy_cap_cents"], "daily_subsidy_cap_cents", minv=0)
    as_num(body["food_cost_target_pct"], "food_cost_target_pct", 0, 1)
    buf = body.get("session_changeover_buffer_minutes", 30)
    as_int(buf, "session_changeover_buffer_minutes", minv=0)
    rec = {
        "name": body["name"],
        "client_name": body["client_name"],
        "currency": currency,
        "employer_subsidy_pct": body["employer_subsidy_pct"],
        "daily_subsidy_cap_cents": body["daily_subsidy_cap_cents"],
        "food_cost_target_pct": body["food_cost_target_pct"],
        "session_changeover_buffer_minutes": buf,
        "status": "ACTIVE",
        "period_food_cost_cents": 0,
        "period_revenue_cents": 0,
    }
    new_common(rec)
    DB["ClientSite"][rec["id"]] = rec
    return ok(ser_site(rec), 201)


@app.route("/api/client-sites/<rid>", methods=["GET"])
def client_site_get(rid):
    authorize([R_SITE_ADMIN, R_CAFE_MGR, R_COORD, R_APPROVER, R_FINANCE, R_DINER])
    rec = get_or_404("ClientSite", rid)
    return ok(ser_site(rec))


@app.route("/api/client-sites", methods=["GET"])
def client_site_list():
    authorize([R_SITE_ADMIN, R_FINANCE])
    return list_response("ClientSite", [], ser_site)


@app.route("/api/client-sites/<rid>/suspend", methods=["POST"])
def client_site_suspend(rid):
    authorize([R_SITE_ADMIN])
    rec = get_or_404("ClientSite", rid)
    if rec["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "site not ACTIVE")
    rec["status"] = "SUSPENDED"
    bump(rec)
    return ok(ser_site(rec))


@app.route("/api/client-sites/<rid>/reactivate", methods=["POST"])
def client_site_reactivate(rid):
    authorize([R_SITE_ADMIN])
    rec = get_or_404("ClientSite", rid)
    if rec["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", 409, "site not SUSPENDED")
    rec["status"] = "ACTIVE"
    bump(rec)
    return ok(ser_site(rec))


# ===========================================================================
# Employee
# ===========================================================================
@app.route("/api/employees", methods=["POST"])
def employee_create():
    authorize([R_SITE_ADMIN])
    body = get_body()
    need(body, "client_site_id", "badge_id", "full_name")
    as_str(body["client_site_id"], "client_site_id")
    as_str(body["badge_id"], "badge_id")
    as_str(body["full_name"], "full_name")
    allergens = as_allergens(body.get("restricted_allergens"), "restricted_allergens")
    wallet = body.get("wallet_balance_cents", 0)
    as_int(wallet, "wallet_balance_cents", minv=0)
    site = get_or_404("ClientSite", body["client_site_id"])
    # uniqueness: badge_id unique within site (priority 9)
    for e in DB["Employee"].values():
        if e["client_site_id"] == site["id"] and e["badge_id"] == body["badge_id"]:
            err("ERR_DUPLICATE_BADGE", 409, "badge_id already used at this site")
    rec = {
        "client_site_id": site["id"],
        "badge_id": body["badge_id"],
        "full_name": body["full_name"],
        "restricted_allergens": allergens,
        "wallet_balance_cents": wallet,
        "daily_subsidy_used_cents": 0,
        "subsidy_day": None,
        "status": "ACTIVE",
    }
    new_common(rec)
    DB["Employee"][rec["id"]] = rec
    return ok(pub(rec), 201)


@app.route("/api/employees/<rid>", methods=["GET"])
def employee_get(rid):
    uid, role = authorize([R_SITE_ADMIN, R_CAFE_MGR, R_DINER])
    rec = get_or_404("Employee", rid)
    if role == R_DINER and rec["id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "diner may only read own record")
    return ok(pub(rec))


@app.route("/api/employees", methods=["GET"])
def employee_list():
    authorize([R_SITE_ADMIN, R_CAFE_MGR])
    return list_response("Employee", ["client_site_id"])


@app.route("/api/employees/<rid>/terminate", methods=["POST"])
def employee_terminate(rid):
    authorize([R_SITE_ADMIN])
    rec = get_or_404("Employee", rid)
    if rec["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "employee not ACTIVE")
    rec["status"] = "TERMINATED"
    bump(rec)
    return ok(pub(rec))


# ===========================================================================
# MenuCycle
# ===========================================================================
@app.route("/api/menu-cycles", methods=["POST"])
def menu_cycle_create():
    authorize([R_CAFE_MGR])
    body = get_body()
    need(body, "client_site_id", "name", "cycle_length_weeks")
    as_str(body["client_site_id"], "client_site_id")
    as_str(body["name"], "name")
    as_int(body["cycle_length_weeks"], "cycle_length_weeks", minv=1)
    site = get_or_404("ClientSite", body["client_site_id"])
    rec = {
        "client_site_id": site["id"],
        "name": body["name"],
        "cycle_length_weeks": body["cycle_length_weeks"],
        "status": "DRAFT",
    }
    new_common(rec)
    DB["MenuCycle"][rec["id"]] = rec
    return ok(pub(rec), 201)


@app.route("/api/menu-cycles/<rid>", methods=["GET"])
def menu_cycle_get(rid):
    authorize([R_CAFE_MGR, R_COORD, R_DINER])
    rec = get_or_404("MenuCycle", rid)
    return ok(pub(rec))


@app.route("/api/menu-cycles", methods=["GET"])
def menu_cycle_list():
    authorize([R_CAFE_MGR, R_COORD])
    return list_response("MenuCycle", ["client_site_id"])


@app.route("/api/menu-cycles/<rid>/publish", methods=["POST"])
def menu_cycle_publish(rid):
    authorize([R_CAFE_MGR])
    rec = get_or_404("MenuCycle", rid)
    if rec["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "cycle not DRAFT")
    has_item = any(
        mi["menu_cycle_id"] == rec["id"] for mi in DB["MenuItem"].values()
    )
    if not has_item:
        err("ERR_EMPTY_MENU_CYCLE", 409, "cycle has no menu items")
    rec["status"] = "PUBLISHED"
    bump(rec)
    return ok(pub(rec))


# ===========================================================================
# MenuItem
# ===========================================================================
@app.route("/api/menu-items", methods=["POST"])
def menu_item_create():
    authorize([R_CAFE_MGR])
    body = get_body()
    need(body, "menu_cycle_id", "name", "category", "price_cents",
         "standard_recipe_cost_cents")
    as_str(body["menu_cycle_id"], "menu_cycle_id")
    as_str(body["name"], "name")
    as_enum(body["category"], "category", ITEM_CATEGORIES)
    as_int(body["price_cents"], "price_cents", minv=0)
    as_int(body["standard_recipe_cost_cents"], "standard_recipe_cost_cents", minv=0)
    allergens = as_allergens(body.get("allergens"), "allergens")
    cycle = get_or_404("MenuCycle", body["menu_cycle_id"])
    rec = {
        "menu_cycle_id": cycle["id"],
        "name": body["name"],
        "category": body["category"],
        "price_cents": body["price_cents"],
        "standard_recipe_cost_cents": body["standard_recipe_cost_cents"],
        "allergens": allergens,
        "status": "ACTIVE",
    }
    new_common(rec)
    DB["MenuItem"][rec["id"]] = rec
    return ok(pub(rec), 201)


@app.route("/api/menu-items/<rid>", methods=["GET"])
def menu_item_get(rid):
    authorize([R_CAFE_MGR, R_COORD, R_DINER])
    rec = get_or_404("MenuItem", rid)
    return ok(pub(rec))


@app.route("/api/menu-items", methods=["GET"])
def menu_item_list():
    authorize([R_CAFE_MGR, R_COORD, R_DINER])
    return list_response("MenuItem", ["menu_cycle_id"])


# ===========================================================================
# CateringVenue
# ===========================================================================
@app.route("/api/catering-venues", methods=["POST"])
def venue_create():
    authorize([R_SITE_ADMIN])
    body = get_body()
    need(body, "client_site_id", "name", "capacity")
    as_str(body["client_site_id"], "client_site_id")
    as_str(body["name"], "name")
    as_int(body["capacity"], "capacity", minv=1)
    site = get_or_404("ClientSite", body["client_site_id"])
    rec = {
        "client_site_id": site["id"],
        "name": body["name"],
        "capacity": body["capacity"],
    }
    new_common(rec)
    DB["CateringVenue"][rec["id"]] = rec
    return ok(pub(rec), 201)


@app.route("/api/catering-venues/<rid>", methods=["GET"])
def venue_get(rid):
    authorize([R_SITE_ADMIN, R_COORD, R_APPROVER, R_FINANCE])
    rec = get_or_404("CateringVenue", rid)
    return ok(pub(rec))


@app.route("/api/catering-venues", methods=["GET"])
def venue_list():
    authorize([R_SITE_ADMIN, R_COORD])
    return list_response("CateringVenue", ["client_site_id"])


# ===========================================================================
# ServiceSession
# ===========================================================================
def buffer_conflict(new_s, new_e, ex_s, ex_e, buffer_min):
    # overlap
    if new_s < ex_e and ex_s < new_e:
        return True
    if new_s >= ex_e:
        gap = (new_s - ex_e).total_seconds() / 60.0
    else:
        gap = (ex_s - new_e).total_seconds() / 60.0
    return gap < buffer_min


@app.route("/api/service-sessions", methods=["POST"])
def session_create():
    authorize([R_CAFE_MGR])
    body = get_body()
    need(body, "client_site_id", "menu_cycle_id", "service_date", "meal_period",
         "window_start", "window_end", "forecast_headcount")
    as_str(body["client_site_id"], "client_site_id")
    as_str(body["menu_cycle_id"], "menu_cycle_id")
    if not isinstance(body["service_date"], str) or not DATE_RE.match(body["service_date"]):
        verr("service_date must be YYYY-MM-DD")
    as_enum(body["meal_period"], "meal_period", MEAL_PERIODS)
    ws = parse_iso(body["window_start"])
    we = parse_iso(body["window_end"])
    if we <= ws:
        verr("window_end must be after window_start")
    as_int(body["forecast_headcount"], "forecast_headcount", minv=0)
    site = get_or_404("ClientSite", body["client_site_id"])
    cycle = get_or_404("MenuCycle", body["menu_cycle_id"])
    # temporal: changeover buffer (priority 8)
    buf = site["session_changeover_buffer_minutes"]
    for s in DB["ServiceSession"].values():
        if (s["client_site_id"] == site["id"] and s["service_date"] == body["service_date"]
                and s["status"] != "CANCELLED"):
            if buffer_conflict(ws, we, parse_iso(s["window_start"]),
                               parse_iso(s["window_end"]), buf):
                err("ERR_SESSION_BUFFER_CONFLICT", 409, "changeover buffer violated")
    # uniqueness: one per (site, date, meal_period) (priority 9)
    for s in DB["ServiceSession"].values():
        if (s["client_site_id"] == site["id"] and s["service_date"] == body["service_date"]
                and s["meal_period"] == body["meal_period"] and s["status"] != "CANCELLED"):
            err("ERR_DUPLICATE_SESSION_SLOT", 409, "session slot already exists")
    rec = {
        "client_site_id": site["id"],
        "menu_cycle_id": cycle["id"],
        "service_date": body["service_date"],
        "meal_period": body["meal_period"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "forecast_headcount": body["forecast_headcount"],
        "actual_headcount": 0,
        "revenue_cents": 0,
        "actual_food_cost_cents": None,
        "theoretical_food_cost_cents": 0,
        "status": "PLANNED",
    }
    new_common(rec)
    DB["ServiceSession"][rec["id"]] = rec
    return ok(pub(rec), 201)


@app.route("/api/service-sessions/<rid>", methods=["GET"])
def session_get(rid):
    authorize([R_CAFE_MGR, R_FINANCE, R_DINER])
    rec = get_or_404("ServiceSession", rid)
    return ok(pub(rec))


@app.route("/api/service-sessions", methods=["GET"])
def session_list():
    authorize([R_CAFE_MGR, R_FINANCE])
    return list_response("ServiceSession",
                         ["client_site_id", "menu_cycle_id", "service_date"])


@app.route("/api/service-sessions/<rid>/lock-forecast", methods=["POST"])
def session_lock(rid):
    authorize([R_CAFE_MGR])
    rec = get_or_404("ServiceSession", rid)
    if rec["status"] != "PLANNED":
        err("ERR_INVALID_STATE", 409, "session not PLANNED")
    if rec["forecast_headcount"] is None:
        verr("forecast_headcount is not set")
    rec["status"] = "FORECAST_LOCKED"
    bump(rec)
    return ok(pub(rec))


@app.route("/api/service-sessions/<rid>/open", methods=["POST"])
def session_open(rid):
    authorize([R_CAFE_MGR])
    rec = get_or_404("ServiceSession", rid)
    if rec["status"] != "FORECAST_LOCKED":
        err("ERR_INVALID_STATE", 409, "session not FORECAST_LOCKED")
    cycle = DB["MenuCycle"].get(rec["menu_cycle_id"])
    if not cycle or cycle["status"] != "PUBLISHED":
        err("ERR_MENU_CYCLE_NOT_PUBLISHED", 409, "menu cycle not PUBLISHED")
    rec["status"] = "IN_SERVICE"
    bump(rec)
    return ok(pub(rec))


@app.route("/api/service-sessions/<rid>/close", methods=["POST"])
def session_close(rid):
    authorize([R_CAFE_MGR])
    body = get_body()
    need(body, "consumed_ingredients")
    needs = parse_qty_ingredients(body["consumed_ingredients"], "consumed_ingredients")
    rec = get_or_404("ServiceSession", rid)
    if rec["status"] != "IN_SERVICE":
        err("ERR_INVALID_STATE", 409, "session not IN_SERVICE")
    site = DB["ClientSite"][rec["client_site_id"]]
    cost = fifo_consume(site["id"], needs)  # raises if insufficient (atomic)
    rec["actual_food_cost_cents"] = cost
    rec["status"] = "CLOSED"
    bump(rec)
    rollup_after_close(site, cost, rec["revenue_cents"])
    bump(site)  # inventory pool changed -> ClientSite.version +1
    return ok(pub(rec))


@app.route("/api/service-sessions/<rid>/cancel", methods=["POST"])
def session_cancel(rid):
    authorize([R_CAFE_MGR])
    rec = get_or_404("ServiceSession", rid)
    if rec["status"] not in ("PLANNED", "FORECAST_LOCKED", "IN_SERVICE"):
        err("ERR_INVALID_STATE", 409, "session not cancellable")
    if rec["status"] == "IN_SERVICE":
        has_sales = any(
            t["service_session_id"] == rec["id"] and t["status"] == "COMPLETED"
            for t in DB["BadgeTransaction"].values()
        )
        if has_sales:
            err("ERR_SESSION_HAS_SALES", 409, "session has completed sales")
    rec["status"] = "CANCELLED"
    bump(rec)
    return ok(pub(rec))


# ===========================================================================
# BadgeTransaction (POS)
# ===========================================================================
@app.route("/api/badge-transactions", methods=["POST"])
def badge_create():
    uid, role = authorize([R_DINER])
    body = get_body()
    need(body, "employee_id", "service_session_id", "lines", "payment_method")
    as_str(body["employee_id"], "employee_id")
    as_str(body["service_session_id"], "service_session_id")
    lines = parse_item_lines(body["lines"], "lines")
    if not lines:
        verr("lines must be non-empty")
    as_enum(body["payment_method"], "payment_method", PAYMENT_METHODS)
    # ownership: diner acts as own employee (PRD 2.1)
    if uid != body["employee_id"]:
        err("ERR_UNAUTHORIZED", 403, "employee_id must equal caller X-User-ID")
    # existence left-to-right
    emp = get_or_404("Employee", body["employee_id"])
    sess = get_or_404("ServiceSession", body["service_session_id"])
    items = []
    for ln in lines:
        items.append(get_or_404("MenuItem", ln["menu_item_id"]))
    # state: session IN_SERVICE
    if sess["status"] != "IN_SERVICE":
        err("ERR_SESSION_NOT_OPEN", 409, "session not IN_SERVICE")
    # allergen safety (priority 6)
    restricted = set(emp["restricted_allergens"])
    for mi in items:
        if restricted.intersection(mi["allergens"]):
            err("ERR_ALLERGEN_CONFLICT", 422, "allergen conflict")
    # referential: employee not terminated (priority 7)
    if emp["status"] == "TERMINATED":
        err("ERR_EMPLOYEE_INACTIVE", 409, "employee terminated")
    # calculations
    site = DB["ClientSite"][sess["client_site_id"]]
    subtotal = 0
    subsidizable = 0
    recipe_cost = 0
    for ln, mi in zip(lines, items):
        subtotal += mi["price_cents"] * ln["qty"]
        recipe_cost += mi["standard_recipe_cost_cents"] * ln["qty"]
        if mi["category"] in SUBSIDIZED_CATEGORIES:
            subsidizable += mi["price_cents"] * ln["qty"]
    gross_subsidy = rhu_cents(
        Decimal(subsidizable) * Decimal(str(site["employer_subsidy_pct"]))
    )
    today = clock_date()
    used = emp["daily_subsidy_used_cents"] if emp["subsidy_day"] == today else 0
    remaining_cap = max(0, site["daily_subsidy_cap_cents"] - used)
    subsidy_applied = min(gross_subsidy, remaining_cap)
    employee_charge = subtotal - subsidy_applied
    # fiscal: wallet sufficiency (priority 10)
    if body["payment_method"] == "WALLET":
        if emp["wallet_balance_cents"] < employee_charge:
            err("ERR_WALLET_INSUFFICIENT", 409, "insufficient wallet balance")
        emp["wallet_balance_cents"] -= employee_charge
    # apply subsidy accounting
    emp["daily_subsidy_used_cents"] = used + subsidy_applied
    emp["subsidy_day"] = today
    bump(emp)
    # session running figures
    sess["revenue_cents"] += subtotal
    sess["theoretical_food_cost_cents"] += recipe_cost
    sess["actual_headcount"] += 1
    bump(sess)
    rec = {
        "employee_id": emp["id"],
        "service_session_id": sess["id"],
        "lines": lines,
        "payment_method": body["payment_method"],
        "subtotal_cents": subtotal,
        "subsidy_applied_cents": subsidy_applied,
        "employee_charge_cents": employee_charge,
        "status": "COMPLETED",
        "_recipe_cost": recipe_cost,
    }
    new_common(rec)
    DB["BadgeTransaction"][rec["id"]] = rec
    return ok(pub(rec), 201)


@app.route("/api/badge-transactions/<rid>", methods=["GET"])
def badge_get(rid):
    uid, role = authorize([R_DINER, R_CAFE_MGR, R_FINANCE])
    rec = get_or_404("BadgeTransaction", rid)
    if role == R_DINER and rec["employee_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "diner may only read own transactions")
    return ok(pub(rec))


@app.route("/api/badge-transactions", methods=["GET"])
def badge_list():
    authorize([R_CAFE_MGR, R_FINANCE])
    return list_response("BadgeTransaction", ["employee_id", "service_session_id"])


@app.route("/api/badge-transactions/<rid>/void", methods=["POST"])
def badge_void(rid):
    authorize([R_CAFE_MGR])
    rec = get_or_404("BadgeTransaction", rid)
    if rec["status"] != "COMPLETED":
        err("ERR_INVALID_STATE", 409, "transaction not COMPLETED")
    sess = DB["ServiceSession"][rec["service_session_id"]]
    if sess["status"] != "IN_SERVICE":
        err("ERR_SESSION_NOT_OPEN", 409, "session not IN_SERVICE")
    emp = DB["Employee"][rec["employee_id"]]
    emp_changed = False
    if rec["payment_method"] == "WALLET":
        emp["wallet_balance_cents"] += rec["employee_charge_cents"]
        emp_changed = True
    if rec["subsidy_applied_cents"] > 0:
        emp["daily_subsidy_used_cents"] = max(
            0, emp["daily_subsidy_used_cents"] - rec["subsidy_applied_cents"]
        )
        emp_changed = True
    if emp_changed:
        bump(emp)
    sess["revenue_cents"] -= rec["subtotal_cents"]
    sess["theoretical_food_cost_cents"] -= rec["_recipe_cost"]
    sess["actual_headcount"] -= 1
    bump(sess)
    rec["status"] = "VOIDED"
    bump(rec)
    return ok(pub(rec))


# ===========================================================================
# Vendor
# ===========================================================================
@app.route("/api/vendors", methods=["POST"])
def vendor_create():
    authorize([R_SITE_ADMIN])
    body = get_body()
    need(body, "name", "category")
    as_str(body["name"], "name")
    as_enum(body["category"], "category", VENDOR_CATEGORIES)
    rec = {"name": body["name"], "category": body["category"], "status": "ACTIVE"}
    new_common(rec)
    DB["Vendor"][rec["id"]] = rec
    return ok(pub(rec), 201)


@app.route("/api/vendors/<rid>", methods=["GET"])
def vendor_get(rid):
    authorize([R_SITE_ADMIN, R_CAFE_MGR, R_FINANCE])
    rec = get_or_404("Vendor", rid)
    return ok(pub(rec))


@app.route("/api/vendors", methods=["GET"])
def vendor_list():
    authorize([R_SITE_ADMIN, R_CAFE_MGR, R_FINANCE])
    return list_response("Vendor", [])


# ===========================================================================
# PurchaseOrder
# ===========================================================================
@app.route("/api/purchase-orders", methods=["POST"])
def po_create():
    authorize([R_CAFE_MGR])
    body = get_body()
    need(body, "vendor_id", "client_site_id", "lines")
    as_str(body["vendor_id"], "vendor_id")
    as_str(body["client_site_id"], "client_site_id")
    lines = parse_ingredient_lines(body["lines"], "lines")
    vendor = get_or_404("Vendor", body["vendor_id"])
    site = get_or_404("ClientSite", body["client_site_id"])
    total = sum(l["qty"] * l["unit_cost_cents"] for l in lines)
    rec = {
        "vendor_id": vendor["id"],
        "client_site_id": site["id"],
        "lines": lines,
        "total_cents": total,
        "status": "DRAFT",
    }
    new_common(rec)
    DB["PurchaseOrder"][rec["id"]] = rec
    return ok(pub(rec), 201)


@app.route("/api/purchase-orders/<rid>", methods=["GET"])
def po_get(rid):
    authorize([R_CAFE_MGR, R_FINANCE])
    rec = get_or_404("PurchaseOrder", rid)
    return ok(pub(rec))


@app.route("/api/purchase-orders", methods=["GET"])
def po_list():
    authorize([R_CAFE_MGR, R_FINANCE])
    return list_response("PurchaseOrder", ["vendor_id", "client_site_id"])


@app.route("/api/purchase-orders/<rid>/issue", methods=["POST"])
def po_issue(rid):
    authorize([R_CAFE_MGR])
    rec = get_or_404("PurchaseOrder", rid)
    if rec["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "PO not DRAFT")
    if len(rec["lines"]) < 1:
        verr("PO has no lines")
    rec["status"] = "ISSUED"
    bump(rec)
    return ok(pub(rec))


@app.route("/api/purchase-orders/<rid>/receive", methods=["POST"])
def po_receive(rid):
    authorize([R_CAFE_MGR])
    rec = get_or_404("PurchaseOrder", rid)
    if rec["status"] != "ISSUED":
        err("ERR_INVALID_STATE", 409, "PO not ISSUED")
    site = DB["ClientSite"][rec["client_site_id"]]
    for ln in rec["lines"]:
        lot = {
            "client_site_id": site["id"],
            "purchase_order_id": rec["id"],
            "ingredient": ln["ingredient"],
            "qty_received": ln["qty"],
            "qty_on_hand": ln["qty"],
            "qty_reserved": 0,
            "unit_cost_cents": ln["unit_cost_cents"],
            "received_at": now_iso(),
            "status": "AVAILABLE",
        }
        new_common(lot)
        DB["InventoryLot"][lot["id"]] = lot
    rec["status"] = "RECEIVED"
    bump(rec)
    bump(site)  # inventory pool changed -> version +1
    return ok(pub(rec))


@app.route("/api/purchase-orders/<rid>/cancel", methods=["POST"])
def po_cancel(rid):
    authorize([R_CAFE_MGR])
    rec = get_or_404("PurchaseOrder", rid)
    if rec["status"] not in ("DRAFT", "ISSUED"):
        err("ERR_INVALID_STATE", 409, "PO not cancellable")
    rec["status"] = "CANCELLED"
    bump(rec)
    return ok(pub(rec))


# ===========================================================================
# InventoryLot
# ===========================================================================
@app.route("/api/inventory-lots/<rid>", methods=["GET"])
def lot_get(rid):
    authorize([R_CAFE_MGR, R_FINANCE])
    rec = get_or_404("InventoryLot", rid)
    return ok(pub(rec))


@app.route("/api/inventory-lots", methods=["GET"])
def lot_list():
    authorize([R_CAFE_MGR, R_FINANCE])
    return list_response("InventoryLot",
                         ["client_site_id", "purchase_order_id", "ingredient", "status"])


# ===========================================================================
# WasteEvent
# ===========================================================================
@app.route("/api/waste-events", methods=["POST"])
def waste_create():
    authorize([R_CAFE_MGR])
    body = get_body()
    need(body, "client_site_id", "inventory_lot_id", "qty", "reason")
    as_str(body["client_site_id"], "client_site_id")
    as_str(body["inventory_lot_id"], "inventory_lot_id")
    as_int(body["qty"], "qty", minv=1)
    as_enum(body["reason"], "reason", WASTE_REASONS)
    site = get_or_404("ClientSite", body["client_site_id"])
    lot = get_or_404("InventoryLot", body["inventory_lot_id"])
    cost = body["qty"] * lot["unit_cost_cents"]
    lot["qty_on_hand"] -= body["qty"]
    if lot["qty_on_hand"] <= 0:
        lot["status"] = "DEPLETED"
    bump(lot)
    # waste is NOT in the site-version-bump list (PRD 2.5); only ledger updates
    site["period_food_cost_cents"] += cost
    rec = {
        "client_site_id": site["id"],
        "inventory_lot_id": lot["id"],
        "qty": body["qty"],
        "reason": body["reason"],
        "cost_cents": cost,
    }
    new_immutable(rec)
    DB["WasteEvent"][rec["id"]] = rec
    return ok(pub(rec), 201)


@app.route("/api/waste-events/<rid>", methods=["GET"])
def waste_get(rid):
    authorize([R_CAFE_MGR, R_FINANCE])
    rec = get_or_404("WasteEvent", rid)
    return ok(pub(rec))


@app.route("/api/waste-events", methods=["GET"])
def waste_list():
    authorize([R_CAFE_MGR, R_FINANCE])
    return list_response("WasteEvent", ["client_site_id", "inventory_lot_id"])


# ===========================================================================
# CateringOrder
# ===========================================================================
def volume_discount(hc):
    if hc >= 100:
        return Decimal("0.15")
    if hc >= 50:
        return Decimal("0.10")
    if hc >= 20:
        return Decimal("0.05")
    return Decimal("0")


def catering_price(order):
    lines = order["lines"]
    recipe_sum = 0
    for ln in lines:
        mi = DB["MenuItem"].get(ln["menu_item_id"])
        recipe_sum += mi["standard_recipe_cost_cents"] * ln["qty"]
    estimated = rhu_cents(Decimal(recipe_sum) * EVENT_OVERHEAD_FACTOR)
    disc = volume_discount(order["headcount"])
    order_charge = 0
    for ln in lines:
        mi = DB["MenuItem"].get(ln["menu_item_id"])
        line_charge = rhu_cents(
            Decimal(mi["price_cents"] * ln["qty"]) * (Decimal(1) - disc)
        )
        order_charge += line_charge
    service_fee = rhu_cents(Decimal(order_charge) * SERVICE_FEE_PCT)
    total = order_charge + service_fee
    return estimated, order_charge, service_fee, total


@app.route("/api/catering-orders", methods=["POST"])
def catering_create():
    uid, role = authorize([R_COORD])
    body = get_body()
    need(body, "client_site_id", "venue_id", "event_date", "event_start",
         "event_end", "headcount", "lines")
    as_str(body["client_site_id"], "client_site_id")
    as_str(body["venue_id"], "venue_id")
    if not isinstance(body["event_date"], str) or not DATE_RE.match(body["event_date"]):
        verr("event_date must be YYYY-MM-DD")
    es = parse_iso(body["event_start"])
    ee = parse_iso(body["event_end"])
    if ee <= es:
        verr("event_end must be after event_start")
    as_int(body["headcount"], "headcount", minv=1)
    lines = parse_item_lines(body["lines"], "lines")
    site = get_or_404("ClientSite", body["client_site_id"])
    venue = get_or_404("CateringVenue", body["venue_id"])
    for ln in lines:
        get_or_404("MenuItem", ln["menu_item_id"])
    if venue["client_site_id"] != site["id"]:
        verr("venue does not belong to the client site")
    rec = {
        "client_site_id": site["id"],
        "venue_id": venue["id"],
        "coordinator_id": uid,
        "event_date": body["event_date"],
        "event_start": body["event_start"],
        "event_end": body["event_end"],
        "headcount": body["headcount"],
        "lines": lines,
        "estimated_cost_cents": None,
        "final_cost_cents": None,
        "order_charge_cents": None,
        "service_fee_cents": None,
        "total_charge_cents": None,
        "requires_finance_review": False,
        "status": "DRAFT",
        "_reservations": [],
    }
    new_common(rec)
    DB["CateringOrder"][rec["id"]] = rec
    return ok(pub(rec), 201)


@app.route("/api/catering-orders/<rid>", methods=["GET"])
def catering_get(rid):
    authorize([R_COORD, R_APPROVER, R_FINANCE, R_CAFE_MGR])
    rec = get_or_404("CateringOrder", rid)
    return ok(pub(rec))


@app.route("/api/catering-orders", methods=["GET"])
def catering_list():
    authorize([R_COORD, R_APPROVER, R_FINANCE, R_CAFE_MGR])
    return list_response("CateringOrder", ["client_site_id", "venue_id", "status"])


@app.route("/api/catering-orders/<rid>/submit", methods=["POST"])
def catering_submit(rid):
    authorize([R_COORD])
    rec = get_or_404("CateringOrder", rid)
    if rec["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "order not DRAFT")
    if not rec["lines"]:
        verr("lines must be non-empty")
    venue = DB["CateringVenue"][rec["venue_id"]]
    es = parse_iso(rec["event_start"])
    ee = parse_iso(rec["event_end"])
    # temporal: venue time conflict (priority 8), half-open [start,end)
    for o in DB["CateringOrder"].values():
        if (o["id"] != rec["id"] and o["venue_id"] == rec["venue_id"]
                and o["status"] not in CATERING_TERMINAL):
            os_ = parse_iso(o["event_start"])
            oe_ = parse_iso(o["event_end"])
            if es < oe_ and os_ < ee:
                err("ERR_VENUE_TIME_CONFLICT", 409, "venue time conflict")
    # capacity (priority 9)
    if rec["headcount"] > venue["capacity"]:
        err("ERR_VENUE_CAPACITY_EXCEEDED", 409, "headcount exceeds venue capacity")
    estimated, order_charge, service_fee, total = catering_price(rec)
    rec["estimated_cost_cents"] = estimated
    rec["order_charge_cents"] = order_charge
    rec["service_fee_cents"] = service_fee
    rec["total_charge_cents"] = total
    rec["status"] = "SUBMITTED"
    bump(rec)
    return ok(pub(rec))


@app.route("/api/catering-orders/<rid>/review", methods=["POST"])
def catering_review(rid):
    uid, role = authorize([R_APPROVER])
    body = get_body()
    need(body, "decision")
    as_enum(body["decision"], "decision", {"APPROVE", "REQUEST_REVISION"})
    rec = get_or_404("CateringOrder", rid)
    if rec["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "order not SUBMITTED")
    # segregation of duties (priority 7)
    if uid == rec["coordinator_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 409, "approver may not be coordinator")
    rec["status"] = "APPROVED" if body["decision"] == "APPROVE" else "REVISION_REQUESTED"
    bump(rec)
    return ok(pub(rec))


@app.route("/api/catering-orders/<rid>/revise", methods=["POST"])
def catering_revise(rid):
    authorize([R_COORD])
    rec = get_or_404("CateringOrder", rid)
    if rec["status"] != "REVISION_REQUESTED":
        err("ERR_INVALID_STATE", 409, "order not REVISION_REQUESTED")
    rec["status"] = "DRAFT"
    bump(rec)
    return ok(pub(rec))


@app.route("/api/catering-orders/<rid>/confirm", methods=["POST"])
def catering_confirm(rid):
    authorize([R_FINANCE])
    body = get_body()
    need(body, "expected_client_site_version", "reserved_ingredients")
    as_int(body["expected_client_site_version"], "expected_client_site_version")
    needs = parse_qty_ingredients(body["reserved_ingredients"], "reserved_ingredients")
    rec = get_or_404("CateringOrder", rid)
    if rec["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "order not APPROVED")
    site = DB["ClientSite"][rec["client_site_id"]]
    # order per PRD 3.6: site ACTIVE, then OCC version, then inventory
    if site["status"] != "ACTIVE":
        err("ERR_SITE_SUSPENDED", 409, "client site suspended")
    if body["expected_client_site_version"] != site["version"]:
        err("ERR_STALE_SITE_VERSION", 412, "stale client site version")
    reserve_inventory(site["id"], needs, rec)  # raises if insufficient (atomic)
    rec["status"] = "CONFIRMED"
    bump(rec)
    bump(site)  # inventory pool availability changed -> version +1
    return ok(pub(rec))


@app.route("/api/catering-orders/<rid>/fulfill", methods=["POST"])
def catering_fulfill(rid):
    authorize([R_CAFE_MGR])
    body = get_body()
    need(body, "consumed_ingredients")
    needs = parse_qty_ingredients(body["consumed_ingredients"], "consumed_ingredients")
    rec = get_or_404("CateringOrder", rid)
    if rec["status"] != "CONFIRMED":
        err("ERR_INVALID_STATE", 409, "order not CONFIRMED")
    site = DB["ClientSite"][rec["client_site_id"]]
    # feasibility check against qty_on_hand (reserved+available), atomic
    for ing, qty in needs.items():
        avail = sum(l["qty_on_hand"] for l in available_lots(site["id"], ing))
        if avail < qty:
            err("ERR_INSUFFICIENT_INVENTORY", 409, "insufficient inventory for %s" % ing)
    # release this order's reservations, then consume FIFO
    release_reservations(rec)
    cost = fifo_consume(site["id"], needs)
    rec["final_cost_cents"] = cost
    rec["status"] = "FULFILLED"
    bump(rec)
    site["period_food_cost_cents"] += cost
    bump(site)  # inventory pool changed -> version +1
    return ok(pub(rec))


@app.route("/api/catering-orders/<rid>/invoice", methods=["POST"])
def catering_invoice(rid):
    authorize([R_FINANCE])
    rec = get_or_404("CateringOrder", rid)
    if rec["status"] != "FULFILLED":
        err("ERR_INVALID_STATE", 409, "order not FULFILLED")
    site = DB["ClientSite"][rec["client_site_id"]]
    # invoice recognizes revenue; NOT in the site-version-bump list (PRD 2.5)
    site["period_revenue_cents"] += rec["total_charge_cents"]
    rec["status"] = "INVOICED"
    bump(rec)
    return ok(pub(rec))


@app.route("/api/catering-orders/<rid>/cancel", methods=["POST"])
def catering_cancel(rid):
    uid, role = authorize([R_COORD, R_FINANCE])
    rec = get_or_404("CateringOrder", rid)
    st = rec["status"]
    coord_states = ("DRAFT", "SUBMITTED")
    finance_states = ("APPROVED", "CONFIRMED")
    if role == R_COORD and st in coord_states:
        pass
    elif role == R_FINANCE and st in finance_states:
        pass
    else:
        err("ERR_INVALID_STATE", 409, "order not cancellable by this role/state")
    if st == "CONFIRMED":
        release_reservations(rec)
        rec["status"] = "CANCELLED"
        bump(rec)
        site = DB["ClientSite"][rec["client_site_id"]]
        bump(site)  # reservations released -> version +1
    else:
        rec["status"] = "CANCELLED"
        bump(rec)
    return ok(pub(rec))


# ===========================================================================
# VendorInvoice
# ===========================================================================
@app.route("/api/vendor-invoices", methods=["POST"])
def invoice_create():
    authorize([R_FINANCE])
    body = get_body()
    need(body, "vendor_id", "purchase_order_id", "invoiced_amount_cents")
    as_str(body["vendor_id"], "vendor_id")
    as_str(body["purchase_order_id"], "purchase_order_id")
    as_int(body["invoiced_amount_cents"], "invoiced_amount_cents", minv=0)
    vendor = get_or_404("Vendor", body["vendor_id"])
    po = get_or_404("PurchaseOrder", body["purchase_order_id"])
    rec = {
        "vendor_id": vendor["id"],
        "purchase_order_id": po["id"],
        "invoiced_amount_cents": body["invoiced_amount_cents"],
        "matched_variance_cents": None,
        "status": "RECEIVED",
    }
    new_common(rec)
    DB["VendorInvoice"][rec["id"]] = rec
    return ok(pub(rec), 201)


@app.route("/api/vendor-invoices/<rid>", methods=["GET"])
def invoice_get(rid):
    authorize([R_FINANCE, R_CAFE_MGR])
    rec = get_or_404("VendorInvoice", rid)
    return ok(pub(rec))


@app.route("/api/vendor-invoices", methods=["GET"])
def invoice_list():
    authorize([R_FINANCE, R_CAFE_MGR])
    return list_response("VendorInvoice", ["vendor_id", "purchase_order_id", "status"])


@app.route("/api/vendor-invoices/<rid>/match", methods=["POST"])
def invoice_match(rid):
    authorize([R_FINANCE])
    rec = get_or_404("VendorInvoice", rid)
    if rec["status"] != "RECEIVED":
        err("ERR_INVALID_STATE", 409, "invoice not RECEIVED")
    po = DB["PurchaseOrder"][rec["purchase_order_id"]]
    if po["status"] != "RECEIVED":
        err("ERR_PO_NOT_RECEIVED", 409, "purchase order not RECEIVED")
    rec["matched_variance_cents"] = rec["invoiced_amount_cents"] - po["total_cents"]
    rec["status"] = "MATCHED"
    bump(rec)
    return ok(pub(rec))


@app.route("/api/vendor-invoices/<rid>/resolve", methods=["POST"])
def invoice_resolve(rid):
    authorize([R_FINANCE])
    body = get_body()
    need(body, "resolution")
    as_enum(body["resolution"], "resolution", {"APPROVE", "DISPUTE"})
    rec = get_or_404("VendorInvoice", rid)
    if rec["status"] != "MATCHED":
        err("ERR_INVALID_STATE", 409, "invoice not MATCHED")
    if body["resolution"] == "APPROVE":
        if abs(rec["matched_variance_cents"]) > MATCH_TOLERANCE_CENTS:
            err("ERR_VARIANCE_TOO_LARGE", 409, "variance exceeds tolerance")
        rec["status"] = "APPROVED"
    else:
        rec["status"] = "DISPUTED"
    bump(rec)
    return ok(pub(rec))


@app.route("/api/vendor-invoices/<rid>/resubmit", methods=["POST"])
def invoice_resubmit(rid):
    authorize([R_FINANCE])
    body = get_body()
    need(body, "invoiced_amount_cents")
    as_int(body["invoiced_amount_cents"], "invoiced_amount_cents", minv=0)
    rec = get_or_404("VendorInvoice", rid)
    if rec["status"] != "DISPUTED":
        err("ERR_INVALID_STATE", 409, "invoice not DISPUTED")
    rec["invoiced_amount_cents"] = body["invoiced_amount_cents"]
    rec["matched_variance_cents"] = None
    rec["status"] = "RECEIVED"
    bump(rec)
    return ok(pub(rec))


@app.route("/api/vendor-invoices/<rid>/pay", methods=["POST"])
def invoice_pay(rid):
    authorize([R_FINANCE])
    rec = get_or_404("VendorInvoice", rid)
    if rec["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "invoice not APPROVED")
    rec["status"] = "PAID"
    bump(rec)
    return ok(pub(rec))


# ===========================================================================
# SatisfactionSurvey
# ===========================================================================
@app.route("/api/satisfaction-surveys", methods=["POST"])
def survey_create():
    authorize([R_DINER])
    body = get_body()
    need(body, "client_site_id", "rating")
    as_str(body["client_site_id"], "client_site_id")
    as_int(body["rating"], "rating", minv=1, maxv=5)
    comment = body.get("comment", "")
    as_str(comment, "comment")
    ssid = body.get("service_session_id")
    coid = body.get("catering_order_id")
    targets = [t for t in (ssid, coid) if t is not None]
    if len(targets) != 1:
        verr("exactly one of service_session_id / catering_order_id must be set")
    site = get_or_404("ClientSite", body["client_site_id"])
    if ssid is not None:
        get_or_404("ServiceSession", ssid)
    if coid is not None:
        get_or_404("CateringOrder", coid)
    rec = {
        "client_site_id": site["id"],
        "service_session_id": ssid,
        "catering_order_id": coid,
        "rating": body["rating"],
        "comment": comment,
    }
    new_immutable(rec)
    DB["SatisfactionSurvey"][rec["id"]] = rec
    return ok(pub(rec), 201)


@app.route("/api/satisfaction-surveys/<rid>", methods=["GET"])
def survey_get(rid):
    authorize([R_DINER, R_CAFE_MGR, R_FINANCE])
    rec = get_or_404("SatisfactionSurvey", rid)
    return ok(pub(rec))


@app.route("/api/satisfaction-surveys", methods=["GET"])
def survey_list():
    authorize([R_CAFE_MGR, R_FINANCE])
    return list_response("SatisfactionSurvey",
                         ["client_site_id", "service_session_id", "catering_order_id"])


# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
