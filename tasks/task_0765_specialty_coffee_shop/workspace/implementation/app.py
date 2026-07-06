"""Specialty Coffee Shop & Multi-Roast Cafe API.

In-memory REST API implementing the PRD contract. Storage is process-local
Python dicts keyed by id; every fresh boot starts empty (no seeding).
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD §1.3 calculations)
# ---------------------------------------------------------------------------
SIZE_MULT = {"SMALL": "1.0", "MEDIUM": "1.25", "LARGE": "1.5"}
FEE_WAIVE_SUBTOTAL_CENTS = 2000
SMALL_ORDER_FEE_CENTS = 50
CENTS_PER_POINT = 5
TIER_DISCOUNT_RATE = {"BRONZE": "0.0", "SILVER": "0.05", "GOLD": "0.10"}
EARN_DIVISOR_CENTS = 100
SILVER_MIN = 500
GOLD_MIN = 1000
CALIBRATION_SHOT_LIMIT = 4
DRIFT_PER_SHOT_PCT = 0.1
PER_HEAD_CENTS = 1500
DEPOSIT_RATE = "0.25"
PRICE_PER_BAG_CENTS = 1800  # standard per-bag retail price (subscription base)

ROLES = {"Manager", "Barista", "Customer"}

ROAST_LEVELS = {"LIGHT", "MEDIUM", "DARK"}
MODIFIER_GROUPS = {"MILK", "SHOT", "SYRUP"}
MENU_CATEGORIES = {"BEVERAGE", "FOOD", "RETAIL_BAG"}
SIZES = {"SMALL", "MEDIUM", "LARGE"}
EQUIPMENT_TYPES = {"ESPRESSO", "BATCH_BREW", "GRINDER"}
REQ_EQUIPMENT_TYPES = {"ESPRESSO", "BATCH_BREW", "GRINDER", "NONE"}
MAINT_KINDS = {"CALIBRATION", "REPAIR", "CLEANING"}
STATION_ROLES = {"ESPRESSO", "BAR", "CATERING"}
BARISTA_STATUSES = {"ACTIVE", "ON_LEAVE"}
MEMBER_STATUSES = {"ACTIVE", "SUSPENDED"}
CHANNELS = {"MOBILE_APP", "IN_STORE"}
FREQUENCIES = {"WEEKLY", "BIWEEKLY", "MONTHLY"}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "bean_lots": {},
    "modifiers": {},
    "menu_items": {},
    "equipment": {},
    "maintenance_windows": {},
    "baristas": {},
    "members": {},
    "orders": {},
    "subscriptions": {},
    "catering_events": {},
    "daily_reconciliations": {},
}
_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def new_id():
    return str(uuid.uuid4())


def rhu(amount, rate_str):
    """round_half_up of amount * rate to whole integer cents."""
    return int((Decimal(amount) * Decimal(rate_str)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def base_record():
    ts = _now_ts()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    rec["updated_at"] = _now_ts()
    rec["version"] += 1


def parse_dt(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test on parsed datetimes."""
    if None in (a_start, a_end, b_start, b_end):
        return False
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def meta(extra=None):
    m = {"api_request_id": req_id(), "api_request_timestamp": _now_ts()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, rtype="object", pagination=None):
    return jsonify({"meta": meta(pagination), "response_type": rtype, "data": data}), status


def ok_list(items, pagination):
    return jsonify({"meta": meta(pagination), "response_type": "array", "data": items}), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed."},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers.")
    return uid, role


def auth(allowed_roles):
    uid, role = authenticate()
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")
    # Roster resolution for entity-backed roles.
    if role == "Barista" and uid not in DB["baristas"]:
        raise err("ERR_ROSTER_MISMATCH", 403, "Barista identity does not resolve.")
    if role == "Customer" and uid not in DB["members"]:
        raise err("ERR_ROSTER_MISMATCH", 403, "Customer identity does not resolve.")
    return uid, role


def check_owner(role, uid, member_id):
    if role == "Customer" and member_id != uid:
        raise err("ERR_NOT_OWNER", 403, "Customer may only act on own resources.")


def body_json():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise err("ERR_VALIDATION", 422, "Request body must be a JSON object.")
    return b


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", 422, f"Missing required field: {field}.")
    return body[field]


def opt_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_VALIDATION", 422, f"Invalid value for {field}.")
    return value


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def query_pagination():
    def to_int(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default
    limit = to_int("limit", 10)
    offset = to_int("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records, serialize):
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    limit, offset = query_pagination()
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok_list([serialize(r) for r in page], pagination)


# ---------------------------------------------------------------------------
# Derived / computed helpers
# ---------------------------------------------------------------------------
def on_hand(lot):
    return lot["received_grams"] - lot["consumed_grams"] - lot["waste_grams_total"]


def tier_of(lifetime):
    if lifetime >= GOLD_MIN:
        return "GOLD"
    if lifetime >= SILVER_MIN:
        return "SILVER"
    return "BRONZE"


def active_lot_for_origin(origin):
    for lot in DB["bean_lots"].values():
        if lot["origin"] == origin and lot["rotation_status"] == "ACTIVE":
            return lot
    return None


def operational_equipment_of_type(eq_type):
    for eq in DB["equipment"].values():
        if eq["equipment_type"] == eq_type and eq["status"] == "OPERATIONAL":
            return eq
    return None


def menu_availability(mi):
    req_type = mi["required_equipment_type"]
    if req_type in EQUIPMENT_TYPES:
        if operational_equipment_of_type(req_type) is None:
            return "UNAVAILABLE"
    if mi["origin_required"]:
        lot = active_lot_for_origin(mi["bean_origin"])
        if lot is None or on_hand(lot) <= 0:
            return "UNAVAILABLE"
    return "AVAILABLE"


def deplete_and_promote(lot):
    """ACTIVE lot reached 0 -> DEPLETED; auto-activate oldest RESERVE of origin."""
    lot["rotation_status"] = "DEPLETED"
    touch(lot)
    reserves = [
        l for l in DB["bean_lots"].values()
        if l["origin"] == lot["origin"] and l["rotation_status"] == "RESERVE"
    ]
    if reserves:
        oldest = min(reserves, key=lambda l: (l["created_at"], l["_seq"]))
        oldest["rotation_status"] = "ACTIVE"
        touch(oldest)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def s_bean_lot(r):
    oh = on_hand(r)
    d = common(r)
    d.update({
        "origin": r["origin"],
        "roast_level": r["roast_level"],
        "received_grams": r["received_grams"],
        "consumed_grams": r["consumed_grams"],
        "waste_grams_total": r["waste_grams_total"],
        "on_hand_grams": oh,
        "par_grams": r["par_grams"],
        "price_per_gram_cents": r["price_per_gram_cents"],
        "rotation_status": r["rotation_status"],
        "reorder_needed": oh <= r["par_grams"],
    })
    return d


def s_modifier(r):
    d = common(r)
    d.update({
        "name": r["name"],
        "modifier_group": r["modifier_group"],
        "surcharge_cents": r["surcharge_cents"],
        "extra_bean_grams": r["extra_bean_grams"],
    })
    return d


def s_menu_item(r):
    d = common(r)
    d.update({
        "name": r["name"],
        "category": r["category"],
        "base_price_cents": r["base_price_cents"],
        "size": r["size"],
        "required_equipment_type": r["required_equipment_type"],
        "bean_grams": r["bean_grams"],
        "origin_required": r["origin_required"],
        "bean_origin": r["bean_origin"],
        "availability": menu_availability(r),
    })
    return d


def s_equipment(r):
    shots = r["shots_since_calibration"]
    d = common(r)
    d.update({
        "name": r["name"],
        "equipment_type": r["equipment_type"],
        "status": r["status"],
        "shots_since_calibration": shots,
        "calibration_drift_pct": round(shots * DRIFT_PER_SHOT_PCT, 4),
        "needs_calibration": shots >= CALIBRATION_SHOT_LIMIT,
        "last_calibrated_at": r["last_calibrated_at"],
    })
    return d


def s_maint(r):
    d = common(r)
    d.update({
        "equipment_id": r["equipment_id"],
        "start_at": r["start_at"],
        "end_at": r["end_at"],
        "kind": r["kind"],
        "status": r["status"],
    })
    return d


def s_barista(r):
    d = common(r)
    d.update({"name": r["name"], "station_role": r["station_role"], "status": r["status"]})
    return d


def s_member(r):
    d = common(r)
    d.update({
        "email": r["email"],
        "full_name": r["full_name"],
        "status": r["status"],
        "points_balance": r["points_balance"],
        "lifetime_points": r["lifetime_points"],
        "tier": tier_of(r["lifetime_points"]),
    })
    return d


def s_order(r):
    d = common(r)
    d.update({
        "member_id": r["member_id"],
        "channel": r["channel"],
        "lines": [
            {
                "menu_item_id": ln["menu_item_id"],
                "quantity": ln["quantity"],
                "modifier_ids": ln["modifier_ids"],
                "line_price_cents": ln["line_price_cents"],
                "line_bean_grams": ln["line_bean_grams"],
            }
            for ln in r["lines"]
        ],
        "points_redeemed": r["points_redeemed"],
        "payment_status": r["payment_status"],
        "fulfillment_status": r["fulfillment_status"],
        "subtotal_cents": r["subtotal_cents"],
        "service_fee_cents": r["service_fee_cents"],
        "discount_cents": r["discount_cents"],
        "total_cents": r["total_cents"],
        "points_earned_provisional": r["points_earned_provisional"],
        "points_earned_final": r["points_earned_final"],
    })
    return d


def s_subscription(r):
    d = common(r)
    d.update({
        "member_id": r["member_id"],
        "bean_origin": r["bean_origin"],
        "frequency": r["frequency"],
        "bags_per_cycle": r["bags_per_cycle"],
        "next_ship_at": r["next_ship_at"],
        "price_per_cycle_cents": r["price_per_cycle_cents"],
        "status": r["status"],
    })
    return d


def s_catering(r):
    d = common(r)
    d.update({
        "member_id": r["member_id"],
        "client_name": r["client_name"],
        "assigned_equipment_id": r["assigned_equipment_id"],
        "assigned_barista_id": r["assigned_barista_id"],
        "scheduled_start": r["scheduled_start"],
        "scheduled_end": r["scheduled_end"],
        "headcount": r["headcount"],
        "travel_fee_cents": r["travel_fee_cents"],
        "quoted_total_cents": r["quoted_total_cents"],
        "deposit_cents": r["deposit_cents"],
        "status": r["status"],
    })
    return d


def s_recon(r):
    d = common(r)
    d.update({
        "business_date": r["business_date"],
        "bean_lot_id": r["bean_lot_id"],
        "status": r["status"],
        "opening_bean_on_hand_grams": r["opening_bean_on_hand_grams"],
        "opening_waste_grams": r["opening_waste_grams"],
        "counted_revenue_cents": r["counted_revenue_cents"],
        "counted_bean_on_hand_grams": r["counted_bean_on_hand_grams"],
        "expected_revenue_cents": r["expected_revenue_cents"],
        "revenue_variance_cents": r["revenue_variance_cents"],
        "ledger_usage_grams": r["ledger_usage_grams"],
        "logged_waste_grams": r["logged_waste_grams"],
        "expected_usage_grams": r["expected_usage_grams"],
        "shrink_grams": r["shrink_grams"],
    })
    return d


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def get_or_404(coll, rid):
    rec = DB[coll].get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", 404, "Referenced resource does not exist.")
    return rec


# ===========================================================================
# BeanLot
# ===========================================================================
@app.route("/bean-lots", methods=["POST"])
def create_bean_lot():
    auth(["Manager"])
    body = body_json()
    origin = require(body, "origin")
    roast_level = opt_enum(require(body, "roast_level"), ROAST_LEVELS, "roast_level")
    received = require(body, "received_grams")
    par = require(body, "par_grams")
    ppg = require(body, "price_per_gram_cents")
    if not is_int(received) or received <= 0:
        raise err("ERR_VALIDATION", 422, "received_grams must be a positive integer.")
    if not is_int(par) or par < 0:
        raise err("ERR_VALIDATION", 422, "par_grams must be >= 0.")
    if not is_int(ppg) or ppg <= 0:
        raise err("ERR_VALIDATION", 422, "price_per_gram_cents must be > 0.")
    rec = base_record()
    rec.update({
        "origin": origin,
        "roast_level": roast_level,
        "received_grams": received,
        "consumed_grams": 0,
        "waste_grams_total": 0,
        "par_grams": par,
        "price_per_gram_cents": ppg,
        "rotation_status": "RESERVE",
    })
    DB["bean_lots"][rec["id"]] = rec
    return ok(s_bean_lot(rec), 201)


@app.route("/bean-lots/<rid>", methods=["GET"])
def get_bean_lot(rid):
    auth(["Manager", "Barista"])
    return ok(s_bean_lot(get_or_404("bean_lots", rid)))


@app.route("/bean-lots", methods=["GET"])
def list_bean_lots():
    auth(["Manager", "Barista"])
    origin = request.args.get("origin")
    status = request.args.get("rotation_status")
    recs = [
        r for r in DB["bean_lots"].values()
        if (origin is None or r["origin"] == origin)
        and (status is None or r["rotation_status"] == status)
    ]
    return paginate(recs, s_bean_lot)


@app.route("/bean-lots/<rid>/activate", methods=["POST"])
def activate_bean_lot(rid):
    auth(["Manager"])
    lot = get_or_404("bean_lots", rid)
    if lot["rotation_status"] == "DEPLETED":
        raise err("ERR_LOT_DEPLETED", 409, "Cannot operate on a depleted lot.")
    if lot["rotation_status"] == "ACTIVE":
        raise err("ERR_ALREADY_ACTIVE", 409, "Lot is already active.")
    if on_hand(lot) <= 0:
        raise err("ERR_INVALID_STATE", 409, "Lot has no on-hand grams to activate.")
    incumbent = active_lot_for_origin(lot["origin"])
    if incumbent is not None and incumbent["id"] != lot["id"]:
        incumbent["rotation_status"] = "RESERVE"
        touch(incumbent)
    lot["rotation_status"] = "ACTIVE"
    touch(lot)
    return ok(s_bean_lot(lot))


@app.route("/bean-lots/<rid>/log-waste", methods=["POST"])
def log_waste(rid):
    auth(["Manager", "Barista"])
    lot = get_or_404("bean_lots", rid)
    body = body_json()
    grams = require(body, "grams")
    require(body, "reason")
    if lot["rotation_status"] == "DEPLETED":
        raise err("ERR_LOT_DEPLETED", 409, "Cannot log waste on a depleted lot.")
    if not is_int(grams) or grams <= 0 or grams > on_hand(lot):
        raise err("ERR_INVALID_WASTE", 422, "grams must be a positive integer not exceeding on_hand_grams.")
    lot["waste_grams_total"] += grams
    touch(lot)
    if lot["rotation_status"] == "ACTIVE" and on_hand(lot) == 0:
        deplete_and_promote(lot)
    return ok(s_bean_lot(lot))


# ===========================================================================
# Modifier
# ===========================================================================
@app.route("/modifiers", methods=["POST"])
def create_modifier():
    auth(["Manager"])
    body = body_json()
    name = require(body, "name")
    group = opt_enum(require(body, "modifier_group"), MODIFIER_GROUPS, "modifier_group")
    surcharge = require(body, "surcharge_cents")
    extra = body.get("extra_bean_grams", 0)
    if extra is None:
        extra = 0
    if not is_int(surcharge) or surcharge < 0:
        raise err("ERR_VALIDATION", 422, "surcharge_cents must be >= 0.")
    if not is_int(extra) or extra < 0:
        raise err("ERR_VALIDATION", 422, "extra_bean_grams must be >= 0.")
    rec = base_record()
    rec.update({
        "name": name,
        "modifier_group": group,
        "surcharge_cents": surcharge,
        "extra_bean_grams": extra,
    })
    DB["modifiers"][rec["id"]] = rec
    return ok(s_modifier(rec), 201)


@app.route("/modifiers", methods=["GET"])
def list_modifiers():
    auth(["Manager", "Barista", "Customer"])
    group = request.args.get("modifier_group")
    recs = [r for r in DB["modifiers"].values() if group is None or r["modifier_group"] == group]
    return paginate(recs, s_modifier)


# ===========================================================================
# MenuItem
# ===========================================================================
@app.route("/menu-items", methods=["POST"])
def create_menu_item():
    auth(["Manager"])
    body = body_json()
    name = require(body, "name")
    category = opt_enum(require(body, "category"), MENU_CATEGORIES, "category")
    base_price = require(body, "base_price_cents")
    req_type = opt_enum(require(body, "required_equipment_type"), REQ_EQUIPMENT_TYPES, "required_equipment_type")
    size = body.get("size", "MEDIUM") or "MEDIUM"
    size = opt_enum(size, SIZES, "size")
    bean_grams = body.get("bean_grams", 0)
    if bean_grams is None:
        bean_grams = 0
    origin_required = body.get("origin_required", False)
    if origin_required is None:
        origin_required = False
    bean_origin = body.get("bean_origin", None)
    if not is_int(base_price) or base_price <= 0:
        raise err("ERR_VALIDATION", 422, "base_price_cents must be > 0.")
    if not is_int(bean_grams) or bean_grams < 0:
        raise err("ERR_VALIDATION", 422, "bean_grams must be >= 0.")
    if not isinstance(origin_required, bool):
        raise err("ERR_VALIDATION", 422, "origin_required must be a boolean.")
    if not origin_required:
        bean_origin = None
    rec = base_record()
    rec.update({
        "name": name,
        "category": category,
        "base_price_cents": base_price,
        "size": size,
        "required_equipment_type": req_type,
        "bean_grams": bean_grams,
        "origin_required": origin_required,
        "bean_origin": bean_origin,
    })
    DB["menu_items"][rec["id"]] = rec
    return ok(s_menu_item(rec), 201)


@app.route("/menu-items/<rid>", methods=["GET"])
def get_menu_item(rid):
    auth(["Manager", "Barista", "Customer"])
    return ok(s_menu_item(get_or_404("menu_items", rid)))


# ===========================================================================
# Equipment
# ===========================================================================
@app.route("/equipment", methods=["POST"])
def create_equipment():
    auth(["Manager"])
    body = body_json()
    name = require(body, "name")
    eq_type = opt_enum(require(body, "equipment_type"), EQUIPMENT_TYPES, "equipment_type")
    rec = base_record()
    rec.update({
        "name": name,
        "equipment_type": eq_type,
        "status": "OPERATIONAL",
        "shots_since_calibration": 0,
        "last_calibrated_at": None,
    })
    DB["equipment"][rec["id"]] = rec
    return ok(s_equipment(rec), 201)


@app.route("/equipment/<rid>", methods=["GET"])
def get_equipment(rid):
    auth(["Manager", "Barista"])
    return ok(s_equipment(get_or_404("equipment", rid)))


@app.route("/equipment/<rid>/calibrate", methods=["POST"])
def calibrate_equipment(rid):
    auth(["Manager", "Barista"])
    eq = get_or_404("equipment", rid)
    if eq["status"] == "IN_MAINTENANCE":
        raise err("ERR_INVALID_STATE", 409, "Cannot calibrate a machine in maintenance.")
    eq["shots_since_calibration"] = 0
    eq["status"] = "OPERATIONAL"
    eq["last_calibrated_at"] = _now_ts()
    touch(eq)
    return ok(s_equipment(eq))


# ===========================================================================
# MaintenanceWindow
# ===========================================================================
@app.route("/maintenance-windows", methods=["POST"])
def create_maint():
    auth(["Manager", "Barista"])
    body = body_json()
    equipment_id = require(body, "equipment_id")
    start_at = require(body, "start_at")
    end_at = require(body, "end_at")
    kind = opt_enum(require(body, "kind"), MAINT_KINDS, "kind")
    eq = get_or_404("equipment", equipment_id)
    s_dt, e_dt = parse_dt(start_at), parse_dt(end_at)
    if s_dt is None or e_dt is None or not (e_dt > s_dt):
        raise err("ERR_INVALID_INTERVAL", 422, "end_at must be strictly after start_at.")
    # Temporal overlap against other SCHEDULED windows on same equipment.
    for w in DB["maintenance_windows"].values():
        if w["equipment_id"] == equipment_id and w["status"] == "SCHEDULED":
            if intervals_overlap(s_dt, e_dt, parse_dt(w["start_at"]), parse_dt(w["end_at"])):
                raise err("ERR_MAINTENANCE_OVERLAP", 409, "Overlaps an existing scheduled window.")
    rec = base_record()
    rec.update({
        "equipment_id": equipment_id,
        "start_at": start_at,
        "end_at": end_at,
        "kind": kind,
        "status": "SCHEDULED",
    })
    DB["maintenance_windows"][rec["id"]] = rec
    # Side effect: equipment offline.
    eq["status"] = "IN_MAINTENANCE"
    touch(eq)
    # Cascade: cancel CONFIRMED catering on this equipment overlapping the window.
    for ev in DB["catering_events"].values():
        if ev["assigned_equipment_id"] == equipment_id and ev["status"] == "CONFIRMED":
            if intervals_overlap(parse_dt(ev["scheduled_start"]), parse_dt(ev["scheduled_end"]), s_dt, e_dt):
                ev["status"] = "CANCELLED"
                touch(ev)
    return ok(s_maint(rec), 201)


@app.route("/maintenance-windows/<rid>", methods=["GET"])
def get_maint(rid):
    auth(["Manager", "Barista"])
    return ok(s_maint(get_or_404("maintenance_windows", rid)))


@app.route("/maintenance-windows", methods=["GET"])
def list_maint():
    auth(["Manager", "Barista"])
    equipment_id = request.args.get("equipment_id")
    status = request.args.get("status")
    recs = [
        r for r in DB["maintenance_windows"].values()
        if (equipment_id is None or r["equipment_id"] == equipment_id)
        and (status is None or r["status"] == status)
    ]
    return paginate(recs, s_maint)


@app.route("/maintenance-windows/<rid>/complete", methods=["POST"])
def complete_maint(rid):
    auth(["Manager", "Barista"])
    w = get_or_404("maintenance_windows", rid)
    if w["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", 409, "Window is not scheduled.")
    eq = DB["equipment"].get(w["equipment_id"])
    if eq is None or eq["status"] != "IN_MAINTENANCE":
        raise err("ERR_INVALID_STATE", 409, "Equipment is not in maintenance for this window.")
    w["status"] = "COMPLETED"
    touch(w)
    eq["status"] = "OPERATIONAL"
    if w["kind"] == "CALIBRATION":
        eq["shots_since_calibration"] = 0
        eq["last_calibrated_at"] = _now_ts()
    touch(eq)
    return ok(s_maint(w))


@app.route("/maintenance-windows/<rid>/cancel", methods=["POST"])
def cancel_maint(rid):
    auth(["Manager", "Barista"])
    w = get_or_404("maintenance_windows", rid)
    if w["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", 409, "Window is not scheduled.")
    w["status"] = "CANCELLED"
    touch(w)
    eq = DB["equipment"].get(w["equipment_id"])
    if eq is not None and eq["status"] == "IN_MAINTENANCE":
        eq["status"] = "OPERATIONAL"
        touch(eq)
    return ok(s_maint(w))


# ===========================================================================
# Barista
# ===========================================================================
@app.route("/baristas", methods=["POST"])
def create_barista():
    auth(["Manager"])
    body = body_json()
    name = require(body, "name")
    station = opt_enum(require(body, "station_role"), STATION_ROLES, "station_role")
    status = body.get("status", "ACTIVE") or "ACTIVE"
    status = opt_enum(status, BARISTA_STATUSES, "status")
    rec = base_record()
    rec.update({"name": name, "station_role": station, "status": status})
    DB["baristas"][rec["id"]] = rec
    return ok(s_barista(rec), 201)


@app.route("/baristas/<rid>", methods=["GET"])
def get_barista(rid):
    auth(["Manager", "Barista"])
    return ok(s_barista(get_or_404("baristas", rid)))


# ===========================================================================
# Member
# ===========================================================================
@app.route("/members", methods=["POST"])
def create_member():
    auth(["Manager"])
    body = body_json()
    email = require(body, "email")
    full_name = require(body, "full_name")
    status = body.get("status", "ACTIVE") or "ACTIVE"
    status = opt_enum(status, MEMBER_STATUSES, "status")
    for m in DB["members"].values():
        if m["email"] == email:
            raise err("ERR_DUPLICATE_EMAIL", 422, "Member email already registered.")
    rec = base_record()
    rec.update({
        "email": email,
        "full_name": full_name,
        "status": status,
        "points_balance": 0,
        "lifetime_points": 0,
    })
    DB["members"][rec["id"]] = rec
    return ok(s_member(rec), 201)


@app.route("/members/<rid>", methods=["GET"])
def get_member(rid):
    uid, role = auth(["Manager", "Barista", "Customer"])
    m = get_or_404("members", rid)
    if role == "Customer" and rid != uid:
        raise err("ERR_NOT_OWNER", 403, "Customer may only read own member record.")
    return ok(s_member(m))


@app.route("/members/<rid>/point-adjustments", methods=["POST"])
def point_adjustment(rid):
    auth(["Manager"])
    m = get_or_404("members", rid)
    body = body_json()
    lp_delta = body.get("lifetime_points_delta", 0)
    pb_delta = body.get("points_balance_delta", 0)
    if lp_delta is None:
        lp_delta = 0
    if pb_delta is None:
        pb_delta = 0
    if not is_int(lp_delta) or not is_int(pb_delta):
        raise err("ERR_VALIDATION", 422, "point deltas must be integers.")
    m["lifetime_points"] += lp_delta
    m["points_balance"] += pb_delta
    if m["points_balance"] < 0:
        m["points_balance"] = 0
    if m["lifetime_points"] < 0:
        m["lifetime_points"] = 0
    touch(m)
    return ok(s_member(m))


# ===========================================================================
# Order
# ===========================================================================
def price_line(mi, modifiers, quantity):
    sized_base = rhu(mi["base_price_cents"], SIZE_MULT[mi["size"]])
    mod_surcharge = sum(mod["surcharge_cents"] for mod in modifiers)
    line_price = (sized_base + mod_surcharge) * quantity
    line_bean = (mi["bean_grams"] + sum(mod["extra_bean_grams"] for mod in modifiers)) * quantity
    return line_price, line_bean


@app.route("/orders", methods=["POST"])
def create_order():
    uid, role = auth(["Customer", "Barista", "Manager"])
    body = body_json()
    member_id = body.get("member_id")
    # Authorization: Customer must place own order.
    if role == "Customer" and member_id != uid:
        raise err("ERR_NOT_OWNER", 403, "Customer must place orders under own member_id.")
    # Shape validation.
    lines = body.get("lines")
    if lines is None or not isinstance(lines, list):
        raise err("ERR_VALIDATION", 422, "lines must be provided as a list.")
    channel = body.get("channel", "MOBILE_APP") or "MOBILE_APP"
    channel = opt_enum(channel, CHANNELS, "channel")
    points_redeemed = body.get("points_redeemed", 0)
    if points_redeemed is None:
        points_redeemed = 0
    if not is_int(points_redeemed):
        raise err("ERR_VALIDATION", 422, "points_redeemed must be an integer.")
    # Existence (left-to-right): member first, then per-line menu items and modifiers.
    member = None
    if member_id is not None:
        member = DB["members"].get(member_id)
        if member is None:
            raise err("ERR_NOT_FOUND", 404, "Member does not exist.")
    resolved = []
    for ln in lines:
        if not isinstance(ln, dict) or "menu_item_id" not in ln or ln["menu_item_id"] is None:
            raise err("ERR_VALIDATION", 422, "Each line requires menu_item_id.")
        mi = DB["menu_items"].get(ln["menu_item_id"])
        if mi is None:
            raise err("ERR_NOT_FOUND", 404, "Menu item does not exist.")
        mod_ids = ln.get("modifier_ids", [])
        if mod_ids is None:
            mod_ids = []
        if not isinstance(mod_ids, list):
            raise err("ERR_VALIDATION", 422, "modifier_ids must be a list.")
        mods = []
        for mid in mod_ids:
            mod = DB["modifiers"].get(mid)
            if mod is None:
                raise err("ERR_NOT_FOUND", 404, "Modifier does not exist.")
            mods.append(mod)
        resolved.append((ln, mi, mods, mod_ids))
    # State: member must be ACTIVE for placement.
    if member is not None and member["status"] == "SUSPENDED":
        raise err("ERR_MEMBER_SUSPENDED", 409, "Member is suspended.")
    # Structural.
    if len(lines) == 0:
        raise err("ERR_EMPTY_ORDER", 422, "Order must have at least one line.")
    for ln, mi, mods, mod_ids in resolved:
        qty = ln.get("quantity")
        if not is_int(qty) or qty < 1:
            raise err("ERR_INVALID_QUANTITY", 422, "Line quantity must be a positive integer.")
    # Fiscal.
    if points_redeemed < 0:
        raise err("ERR_INVALID_REDEMPTION", 422, "points_redeemed cannot be negative.")
    balance = member["points_balance"] if member is not None else 0
    if points_redeemed > balance:
        raise err("ERR_INSUFFICIENT_POINTS", 422, "points_redeemed exceeds member balance.")

    # Compute lines.
    order_lines = []
    subtotal = 0
    for ln, mi, mods, mod_ids in resolved:
        qty = ln["quantity"]
        lp, lb = price_line(mi, mods, qty)
        subtotal += lp
        order_lines.append({
            "menu_item_id": mi["id"],
            "quantity": qty,
            "modifier_ids": list(mod_ids),
            "line_price_cents": lp,
            "line_bean_grams": lb,
        })
    # Totals (pinned order).
    service_fee = 0 if subtotal >= FEE_WAIVE_SUBTOTAL_CENTS else SMALL_ORDER_FEE_CENTS
    tier = tier_of(member["lifetime_points"]) if member is not None else "BRONZE"
    tier_discount = rhu(subtotal, TIER_DISCOUNT_RATE[tier])
    redemption_discount = min(points_redeemed * CENTS_PER_POINT, subtotal)
    discount = tier_discount + redemption_discount
    total = max(subtotal - discount + service_fee, 0)
    provisional = subtotal // EARN_DIVISOR_CENTS

    rec = base_record()
    rec.update({
        "member_id": member_id,
        "channel": channel,
        "lines": order_lines,
        "points_redeemed": points_redeemed,
        "payment_status": "UNPAID",
        "fulfillment_status": "PLACED",
        "subtotal_cents": subtotal,
        "service_fee_cents": service_fee,
        "discount_cents": discount,
        "total_cents": total,
        "points_earned_provisional": provisional,
        "points_earned_final": None,
        "_draws": [],
    })
    DB["orders"][rec["id"]] = rec
    if points_redeemed > 0 and member is not None:
        member["points_balance"] -= points_redeemed
        touch(member)
    return ok(s_order(rec), 201)


@app.route("/orders/<rid>", methods=["GET"])
def get_order(rid):
    uid, role = auth(["Customer", "Barista", "Manager"])
    o = get_or_404("orders", rid)
    check_owner(role, uid, o["member_id"])
    return ok(s_order(o))


@app.route("/orders", methods=["GET"])
def list_orders():
    uid, role = auth(["Customer", "Barista", "Manager"])
    member_id = request.args.get("member_id")
    fulfillment = request.args.get("fulfillment_status")
    payment = request.args.get("payment_status")
    if role == "Customer":
        member_id = uid
    recs = [
        r for r in DB["orders"].values()
        if (member_id is None or r["member_id"] == member_id)
        and (fulfillment is None or r["fulfillment_status"] == fulfillment)
        and (payment is None or r["payment_status"] == payment)
    ]
    return paginate(recs, s_order)


@app.route("/orders/<rid>/pay", methods=["POST"])
def pay_order(rid):
    uid, role = auth(["Customer", "Barista", "Manager"])
    o = get_or_404("orders", rid)
    check_owner(role, uid, o["member_id"])
    if o["fulfillment_status"] == "VOIDED":
        raise err("ERR_INVALID_STATE", 409, "Cannot pay a voided order.")
    if o["payment_status"] != "UNPAID":
        raise err("ERR_INVALID_STATE", 409, "Order is not unpaid.")
    o["payment_status"] = "PAID"
    touch(o)
    return ok(s_order(o))


@app.route("/orders/<rid>/fulfill", methods=["POST"])
def fulfill_order(rid):
    auth(["Barista", "Manager"])
    o = get_or_404("orders", rid)
    if o["fulfillment_status"] != "PLACED":
        raise err("ERR_INVALID_STATE", 409, "Order is not in PLACED state.")

    lines_ctx = []
    for ln in o["lines"]:
        mi = DB["menu_items"].get(ln["menu_item_id"])
        lines_ctx.append((ln, mi))

    # Referential: every required equipment type has an OPERATIONAL machine.
    for ln, mi in lines_ctx:
        req_type = mi["required_equipment_type"]
        if req_type in EQUIPMENT_TYPES and operational_equipment_of_type(req_type) is None:
            raise err("ERR_EQUIPMENT_UNAVAILABLE", 409, "No operational equipment of required type.")

    # Referential: every origin_required line has an ACTIVE bean lot.
    origin_demand = {}
    for ln, mi in lines_ctx:
        if mi["origin_required"]:
            origin_demand.setdefault(mi["bean_origin"], 0)
            origin_demand[mi["bean_origin"]] += ln["line_bean_grams"]
    for origin in origin_demand:
        if active_lot_for_origin(origin) is None:
            raise err("ERR_BEAN_LOT_UNAVAILABLE", 409, "No active bean lot for origin.")
    # Fiscal: active lot has enough on-hand for the origin's cumulative demand.
    for origin, demand in origin_demand.items():
        lot = active_lot_for_origin(origin)
        if on_hand(lot) < demand:
            raise err("ERR_INSUFFICIENT_BEANS", 422, "Insufficient beans on active lot.")

    # --- Apply side effects ---
    draws = []
    for ln, mi in lines_ctx:
        if mi["origin_required"]:
            lot = active_lot_for_origin(mi["bean_origin"])
            grams = ln["line_bean_grams"]
            lot["consumed_grams"] += grams
            touch(lot)
            draws.append({"lot_id": lot["id"], "grams": grams})
            if on_hand(lot) == 0:
                deplete_and_promote(lot)
    o["_draws"] = draws

    # Espresso shots.
    shots = 0
    for ln, mi in lines_ctx:
        if mi["required_equipment_type"] == "ESPRESSO":
            shot_mods = 0
            for mid in ln["modifier_ids"]:
                mod = DB["modifiers"].get(mid)
                if mod is not None and mod["modifier_group"] == "SHOT":
                    shot_mods += 1
            shots += (1 + shot_mods) * ln["quantity"]
    if shots > 0:
        machine = operational_equipment_of_type("ESPRESSO")
        if machine is not None:
            machine["shots_since_calibration"] += shots
            if machine["shots_since_calibration"] >= CALIBRATION_SHOT_LIMIT:
                machine["status"] = "NEEDS_CALIBRATION"
            touch(machine)

    # Final loyalty earning.
    final = o["total_cents"] // EARN_DIVISOR_CENTS
    o["points_earned_final"] = final
    o["fulfillment_status"] = "FULFILLED"
    touch(o)
    member = DB["members"].get(o["member_id"]) if o["member_id"] else None
    if member is not None:
        member["lifetime_points"] += final
        member["points_balance"] += final
        touch(member)
    return ok(s_order(o))


@app.route("/orders/<rid>/void", methods=["POST"])
def void_order(rid):
    auth(["Barista", "Manager"])
    o = get_or_404("orders", rid)
    if o["fulfillment_status"] == "VOIDED":
        raise err("ERR_INVALID_STATE", 409, "Order is already voided.")
    was_fulfilled = o["fulfillment_status"] == "FULFILLED"
    member = DB["members"].get(o["member_id"]) if o["member_id"] else None

    if was_fulfilled:
        # Restore beans.
        for d in o.get("_draws", []):
            lot = DB["bean_lots"].get(d["lot_id"])
            if lot is not None:
                lot["consumed_grams"] -= d["grams"]
                touch(lot)
        # Reverse earned + restore redeemed.
        if member is not None:
            final = o["points_earned_final"] or 0
            member["lifetime_points"] -= final
            member["points_balance"] -= final
            member["points_balance"] += o["points_redeemed"]
            if member["lifetime_points"] < 0:
                member["lifetime_points"] = 0
            if member["points_balance"] < 0:
                member["points_balance"] = 0
            touch(member)
    else:
        # PLACED -> VOIDED: restore redeemed points only.
        if member is not None and o["points_redeemed"] > 0:
            member["points_balance"] += o["points_redeemed"]
            touch(member)

    if o["payment_status"] == "PAID":
        o["payment_status"] = "REFUNDED"
    o["fulfillment_status"] = "VOIDED"
    touch(o)
    return ok(s_order(o))


# ===========================================================================
# Subscription
# ===========================================================================
@app.route("/subscriptions", methods=["POST"])
def create_subscription():
    uid, role = auth(["Customer", "Manager"])
    body = body_json()
    member_id = body.get("member_id")
    if role == "Customer" and member_id != uid:
        raise err("ERR_NOT_OWNER", 403, "Customer must create own subscription.")
    require(body, "member_id")
    bean_origin = require(body, "bean_origin")
    frequency = opt_enum(require(body, "frequency"), FREQUENCIES, "frequency")
    bags = require(body, "bags_per_cycle")
    next_ship = require(body, "next_ship_at")
    expected_version = require(body, "expected_member_version")
    member = DB["members"].get(member_id)
    if member is None:
        raise err("ERR_NOT_FOUND", 404, "Member does not exist.")
    # OCC (state category).
    if not is_int(expected_version) or expected_version != member["version"]:
        raise err("ERR_STALE_VERSION", 412, "Stale member version.")
    if not is_int(bags) or bags <= 0:
        raise err("ERR_VALIDATION", 422, "bags_per_cycle must be > 0.")
    # Supersede prior ACTIVE subscription.
    for sub in DB["subscriptions"].values():
        if sub["member_id"] == member_id and sub["status"] == "ACTIVE":
            sub["status"] = "SUPERSEDED"
            touch(sub)
    tier = tier_of(member["lifetime_points"])
    base = bags * PRICE_PER_BAG_CENTS
    price = base - rhu(base, TIER_DISCOUNT_RATE[tier])
    rec = base_record()
    rec.update({
        "member_id": member_id,
        "bean_origin": bean_origin,
        "frequency": frequency,
        "bags_per_cycle": bags,
        "next_ship_at": next_ship,
        "price_per_cycle_cents": price,
        "status": "ACTIVE",
    })
    DB["subscriptions"][rec["id"]] = rec
    touch(member)  # increments Member.version by 1
    return ok(s_subscription(rec), 201)


@app.route("/subscriptions/<rid>", methods=["GET"])
def get_subscription(rid):
    uid, role = auth(["Customer", "Manager"])
    sub = get_or_404("subscriptions", rid)
    check_owner(role, uid, sub["member_id"])
    return ok(s_subscription(sub))


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    uid, role = auth(["Customer", "Manager"])
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if role == "Customer":
        member_id = uid
    recs = [
        r for r in DB["subscriptions"].values()
        if (member_id is None or r["member_id"] == member_id)
        and (status is None or r["status"] == status)
    ]
    return paginate(recs, s_subscription)


@app.route("/subscriptions/<rid>/cancel", methods=["POST"])
def cancel_subscription(rid):
    uid, role = auth(["Customer", "Manager"])
    sub = get_or_404("subscriptions", rid)
    check_owner(role, uid, sub["member_id"])
    if sub["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409, "Subscription is not active.")
    sub["status"] = "CANCELLED"
    touch(sub)
    return ok(s_subscription(sub))


# ===========================================================================
# CateringEvent
# ===========================================================================
@app.route("/catering-events", methods=["POST"])
def create_catering():
    uid, role = auth(["Customer", "Barista", "Manager"])
    body = body_json()
    member_id = body.get("member_id")
    if role == "Customer" and member_id != uid:
        raise err("ERR_NOT_OWNER", 403, "Customer must request own catering.")
    client_name = require(body, "client_name")
    equipment_id = require(body, "assigned_equipment_id")
    barista_id = require(body, "assigned_barista_id")
    scheduled_start = require(body, "scheduled_start")
    scheduled_end = require(body, "scheduled_end")
    headcount = require(body, "headcount")
    travel_fee = body.get("travel_fee_cents", 0)
    if travel_fee is None:
        travel_fee = 0
    # Existence (left-to-right): member, equipment, barista.
    if member_id is not None and member_id not in DB["members"]:
        raise err("ERR_NOT_FOUND", 404, "Member does not exist.")
    get_or_404("equipment", equipment_id)
    get_or_404("baristas", barista_id)
    # Structural.
    s_dt, e_dt = parse_dt(scheduled_start), parse_dt(scheduled_end)
    if s_dt is None or e_dt is None or not (e_dt > s_dt):
        raise err("ERR_INVALID_INTERVAL", 422, "scheduled_end must be strictly after scheduled_start.")
    if not is_int(headcount) or headcount <= 0:
        raise err("ERR_VALIDATION", 422, "headcount must be > 0.")
    if not is_int(travel_fee) or travel_fee < 0:
        raise err("ERR_VALIDATION", 422, "travel_fee_cents must be >= 0.")
    quoted = headcount * PER_HEAD_CENTS + travel_fee
    deposit = rhu(quoted, DEPOSIT_RATE)
    rec = base_record()
    rec.update({
        "member_id": member_id,
        "client_name": client_name,
        "assigned_equipment_id": equipment_id,
        "assigned_barista_id": barista_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "headcount": headcount,
        "travel_fee_cents": travel_fee,
        "quoted_total_cents": quoted,
        "deposit_cents": deposit,
        "status": "QUOTED",
    })
    DB["catering_events"][rec["id"]] = rec
    return ok(s_catering(rec), 201)


@app.route("/catering-events/<rid>", methods=["GET"])
def get_catering(rid):
    uid, role = auth(["Customer", "Barista", "Manager"])
    ev = get_or_404("catering_events", rid)
    check_owner(role, uid, ev["member_id"])
    return ok(s_catering(ev))


@app.route("/catering-events", methods=["GET"])
def list_catering():
    uid, role = auth(["Customer", "Barista", "Manager"])
    member_id = request.args.get("member_id")
    equipment_id = request.args.get("assigned_equipment_id")
    barista_id = request.args.get("assigned_barista_id")
    status = request.args.get("status")
    if role == "Customer":
        member_id = uid
    recs = [
        r for r in DB["catering_events"].values()
        if (member_id is None or r["member_id"] == member_id)
        and (equipment_id is None or r["assigned_equipment_id"] == equipment_id)
        and (barista_id is None or r["assigned_barista_id"] == barista_id)
        and (status is None or r["status"] == status)
    ]
    return paginate(recs, s_catering)


@app.route("/catering-events/<rid>/confirm", methods=["POST"])
def confirm_catering(rid):
    auth(["Barista", "Manager"])
    ev = get_or_404("catering_events", rid)
    if ev["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", 409, "Event is not quoted.")
    barista = DB["baristas"].get(ev["assigned_barista_id"])
    equipment = DB["equipment"].get(ev["assigned_equipment_id"])
    # Referential: barista ACTIVE, then equipment OPERATIONAL.
    if barista is None or barista["status"] != "ACTIVE":
        raise err("ERR_BARISTA_UNAVAILABLE", 409, "Assigned barista is not active.")
    if equipment is None or equipment["status"] != "OPERATIONAL":
        raise err("ERR_EQUIPMENT_UNAVAILABLE", 409, "Assigned equipment is not operational.")
    # Temporal: no CONFIRMED overlap on same barista (half-open).
    s_dt, e_dt = parse_dt(ev["scheduled_start"]), parse_dt(ev["scheduled_end"])
    for other in DB["catering_events"].values():
        if other["id"] == ev["id"]:
            continue
        if other["assigned_barista_id"] == ev["assigned_barista_id"] and other["status"] == "CONFIRMED":
            if intervals_overlap(s_dt, e_dt, parse_dt(other["scheduled_start"]), parse_dt(other["scheduled_end"])):
                raise err("ERR_BARISTA_OVERLAP", 409, "Barista has a conflicting confirmed event.")
    ev["status"] = "CONFIRMED"
    touch(ev)
    return ok(s_catering(ev))


@app.route("/catering-events/<rid>/cancel", methods=["POST"])
def cancel_catering(rid):
    uid, role = auth(["Customer", "Barista", "Manager"])
    ev = get_or_404("catering_events", rid)
    check_owner(role, uid, ev["member_id"])
    if ev["status"] not in ("QUOTED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", 409, "Event cannot be cancelled.")
    ev["status"] = "CANCELLED"
    touch(ev)
    return ok(s_catering(ev))


# ===========================================================================
# DailyReconciliation
# ===========================================================================
@app.route("/daily-reconciliations", methods=["POST"])
def create_recon():
    auth(["Manager"])
    body = body_json()
    business_date = require(body, "business_date")
    bean_lot_id = require(body, "bean_lot_id")
    for r in DB["daily_reconciliations"].values():
        if r["business_date"] == business_date:
            raise err("ERR_DUPLICATE_BUSINESS_DATE", 422, "business_date already reconciled.")
    lot = get_or_404("bean_lots", bean_lot_id)
    rec = base_record()
    rec.update({
        "business_date": business_date,
        "bean_lot_id": bean_lot_id,
        "status": "OPEN",
        "opening_bean_on_hand_grams": on_hand(lot),
        "opening_waste_grams": lot["waste_grams_total"],
        "counted_revenue_cents": None,
        "counted_bean_on_hand_grams": None,
        "expected_revenue_cents": None,
        "revenue_variance_cents": None,
        "ledger_usage_grams": None,
        "logged_waste_grams": None,
        "expected_usage_grams": None,
        "shrink_grams": None,
    })
    DB["daily_reconciliations"][rec["id"]] = rec
    return ok(s_recon(rec), 201)


@app.route("/daily-reconciliations/<rid>", methods=["GET"])
def get_recon(rid):
    auth(["Manager", "Barista"])
    return ok(s_recon(get_or_404("daily_reconciliations", rid)))


@app.route("/daily-reconciliations", methods=["GET"])
def list_recon():
    auth(["Manager", "Barista"])
    bean_lot_id = request.args.get("bean_lot_id")
    status = request.args.get("status")
    recs = [
        r for r in DB["daily_reconciliations"].values()
        if (bean_lot_id is None or r["bean_lot_id"] == bean_lot_id)
        and (status is None or r["status"] == status)
    ]
    return paginate(recs, s_recon)


@app.route("/daily-reconciliations/<rid>/submit-count", methods=["POST"])
def submit_count(rid):
    auth(["Manager", "Barista"])
    rec = get_or_404("daily_reconciliations", rid)
    body = body_json()
    counted_rev = require(body, "counted_revenue_cents")
    counted_beans = require(body, "counted_bean_on_hand_grams")
    expected_version = require(body, "expected_reconciliation_version")
    if rec["status"] == "CLOSED":
        raise err("ERR_INVALID_STATE", 409, "Reconciliation is closed.")
    if not is_int(expected_version) or expected_version != rec["version"]:
        raise err("ERR_STALE_VERSION", 412, "Stale reconciliation version.")
    if not is_int(counted_rev) or not is_int(counted_beans):
        raise err("ERR_VALIDATION", 422, "counted values must be integers.")
    rec["counted_revenue_cents"] = counted_rev
    rec["counted_bean_on_hand_grams"] = counted_beans
    rec["status"] = "COUNTING"
    touch(rec)
    return ok(s_recon(rec))


@app.route("/daily-reconciliations/<rid>/close", methods=["POST"])
def close_recon(rid):
    auth(["Manager"])
    rec = get_or_404("daily_reconciliations", rid)
    if rec["status"] == "CLOSED":
        raise err("ERR_INVALID_STATE", 409, "Reconciliation is already closed.")
    if rec["counted_revenue_cents"] is None or rec["counted_bean_on_hand_grams"] is None:
        raise err("ERR_COUNT_NOT_SUBMITTED", 409, "No count submitted.")
    lot = DB["bean_lots"].get(rec["bean_lot_id"])
    closing_on_hand = on_hand(lot) if lot is not None else 0
    closing_waste = lot["waste_grams_total"] if lot is not None else 0
    expected_revenue = sum(
        o["total_cents"] for o in DB["orders"].values()
        if o["payment_status"] == "PAID" and o["fulfillment_status"] == "FULFILLED"
    )
    ledger_usage = rec["opening_bean_on_hand_grams"] - closing_on_hand
    logged_waste = closing_waste - rec["opening_waste_grams"]
    expected_usage = ledger_usage - logged_waste
    shrink = closing_on_hand - rec["counted_bean_on_hand_grams"]
    rec["expected_revenue_cents"] = expected_revenue
    rec["revenue_variance_cents"] = rec["counted_revenue_cents"] - expected_revenue
    rec["ledger_usage_grams"] = ledger_usage
    rec["logged_waste_grams"] = logged_waste
    rec["expected_usage_grams"] = expected_usage
    rec["shrink_grams"] = shrink
    rec["status"] = "CLOSED"
    touch(rec)
    return ok(s_recon(rec))


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def root():
    return ok({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
