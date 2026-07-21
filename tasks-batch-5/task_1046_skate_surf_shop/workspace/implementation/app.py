"""Skate & Surf Shop API — Python + Flask, in-memory only.

Boots empty on every process start (no seeding). All state lives in module-level
dicts; the per-test-server harness restarts the process before each test.
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"ShopManager", "Associate", "Instructor", "Member"}

PRODUCT_CATEGORIES = {"DECK", "TRUCK", "WHEELS", "BEARINGS", "GRIP", "WAX", "SURFBOARD", "ACCESSORY"}
MEMBER_TIERS = {"STANDARD", "PRO", "TEAM"}
INSTRUCTOR_DISCIPLINES = {"SKATE", "SURF"}
INSTRUCTOR_STATUSES = {"ACTIVE", "INACTIVE"}
BAY_STATUSES = {"OPEN", "CLOSED"}
UNIT_KINDS = {"SKATEBOARD", "SURFBOARD", "WETSUIT"}
UNIT_STATUSES = {"AVAILABLE", "RETIRED"}
SERVICE_TYPES = {"GRIP", "WHEEL", "WAX"}
PAYOUT_METHODS_BUYOUT = {"CASH", "STORE_CREDIT"}

TIER_DISCOUNT = {"STANDARD": Decimal("0.0"), "PRO": Decimal("0.10"), "TEAM": Decimal("0.20")}
SETUP_FEE_CENTS = 2500
CASH_RATE = Decimal("0.50")
CREDIT_RATE = Decimal("0.70")
CONSIGNMENT_FEE = Decimal("0.30")
POINTS_DIVISOR = 100
TIER_MULTIPLIER = {"STANDARD": 1, "PRO": 2, "TEAM": 3}
MAX_POINTS_PER_TXN = 500
SERVICE_LABOR_CENTS = {"GRIP": 800, "WHEEL": 1500, "WAX": 500}
LATE_FEE_PER_DAY_CENTS = 1500
MAX_RENTAL_DAYS = 14
SETUP_BUFFER_MINUTES = 30

# ---------------------------------------------------------------------------
# In-memory store (empty on boot; NO seeding)
# ---------------------------------------------------------------------------
db = {
    "products": {},
    "members": {},
    "instructors": {},
    "service_bays": {},
    "rental_units": {},
    "board_builds": {},
    "service_orders": {},
    "rentals": {},
    "lessons": {},
    "trade_ins": {},
    "special_orders": {},
    "events": {},
    "event_registrations": {},
}

STATE = {"clock": datetime(2026, 7, 1, 0, 0, 0)}  # logical clock, naive UTC


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


NOT_FOUND = {
    "members": "ERR_MEMBER_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "instructors": "ERR_INSTRUCTOR_NOT_FOUND",
    "service_bays": "ERR_BAY_NOT_FOUND",
    "rental_units": "ERR_UNIT_NOT_FOUND",
    "board_builds": "ERR_BUILD_NOT_FOUND",
    "service_orders": "ERR_SERVICE_ORDER_NOT_FOUND",
    "rentals": "ERR_RENTAL_NOT_FOUND",
    "lessons": "ERR_LESSON_NOT_FOUND",
    "trade_ins": "ERR_TRADEIN_NOT_FOUND",
    "special_orders": "ERR_SPECIAL_ORDER_NOT_FOUND",
    "events": "ERR_EVENT_NOT_FOUND",
    "event_registrations": "ERR_REGISTRATION_NOT_FOUND",
}


# ---------------------------------------------------------------------------
# Time / id helpers
# ---------------------------------------------------------------------------
def clock():
    return STATE["clock"]


def fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_stamp():
    return fmt(clock())


def new_id():
    return str(uuid.uuid4())


def request_meta():
    wall = datetime.now(timezone.utc)
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": fmt(wall)}


def base_entity():
    ts = now_stamp()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(ent):
    ent["version"] += 1
    ent["updated_at"] = now_stamp()


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "bad datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "bad datetime")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_date(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "bad date")
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "bad date")


def rhu(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def ok(data, response_type="object", code=200, pagination=None):
    meta = request_meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def err_response(error_id, http_status, message):
    meta = request_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return err_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def handle_405(e):
    return err_response("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed")


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return err_response("ERR_INTERNAL", 500, str(e))


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def require(cond, msg="invalid request"):
    if not cond:
        raise ApiError("ERR_VALIDATION", 422, msg)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def body_json():
    return request.get_json(silent=True) or {}


def req_str(body, field):
    v = body.get(field)
    require(isinstance(v, str) and v != "", f"{field} required")
    return v


def req_int(body, field, min_val=None, gt=None):
    v = body.get(field)
    require(is_int(v), f"{field} required integer")
    if min_val is not None:
        require(v >= min_val, f"{field} must be >= {min_val}")
    if gt is not None:
        require(v > gt, f"{field} must be > {gt}")
    return v


def opt_int(body, field, default=None, min_val=None, gt=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, min_val=min_val, gt=gt)


def req_enum(body, field, allowed):
    v = body.get(field)
    require(isinstance(v, str) and v in allowed, f"{field} invalid")
    return v


def opt_enum(body, field, allowed, default):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def opt_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    require(isinstance(v, bool), f"{field} must be boolean")
    return v


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted")


def lookup(collection, ident):
    if not isinstance(ident, str) or ident not in db[collection]:
        raise ApiError(NOT_FOUND[collection], 404, f"{collection} not found")
    return db[collection][ident]


def exists_fk(collection, ident):
    """Existence check for a *present* body FK; missing handled at validation."""
    if ident is not None:
        if not isinstance(ident, str) or ident not in db[collection]:
            raise ApiError(NOT_FOUND[collection], 404, f"{collection} not found")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def s_product(p):
    return {
        "id": p["id"], "sku": p["sku"], "name": p["name"], "category": p["category"],
        "unit_price_cents": p["unit_price_cents"], "buildable_component": p["buildable_component"],
        "stock_on_hand": p["stock_on_hand"], "stock_reserved": p["stock_reserved"],
        "reorder_threshold": p["reorder_threshold"], "status": p["status"],
        "stock_available": p["stock_on_hand"] - p["stock_reserved"],
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


def s_member(m):
    return {
        "id": m["id"], "email": m["email"], "full_name": m["full_name"], "tier": m["tier"],
        "status": m["status"], "points_balance": m["points_balance"],
        "lifetime_points": m["lifetime_points"], "store_credit_cents": m["store_credit_cents"],
        "created_at": m["created_at"], "updated_at": m["updated_at"], "version": m["version"],
    }


def s_instructor(i):
    return {k: i[k] for k in ("id", "full_name", "discipline", "status", "created_at", "updated_at", "version")}


def s_bay(b):
    return {k: b[k] for k in ("id", "name", "status", "created_at", "updated_at", "version")}


def s_unit(u):
    return {k: u[k] for k in ("id", "name", "kind", "daily_rate_cents", "status", "created_at", "updated_at", "version")}


def s_build(b):
    return {k: b[k] for k in (
        "id", "member_id", "component_lines", "status", "provisional_total_cents",
        "final_total_cents", "reserved_at", "assembled_at", "setup_at", "completed_at",
        "created_at", "updated_at", "version")}


def s_service_order(o):
    return {k: o[k] for k in (
        "id", "member_id", "bay_id", "build_id", "service_type", "parts_lines",
        "slot_start", "slot_end", "status", "labor_total_cents", "parts_total_cents",
        "total_cents", "started_at", "completed_at", "created_at", "updated_at", "version")}


def s_rental(r):
    return {k: r[k] for k in (
        "id", "member_id", "unit_id", "lesson_id", "start_date", "end_date", "deposit_cents",
        "status", "rental_total_cents", "late_fee_cents", "returned_on", "checked_out_at",
        "cancelled_at", "created_at", "updated_at", "version")}


def s_lesson(l):
    return {k: l[k] for k in (
        "id", "member_id", "instructor_id", "discipline", "start_at", "end_at", "fee_cents",
        "status", "confirmed_at", "completed_at", "created_at", "updated_at", "version")}


def s_tradein(t):
    return {k: t[k] for k in (
        "id", "member_id", "description", "status", "appraised_value_cents", "list_price_cents",
        "payout_cents", "payout_method", "appraised_at", "settled_at",
        "created_at", "updated_at", "version")}


def s_special(o):
    return {k: o[k] for k in (
        "id", "member_id", "product_name", "qty", "status", "quoted_price_cents",
        "deposit_cents", "quoted_at", "fulfilled_at", "created_at", "updated_at", "version")}


def s_event(e):
    return {k: e[k] for k in (
        "id", "name", "capacity", "entry_points_cost", "status", "registration_count",
        "created_at", "updated_at", "version")}


def s_reg(r):
    return {k: r[k] for k in (
        "id", "event_id", "member_id", "status", "points_charged",
        "created_at", "updated_at", "version")}


# ---------------------------------------------------------------------------
# Pagination + listing
# ---------------------------------------------------------------------------
def pagination_params():
    q = request.args
    limit_raw = q.get("limit")
    offset_raw = q.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 422, "limit must be an integer")
        limit = max(1, min(100, limit))
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 422, "offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def list_response(items, serializer):
    limit, offset = pagination_params()
    items = sorted(items, key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok([serializer(x) for x in page], "array", 200, pagination=meta)


def filter_by(collection, fields):
    q = request.args
    out = []
    for ent in db[collection].values():
        keep = True
        for field in fields:
            val = q.get(field)
            if val is not None and str(ent.get(field)) != val:
                keep = False
                break
        if keep:
            out.append(ent)
    return out


# ---------------------------------------------------------------------------
# Stock helpers
# ---------------------------------------------------------------------------
def agg_lines(lines):
    m = {}
    for ln in lines:
        m[ln["product_id"]] = m.get(ln["product_id"], 0) + ln["qty"]
    return m


def check_stock(lines):
    for pid, q in agg_lines(lines).items():
        p = db["products"][pid]
        if (p["stock_on_hand"] - p["stock_reserved"]) < q:
            raise ApiError("ERR_INSUFFICIENT_STOCK", 409, "insufficient stock")


def reserve_stock(lines):
    for pid, q in agg_lines(lines).items():
        p = db["products"][pid]
        p["stock_reserved"] += q
        touch(p)


def release_stock(lines):
    for pid, q in agg_lines(lines).items():
        p = db["products"][pid]
        p["stock_reserved"] -= q
        touch(p)


def consume_stock(lines):
    for pid, q in agg_lines(lines).items():
        p = db["products"][pid]
        p["stock_on_hand"] -= q
        p["stock_reserved"] -= q
        touch(p)


def exist_line_products(lines):
    if isinstance(lines, list):
        for ln in lines:
            if isinstance(ln, dict):
                pid = ln.get("product_id")
                if isinstance(pid, str):
                    if pid not in db["products"]:
                        raise ApiError("ERR_PRODUCT_NOT_FOUND", 404, "product not found")


def validate_lines(lines, require_buildable):
    require(isinstance(lines, list) and len(lines) >= 1, "lines required")
    for ln in lines:
        require(isinstance(ln, dict), "line must be object")
        pid = ln.get("product_id")
        qty = ln.get("qty")
        require(isinstance(pid, str) and pid != "", "product_id required")
        require(is_int(qty) and qty > 0, "qty must be > 0")
        p = db["products"][pid]
        if require_buildable:
            require(p["buildable_component"] is True, "product not buildable")


# ---------------------------------------------------------------------------
# Loyalty
# ---------------------------------------------------------------------------
def award_loyalty(member, net_cents, double_points):
    base = net_cents // POINTS_DIVISOR
    mult = TIER_MULTIPLIER[member["tier"]] * (2 if double_points else 1)
    earned = min(base * mult, MAX_POINTS_PER_TXN)
    member["points_balance"] += earned
    member["lifetime_points"] += earned
    touch(member)
    return earned


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------
def cancel_service_order_internal(so):
    if so["status"] in ("SCHEDULED", "IN_PROGRESS"):
        if so["parts_lines"]:
            release_stock(so["parts_lines"])
        so["status"] = "CANCELLED"
        touch(so)


def cancel_build_internal(build):
    st = build["status"]
    if st in ("COMPONENTS_RESERVED", "ASSEMBLED", "SETUP_COMPLETE"):
        release_stock(build["component_lines"])
        for so in db["service_orders"].values():
            if so["build_id"] == build["id"] and so["status"] in ("SCHEDULED", "IN_PROGRESS"):
                cancel_service_order_internal(so)
    build["status"] = "CANCELLED"
    touch(build)


def cancel_registration_internal(reg):
    member = db["members"].get(reg["member_id"])
    if member is not None:
        member["points_balance"] += reg["points_charged"]
        touch(member)
    reg["status"] = "CANCELLED"
    touch(reg)
    event = db["events"].get(reg["event_id"])
    if event is not None:
        event["registration_count"] -= 1


# ===========================================================================
# ROUTES
# ===========================================================================

# ---- Logical clock ----
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    body = body_json()
    iso = req_str(body, "to_iso8601")
    STATE["clock"] = parse_dt(iso)
    return ok({}, "object", 200)


# ---- Products ----
@app.route("/products", methods=["POST"])
def create_product():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    body = body_json()
    sku = req_str(body, "sku")
    name = req_str(body, "name")
    category = req_enum(body, "category", PRODUCT_CATEGORIES)
    unit_price = req_int(body, "unit_price_cents", min_val=0)
    buildable = opt_bool(body, "buildable_component", False)
    stock_on_hand = opt_int(body, "stock_on_hand", default=0, min_val=0)
    reorder = opt_int(body, "reorder_threshold", default=0, min_val=0)
    for p in db["products"].values():
        require(p["sku"] != sku, "sku already exists")
    ent = base_entity()
    ent.update({
        "sku": sku, "name": name, "category": category, "unit_price_cents": unit_price,
        "buildable_component": buildable, "stock_on_hand": stock_on_hand, "stock_reserved": 0,
        "reorder_threshold": reorder, "status": "ACTIVE",
    })
    db["products"][ent["id"]] = ent
    return ok(s_product(ent), "object", 201)


@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    authenticate()
    return ok(s_product(lookup("products", pid)), "object", 200)


@app.route("/products", methods=["GET"])
def list_products():
    authenticate()
    return list_response(filter_by("products", ["category", "status"]), s_product)


@app.route("/products/<pid>", methods=["PATCH"])
def update_product(pid):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    p = lookup("products", pid)
    body = body_json()
    changed = False
    if "unit_price_cents" in body and body.get("unit_price_cents") is not None:
        p["unit_price_cents"] = req_int(body, "unit_price_cents", min_val=0)
        changed = True
    if "status" in body and body.get("status") is not None:
        p["status"] = req_enum(body, "status", {"ACTIVE", "DISCONTINUED"})
        changed = True
    if changed:
        touch(p)
    return ok(s_product(p), "object", 200)


@app.route("/products/<pid>/restock", methods=["POST"])
def restock_product(pid):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    p = lookup("products", pid)
    body = body_json()
    qty = req_int(body, "quantity", gt=0)
    p["stock_on_hand"] += qty
    touch(p)
    return ok(s_product(p), "object", 200)


# ---- Members ----
@app.route("/members", methods=["POST"])
def create_member():
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    body = body_json()
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    tier = opt_enum(body, "tier", MEMBER_TIERS, "STANDARD")
    for m in db["members"].values():
        require(m["email"] != email, "email already exists")
    ent = base_entity()
    ent.update({
        "email": email, "full_name": full_name, "tier": tier, "status": "ACTIVE",
        "points_balance": 0, "lifetime_points": 0, "store_credit_cents": 0,
    })
    db["members"][ent["id"]] = ent
    return ok(s_member(ent), "object", 201)


@app.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    authenticate()
    return ok(s_member(lookup("members", mid)), "object", 200)


@app.route("/members/<mid>/suspend", methods=["POST"])
def suspend_member(mid):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    m = lookup("members", mid)
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "member not ACTIVE")
    m["status"] = "SUSPENDED"
    touch(m)
    for build in list(db["board_builds"].values()):
        if build["member_id"] == mid and build["status"] in (
                "DRAFT", "COMPONENTS_RESERVED", "ASSEMBLED", "SETUP_COMPLETE"):
            cancel_build_internal(build)
    return ok(s_member(m), "object", 200)


@app.route("/members/<mid>/reinstate", methods=["POST"])
def reinstate_member(mid):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    m = lookup("members", mid)
    if m["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "member not SUSPENDED")
    m["status"] = "ACTIVE"
    touch(m)
    return ok(s_member(m), "object", 200)


# ---- Instructors ----
@app.route("/instructors", methods=["POST"])
def create_instructor():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    body = body_json()
    full_name = req_str(body, "full_name")
    discipline = req_enum(body, "discipline", INSTRUCTOR_DISCIPLINES)
    status = opt_enum(body, "status", INSTRUCTOR_STATUSES, "ACTIVE")
    ent = base_entity()
    ent.update({"full_name": full_name, "discipline": discipline, "status": status})
    db["instructors"][ent["id"]] = ent
    return ok(s_instructor(ent), "object", 201)


@app.route("/instructors/<iid>", methods=["GET"])
def get_instructor(iid):
    authenticate()
    return ok(s_instructor(lookup("instructors", iid)), "object", 200)


# ---- Service bays ----
@app.route("/service-bays", methods=["POST"])
def create_bay():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    body = body_json()
    name = req_str(body, "name")
    status = opt_enum(body, "status", BAY_STATUSES, "OPEN")
    ent = base_entity()
    ent.update({"name": name, "status": status})
    db["service_bays"][ent["id"]] = ent
    return ok(s_bay(ent), "object", 201)


@app.route("/service-bays/<bid>", methods=["GET"])
def get_bay(bid):
    authenticate()
    return ok(s_bay(lookup("service_bays", bid)), "object", 200)


# ---- Rental units ----
@app.route("/rental-units", methods=["POST"])
def create_unit():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    body = body_json()
    name = req_str(body, "name")
    kind = req_enum(body, "kind", UNIT_KINDS)
    daily_rate = req_int(body, "daily_rate_cents", min_val=0)
    status = opt_enum(body, "status", UNIT_STATUSES, "AVAILABLE")
    ent = base_entity()
    ent.update({"name": name, "kind": kind, "daily_rate_cents": daily_rate, "status": status})
    db["rental_units"][ent["id"]] = ent
    return ok(s_unit(ent), "object", 201)


@app.route("/rental-units/<uid>", methods=["GET"])
def get_unit(uid):
    authenticate()
    return ok(s_unit(lookup("rental_units", uid)), "object", 200)


# ---- Board builds ----
@app.route("/board-builds", methods=["POST"])
def create_build():
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    body = body_json()
    # existence: member then component products
    exists_fk("members", body.get("member_id"))
    exist_line_products(body.get("component_lines"))
    # validation
    member_id = req_str(body, "member_id")
    lines = body.get("component_lines")
    validate_lines(lines, require_buildable=True)
    norm_lines = [{"product_id": ln["product_id"], "qty": ln["qty"]} for ln in lines]
    ent = base_entity()
    ent.update({
        "member_id": member_id, "component_lines": norm_lines, "status": "DRAFT",
        "provisional_total_cents": None, "final_total_cents": None,
        "reserved_at": None, "assembled_at": None, "setup_at": None, "completed_at": None,
    })
    db["board_builds"][ent["id"]] = ent
    return ok(s_build(ent), "object", 201)


@app.route("/board-builds/<bid>", methods=["GET"])
def get_build(bid):
    authenticate()
    return ok(s_build(lookup("board_builds", bid)), "object", 200)


@app.route("/board-builds", methods=["GET"])
def list_builds():
    authenticate()
    return list_response(filter_by("board_builds", ["member_id", "status"]), s_build)


@app.route("/board-builds/<bid>/reserve", methods=["POST"])
def reserve_build(bid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    build = lookup("board_builds", bid)
    if build["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "build not DRAFT")
    lines = build["component_lines"]
    for ln in lines:
        p = db["products"][ln["product_id"]]
        if p["status"] != "ACTIVE":
            raise ApiError("ERR_PRODUCT_DISCONTINUED", 409, "component discontinued")
    check_stock(lines)
    reserve_stock(lines)
    provisional = sum(db["products"][ln["product_id"]]["unit_price_cents"] * ln["qty"] for ln in lines)
    build["provisional_total_cents"] = provisional
    build["reserved_at"] = now_stamp()
    build["status"] = "COMPONENTS_RESERVED"
    touch(build)
    return ok(s_build(build), "object", 200)


@app.route("/board-builds/<bid>/assemble", methods=["POST"])
def assemble_build(bid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    build = lookup("board_builds", bid)
    if build["status"] != "COMPONENTS_RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409, "build not COMPONENTS_RESERVED")
    build["assembled_at"] = now_stamp()
    build["status"] = "ASSEMBLED"
    touch(build)
    return ok(s_build(build), "object", 200)


@app.route("/board-builds/<bid>/revise", methods=["POST"])
def revise_build(bid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    build = lookup("board_builds", bid)
    if build["status"] != "ASSEMBLED":
        raise ApiError("ERR_INVALID_STATE", 409, "build not ASSEMBLED")
    release_stock(build["component_lines"])
    build["provisional_total_cents"] = None
    build["assembled_at"] = None
    build["status"] = "DRAFT"
    touch(build)
    return ok(s_build(build), "object", 200)


@app.route("/board-builds/<bid>/setup", methods=["POST"])
def setup_build(bid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    build = lookup("board_builds", bid)
    if build["status"] != "ASSEMBLED":
        raise ApiError("ERR_INVALID_STATE", 409, "build not ASSEMBLED")
    member = db["members"][build["member_id"]]
    disc = TIER_DISCOUNT[member["tier"]]
    total = 0
    for ln in build["component_lines"]:
        p = db["products"][ln["product_id"]]
        disc_unit = rhu(Decimal(p["unit_price_cents"]) * (Decimal(1) - disc))
        total += disc_unit * ln["qty"]
    build["final_total_cents"] = total + SETUP_FEE_CENTS
    build["setup_at"] = now_stamp()
    build["status"] = "SETUP_COMPLETE"
    touch(build)
    return ok(s_build(build), "object", 200)


@app.route("/board-builds/<bid>/complete", methods=["POST"])
def complete_build(bid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    build = lookup("board_builds", bid)
    body = body_json()
    if build["status"] != "SETUP_COMPLETE":
        raise ApiError("ERR_INVALID_STATE", 409, "build not SETUP_COMPLETE")
    member = db["members"][build["member_id"]]
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_SUSPENDED", 409, "member suspended")
    double = opt_bool(body, "double_points", False)
    consume_stock(build["component_lines"])
    award_loyalty(member, build["final_total_cents"], double)
    build["completed_at"] = now_stamp()
    build["status"] = "COMPLETED"
    touch(build)
    return ok(s_build(build), "object", 200)


@app.route("/board-builds/<bid>/cancel", methods=["POST"])
def cancel_build(bid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    build = lookup("board_builds", bid)
    if build["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE", 409, "build terminal")
    cancel_build_internal(build)
    return ok(s_build(build), "object", 200)


# ---- Service orders ----
@app.route("/service-orders", methods=["POST"])
def create_service_order():
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    body = body_json()
    # existence: member, bay, build?, parts products
    exists_fk("members", body.get("member_id"))
    exists_fk("service_bays", body.get("bay_id"))
    if body.get("build_id") is not None:
        exists_fk("board_builds", body.get("build_id"))
    exist_line_products(body.get("parts_lines"))
    # validation
    member_id = req_str(body, "member_id")
    bay_id = req_str(body, "bay_id")
    service_type = req_enum(body, "service_type", SERVICE_TYPES)
    slot_start_raw = body.get("slot_start")
    slot_end_raw = body.get("slot_end")
    ss = parse_dt(slot_start_raw)
    se = parse_dt(slot_end_raw)
    require(ss < se, "slot_start must be before slot_end")
    build_id = body.get("build_id")
    if build_id is not None:
        require(isinstance(build_id, str), "build_id invalid")
    parts_lines = body.get("parts_lines")
    if parts_lines is None:
        parts_lines = []
    if parts_lines:
        validate_lines(parts_lines, require_buildable=False)
    norm_parts = [{"product_id": ln["product_id"], "qty": ln["qty"]} for ln in parts_lines]
    # state: bay OPEN
    bay = db["service_bays"][bay_id]
    if bay["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "bay not OPEN")
    # referential: build ready
    if build_id is not None:
        build = db["board_builds"][build_id]
        if build["status"] not in ("SETUP_COMPLETE", "COMPLETED"):
            raise ApiError("ERR_BUILD_NOT_READY", 409, "build not ready")
    # stock
    if norm_parts:
        check_stock(norm_parts)
    # temporal: bay separation buffer
    buffer = timedelta(minutes=SETUP_BUFFER_MINUTES)
    for other in db["service_orders"].values():
        if other["bay_id"] != bay_id:
            continue
        if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        os_ = parse_dt(other["slot_start"])
        oe_ = parse_dt(other["slot_end"])
        if ss < oe_ and os_ < se:
            raise ApiError("ERR_BAY_UNAVAILABLE", 409, "bay unavailable")
        if se <= os_:
            gap = os_ - se
        else:
            gap = ss - oe_
        if gap < buffer:
            raise ApiError("ERR_BAY_UNAVAILABLE", 409, "bay unavailable")
    if norm_parts:
        reserve_stock(norm_parts)
    ent = base_entity()
    ent.update({
        "member_id": member_id, "bay_id": bay_id, "build_id": build_id,
        "service_type": service_type, "parts_lines": norm_parts,
        "slot_start": slot_start_raw, "slot_end": slot_end_raw, "status": "SCHEDULED",
        "labor_total_cents": None, "parts_total_cents": None, "total_cents": None,
        "started_at": None, "completed_at": None,
    })
    db["service_orders"][ent["id"]] = ent
    return ok(s_service_order(ent), "object", 201)


@app.route("/service-orders/<oid>", methods=["GET"])
def get_service_order(oid):
    authenticate()
    return ok(s_service_order(lookup("service_orders", oid)), "object", 200)


@app.route("/service-orders", methods=["GET"])
def list_service_orders():
    authenticate()
    return list_response(filter_by("service_orders", ["member_id", "bay_id", "build_id", "status"]), s_service_order)


@app.route("/service-orders/<oid>/start", methods=["POST"])
def start_service_order(oid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    so = lookup("service_orders", oid)
    if so["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "order not SCHEDULED")
    so["started_at"] = now_stamp()
    so["status"] = "IN_PROGRESS"
    touch(so)
    return ok(s_service_order(so), "object", 200)


@app.route("/service-orders/<oid>/complete", methods=["POST"])
def complete_service_order(oid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    so = lookup("service_orders", oid)
    body = body_json()
    if so["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "order not IN_PROGRESS")
    double = opt_bool(body, "double_points", False)
    labor = SERVICE_LABOR_CENTS[so["service_type"]]
    parts_total = sum(db["products"][ln["product_id"]]["unit_price_cents"] * ln["qty"] for ln in so["parts_lines"])
    so["labor_total_cents"] = labor
    so["parts_total_cents"] = parts_total
    so["total_cents"] = labor + parts_total
    if so["parts_lines"]:
        consume_stock(so["parts_lines"])
    member = db["members"][so["member_id"]]
    award_loyalty(member, so["total_cents"], double)
    so["completed_at"] = now_stamp()
    so["status"] = "DONE"
    touch(so)
    return ok(s_service_order(so), "object", 200)


@app.route("/service-orders/<oid>/cancel", methods=["POST"])
def cancel_service_order(oid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    so = lookup("service_orders", oid)
    if so["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", 409, "order terminal")
    cancel_service_order_internal(so)
    return ok(s_service_order(so), "object", 200)


# ---- Rentals ----
@app.route("/rentals", methods=["POST"])
def create_rental():
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    body = body_json()
    exists_fk("members", body.get("member_id"))
    exists_fk("rental_units", body.get("unit_id"))
    if body.get("lesson_id") is not None:
        exists_fk("lessons", body.get("lesson_id"))
    member_id = req_str(body, "member_id")
    unit_id = req_str(body, "unit_id")
    start_raw = body.get("start_date")
    end_raw = body.get("end_date")
    sd = parse_date(start_raw)
    ed = parse_date(end_raw)
    require(sd <= ed, "start_date must be <= end_date")
    lesson_id = body.get("lesson_id")
    if lesson_id is not None:
        require(isinstance(lesson_id, str), "lesson_id invalid")
    deposit = opt_int(body, "deposit_cents", default=0, min_val=0)
    unit = db["rental_units"][unit_id]
    if unit["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "unit not AVAILABLE")
    duration = (ed - sd).days + 1
    if duration > MAX_RENTAL_DAYS:
        raise ApiError("ERR_RENTAL_TOO_LONG", 422, "rental too long")
    for other in db["rentals"].values():
        if other["unit_id"] != unit_id:
            continue
        if other["status"] not in ("RESERVED", "CHECKED_OUT"):
            continue
        osd = parse_date(other["start_date"])
        oed = parse_date(other["end_date"])
        if sd <= oed and osd <= ed:
            raise ApiError("ERR_UNIT_UNAVAILABLE", 409, "unit unavailable")
    ent = base_entity()
    ent.update({
        "member_id": member_id, "unit_id": unit_id, "lesson_id": lesson_id,
        "start_date": start_raw, "end_date": end_raw, "deposit_cents": deposit,
        "status": "RESERVED", "rental_total_cents": None, "late_fee_cents": None,
        "returned_on": None, "checked_out_at": None, "cancelled_at": None,
    })
    db["rentals"][ent["id"]] = ent
    return ok(s_rental(ent), "object", 201)


@app.route("/rentals/<rid>", methods=["GET"])
def get_rental(rid):
    authenticate()
    return ok(s_rental(lookup("rentals", rid)), "object", 200)


@app.route("/rentals", methods=["GET"])
def list_rentals():
    authenticate()
    return list_response(filter_by("rentals", ["member_id", "unit_id", "lesson_id", "status"]), s_rental)


@app.route("/rentals/<rid>/checkout", methods=["POST"])
def checkout_rental(rid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    r = lookup("rentals", rid)
    if r["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409, "rental not RESERVED")
    r["checked_out_at"] = now_stamp()
    r["status"] = "CHECKED_OUT"
    touch(r)
    return ok(s_rental(r), "object", 200)


@app.route("/rentals/<rid>/return", methods=["POST"])
def return_rental(rid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    r = lookup("rentals", rid)
    body = body_json()
    if r["status"] != "CHECKED_OUT":
        raise ApiError("ERR_INVALID_STATE", 409, "rental not CHECKED_OUT")
    double = opt_bool(body, "double_points", False)
    unit = db["rental_units"][r["unit_id"]]
    sd = parse_date(r["start_date"])
    ed = parse_date(r["end_date"])
    duration = (ed - sd).days + 1
    rental_total = unit["daily_rate_cents"] * duration
    current_date = clock().date()
    late_days = max(0, (current_date - ed).days)
    late_fee = late_days * LATE_FEE_PER_DAY_CENTS
    r["rental_total_cents"] = rental_total
    r["late_fee_cents"] = late_fee
    r["returned_on"] = current_date.strftime("%Y-%m-%d")
    r["status"] = "RETURNED"
    member = db["members"][r["member_id"]]
    award_loyalty(member, rental_total + late_fee, double)
    touch(r)
    return ok(s_rental(r), "object", 200)


@app.route("/rentals/<rid>/cancel", methods=["POST"])
def cancel_rental(rid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    r = lookup("rentals", rid)
    if r["status"] not in ("RESERVED", "CHECKED_OUT"):
        raise ApiError("ERR_INVALID_STATE", 409, "rental terminal")
    r["cancelled_at"] = now_stamp()
    r["status"] = "CANCELLED"
    touch(r)
    return ok(s_rental(r), "object", 200)


# ---- Lessons ----
@app.route("/lessons", methods=["POST"])
def create_lesson():
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    body = body_json()
    exists_fk("members", body.get("member_id"))
    exists_fk("instructors", body.get("instructor_id"))
    member_id = req_str(body, "member_id")
    instructor_id = req_str(body, "instructor_id")
    discipline = req_enum(body, "discipline", INSTRUCTOR_DISCIPLINES)
    start_raw = body.get("start_at")
    end_raw = body.get("end_at")
    sa = parse_dt(start_raw)
    ea = parse_dt(end_raw)
    require(sa < ea, "start_at must be before end_at")
    fee = req_int(body, "fee_cents", min_val=0)
    instructor = db["instructors"][instructor_id]
    if instructor["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "instructor not ACTIVE")
    for other in db["lessons"].values():
        if other["instructor_id"] != instructor_id:
            continue
        if other["status"] not in ("BOOKED", "CONFIRMED"):
            continue
        osa = parse_dt(other["start_at"])
        oea = parse_dt(other["end_at"])
        if sa < oea and osa < ea:
            raise ApiError("ERR_INSTRUCTOR_UNAVAILABLE", 409, "instructor unavailable")
    ent = base_entity()
    ent.update({
        "member_id": member_id, "instructor_id": instructor_id, "discipline": discipline,
        "start_at": start_raw, "end_at": end_raw, "fee_cents": fee, "status": "BOOKED",
        "confirmed_at": None, "completed_at": None,
    })
    db["lessons"][ent["id"]] = ent
    return ok(s_lesson(ent), "object", 201)


@app.route("/lessons/<lid>", methods=["GET"])
def get_lesson(lid):
    authenticate()
    return ok(s_lesson(lookup("lessons", lid)), "object", 200)


@app.route("/lessons", methods=["GET"])
def list_lessons():
    authenticate()
    return list_response(filter_by("lessons", ["member_id", "instructor_id", "status"]), s_lesson)


def _lesson_owner_check(role, uid, lesson):
    if role == "Instructor" and lesson["instructor_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not owner")


@app.route("/lessons/<lid>/confirm", methods=["POST"])
def confirm_lesson(lid):
    uid, role = authenticate()
    require_role(role, {"ShopManager", "Instructor"})
    lesson = lookup("lessons", lid)
    _lesson_owner_check(role, uid, lesson)
    if lesson["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409, "lesson not BOOKED")
    for r in db["rentals"].values():
        if r["lesson_id"] == lid and r["status"] not in ("RESERVED", "CHECKED_OUT"):
            raise ApiError("ERR_RENTAL_NOT_READY", 409, "linked rental not ready")
    lesson["confirmed_at"] = now_stamp()
    lesson["status"] = "CONFIRMED"
    touch(lesson)
    return ok(s_lesson(lesson), "object", 200)


@app.route("/lessons/<lid>/complete", methods=["POST"])
def complete_lesson(lid):
    uid, role = authenticate()
    require_role(role, {"ShopManager", "Instructor"})
    lesson = lookup("lessons", lid)
    _lesson_owner_check(role, uid, lesson)
    body = body_json()
    if lesson["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "lesson not CONFIRMED")
    double = opt_bool(body, "double_points", False)
    member = db["members"][lesson["member_id"]]
    award_loyalty(member, lesson["fee_cents"], double)
    lesson["completed_at"] = now_stamp()
    lesson["status"] = "COMPLETED"
    touch(lesson)
    return ok(s_lesson(lesson), "object", 200)


@app.route("/lessons/<lid>/cancel", methods=["POST"])
def cancel_lesson(lid):
    uid, role = authenticate()
    require_role(role, {"ShopManager", "Instructor"})
    lesson = lookup("lessons", lid)
    _lesson_owner_check(role, uid, lesson)
    if lesson["status"] not in ("BOOKED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "lesson terminal")
    for r in db["rentals"].values():
        if r["lesson_id"] == lid and r["status"] in ("RESERVED", "CHECKED_OUT"):
            r["cancelled_at"] = now_stamp()
            r["status"] = "CANCELLED"
            touch(r)
    lesson["status"] = "CANCELLED"
    touch(lesson)
    return ok(s_lesson(lesson), "object", 200)


# ---- Trade-ins ----
@app.route("/trade-ins", methods=["POST"])
def create_tradein():
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    body = body_json()
    exists_fk("members", body.get("member_id"))
    member_id = req_str(body, "member_id")
    description = req_str(body, "description")
    ent = base_entity()
    ent.update({
        "member_id": member_id, "description": description, "status": "RECEIVED",
        "appraised_value_cents": None, "list_price_cents": None, "payout_cents": None,
        "payout_method": None, "appraised_at": None, "settled_at": None,
    })
    db["trade_ins"][ent["id"]] = ent
    return ok(s_tradein(ent), "object", 201)


@app.route("/trade-ins/<tid>", methods=["GET"])
def get_tradein(tid):
    authenticate()
    return ok(s_tradein(lookup("trade_ins", tid)), "object", 200)


@app.route("/trade-ins", methods=["GET"])
def list_tradeins():
    authenticate()
    return list_response(filter_by("trade_ins", ["member_id", "status"]), s_tradein)


@app.route("/trade-ins/<tid>/appraise", methods=["POST"])
def appraise_tradein(tid):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    t = lookup("trade_ins", tid)
    body = body_json()
    value = req_int(body, "appraised_value_cents", min_val=0)
    if t["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", 409, "trade-in not RECEIVED")
    t["appraised_value_cents"] = value
    t["appraised_at"] = now_stamp()
    t["status"] = "APPRAISED"
    touch(t)
    return ok(s_tradein(t), "object", 200)


@app.route("/trade-ins/<tid>/buyout", methods=["POST"])
def buyout_tradein(tid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    t = lookup("trade_ins", tid)
    body = body_json()
    method = req_enum(body, "payout_method", PAYOUT_METHODS_BUYOUT)
    if t["status"] != "APPRAISED":
        raise ApiError("ERR_INVALID_STATE", 409, "trade-in not APPRAISED")
    if method == "CASH":
        payout = rhu(Decimal(t["appraised_value_cents"]) * CASH_RATE)
    else:
        payout = rhu(Decimal(t["appraised_value_cents"]) * CREDIT_RATE)
    t["payout_cents"] = payout
    t["payout_method"] = method
    if method == "STORE_CREDIT":
        member = db["members"][t["member_id"]]
        member["store_credit_cents"] += payout
        touch(member)
    t["settled_at"] = now_stamp()
    t["status"] = "CASH_SETTLED"
    touch(t)
    return ok(s_tradein(t), "object", 200)


@app.route("/trade-ins/<tid>/list", methods=["POST"])
def list_tradein(tid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    t = lookup("trade_ins", tid)
    body = body_json()
    price = req_int(body, "list_price_cents", min_val=0)
    if t["status"] != "APPRAISED":
        raise ApiError("ERR_INVALID_STATE", 409, "trade-in not APPRAISED")
    t["list_price_cents"] = price
    t["status"] = "LISTED"
    touch(t)
    return ok(s_tradein(t), "object", 200)


@app.route("/trade-ins/<tid>/sell", methods=["POST"])
def sell_tradein(tid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    t = lookup("trade_ins", tid)
    if t["status"] != "LISTED":
        raise ApiError("ERR_INVALID_STATE", 409, "trade-in not LISTED")
    payout = rhu(Decimal(t["list_price_cents"]) * (Decimal(1) - CONSIGNMENT_FEE))
    t["payout_cents"] = payout
    t["payout_method"] = "CONSIGNMENT"
    member = db["members"][t["member_id"]]
    member["store_credit_cents"] += payout
    touch(member)
    t["settled_at"] = now_stamp()
    t["status"] = "SOLD"
    touch(t)
    return ok(s_tradein(t), "object", 200)


@app.route("/trade-ins/<tid>/return", methods=["POST"])
def return_tradein(tid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    t = lookup("trade_ins", tid)
    if t["status"] not in ("RECEIVED", "APPRAISED", "LISTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "trade-in not returnable")
    if t["status"] == "LISTED":
        t["list_price_cents"] = None
    t["status"] = "RETURNED"
    touch(t)
    return ok(s_tradein(t), "object", 200)


# ---- Special orders ----
@app.route("/special-orders", methods=["POST"])
def create_special():
    uid, role = authenticate()
    require_role(role, {"ShopManager", "Associate", "Member"})
    body = body_json()
    if role == "Member" and body.get("member_id") != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not owner")
    exists_fk("members", body.get("member_id"))
    member_id = req_str(body, "member_id")
    product_name = req_str(body, "product_name")
    qty = req_int(body, "qty", gt=0)
    ent = base_entity()
    ent.update({
        "member_id": member_id, "product_name": product_name, "qty": qty, "status": "REQUESTED",
        "quoted_price_cents": None, "deposit_cents": None, "quoted_at": None, "fulfilled_at": None,
    })
    db["special_orders"][ent["id"]] = ent
    return ok(s_special(ent), "object", 201)


@app.route("/special-orders/<sid>", methods=["GET"])
def get_special(sid):
    authenticate()
    return ok(s_special(lookup("special_orders", sid)), "object", 200)


@app.route("/special-orders", methods=["GET"])
def list_specials():
    authenticate()
    return list_response(filter_by("special_orders", ["member_id", "status"]), s_special)


@app.route("/special-orders/<sid>/quote", methods=["POST"])
def quote_special(sid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    so = lookup("special_orders", sid)
    body = body_json()
    price = req_int(body, "quoted_price_cents", min_val=0)
    expected = req_int(body, "expected_special_order_version")
    if so["status"] not in ("REQUESTED", "QUOTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "order not quotable")
    if expected != so["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale version")
    so["quoted_price_cents"] = price
    so["quoted_at"] = now_stamp()
    so["status"] = "QUOTED"
    touch(so)
    return ok(s_special(so), "object", 200)


@app.route("/special-orders/<sid>/deposit", methods=["POST"])
def deposit_special(sid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    so = lookup("special_orders", sid)
    body = body_json()
    deposit = req_int(body, "deposit_cents", min_val=0)
    if so["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", 409, "order not QUOTED")
    so["deposit_cents"] = deposit
    so["status"] = "DEPOSIT_PAID"
    touch(so)
    return ok(s_special(so), "object", 200)


@app.route("/special-orders/<sid>/fulfill", methods=["POST"])
def fulfill_special(sid):
    _, role = authenticate()
    require_role(role, {"ShopManager", "Associate"})
    so = lookup("special_orders", sid)
    body = body_json()
    if so["status"] != "DEPOSIT_PAID":
        raise ApiError("ERR_INVALID_STATE", 409, "order not DEPOSIT_PAID")
    double = opt_bool(body, "double_points", False)
    member = db["members"][so["member_id"]]
    award_loyalty(member, so["quoted_price_cents"], double)
    so["fulfilled_at"] = now_stamp()
    so["status"] = "FULFILLED"
    touch(so)
    return ok(s_special(so), "object", 200)


@app.route("/special-orders/<sid>/cancel", methods=["POST"])
def cancel_special(sid):
    uid, role = authenticate()
    require_role(role, {"ShopManager", "Associate", "Member"})
    so = lookup("special_orders", sid)
    if role == "Member" and so["member_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not owner")
    if so["status"] not in ("REQUESTED", "QUOTED", "DEPOSIT_PAID"):
        raise ApiError("ERR_INVALID_STATE", 409, "order terminal")
    so["status"] = "CANCELLED"
    touch(so)
    return ok(s_special(so), "object", 200)


# ---- Events ----
@app.route("/events", methods=["POST"])
def create_event():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    body = body_json()
    name = req_str(body, "name")
    capacity = req_int(body, "capacity", gt=0)
    entry_cost = opt_int(body, "entry_points_cost", default=0, min_val=0)
    ent = base_entity()
    ent.update({
        "name": name, "capacity": capacity, "entry_points_cost": entry_cost,
        "status": "OPEN", "registration_count": 0,
    })
    db["events"][ent["id"]] = ent
    return ok(s_event(ent), "object", 201)


@app.route("/events/<eid>", methods=["GET"])
def get_event(eid):
    authenticate()
    return ok(s_event(lookup("events", eid)), "object", 200)


@app.route("/events/<eid>/close", methods=["POST"])
def close_event(eid):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    event = lookup("events", eid)
    if event["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "event not OPEN")
    event["status"] = "CLOSED"
    for reg in list(db["event_registrations"].values()):
        if reg["event_id"] == eid and reg["status"] == "REGISTERED":
            cancel_registration_internal(reg)
    touch(event)
    return ok(s_event(event), "object", 200)


@app.route("/events/<eid>/register", methods=["POST"])
def register_event(eid):
    uid, role = authenticate()
    require_role(role, {"ShopManager", "Associate", "Member"})
    body = body_json()
    if role == "Member" and body.get("member_id") != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not owner")
    event = lookup("events", eid)
    exists_fk("members", body.get("member_id"))
    member_id = req_str(body, "member_id")
    member = db["members"][member_id]
    # state / precedence order per PRD 2.5
    if event["status"] != "OPEN":
        raise ApiError("ERR_EVENT_CLOSED", 409, "event closed")
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_SUSPENDED", 409, "member suspended")
    for reg in db["event_registrations"].values():
        if reg["event_id"] == eid and reg["member_id"] == member_id and reg["status"] == "REGISTERED":
            raise ApiError("ERR_DUPLICATE_REGISTRATION", 409, "duplicate registration")
    if event["registration_count"] >= event["capacity"]:
        raise ApiError("ERR_EVENT_FULL", 409, "event full")
    if member["points_balance"] < event["entry_points_cost"]:
        raise ApiError("ERR_INSUFFICIENT_POINTS", 402, "insufficient points")
    points = event["entry_points_cost"]
    ent = base_entity()
    ent.update({
        "event_id": eid, "member_id": member_id, "status": "REGISTERED", "points_charged": points,
    })
    db["event_registrations"][ent["id"]] = ent
    member["points_balance"] -= points
    touch(member)
    event["registration_count"] += 1
    touch(event)
    return ok(s_reg(ent), "object", 201)


@app.route("/event-registrations/<rid>", methods=["GET"])
def get_registration(rid):
    authenticate()
    return ok(s_reg(lookup("event_registrations", rid)), "object", 200)


@app.route("/event-registrations", methods=["GET"])
def list_registrations():
    authenticate()
    return list_response(filter_by("event_registrations", ["event_id", "member_id", "status"]), s_reg)


@app.route("/event-registrations/<rid>/cancel", methods=["POST"])
def cancel_registration(rid):
    uid, role = authenticate()
    require_role(role, {"ShopManager", "Member"})
    reg = lookup("event_registrations", rid)
    if role == "Member" and reg["member_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not owner")
    if reg["status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE", 409, "registration not REGISTERED")
    member = db["members"].get(reg["member_id"])
    if member is not None:
        member["points_balance"] += reg["points_charged"]
        touch(member)
    reg["status"] = "CANCELLED"
    touch(reg)
    event = db["events"].get(reg["event_id"])
    if event is not None:
        event["registration_count"] -= 1
        touch(event)
    return ok(s_reg(reg), "object", 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
