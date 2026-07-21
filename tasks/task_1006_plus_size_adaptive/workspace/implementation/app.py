"""Plus-Size & Adaptive-Clothing Retail API — Flask entry point.

All state is in-memory and reset on every process boot. No entity data is
seeded, preloaded, or hardcoded at startup.
"""
import os

from flask import Flask

from store import (
    db, new_record, touch, public, iso, parse_dt,
    ADAPTIVE_FEATURES, PRODUCT_CATEGORIES, SPECIALTIES, APPOINTMENT_TOPICS,
    RETURN_TYPES, FIT_VERDICTS, REFUND_DESTINATIONS, PLAN_TIERS, CADENCES,
    TIER_DISCOUNT, TIER_RANK, TIER_INSIDER_MIN, TIER_VIP_MIN,
    TIER_UP_BONUS_CENTS, EARN_CENTS_PER_POINT, REDEEM_VALUE_CENTS_PER_POINT,
    REDEEM_CAP_PCT, STYLING_FEE_CENTS, RETURN_WINDOW_DAYS, TRYON_WINDOW_DAYS,
    LATE_CANCEL_WINDOW_HOURS, LATE_CANCEL_FEE_CENTS, NO_SHOW_SUSPEND_THRESHOLD,
)
from envelope import ApiError, ok, ok_list, error_response
from auth import (
    get_body, get_auth, require, optional, require_str_array, require_roles,
    forbidden, find_or_404, paginate_params, apply_pagination,
)
from calc import round_half_up, pct_of
from serialize import variant_out, order_out, line_out, generic_out
from datetime import timedelta

app = Flask(__name__)


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(400)
def _handle_400(_e):
    return error_response(ApiError("ERR_VALIDATION", 400, "Malformed request"))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_VALIDATION", 400, str(err)))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def sorted_records(collection):
    return sorted(collection.values(), key=lambda r: r["_seq"])


def check_owner(role, user_id, owner_id):
    """Entity-backed ownership gate. StoreManager bypasses."""
    if role == "Customer" and user_id != owner_id:
        forbidden()


def recompute_tier(customer):
    lp = customer["loyalty_lifetime_points"]
    if lp >= TIER_VIP_MIN:
        return "VIP"
    if lp >= TIER_INSIDER_MIN:
        return "INSIDER"
    return "STANDARD"


def earn_loyalty(customer, spend_cents):
    """Shared DELIVER / SETTLE loyalty cascade. Returns points_earned."""
    earned = spend_cents // EARN_CENTS_PER_POINT
    if earned == 0:
        return 0  # no field changes -> no version bump
    customer["loyalty_points_balance"] += earned
    customer["loyalty_lifetime_points"] += earned
    old_tier = customer["loyalty_tier"]
    new_tier = recompute_tier(customer)
    if TIER_RANK[new_tier] > TIER_RANK[old_tier]:
        customer["wallet_credit_cents"] += TIER_UP_BONUS_CENTS[new_tier]
    customer["loyalty_tier"] = new_tier
    touch(customer)
    return earned


def variant_retail(v):
    prod = db.products[v["product_id"]]
    return prod["base_price_cents"] + v["price_delta_cents"]


# ---------------------------------------------------------------------------
# Logical clock (StoreManager)
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"StoreManager"})
    to_iso = require(body, "to_iso8601", "datetime")
    dt = db.set_clock(to_iso)
    return ok({"current_utc": iso(dt)}, 200)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@app.route("/customers/register", methods=["POST"])
def customer_register():
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"Anonymous"})
    email = require(body, "email", "string")
    full_name = require(body, "full_name", "string")
    size_code = require(body, "size_code", "integer")
    adaptive_needs = require_str_array(body, "adaptive_needs", required=False, default=[])
    for a in adaptive_needs:
        if a not in ADAPTIVE_FEATURES:
            raise ApiError("ERR_VALIDATION", 400, "invalid adaptive_needs value")
    rec = new_record()
    rec.update({
        "email": email,
        "full_name": full_name,
        "size_code": size_code,
        "adaptive_needs": adaptive_needs,
        "loyalty_points_balance": 0,
        "loyalty_lifetime_points": 0,
        "loyalty_tier": "STANDARD",
        "wallet_credit_cents": 0,
        "no_show_count": 0,
        "booking_status": "ACTIVE",
        "account_status": "ACTIVE",
    })
    db.customers[rec["id"]] = rec
    return ok(public(rec), 201)


@app.route("/customers/<cid>", methods=["GET"])
def customer_get(cid):
    role, uid = get_auth()
    require_roles(role, {"Customer", "StoreManager"})
    cust = find_or_404(db.customers, cid)
    check_owner(role, uid, cust["id"])
    return ok(public(cust), 200)


@app.route("/customers/<cid>/status", methods=["POST"])
def customer_status(cid):
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"StoreManager"})
    cust = find_or_404(db.customers, cid)
    to_status = require(body, "to_status", "string", enum={"ACTIVE", "SUSPENDED", "CLOSED"})
    cur = cust["account_status"]
    allowed = {
        ("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE"),
        ("ACTIVE", "CLOSED"), ("SUSPENDED", "CLOSED"),
    }
    if (cur, to_status) not in allowed:
        raise ApiError("ERR_INVALID_STATE", 409, "Account status transition not permitted")
    cust["account_status"] = to_status
    touch(cust)
    return ok(public(cust), 200)


@app.route("/customers/<cid>/wallet-adjustments", methods=["POST"])
def customer_wallet_adjust(cid):
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"StoreManager"})
    cust = find_or_404(db.customers, cid)
    delta = require(body, "delta_cents", "integer")
    optional(body, "reason", "string")
    cust["wallet_credit_cents"] = max(0, cust["wallet_credit_cents"] + delta)
    touch(cust)
    return ok(public(cust), 200)


@app.route("/customers/<cid>/loyalty-adjustments", methods=["POST"])
def customer_loyalty_adjust(cid):
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"StoreManager"})
    cust = find_or_404(db.customers, cid)
    delta = require(body, "delta_points", "integer")
    optional(body, "reason", "string")
    cust["loyalty_points_balance"] += delta
    cust["loyalty_lifetime_points"] += delta
    cust["loyalty_tier"] = recompute_tier(cust)
    touch(cust)
    return ok(public(cust), 200)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
@app.route("/products", methods=["POST"])
def product_create():
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"StoreManager"})
    name = require(body, "name", "string")
    category = require(body, "category", "string", enum=PRODUCT_CATEGORIES)
    base_price = require(body, "base_price_cents", "integer")
    size_min = require(body, "size_min", "integer")
    size_max = require(body, "size_max", "integer")
    adaptive_features = require_str_array(body, "adaptive_features", required=False, default=[])
    for a in adaptive_features:
        if a not in ADAPTIVE_FEATURES:
            raise ApiError("ERR_VALIDATION", 400, "invalid adaptive_features value")
    is_special = optional(body, "is_special_order", "boolean", default=False)
    restock_fee = optional(body, "restock_fee_pct", "number", default=0.15)
    rec = new_record()
    rec.update({
        "name": name,
        "category": category,
        "base_price_cents": base_price,
        "adaptive_features": adaptive_features,
        "size_min": size_min,
        "size_max": size_max,
        "is_special_order": is_special,
        "restock_fee_pct": restock_fee,
        "status": "ACTIVE",
    })
    db.products[rec["id"]] = rec
    return ok(public(rec), 201)


@app.route("/products", methods=["GET"])
def product_list():
    role, uid = get_auth()
    require_roles(role, {"Anonymous", "Customer", "StoreManager"})
    from flask import request
    args = request.args
    items = sorted_records(db.products)

    if "adaptive_feature" in args:
        feat = args.get("adaptive_feature")
        items = [p for p in items if feat in p["adaptive_features"]]
    if "size_code" in args and args.get("size_code") != "":
        try:
            sc = int(args.get("size_code"))
        except ValueError:
            raise ApiError("ERR_VALIDATION", 400, "size_code must be an integer")
        items = [p for p in items if p["size_min"] <= sc <= p["size_max"]]
    if "category" in args:
        items = [p for p in items if p["category"] == args.get("category")]
    if "is_special_order" in args and args.get("is_special_order") != "":
        want = args.get("is_special_order").lower() in ("true", "1")
        items = [p for p in items if p["is_special_order"] == want]

    limit, offset = paginate_params()
    page, total = apply_pagination(items, limit, offset)
    return ok_list([public(p) for p in page], limit, offset, total)


@app.route("/products/<pid>", methods=["GET"])
def product_get(pid):
    role, uid = get_auth()
    require_roles(role, {"Anonymous", "Customer", "StoreManager"})
    prod = find_or_404(db.products, pid)
    return ok(public(prod), 200)


@app.route("/products/<pid>/variants", methods=["POST"])
def variant_create(pid):
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"StoreManager"})
    prod = find_or_404(db.products, pid)
    size_code = require(body, "size_code", "integer")
    color = require(body, "color", "string")
    price_delta = optional(body, "price_delta_cents", "integer", default=0)
    on_hand = optional(body, "inventory_on_hand", "integer", default=0)
    if not (prod["size_min"] <= size_code <= prod["size_max"]):
        raise ApiError("ERR_SIZE_OUT_OF_RANGE", 409, "Variant size outside product range")
    rec = new_record()
    rec.update({
        "product_id": pid,
        "size_code": size_code,
        "color": color,
        "price_delta_cents": price_delta,
        "inventory_on_hand": on_hand,
        "inventory_reserved": 0,
        "inventory_available": on_hand,
        "status": "ACTIVE",
    })
    db.variants[rec["id"]] = rec
    return ok(variant_out(rec), 201)


@app.route("/products/<pid>/variants", methods=["GET"])
def variant_list(pid):
    role, uid = get_auth()
    require_roles(role, {"Anonymous", "Customer", "StoreManager"})
    find_or_404(db.products, pid)
    items = [v for v in sorted_records(db.variants) if v["product_id"] == pid]
    limit, offset = paginate_params()
    page, total = apply_pagination(items, limit, offset)
    return ok_list([variant_out(v) for v in page], limit, offset, total)


@app.route("/variants/<vid>", methods=["GET"])
def variant_get(vid):
    role, uid = get_auth()
    require_roles(role, {"Anonymous", "Customer", "StoreManager"})
    v = find_or_404(db.variants, vid)
    return ok(variant_out(v), 200)


@app.route("/variants/<vid>/restock", methods=["POST"])
def variant_restock(vid):
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"StoreManager"})
    v = find_or_404(db.variants, vid)
    qty = require(body, "quantity", "integer")
    v["inventory_on_hand"] += qty
    v["inventory_available"] = v["inventory_on_hand"] - v["inventory_reserved"]
    touch(v)
    return ok(variant_out(v), 200)


@app.route("/variants/<vid>/order-lines", methods=["GET"])
def variant_order_lines(vid):
    role, uid = get_auth()
    require_roles(role, {"StoreManager"})
    find_or_404(db.variants, vid)
    items = [l for l in sorted_records(db.order_lines) if l["variant_id"] == vid]
    limit, offset = paginate_params()
    page, total = apply_pagination(items, limit, offset)
    return ok_list([line_out(l) for l in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Fit specialists
# ---------------------------------------------------------------------------
@app.route("/specialists", methods=["POST"])
def specialist_create():
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"StoreManager"})
    full_name = require(body, "full_name", "string")
    specialties = require_str_array(body, "specialties", required=True)
    for s in specialties:
        if s not in SPECIALTIES:
            raise ApiError("ERR_VALIDATION", 400, "invalid specialties value")
    buffer_minutes = optional(body, "buffer_minutes", "integer", default=15)
    rec = new_record()
    rec.update({
        "full_name": full_name,
        "specialties": specialties,
        "buffer_minutes": buffer_minutes,
        "status": "ACTIVE",
    })
    db.specialists[rec["id"]] = rec
    return ok(public(rec), 201)


@app.route("/specialists/<sid>", methods=["GET"])
def specialist_get(sid):
    role, uid = get_auth()
    require_roles(role, {"Customer", "StoreManager"})
    s = find_or_404(db.specialists, sid)
    return ok(public(s), 200)


@app.route("/specialists/<sid>/status", methods=["POST"])
def specialist_status(sid):
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"StoreManager"})
    s = find_or_404(db.specialists, sid)
    to_status = require(body, "to_status", "string", enum={"ACTIVE", "ON_LEAVE"})
    s["status"] = to_status
    touch(s)
    return ok(public(s), 200)


# ---------------------------------------------------------------------------
# Styling appointments
# ---------------------------------------------------------------------------
def _appt_owner_check(role, uid, appt):
    if role == "Customer" and appt["customer_id"] != uid:
        forbidden()
    if role == "FitSpecialist" and appt["specialist_id"] != uid:
        forbidden()


def _specialist_conflict(appt_id, specialist_id, s_dt, e_dt, buffer_min):
    buf = timedelta(minutes=buffer_min)
    for a in db.appointments.values():
        if a["id"] == appt_id:
            continue
        if a["specialist_id"] != specialist_id:
            continue
        if a["status"] not in ("CONFIRMED", "RESCHEDULE_REQUESTED"):
            continue
        a_start = parse_dt(a["start_at"])
        a_end = parse_dt(a["end_at"])
        if (s_dt - buf) < a_end and a_start < (e_dt + buf):
            return True
    return False


def _customer_conflict(appt_id, customer_id, s_dt, e_dt):
    for a in db.appointments.values():
        if a["id"] == appt_id:
            continue
        if a["customer_id"] != customer_id:
            continue
        if a["status"] != "CONFIRMED":
            continue
        a_start = parse_dt(a["start_at"])
        a_end = parse_dt(a["end_at"])
        if s_dt < a_end and a_start < e_dt:
            return True
    return False


@app.route("/appointments", methods=["POST"])
def appointment_create():
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"Customer"})
    specialist_id = require(body, "specialist_id", "string")
    start_at = require(body, "start_at", "datetime")
    end_at = require(body, "end_at", "datetime")
    topic = optional(body, "topic", "string", default="GENERAL", enum=APPOINTMENT_TOPICS)
    find_or_404(db.specialists, specialist_id)
    rec = new_record()
    rec.update({
        "customer_id": uid,
        "specialist_id": specialist_id,
        "start_at": iso(parse_dt(start_at)),
        "end_at": iso(parse_dt(end_at)),
        "topic": topic,
        "status": "REQUESTED",
        "proposed_start_at": None,
        "proposed_end_at": None,
        "late_cancel_fee_cents": 0,
    })
    db.appointments[rec["id"]] = rec
    return ok(public(rec), 201)


@app.route("/appointments/<aid>", methods=["GET"])
def appointment_get(aid):
    role, uid = get_auth()
    require_roles(role, {"Customer", "FitSpecialist", "StoreManager"})
    appt = find_or_404(db.appointments, aid)
    _appt_owner_check(role, uid, appt)
    return ok(public(appt), 200)


@app.route("/appointments", methods=["GET"])
def appointment_list():
    from flask import request
    role, uid = get_auth()
    require_roles(role, {"Customer", "FitSpecialist", "StoreManager"})
    items = sorted_records(db.appointments)
    if role == "Customer":
        items = [a for a in items if a["customer_id"] == uid]
    elif role == "FitSpecialist":
        items = [a for a in items if a["specialist_id"] == uid]
    if request.args.get("customer_id"):
        items = [a for a in items if a["customer_id"] == request.args.get("customer_id")]
    if request.args.get("specialist_id"):
        items = [a for a in items if a["specialist_id"] == request.args.get("specialist_id")]
    limit, offset = paginate_params()
    page, total = apply_pagination(items, limit, offset)
    return ok_list([public(a) for a in page], limit, offset, total)


_APPT_ACTORS = {
    "CONFIRM": {"FitSpecialist", "StoreManager"},
    "RESCHEDULE_REQUEST": {"Customer"},
    "RESCHEDULE_CONFIRM": {"FitSpecialist", "StoreManager"},
    "COMPLETE": {"FitSpecialist"},
    "CANCEL": {"Customer", "FitSpecialist"},
    "NO_SHOW": {"FitSpecialist", "StoreManager"},
}


@app.route("/appointments/<aid>/transition", methods=["POST"])
def appointment_transition(aid):
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"Customer", "FitSpecialist", "StoreManager"})
    action = require(body, "action", "string", enum=set(_APPT_ACTORS.keys()))
    if role not in _APPT_ACTORS[action]:
        forbidden()
    appt = find_or_404(db.appointments, aid)
    _appt_owner_check(role, uid, appt)
    specialist = db.specialists.get(appt["specialist_id"])
    customer = db.customers.get(appt["customer_id"])

    if action == "CONFIRM":
        if appt["status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Appointment not in REQUESTED")
        if specialist["status"] != "ACTIVE":
            raise ApiError("ERR_SPECIALIST_ON_LEAVE", 409, "Specialist on leave")
        if customer is not None and customer["booking_status"] != "ACTIVE":
            raise ApiError("ERR_BOOKING_SUSPENDED", 409, "Customer booking suspended")
        if appt["topic"] != "GENERAL" and appt["topic"] not in specialist["specialties"]:
            raise ApiError("ERR_SPECIALTY_MISMATCH", 409, "Topic not in specialties")
        s_dt = parse_dt(appt["start_at"])
        e_dt = parse_dt(appt["end_at"])
        if _specialist_conflict(appt["id"], appt["specialist_id"], s_dt, e_dt,
                                specialist["buffer_minutes"]):
            raise ApiError("ERR_SPECIALIST_UNAVAILABLE", 409, "Specialist unavailable")
        if _customer_conflict(appt["id"], appt["customer_id"], s_dt, e_dt):
            raise ApiError("ERR_CUSTOMER_DOUBLE_BOOKED", 409, "Customer double booked")
        appt["status"] = "CONFIRMED"

    elif action == "RESCHEDULE_REQUEST":
        if appt["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE", 409, "Appointment not CONFIRMED")
        ps = require(body, "proposed_start_at", "datetime")
        pe = require(body, "proposed_end_at", "datetime")
        ps_dt = parse_dt(ps)
        pe_dt = parse_dt(pe)
        if not (ps_dt < pe_dt):
            raise ApiError("ERR_VALIDATION", 400, "proposed_start_at must be before proposed_end_at")
        appt["proposed_start_at"] = iso(ps_dt)
        appt["proposed_end_at"] = iso(pe_dt)
        appt["status"] = "RESCHEDULE_REQUESTED"

    elif action == "RESCHEDULE_CONFIRM":
        if appt["status"] != "RESCHEDULE_REQUESTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Appointment not RESCHEDULE_REQUESTED")
        s_dt = parse_dt(appt["proposed_start_at"])
        e_dt = parse_dt(appt["proposed_end_at"])
        if _specialist_conflict(appt["id"], appt["specialist_id"], s_dt, e_dt,
                                specialist["buffer_minutes"]):
            raise ApiError("ERR_SPECIALIST_UNAVAILABLE", 409, "Specialist unavailable")
        if _customer_conflict(appt["id"], appt["customer_id"], s_dt, e_dt):
            raise ApiError("ERR_CUSTOMER_DOUBLE_BOOKED", 409, "Customer double booked")
        appt["start_at"] = appt["proposed_start_at"]
        appt["end_at"] = appt["proposed_end_at"]
        appt["proposed_start_at"] = None
        appt["proposed_end_at"] = None
        appt["status"] = "CONFIRMED"

    elif action == "COMPLETE":
        if appt["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE", 409, "Appointment not CONFIRMED")
        if db.clock_now() < parse_dt(appt["end_at"]):
            raise ApiError("ERR_APPOINTMENT_NOT_ENDED", 409, "Appointment not ended")
        appt["status"] = "COMPLETED"

    elif action == "NO_SHOW":
        if appt["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE", 409, "Appointment not CONFIRMED")
        if db.clock_now() < parse_dt(appt["start_at"]):
            raise ApiError("ERR_APPOINTMENT_NOT_STARTED", 409, "Appointment not started")
        appt["status"] = "NO_SHOW"
        if customer is not None:
            customer["no_show_count"] += 1
            if customer["no_show_count"] >= NO_SHOW_SUSPEND_THRESHOLD:
                customer["booking_status"] = "SUSPENDED"
            touch(customer)

    elif action == "CANCEL":
        if appt["status"] not in ("REQUESTED", "CONFIRMED", "RESCHEDULE_REQUESTED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Appointment not cancellable")
        was_confirmed = appt["status"] == "CONFIRMED"
        fee = 0
        if was_confirmed:
            gap = parse_dt(appt["start_at"]) - db.clock_now()
            if gap < timedelta(hours=LATE_CANCEL_WINDOW_HOURS):
                fee = LATE_CANCEL_FEE_CENTS
                if customer is not None:
                    customer["wallet_credit_cents"] = max(
                        0, customer["wallet_credit_cents"] - fee)
                    touch(customer)
        appt["late_cancel_fee_cents"] = fee
        appt["status"] = "CANCELLED"

    touch(appt)
    return ok(public(appt), 200)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@app.route("/orders", methods=["POST"])
def order_create():
    get_body()
    role, uid = get_auth()
    require_roles(role, {"Customer"})
    rec = new_record()
    rec.update({
        "customer_id": uid,
        "payment_status": "PENDING",
        "fulfillment_status": "UNFULFILLED",
        "subtotal_cents": 0,
        "tier_discount_cents": 0,
        "loyalty_redeemed_points": 0,
        "loyalty_redeemed_cents": 0,
        "wallet_applied_cents": 0,
        "total_cents": 0,
        "points_earned": 0,
        "delivered_at": None,
    })
    db.orders[rec["id"]] = rec
    return ok(public(rec), 201)


@app.route("/orders/<oid>", methods=["GET"])
def order_get(oid):
    role, uid = get_auth()
    require_roles(role, {"Customer", "StoreManager"})
    o = find_or_404(db.orders, oid)
    check_owner(role, uid, o["customer_id"])
    return ok(public(o), 200)


@app.route("/orders", methods=["GET"])
def order_list():
    from flask import request
    role, uid = get_auth()
    require_roles(role, {"Customer", "StoreManager"})
    items = sorted_records(db.orders)
    if role == "Customer":
        items = [o for o in items if o["customer_id"] == uid]
    if request.args.get("customer_id"):
        items = [o for o in items if o["customer_id"] == request.args.get("customer_id")]
    limit, offset = paginate_params()
    page, total = apply_pagination(items, limit, offset)
    return ok_list([public(o) for o in page], limit, offset, total)


@app.route("/orders/<oid>/lines", methods=["POST"])
def order_add_line(oid):
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"Customer"})
    o = find_or_404(db.orders, oid)
    check_owner(role, uid, o["customer_id"])
    variant_id = require(body, "variant_id", "string")
    quantity = require(body, "quantity", "integer")
    if quantity < 1:
        raise ApiError("ERR_VALIDATION", 400, "quantity must be >= 1")
    v = find_or_404(db.variants, variant_id)
    if o["payment_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not open for new lines")
    available = v["inventory_on_hand"] - v["inventory_reserved"]
    if available < quantity:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", 409, "Insufficient inventory")
    unit_price = variant_retail(v)
    line = new_record(full=False)
    line.update({
        "order_id": oid,
        "variant_id": variant_id,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "line_total_cents": unit_price * quantity,
    })
    db.order_lines[line["id"]] = line
    v["inventory_reserved"] += quantity
    v["inventory_available"] = v["inventory_on_hand"] - v["inventory_reserved"]
    touch(v)
    return ok(public(line), 201)


@app.route("/orders/<oid>/lines", methods=["GET"])
def order_list_lines(oid):
    role, uid = get_auth()
    require_roles(role, {"Customer", "StoreManager"})
    o = find_or_404(db.orders, oid)
    check_owner(role, uid, o["customer_id"])
    items = [l for l in sorted_records(db.order_lines) if l["order_id"] == oid]
    limit, offset = paginate_params()
    page, total = apply_pagination(items, limit, offset)
    return ok_list([public(l) for l in page], limit, offset, total)


def _order_lines_of(oid):
    return [l for l in sorted_records(db.order_lines) if l["order_id"] == oid]


@app.route("/orders/<oid>/checkout", methods=["POST"])
def order_checkout(oid):
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"Customer"})
    o = find_or_404(db.orders, oid)
    check_owner(role, uid, o["customer_id"])
    redeem_points = optional(body, "loyalty_redeem_points", "integer", default=0)
    use_wallet = optional(body, "use_wallet_credit", "boolean", default=False)
    if redeem_points is None:
        redeem_points = 0
    if redeem_points < 0:
        raise ApiError("ERR_VALIDATION", 400, "loyalty_redeem_points must be >= 0")

    # state (5)
    if o["payment_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not in PENDING payment state")
    customer = db.customers.get(o["customer_id"])
    # referential (7): account active
    if customer is not None and customer["account_status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 409, "Customer account not active")
    # fiscal (9): non-empty order, then sufficient points
    lines = _order_lines_of(oid)
    if not lines:
        raise ApiError("ERR_EMPTY_ORDER", 409, "Order has no lines")
    balance = customer["loyalty_points_balance"] if customer else 0
    if redeem_points > balance:
        raise ApiError("ERR_INSUFFICIENT_POINTS", 409, "Insufficient loyalty points")

    subtotal = sum(l["line_total_cents"] for l in lines)
    tier = customer["loyalty_tier"] if customer else "STANDARD"
    tier_discount = pct_of(subtotal, TIER_DISCOUNT[tier])
    after_tier = subtotal - tier_discount
    redeem_cap = pct_of(subtotal, REDEEM_CAP_PCT)
    redeemed_cents = min(redeem_points * REDEEM_VALUE_CENTS_PER_POINT, redeem_cap, after_tier)
    after_redeem = after_tier - redeemed_cents
    if use_wallet and customer is not None:
        wallet_applied = min(customer["wallet_credit_cents"], after_redeem)
    else:
        wallet_applied = 0
    total = after_redeem - wallet_applied

    o["subtotal_cents"] = subtotal
    o["tier_discount_cents"] = tier_discount
    o["loyalty_redeemed_points"] = redeem_points
    o["loyalty_redeemed_cents"] = redeemed_cents
    o["wallet_applied_cents"] = wallet_applied
    o["total_cents"] = total
    o["payment_status"] = "AUTHORIZED"

    if customer is not None and (redeem_points != 0 or wallet_applied != 0):
        customer["loyalty_points_balance"] -= redeem_points
        customer["wallet_credit_cents"] -= wallet_applied
        touch(customer)
    touch(o)
    return ok(public(o), 200)


_ORDER_ACTORS = {
    "CAPTURE": {"StoreManager"},
    "PICK": {"StoreManager"},
    "SHIP": {"StoreManager"},
    "DELIVER": {"StoreManager"},
    "CANCEL": {"Customer", "StoreManager"},
}


@app.route("/orders/<oid>/transition", methods=["POST"])
def order_transition(oid):
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"Customer", "StoreManager"})
    action = require(body, "action", "string", enum=set(_ORDER_ACTORS.keys()))
    if role not in _ORDER_ACTORS[action]:
        forbidden()
    o = find_or_404(db.orders, oid)
    check_owner(role, uid, o["customer_id"])
    customer = db.customers.get(o["customer_id"])

    if action == "CAPTURE":
        if o["payment_status"] != "AUTHORIZED":
            raise ApiError("ERR_INVALID_STATE", 409, "Payment not AUTHORIZED")
        o["payment_status"] = "CAPTURED"

    elif action == "PICK":
        if o["fulfillment_status"] != "UNFULFILLED":
            raise ApiError("ERR_INVALID_STATE", 409, "Fulfillment not UNFULFILLED")
        if o["payment_status"] != "CAPTURED":
            raise ApiError("ERR_INVALID_STATE", 409, "Payment not CAPTURED")
        o["fulfillment_status"] = "PICKING"

    elif action == "SHIP":
        if o["fulfillment_status"] != "PICKING":
            raise ApiError("ERR_INVALID_STATE", 409, "Fulfillment not PICKING")
        for l in _order_lines_of(oid):
            v = db.variants.get(l["variant_id"])
            if v is not None:
                v["inventory_on_hand"] -= l["quantity"]
                v["inventory_reserved"] -= l["quantity"]
                v["inventory_available"] = v["inventory_on_hand"] - v["inventory_reserved"]
                touch(v)
        o["fulfillment_status"] = "SHIPPED"

    elif action == "DELIVER":
        if o["fulfillment_status"] != "SHIPPED":
            raise ApiError("ERR_INVALID_STATE", 409, "Fulfillment not SHIPPED")
        o["delivered_at"] = iso(db.clock_now())
        o["fulfillment_status"] = "DELIVERED"
        if customer is not None:
            o["points_earned"] = earn_loyalty(customer, o["total_cents"])
        else:
            o["points_earned"] = o["total_cents"] // EARN_CENTS_PER_POINT

    elif action == "CANCEL":
        if o["fulfillment_status"] not in ("UNFULFILLED", "PICKING"):
            raise ApiError("ERR_INVALID_STATE", 409, "Order not cancellable")
        for l in _order_lines_of(oid):
            v = db.variants.get(l["variant_id"])
            if v is not None:
                v["inventory_reserved"] -= l["quantity"]
                v["inventory_available"] = v["inventory_on_hand"] - v["inventory_reserved"]
                touch(v)
        cust_changed = False
        if customer is not None:
            if o["loyalty_redeemed_points"] != 0 or o["wallet_applied_cents"] != 0:
                customer["loyalty_points_balance"] += o["loyalty_redeemed_points"]
                customer["wallet_credit_cents"] += o["wallet_applied_cents"]
                cust_changed = True
        if o["payment_status"] == "CAPTURED":
            o["payment_status"] = "REFUNDED"
            if customer is not None:
                customer["wallet_credit_cents"] += o["total_cents"]
                cust_changed = True
        if customer is not None and cust_changed:
            touch(customer)
        o["fulfillment_status"] = "CANCELLED"

    touch(o)
    return ok(public(o), 200)


# ---------------------------------------------------------------------------
# Returns / exchanges
# ---------------------------------------------------------------------------
def _return_owner(ret):
    o = db.orders.get(ret["order_id"])
    return o["customer_id"] if o else None


def _line_product(line):
    v = db.variants.get(line["variant_id"])
    if v is None:
        return None
    return db.products.get(v["product_id"])


@app.route("/returns", methods=["POST"])
def return_create():
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"Customer"})
    order_id = require(body, "order_id", "string")
    return_type = require(body, "return_type", "string", enum=RETURN_TYPES)
    line_ids = require_str_array(body, "line_ids", required=True)
    exchange_variant_id = optional(body, "exchange_variant_id", "string", default=None)
    fit_verdict = optional(body, "fit_verdict", "string", default="TRUE_TO_SIZE", enum=FIT_VERDICTS)
    refund_destination = optional(body, "refund_destination", "string",
                                  default="WALLET", enum=REFUND_DESTINATIONS)

    o = find_or_404(db.orders, order_id)
    check_owner(role, uid, o["customer_id"])
    if exchange_variant_id is not None:
        find_or_404(db.variants, exchange_variant_id)
    for lid in line_ids:
        find_or_404(db.order_lines, lid)

    # state (5): order delivered
    if o["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not delivered")
    # domain (6)
    if return_type == "EXCHANGE" and exchange_variant_id is None:
        raise ApiError("ERR_EXCHANGE_VARIANT_REQUIRED", 409, "exchange_variant_id required")
    for lid in line_ids:
        if db.order_lines[lid]["order_id"] != order_id:
            raise ApiError("ERR_INVALID_LINE_SELECTION", 409, "line not in order")
    # temporal (8): return window
    if o.get("delivered_at"):
        deadline = parse_dt(o["delivered_at"]) + timedelta(days=RETURN_WINDOW_DAYS)
        if db.clock_now() > deadline:
            raise ApiError("ERR_RETURN_WINDOW_CLOSED", 409, "Return window closed")

    provisional = sum(db.order_lines[lid]["line_total_cents"] for lid in line_ids)
    rec = new_record()
    rec.update({
        "order_id": order_id,
        "return_type": return_type,
        "line_ids": line_ids,
        "exchange_variant_id": exchange_variant_id,
        "fit_verdict": fit_verdict,
        "refund_destination": refund_destination,
        "damaged_line_ids": [],
        "status": "REQUESTED",
        "provisional_refund_cents": provisional,
        "restock_fee_cents": 0,
        "final_refund_cents": 0,
        "_exchange_reserved": False,
    })
    db.returns[rec["id"]] = rec
    return ok(public(rec), 201)


@app.route("/returns/<rid>", methods=["GET"])
def return_get(rid):
    role, uid = get_auth()
    require_roles(role, {"Customer", "StoreManager"})
    ret = find_or_404(db.returns, rid)
    check_owner(role, uid, _return_owner(ret))
    return ok(public(ret), 200)


@app.route("/returns", methods=["GET"])
def return_list():
    from flask import request
    role, uid = get_auth()
    require_roles(role, {"Customer", "StoreManager"})
    items = sorted_records(db.returns)
    if role == "Customer":
        items = [r for r in items if _return_owner(r) == uid]
    if request.args.get("order_id"):
        items = [r for r in items if r["order_id"] == request.args.get("order_id")]
    if request.args.get("exchange_variant_id"):
        items = [r for r in items if r["exchange_variant_id"] == request.args.get("exchange_variant_id")]
    limit, offset = paginate_params()
    page, total = apply_pagination(items, limit, offset)
    return ok_list([public(r) for r in page], limit, offset, total)


@app.route("/returns/<rid>/transition", methods=["POST"])
def return_transition(rid):
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"StoreManager"})
    action = require(body, "action", "string",
                     enum={"APPROVE", "INSPECT", "COMPLETE", "REJECT"})
    ret = find_or_404(db.returns, rid)

    if action == "APPROVE":
        if ret["status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Return not REQUESTED")
        ret["status"] = "APPROVED"

    elif action == "INSPECT":
        if ret["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", 409, "Return not APPROVED")
        damaged = require_str_array(body, "damaged_line_ids", required=False, default=[])
        if any(d not in ret["line_ids"] for d in damaged):
            raise ApiError("ERR_INVALID_LINE_SELECTION", 409, "damaged not subset of line_ids")
        ret["damaged_line_ids"] = damaged
        nondamaged = [lid for lid in ret["line_ids"] if lid not in damaged]
        nondamaged_total = sum(db.order_lines[lid]["line_total_cents"] for lid in nondamaged)
        fee_raw = 0
        for lid in nondamaged:
            line = db.order_lines[lid]
            prod = _line_product(line)
            pct = prod["restock_fee_pct"] if prod else 0
            from decimal import Decimal
            fee_raw += Decimal(str(pct)) * Decimal(int(line["line_total_cents"]))
        ret["restock_fee_cents"] = round_half_up(fee_raw)
        ret["final_refund_cents"] = nondamaged_total - ret["restock_fee_cents"]
        for lid in nondamaged:
            line = db.order_lines[lid]
            v = db.variants.get(line["variant_id"])
            if v is not None:
                v["inventory_on_hand"] += line["quantity"]
                v["inventory_available"] = v["inventory_on_hand"] - v["inventory_reserved"]
                touch(v)
        if ret["return_type"] == "EXCHANGE":
            ev = db.variants.get(ret["exchange_variant_id"])
            if ev is not None:
                ev["inventory_reserved"] += 1
                ev["inventory_available"] = ev["inventory_on_hand"] - ev["inventory_reserved"]
                touch(ev)
                ret["_exchange_reserved"] = True
        ret["status"] = "INSPECTED"

    elif action == "COMPLETE":
        if ret["status"] != "INSPECTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Return not INSPECTED")
        order = db.orders.get(ret["order_id"])
        customer = db.customers.get(order["customer_id"]) if order else None
        if ret["return_type"] == "RETURN":
            if ret["refund_destination"] == "WALLET" and customer is not None:
                customer["wallet_credit_cents"] += ret["final_refund_cents"]
                touch(customer)
        else:  # EXCHANGE
            ev = db.variants.get(ret["exchange_variant_id"])
            if ev is not None:
                ev["inventory_reserved"] -= 1
                ev["inventory_on_hand"] -= 1
                ev["inventory_available"] = ev["inventory_on_hand"] - ev["inventory_reserved"]
                touch(ev)
                exch_price = variant_retail(ev)
                net = exch_price - ret["final_refund_cents"]
                if customer is not None:
                    customer["wallet_credit_cents"] -= net
                    touch(customer)
        ret["status"] = "COMPLETED"

    elif action == "REJECT":
        if ret["status"] not in ("REQUESTED", "APPROVED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Return not rejectable")
        if ret["return_type"] == "EXCHANGE" and ret.get("_exchange_reserved"):
            ev = db.variants.get(ret["exchange_variant_id"])
            if ev is not None:
                ev["inventory_reserved"] -= 1
                ev["inventory_available"] = ev["inventory_on_hand"] - ev["inventory_reserved"]
                touch(ev)
            ret["_exchange_reserved"] = False
        ret["status"] = "REJECTED"

    touch(ret)
    return ok(public(ret), 200)


# ---------------------------------------------------------------------------
# Box subscriptions
# ---------------------------------------------------------------------------
@app.route("/box-subscriptions", methods=["POST"])
def subscription_create():
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"Customer"})
    plan_tier = require(body, "plan_tier", "string", enum=PLAN_TIERS)
    cadence = optional(body, "cadence", "string", default="MONTHLY", enum=CADENCES)
    rec = new_record()
    rec.update({
        "customer_id": uid,
        "plan_tier": plan_tier,
        "cadence": cadence,
        "styling_fee_cents": STYLING_FEE_CENTS[plan_tier],
        "status": "ACTIVE",
    })
    db.subscriptions[rec["id"]] = rec
    return ok(public(rec), 201)


@app.route("/box-subscriptions/<sid>", methods=["GET"])
def subscription_get(sid):
    role, uid = get_auth()
    require_roles(role, {"Customer", "StoreManager"})
    sub = find_or_404(db.subscriptions, sid)
    check_owner(role, uid, sub["customer_id"])
    return ok(public(sub), 200)


@app.route("/box-subscriptions", methods=["GET"])
def subscription_list():
    from flask import request
    role, uid = get_auth()
    require_roles(role, {"Customer", "StoreManager"})
    items = sorted_records(db.subscriptions)
    if role == "Customer":
        items = [s for s in items if s["customer_id"] == uid]
    if request.args.get("customer_id"):
        items = [s for s in items if s["customer_id"] == request.args.get("customer_id")]
    limit, offset = paginate_params()
    page, total = apply_pagination(items, limit, offset)
    return ok_list([public(s) for s in page], limit, offset, total)


@app.route("/box-subscriptions/<sid>/status", methods=["POST"])
def subscription_status(sid):
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"Customer"})
    sub = find_or_404(db.subscriptions, sid)
    check_owner(role, uid, sub["customer_id"])
    to_status = require(body, "to_status", "string", enum={"ACTIVE", "PAUSED", "CANCELLED"})
    cur = sub["status"]
    allowed = {
        ("ACTIVE", "PAUSED"), ("PAUSED", "ACTIVE"),
        ("ACTIVE", "CANCELLED"), ("PAUSED", "CANCELLED"),
    }
    if (cur, to_status) not in allowed:
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription status transition not permitted")
    sub["status"] = to_status
    touch(sub)  # increments version
    return ok(public(sub), 200)


@app.route("/box-subscriptions/<sid>/shipments", methods=["POST"])
def shipment_curate(sid):
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"FitSpecialist", "StoreManager"})
    expected_version = require(body, "expected_subscription_version", "integer")
    item_variant_ids = require_str_array(body, "item_variant_ids", required=True)
    sub = find_or_404(db.subscriptions, sid)
    for vid in item_variant_ids:
        find_or_404(db.variants, vid)
    if expected_version != sub["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Subscription version is stale")

    items = []
    for vid in item_variant_ids:
        v = db.variants[vid]
        items.append({"variant_id": vid, "retail_cents": variant_retail(v)})
    rec = new_record()
    rec.update({
        "subscription_id": sid,
        "items": items,
        "kept_variant_ids": [],
        "status": "CURATED",
        "shipped_at": None,
        "provisional_charge_cents": 0,
        "final_charge_cents": 0,
        "points_earned": 0,
    })
    db.shipments[rec["id"]] = rec
    for vid in item_variant_ids:
        v = db.variants[vid]
        v["inventory_reserved"] += 1
        v["inventory_available"] = v["inventory_on_hand"] - v["inventory_reserved"]
        touch(v)
    touch(sub)  # increments version
    return ok(public(rec), 201)


# ---------------------------------------------------------------------------
# Box shipments
# ---------------------------------------------------------------------------
def _shipment_owner(sh):
    sub = db.subscriptions.get(sh["subscription_id"])
    return sub["customer_id"] if sub else None


@app.route("/box-shipments/<shid>", methods=["GET"])
def shipment_get(shid):
    role, uid = get_auth()
    require_roles(role, {"Customer", "FitSpecialist", "StoreManager"})
    sh = find_or_404(db.shipments, shid)
    if role == "Customer" and _shipment_owner(sh) != uid:
        forbidden()
    return ok(public(sh), 200)


@app.route("/box-subscriptions/<sid>/shipments", methods=["GET"])
def subscription_shipments(sid):
    role, uid = get_auth()
    require_roles(role, {"Customer", "StoreManager"})
    sub = find_or_404(db.subscriptions, sid)
    check_owner(role, uid, sub["customer_id"])
    items = [s for s in sorted_records(db.shipments) if s["subscription_id"] == sid]
    limit, offset = paginate_params()
    page, total = apply_pagination(items, limit, offset)
    return ok_list([public(s) for s in page], limit, offset, total)


@app.route("/box-shipments/<shid>/ship", methods=["POST"])
def shipment_ship(shid):
    get_body()
    role, uid = get_auth()
    require_roles(role, {"StoreManager"})
    sh = find_or_404(db.shipments, shid)
    if sh["status"] != "CURATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Shipment not CURATED")
    sub = db.subscriptions.get(sh["subscription_id"])
    if sub is None or sub["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Subscription not active")
    sh["shipped_at"] = iso(db.clock_now())
    sh["provisional_charge_cents"] = sum(it["retail_cents"] for it in sh["items"])
    sh["status"] = "SHIPPED"
    touch(sh)
    return ok(public(sh), 200)


@app.route("/box-shipments/<shid>/keep-decisions", methods=["POST"])
def shipment_keep(shid):
    body = get_body()
    role, uid = get_auth()
    require_roles(role, {"Customer"})
    sh = find_or_404(db.shipments, shid)
    if _shipment_owner(sh) != uid:
        forbidden()
    kept = require_str_array(body, "kept_variant_ids", required=True)
    if sh["status"] != "SHIPPED":
        raise ApiError("ERR_INVALID_STATE", 409, "Shipment not SHIPPED")
    item_vids = {it["variant_id"] for it in sh["items"]}
    if any(k not in item_vids for k in kept):
        raise ApiError("ERR_INVALID_KEEP_SELECTION", 409, "kept not subset of items")
    sh["kept_variant_ids"] = kept
    sh["status"] = "KEPT_PENDING"
    touch(sh)
    return ok(public(sh), 200)


@app.route("/box-shipments/<shid>/settle", methods=["POST"])
def shipment_settle(shid):
    get_body()
    role, uid = get_auth()
    require_roles(role, {"StoreManager"})
    sh = find_or_404(db.shipments, shid)
    if sh["status"] != "KEPT_PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Shipment not KEPT_PENDING")
    gate = parse_dt(sh["shipped_at"]) + timedelta(days=TRYON_WINDOW_DAYS)
    if db.clock_now() < gate:
        raise ApiError("ERR_TRYON_WINDOW_OPEN", 409, "Try-on window still open")

    sub = db.subscriptions.get(sh["subscription_id"])
    customer = db.customers.get(sub["customer_id"]) if sub else None
    tier = customer["loyalty_tier"] if customer else "STANDARD"
    tier_pct = TIER_DISCOUNT[tier]
    from decimal import Decimal
    kept_set = set(sh["kept_variant_ids"])

    kept_subtotal = 0
    for it in sh["items"]:
        if it["variant_id"] in kept_set:
            kept_subtotal += round_half_up(
                Decimal(int(it["retail_cents"])) * (Decimal("1") - Decimal(str(tier_pct))))
    styling_fee = sub["styling_fee_cents"] if sub else 0
    styling_credit = min(styling_fee, kept_subtotal)
    final_charge = kept_subtotal - styling_credit
    sh["final_charge_cents"] = final_charge

    for it in sh["items"]:
        vid = it["variant_id"]
        v = db.variants.get(vid)
        is_kept = vid in kept_set
        if v is not None:
            if is_kept:
                v["inventory_on_hand"] -= 1
                v["inventory_reserved"] -= 1
            else:
                v["inventory_reserved"] -= 1
            v["inventory_available"] = v["inventory_on_hand"] - v["inventory_reserved"]
            touch(v)

    if customer is not None:
        sh["points_earned"] = earn_loyalty(customer, final_charge)
    else:
        sh["points_earned"] = final_charge // EARN_CENTS_PER_POINT
    sh["status"] = "SETTLED"
    touch(sh)
    return ok(public(sh), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
