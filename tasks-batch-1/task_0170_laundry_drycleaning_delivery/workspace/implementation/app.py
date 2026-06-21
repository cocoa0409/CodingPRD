"""Laundry & Dry-Cleaning Delivery API (PRD task 0170).

Single Flask app, in-memory store. No entity seeding at startup.
"""

import os
import datetime
from decimal import Decimal

from flask import Flask, request

import db
import constants as C
import helpers as H
import views as V
from errors import ApiError, err
from response import ok_object, ok_array, error_response

app = Flask(__name__)
app.url_map.strict_slashes = False


# ==========================================================================
# Transport hygiene
# ==========================================================================
# The test client (requests.Session) keeps connections alive and pools them.
# Under the threaded Werkzeug dev server, a pooled socket can be reused by the
# client at the exact moment the server-side worker is tearing the connection
# down, which surfaces to the client as BadStatusLine / ConnectionError. Force
# every response to close its connection so the client always opens a fresh one
# and never races a half-closed keep-alive socket.
@app.after_request
def _no_keep_alive(resp):
    resp.headers["Connection"] = "close"
    return resp


# ==========================================================================
# Error handling
# ==========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_ORDER_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed", 400)


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", "Unexpected: %s" % e, 400)


# ==========================================================================
# Existence helpers (priority 3, left-to-right, PRD §2.7)
# ==========================================================================
def find_plan(pid):
    r = db.plans.get(pid)
    if r is None:
        raise err("ERR_PLAN_NOT_FOUND")
    return r


def find_customer(cid):
    r = db.customers.get(cid)
    if r is None:
        raise err("ERR_CUSTOMER_NOT_FOUND")
    return r


def find_subscription(sid):
    r = db.subscriptions.get(sid)
    if r is None:
        raise err("ERR_SUBSCRIPTION_NOT_FOUND")
    return r


def find_window(wid):
    r = db.route_windows.get(wid)
    if r is None:
        raise err("ERR_WINDOW_NOT_FOUND")
    return r


def find_locker(lid):
    r = db.lockers.get(lid)
    if r is None:
        raise err("ERR_LOCKER_NOT_FOUND")
    return r


def find_order(oid):
    r = db.orders.get(oid)
    if r is None:
        raise err("ERR_ORDER_NOT_FOUND")
    return r


def find_garment_in_order(order, gid):
    r = db.garments.get(gid)
    if r is None or r["order_id"] != order["id"]:
        raise err("ERR_GARMENT_NOT_FOUND")
    return r


def find_assignment(aid):
    r = db.locker_assignments.get(aid)
    if r is None:
        raise err("ERR_ASSIGNMENT_NOT_FOUND")
    return r


def find_claim(cid):
    r = db.claims.get(cid)
    if r is None:
        raise err("ERR_CLAIM_NOT_FOUND")
    return r


def find_note(nid):
    r = db.garment_notes.get(nid)
    if r is None:
        raise err("ERR_GARMENT_NOT_FOUND")
    return r


# Owner check (priority 6, PRD §2.1, §2.9): a Customer must own the resource.
def assert_owner(role, user_id, owner_customer_id):
    if role == "Customer" and user_id != owner_customer_id:
        raise err("ERR_NOT_RESOURCE_OWNER")


def garments_of_order(order_id):
    return [g for g in db.garments.values() if g["order_id"] == order_id]


# ==========================================================================
# SubscriptionPlan
# ==========================================================================
@app.route("/subscription-plans", methods=["POST"])
def create_plan():
    H.require_auth(["PlatformAdmin"])
    body = H.get_body()
    tier = H.req_enum(body, "tier", ["LITE", "PLUS", "PREMIUM"])
    monthly_fee = H.req_int(body, "monthly_fee_cents", minimum=0)
    included = H.req_int(body, "included_wash_fold_grams", minimum=0)
    overage = H.req_int(body, "overage_rate_cents_per_kg", minimum=0)
    discount = H.req_number(body, "dryclean_discount_pct", minimum=0.0, maximum=0.5)
    rush_waived = H.req_bool(body, "rush_waived", default=False)
    active = H.req_bool(body, "active", default=True)
    rec = {
        "tier": tier,
        "monthly_fee_cents": monthly_fee,
        "included_wash_fold_grams": included,
        "overage_rate_cents_per_kg": overage,
        "dryclean_discount_pct": discount,
        "rush_waived": rush_waived,
        "active": active,
    }
    H.stamp_new(rec)
    db.plans[rec["id"]] = rec
    return ok_object(V.plan_view(rec), 201)


@app.route("/subscription-plans", methods=["GET"])
def list_plans():
    H.require_auth(C.ROLES)
    page, limit, offset, total = H.paginate(list(db.plans.values()))
    return ok_array([V.plan_view(r) for r in page], limit, offset, total)


@app.route("/subscription-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    H.require_auth(C.ROLES)
    return ok_object(V.plan_view(find_plan(plan_id)))


# ==========================================================================
# Customer
# ==========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    H.require_auth(["PlatformAdmin"])
    body = H.get_body()
    email = H.req_str(body, "email")
    full_name = H.req_str(body, "full_name")
    default_address = H.req_str(body, "default_address")
    zone_code = H.req_str(body, "zone_code")
    # Unique email across customers (PRD §3.1).
    for c in db.customers.values():
        if c["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email already registered")
    rec = {
        "email": email,
        "full_name": full_name,
        "default_address": default_address,
        "zone_code": zone_code,
        "wallet_credit_cents": 0,
        "risk_score": 0,
        "status": "ACTIVE",
    }
    H.stamp_new(rec)
    db.customers[rec["id"]] = rec
    return ok_object(V.customer_view(rec), 201)


@app.route("/customers", methods=["GET"])
def list_customers():
    H.require_auth(["PlatformAdmin", "DispatchAgent", "ClaimsAdjuster"])
    recs = list(db.customers.values())
    zone = request.args.get("zone_code")
    if zone is not None:
        recs = [r for r in recs if r["zone_code"] == zone]
    page, limit, offset, total = H.paginate(recs)
    return ok_array([V.customer_view(r) for r in page], limit, offset, total)


@app.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    H.require_auth(["PlatformAdmin", "Customer", "DispatchAgent", "ClaimsAdjuster"])
    return ok_object(V.customer_view(find_customer(customer_id)))


@app.route("/customers/<customer_id>/block", methods=["POST"])
def block_customer(customer_id):
    H.require_auth(["PlatformAdmin"])
    c = find_customer(customer_id)
    c["status"] = "BLOCKED"
    H.touch(c)
    return ok_object(V.customer_view(c))


# ==========================================================================
# Subscription
# ==========================================================================
@app.route("/subscriptions", methods=["POST"])
def create_subscription():
    uid, role = H.require_auth(["PlatformAdmin", "Customer"])
    body = H.get_body()
    customer_id = H.req_str(body, "customer_id")
    plan_id = H.req_str(body, "plan_id")
    # Existence (priority 3) before owner (priority 6) and business rules.
    customer = find_customer(customer_id)
    plan = find_plan(plan_id)
    assert_owner(role, uid, customer_id)
    rec = {
        "customer_id": customer_id,
        "plan_id": plan_id,
        "cycle_start_utc": db.iso_now(),
        "cycle_wash_fold_grams_used": 0,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
    }
    H.stamp_new(rec)
    db.subscriptions[rec["id"]] = rec
    return ok_object(V.subscription_view(rec), 201)


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    H.require_auth(["PlatformAdmin", "Customer"])
    recs = list(db.subscriptions.values())
    cid = request.args.get("customer_id")
    pid = request.args.get("plan_id")
    if cid is not None:
        recs = [r for r in recs if r["customer_id"] == cid]
    if pid is not None:
        recs = [r for r in recs if r["plan_id"] == pid]
    page, limit, offset, total = H.paginate(recs)
    return ok_array([V.subscription_view(r) for r in page], limit, offset, total)


@app.route("/subscriptions/<subscription_id>", methods=["GET"])
def get_subscription(subscription_id):
    uid, role = H.require_auth(["PlatformAdmin", "Customer"])
    sub = find_subscription(subscription_id)
    assert_owner(role, uid, sub["customer_id"])
    return ok_object(V.subscription_view(sub))


@app.route("/subscriptions/<subscription_id>/change-plan", methods=["POST"])
def change_plan(subscription_id):
    uid, role = H.require_auth(["PlatformAdmin", "Customer"])
    body = H.get_body()
    sub = find_subscription(subscription_id)
    new_plan_id = H.req_str(body, "plan_id")
    expected_version = H.req_int(body, "expected_subscription_version")
    plan = find_plan(new_plan_id)
    assert_owner(role, uid, sub["customer_id"])
    # State: subscription must be ACTIVE? PRD only names change-plan as a mutating
    # op alongside cancel; OCC is the named guard. (priority 7 state then 16 OCC)
    if sub["status"] != "ACTIVE":
        raise err("ERR_INVALID_SUBSCRIPTION_STATE")
    if expected_version != sub["version"]:
        raise err("ERR_STALE_SUBSCRIPTION_VERSION")
    sub["plan_id"] = new_plan_id
    H.touch(sub)
    return ok_object(V.subscription_view(sub))


@app.route("/subscriptions/<subscription_id>/cancel", methods=["POST"])
def cancel_subscription(subscription_id):
    uid, role = H.require_auth(["PlatformAdmin", "Customer"])
    body = H.get_body()
    sub = find_subscription(subscription_id)
    expected_version = H.req_int(body, "expected_subscription_version")
    assert_owner(role, uid, sub["customer_id"])
    if sub["status"] != "ACTIVE":
        raise err("ERR_INVALID_SUBSCRIPTION_STATE")
    if expected_version != sub["version"]:
        raise err("ERR_STALE_SUBSCRIPTION_VERSION")
    sub["status"] = "CANCELLED"
    H.touch(sub)
    return ok_object(V.subscription_view(sub))


# ==========================================================================
# RouteWindow
# ==========================================================================
@app.route("/route-windows", methods=["POST"])
def create_window():
    H.require_auth(["PlatformAdmin", "DispatchAgent"])
    body = H.get_body()
    zone_code = H.req_str(body, "zone_code")
    window_kind = H.req_enum(body, "window_kind", ["PICKUP", "DELIVERY"])
    start = H.parse_dt(body, "start_utc")
    end = H.parse_dt(body, "end_utc")
    stop_capacity = H.req_int(body, "stop_capacity", minimum=1)
    # priority 5: interval validity
    if not (end > start):
        raise err("ERR_INVALID_INTERVAL")
    rec = {
        "zone_code": zone_code,
        "window_kind": window_kind,
        "start_utc": db.format_ts(start),
        "end_utc": db.format_ts(end),
        "stop_capacity": stop_capacity,
        "booked_stops": 0,
        "status": "OPEN",
        "_start_dt": start,
    }
    H.stamp_new(rec)
    db.route_windows[rec["id"]] = rec
    return ok_object(V.route_window_view(rec), 201)


@app.route("/route-windows", methods=["GET"])
def list_windows():
    H.require_auth(["PlatformAdmin", "Customer", "DispatchAgent"])
    recs = list(db.route_windows.values())
    zone = request.args.get("zone_code")
    kind = request.args.get("window_kind")
    if zone is not None:
        recs = [r for r in recs if r["zone_code"] == zone]
    if kind is not None:
        recs = [r for r in recs if r["window_kind"] == kind]
    page, limit, offset, total = H.paginate(recs)
    return ok_array([V.route_window_view(r) for r in page], limit, offset, total)


@app.route("/route-windows/<window_id>", methods=["GET"])
def get_window(window_id):
    H.require_auth(["PlatformAdmin", "Customer", "DispatchAgent"])
    return ok_object(V.route_window_view(find_window(window_id)))


# ==========================================================================
# Locker
# ==========================================================================
@app.route("/lockers", methods=["POST"])
def create_locker():
    H.require_auth(["PlatformAdmin", "DispatchAgent"])
    body = H.get_body()
    zone_code = H.req_str(body, "zone_code")
    location_label = H.req_str(body, "location_label")
    compartment_count = H.req_int(body, "compartment_count", minimum=1)
    hold_buffer = H.opt_int(body, "hold_buffer_minutes", default=30, minimum=0)
    rec = {
        "zone_code": zone_code,
        "location_label": location_label,
        "compartment_count": compartment_count,
        "hold_buffer_minutes": hold_buffer,
        "status": "OPEN",
    }
    H.stamp_new(rec)
    db.lockers[rec["id"]] = rec
    return ok_object(V.locker_view(rec), 201)


@app.route("/lockers", methods=["GET"])
def list_lockers():
    H.require_auth(["PlatformAdmin", "DispatchAgent"])
    recs = list(db.lockers.values())
    zone = request.args.get("zone_code")
    if zone is not None:
        recs = [r for r in recs if r["zone_code"] == zone]
    page, limit, offset, total = H.paginate(recs)
    return ok_array([V.locker_view(r) for r in page], limit, offset, total)


@app.route("/lockers/<locker_id>", methods=["GET"])
def get_locker(locker_id):
    H.require_auth(["PlatformAdmin", "DispatchAgent"])
    return ok_object(V.locker_view(find_locker(locker_id)))


# ==========================================================================
# Order
# ==========================================================================
@app.route("/orders", methods=["POST"])
def create_order():
    uid, role = H.require_auth(["PlatformAdmin", "Customer"])
    body = H.get_body()
    customer_id = H.req_str(body, "customer_id")
    pickup_window_id = H.req_str(body, "pickup_window_id")
    delivery_window_id = H.req_str(body, "delivery_window_id")
    handoff_method = H.req_enum(body, "handoff_method", ["DOORSTEP", "LOCKER"])
    rush = H.req_bool(body, "rush", default=False)
    subscription_id = body.get("subscription_id")
    if subscription_id is not None and not isinstance(subscription_id, str):
        raise err("ERR_INVALID_REQUEST", "subscription_id must be a string")

    # Existence (priority 3): customer, then subscription (if present), windows.
    customer = find_customer(customer_id)
    if subscription_id:
        find_subscription(subscription_id)
    find_window(pickup_window_id)
    find_window(delivery_window_id)

    # Owner (priority 6)
    assert_owner(role, uid, customer_id)

    # Customer safety (priority 9): not BLOCKED and risk below threshold.
    if customer["status"] == "BLOCKED" or customer["risk_score"] >= C.CUSTOMER_BLOCK_THRESHOLD:
        raise err("ERR_CUSTOMER_BLOCKED")

    rec = {
        "customer_id": customer_id,
        "subscription_id": subscription_id if subscription_id else None,
        "pickup_window_id": pickup_window_id,
        "delivery_window_id": delivery_window_id,
        "handoff_method": handoff_method,
        "rush": rush,
        "ready_by_utc": None,
        "estimate_total_cents": 0,
        "final_total_cents": 0,
        "risk_flag": False,
        "status": "CREATED",
        "_ready_by_dt": None,
        "_pickup_booked": False,
        "_delivery_booked": False,
    }
    H.stamp_new(rec)
    db.orders[rec["id"]] = rec
    return ok_object(V.order_view(rec), 201)


@app.route("/orders", methods=["GET"])
def list_orders():
    H.require_auth(["PlatformAdmin", "Customer", "DispatchAgent", "PlantOperator"])
    recs = list(db.orders.values())
    for key in ("customer_id", "subscription_id", "pickup_window_id",
                "delivery_window_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r.get(key) == val]
    page, limit, offset, total = H.paginate(recs)
    return ok_array([V.order_view(r) for r in page], limit, offset, total)


@app.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    H.require_auth(["PlatformAdmin", "Customer", "DispatchAgent", "PlantOperator", "ClaimsAdjuster"])
    return ok_object(V.order_view(find_order(order_id)))


# -------------------- Garment under Order --------------------
@app.route("/orders/<order_id>/garments", methods=["POST"])
def add_garment(order_id):
    uid, role = H.require_auth(["PlatformAdmin", "Customer"])
    order = find_order(order_id)
    body = H.get_body()
    service_type = H.req_enum(body, "service_type", ["WASH_FOLD", "DRY_CLEAN", "ALTERATION"])
    declared_weight = H.opt_int(body, "declared_weight_grams", default=0, minimum=0)
    declared_piece = H.opt_int(body, "declared_piece_count", default=0, minimum=0)
    alteration_fee = H.opt_int(body, "alteration_fee_cents", default=0, minimum=0)

    assert_owner(role, uid, order["customer_id"])

    # Order must be CREATED to add a garment (PRD §3.2 "Onto a CREATED order").
    if order["status"] != "CREATED":
        raise err("ERR_INVALID_ORDER_STATE")

    # priority 10: service-type field consistency (422).
    if service_type == "WASH_FOLD":
        if not (declared_weight > 0 and declared_piece == 0 and alteration_fee == 0):
            raise err("ERR_SERVICE_TYPE_FIELD_MISMATCH")
    elif service_type == "DRY_CLEAN":
        if not (declared_piece > 0 and declared_weight == 0 and alteration_fee == 0):
            raise err("ERR_SERVICE_TYPE_FIELD_MISMATCH")
    else:  # ALTERATION
        if not (declared_piece > 0 and alteration_fee > 0 and declared_weight == 0):
            raise err("ERR_SERVICE_TYPE_FIELD_MISMATCH")

    rec = {
        "order_id": order_id,
        "service_type": service_type,
        "declared_weight_grams": declared_weight,
        "declared_piece_count": declared_piece,
        "actual_weight_grams": 0,
        "actual_piece_count": 0,
        "alteration_fee_cents": alteration_fee,
        "estimate_line_cents": 0,
        "final_line_cents": 0,
        "status": "INTAKE_PENDING",
    }
    H.stamp_new(rec)
    db.garments[rec["id"]] = rec
    return ok_object(V.garment_view(rec), 201)


@app.route("/orders/<order_id>/garments", methods=["GET"])
def list_garments(order_id):
    H.require_auth(["PlatformAdmin", "Customer", "DispatchAgent", "PlantOperator", "ClaimsAdjuster"])
    order = find_order(order_id)
    recs = garments_of_order(order["id"])
    page, limit, offset, total = H.paginate(recs)
    return ok_array([V.garment_view(r) for r in page], limit, offset, total)


@app.route("/orders/<order_id>/garments/<garment_id>", methods=["GET"])
def get_garment(order_id, garment_id):
    H.require_auth(["PlatformAdmin", "Customer", "DispatchAgent", "PlantOperator", "ClaimsAdjuster"])
    order = find_order(order_id)
    g = find_garment_in_order(order, garment_id)
    return ok_object(V.garment_view(g))


# -------------------- Order transitions --------------------
@app.route("/orders/<order_id>/schedule", methods=["POST"])
def schedule_order(order_id):
    uid, role = H.require_auth(["PlatformAdmin", "Customer"])
    order = find_order(order_id)
    assert_owner(role, uid, order["customer_id"])

    # priority 7: state
    if order["status"] != "CREATED":
        raise err("ERR_INVALID_ORDER_STATE")

    gs = garments_of_order(order["id"])
    # precondition: >= 1 garment
    if len(gs) < 1:
        raise err("ERR_NO_GARMENTS")

    customer = db.customers[order["customer_id"]]
    # customer ACTIVE & risk below threshold
    if customer["status"] == "BLOCKED" or customer["risk_score"] >= C.CUSTOMER_BLOCK_THRESHOLD:
        raise err("ERR_CUSTOMER_BLOCKED")

    pickup = db.route_windows[order["pickup_window_id"]]
    # zone match
    if pickup["window_kind"] != "PICKUP" or pickup["zone_code"] != customer["zone_code"]:
        raise err("ERR_WINDOW_ZONE_MISMATCH")
    # capacity
    if pickup["booked_stops"] >= pickup["stop_capacity"]:
        raise err("ERR_WINDOW_FULL")

    # side effects
    pickup["booked_stops"] += 1
    if pickup["booked_stops"] == pickup["stop_capacity"]:
        pickup["status"] = "FULL"
    H.touch(pickup)
    order["_pickup_booked"] = True

    # estimate pricing
    plan = H.active_plan_for_order(order)
    total = 0
    for g in gs:
        line = H.garment_line_price(g, order, plan,
                                    g["declared_weight_grams"], g["declared_piece_count"])
        g["estimate_line_cents"] = line
        H.touch(g)
        total += line
    order["estimate_total_cents"] = total
    order["status"] = "SCHEDULED"
    H.touch(order)
    return ok_object(V.order_view(order))


@app.route("/orders/<order_id>/pickup", methods=["POST"])
def pickup_order(order_id):
    H.require_auth(["DispatchAgent"])
    order = find_order(order_id)
    if order["status"] != "SCHEDULED":
        raise err("ERR_INVALID_ORDER_STATE")
    hours = C.RUSH_SLA_HOURS if order["rush"] else C.STANDARD_SLA_HOURS
    ready_dt = db.now_dt() + datetime.timedelta(hours=hours)
    order["_ready_by_dt"] = ready_dt
    order["ready_by_utc"] = db.format_ts(ready_dt)
    order["status"] = "PICKED_UP"
    H.touch(order)
    return ok_object(V.order_view(order))


@app.route("/orders/<order_id>/garments/<garment_id>/log-intake", methods=["POST"])
def log_intake(order_id, garment_id):
    H.require_auth(["PlantOperator"])
    order = find_order(order_id)
    g = find_garment_in_order(order, garment_id)
    body = H.get_body()
    actual_weight = H.opt_int(body, "actual_weight_grams", default=0, minimum=0)
    actual_piece = H.opt_int(body, "actual_piece_count", default=0, minimum=0)

    # garment state for transition (priority 7-ish): must be INTAKE_PENDING.
    if g["status"] != "INTAKE_PENDING":
        raise err("ERR_INVALID_ORDER_STATE")
    # parent order must be PICKED_UP
    if order["status"] != "PICKED_UP":
        raise err("ERR_ORDER_NOT_PICKED_UP")
    # measurement consistency (422)
    if g["service_type"] == "WASH_FOLD":
        if not (actual_weight > 0):
            raise err("ERR_INVALID_INTAKE_MEASUREMENT")
    else:
        if not (actual_piece > 0):
            raise err("ERR_INVALID_INTAKE_MEASUREMENT")

    g["actual_weight_grams"] = actual_weight
    g["actual_piece_count"] = actual_piece
    g["status"] = "INTAKE_LOGGED"
    H.touch(g)
    return ok_object(V.garment_view(g))


@app.route("/orders/<order_id>/start-processing", methods=["POST"])
def start_processing(order_id):
    H.require_auth(["PlantOperator"])
    order = find_order(order_id)
    if order["status"] != "PICKED_UP":
        raise err("ERR_INVALID_ORDER_STATE")
    gs = garments_of_order(order["id"])
    if any(g["status"] != "INTAKE_LOGGED" for g in gs):
        raise err("ERR_GARMENTS_NOT_LOGGED")
    for g in gs:
        g["status"] = "CLEANING"
        H.touch(g)
    order["status"] = "IN_PROCESSING"
    H.touch(order)
    return ok_object(V.order_view(order))


@app.route("/orders/<order_id>/garments/<garment_id>/finish-clean", methods=["POST"])
def finish_clean(order_id, garment_id):
    H.require_auth(["PlantOperator"])
    order = find_order(order_id)
    g = find_garment_in_order(order, garment_id)
    if g["status"] != "CLEANING":
        raise err("ERR_GARMENT_NOT_CLEANING")
    plan = H.active_plan_for_order(order)
    line = H.garment_line_price(g, order, plan,
                                g["actual_weight_grams"], g["actual_piece_count"])
    g["final_line_cents"] = line
    g["status"] = "CLEANED"
    H.touch(g)
    return ok_object(V.garment_view(g))


@app.route("/orders/<order_id>/garments/<garment_id>/rewash", methods=["POST"])
def rewash(order_id, garment_id):
    H.require_auth(["PlantOperator"])
    order = find_order(order_id)
    g = find_garment_in_order(order, garment_id)
    if g["status"] != "CLEANED":
        raise err("ERR_GARMENT_NOT_CLEANED")
    if order["status"] not in ("IN_PROCESSING", "QC_HOLD"):
        raise err("ERR_INVALID_ORDER_STATE")
    g["status"] = "CLEANING"
    H.touch(g)
    order["_rewashed_since_qc"] = True
    return ok_object(V.garment_view(g))


@app.route("/orders/<order_id>/garments/<garment_id>/mark-lost", methods=["POST"])
def mark_lost(order_id, garment_id):
    H.require_auth(["PlantOperator"])
    order = find_order(order_id)
    g = find_garment_in_order(order, garment_id)
    if g["status"] not in ("INTAKE_LOGGED", "CLEANING", "CLEANED"):
        raise err("ERR_GARMENT_NOT_LOSABLE")
    if order["status"] not in ("IN_PROCESSING", "QC_HOLD"):
        raise err("ERR_INVALID_ORDER_STATE")
    g["status"] = "LOST"
    H.touch(g)
    customer = db.customers[order["customer_id"]]
    customer["risk_score"] = max(0, customer["risk_score"] + C.LOST_GARMENT_RISK_POINTS)
    H.touch(customer)
    # PRD §2.6: marking a garment lost re-totals the order (lost garments are
    # excluded from final_total) so the order's view is stale for a claim filed
    # against a pre-mark-lost version. PRD §2.8: the affected garment is versioned
    # alongside the order itself — bump the order's version on this cascade.
    H.touch(order)
    return ok_object(V.garment_view(g))


@app.route("/orders/<order_id>/garments/<garment_id>/notes", methods=["POST"])
def add_note(order_id, garment_id):
    uid, role = H.require_auth(["PlantOperator"])
    order = find_order(order_id)
    g = find_garment_in_order(order, garment_id)
    body = H.get_body()
    note_kind = H.req_enum(body, "note_kind", ["STAIN", "DAMAGE"])
    severity = H.req_int(body, "severity", minimum=1, maximum=10)
    description = H.req_str(body, "description", allow_empty=True)

    rec = {
        "garment_id": garment_id,
        "note_kind": note_kind,
        "severity": severity,
        "description": description,
        "logged_by_role": role,
        "id": db.new_id(),
        "created_at": db.iso_now(),
    }
    db.garment_notes[rec["id"]] = rec

    # side effect 1: customer.risk_score += severity
    customer = db.customers[order["customer_id"]]
    customer["risk_score"] = max(0, customer["risk_score"] + severity)
    H.touch(customer)
    # side effect 2: recompute order.risk_flag
    recompute_order_risk_flag(order)
    H.touch(order)
    return ok_object(V.garment_note_view(rec), 201)


def recompute_order_risk_flag(order):
    gids = set(g["id"] for g in garments_of_order(order["id"]))
    severity_sum = sum(n["severity"] for n in db.garment_notes.values()
                       if n["garment_id"] in gids)
    order["risk_flag"] = severity_sum >= C.ORDER_RISK_THRESHOLD


@app.route("/orders/<order_id>/qc-hold", methods=["POST"])
def qc_hold(order_id):
    H.require_auth(["PlantOperator"])
    order = find_order(order_id)
    if order["status"] != "IN_PROCESSING":
        raise err("ERR_INVALID_ORDER_STATE")
    gs = garments_of_order(order["id"])
    if any(g["status"] not in ("CLEANED", "LOST") for g in gs):
        raise err("ERR_GARMENTS_NOT_CLEANED")
    total = sum(g["final_line_cents"] for g in gs if g["status"] != "LOST")
    order["final_total_cents"] = total
    recompute_order_risk_flag(order)
    order["status"] = "QC_HOLD"
    order["_rewashed_since_qc"] = False
    H.touch(order)
    return ok_object(V.order_view(order))


@app.route("/orders/<order_id>/reopen-processing", methods=["POST"])
def reopen_processing(order_id):
    H.require_auth(["PlantOperator"])
    order = find_order(order_id)
    body = H.get_body()
    rework_requested = H.req_bool(body, "rework_requested", default=False)
    if order["status"] != "QC_HOLD":
        raise err("ERR_INVALID_ORDER_STATE")
    rewashed = order.get("_rewashed_since_qc", False)
    if not (rewashed or rework_requested):
        raise err("ERR_NO_REWORK_REQUESTED")
    order["final_total_cents"] = 0
    order["status"] = "IN_PROCESSING"
    H.touch(order)
    return ok_object(V.order_view(order))


@app.route("/orders/<order_id>/qc-pass", methods=["POST"])
def qc_pass(order_id):
    H.require_auth(["PlantOperator"])
    order = find_order(order_id)
    if order["status"] != "QC_HOLD":
        raise err("ERR_INVALID_ORDER_STATE")
    gs = garments_of_order(order["id"])
    non_lost = [g for g in gs if g["status"] != "LOST"]
    if any(g["status"] != "CLEANED" for g in non_lost):
        raise err("ERR_GARMENTS_NOT_CLEANED")

    # pack non-lost garments
    for g in non_lost:
        g["status"] = "PACKED"
        H.touch(g)

    # create DRAFT invoice with waterfall amounts
    customer = db.customers[order["customer_id"]]
    gross = order["final_total_cents"]

    # subscription_billing (PRD §3.6)
    subscription_credit = 0
    sub = None
    sub_id = order.get("subscription_id")
    if sub_id:
        sub = db.subscriptions.get(sub_id)
        if sub is not None and sub["status"] == "ACTIVE":
            plan = db.plans.get(sub["plan_id"])
            if plan is not None:
                wf_grams = sum(g["actual_weight_grams"] for g in gs
                               if g["service_type"] == "WASH_FOLD" and g["status"] != "LOST")
                prior_used = sub["cycle_wash_fold_grams_used"]
                included_remaining = max(0, plan["included_wash_fold_grams"] - prior_used)
                covered_grams = min(wf_grams, included_remaining)
                subscription_credit = H.round_half_up(
                    (Decimal(covered_grams) / Decimal(1000)) * Decimal(C.WF_RATE1_CENTS_PER_KG))
                sub["cycle_wash_fold_grams_used"] = prior_used + wf_grams
                H.touch(sub)
                order["_sub_grams_added"] = wf_grams
                order["_sub_id_billed"] = sub_id
            else:
                sub = None
        else:
            sub = None

    after_sub = max(0, gross - subscription_credit)
    wallet_applied = min(after_sub, customer["wallet_credit_cents"])
    amount_due = max(0, after_sub - wallet_applied)
    # reserve wallet at DRAFT
    customer["wallet_credit_cents"] = customer["wallet_credit_cents"] - wallet_applied
    H.touch(customer)

    inv = {
        "order_id": order["id"],
        "gross_cents": gross,
        "subscription_credit_cents": subscription_credit,
        "wallet_applied_cents": wallet_applied,
        "amount_due_cents": amount_due,
        "status": "DRAFT",
    }
    H.stamp_new(inv)
    db.invoices[inv["id"]] = inv

    order["status"] = "READY"
    H.touch(order)
    return ok_object(V.order_view(order))


def invoice_of_order(order_id):
    for inv in db.invoices.values():
        if inv["order_id"] == order_id:
            return inv
    return None


@app.route("/orders/<order_id>/dispatch-delivery", methods=["POST"])
def dispatch_delivery(order_id):
    H.require_auth(["DispatchAgent"])
    order = find_order(order_id)
    if order["status"] != "READY":
        raise err("ERR_INVALID_ORDER_STATE")
    customer = db.customers[order["customer_id"]]
    delivery = db.route_windows[order["delivery_window_id"]]
    if delivery["window_kind"] != "DELIVERY" or delivery["zone_code"] != customer["zone_code"]:
        raise err("ERR_WINDOW_ZONE_MISMATCH")
    if delivery["booked_stops"] >= delivery["stop_capacity"]:
        raise err("ERR_WINDOW_FULL")
    # delivery_window.start_utc >= ready_by_utc
    if order["_ready_by_dt"] is not None and delivery["_start_dt"] < order["_ready_by_dt"]:
        raise err("ERR_DELIVERY_BEFORE_READY")
    # locker requirement
    if order["handoff_method"] == "LOCKER":
        has_la = any(la["order_id"] == order["id"] and la["status"] in ("OCCUPIED", "RESERVED")
                     for la in db.locker_assignments.values())
        if not has_la:
            raise err("ERR_NO_LOCKER_ASSIGNED")

    delivery["booked_stops"] += 1
    if delivery["booked_stops"] == delivery["stop_capacity"]:
        delivery["status"] = "FULL"
    H.touch(delivery)
    order["_delivery_booked"] = True

    inv = invoice_of_order(order["id"])
    if inv is not None and inv["status"] == "DRAFT":
        inv["status"] = "ISSUED"
        H.touch(inv)

    order["status"] = "OUT_FOR_DELIVERY"
    H.touch(order)
    return ok_object(V.order_view(order))


@app.route("/orders/<order_id>/confirm-delivery", methods=["POST"])
def confirm_delivery(order_id):
    H.require_auth(["DispatchAgent"])
    order = find_order(order_id)
    if order["status"] != "OUT_FOR_DELIVERY":
        raise err("ERR_INVALID_ORDER_STATE")
    if order["handoff_method"] == "LOCKER":
        for la in db.locker_assignments.values():
            if la["order_id"] == order["id"] and la["status"] == "OCCUPIED":
                la["status"] = "RELEASED"
                H.touch(la)
    inv = invoice_of_order(order["id"])
    if inv is not None and inv["status"] == "ISSUED":
        inv["status"] = "PAID"
        H.touch(inv)
    order["status"] = "DELIVERED"
    H.touch(order)
    return ok_object(V.order_view(order))


@app.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    uid, role = H.require_auth(["PlatformAdmin", "Customer"])
    order = find_order(order_id)
    body = H.get_body()
    expected_version = H.req_int(body, "expected_order_version")
    assert_owner(role, uid, order["customer_id"])
    if order["status"] in ("OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"):
        raise err("ERR_INVALID_ORDER_STATE")
    if expected_version != order["version"]:
        raise err("ERR_STALE_ORDER_VERSION")

    # unwind pickup booking
    if order.get("_pickup_booked"):
        pickup = db.route_windows.get(order["pickup_window_id"])
        if pickup is not None and pickup["booked_stops"] > 0:
            pickup["booked_stops"] -= 1
            if pickup["status"] == "FULL":
                pickup["status"] = "OPEN"
            H.touch(pickup)
        order["_pickup_booked"] = False
    # unwind delivery booking
    if order.get("_delivery_booked"):
        delivery = db.route_windows.get(order["delivery_window_id"])
        if delivery is not None and delivery["booked_stops"] > 0:
            delivery["booked_stops"] -= 1
            if delivery["status"] == "FULL":
                delivery["status"] = "OPEN"
            H.touch(delivery)
        order["_delivery_booked"] = False
    # release locker assignments
    for la in db.locker_assignments.values():
        if la["order_id"] == order["id"] and la["status"] in ("RESERVED", "OCCUPIED"):
            la["status"] = "RELEASED"
            H.touch(la)
    # void DRAFT invoice
    inv = invoice_of_order(order["id"])
    if inv is not None and inv["status"] == "DRAFT":
        inv["status"] = "VOID"
        # restore wallet
        customer = db.customers[order["customer_id"]]
        customer["wallet_credit_cents"] = customer["wallet_credit_cents"] + inv["wallet_applied_cents"]
        H.touch(customer)
        # reverse subscription tally increment
        billed_sub_id = order.get("_sub_id_billed")
        grams_added = order.get("_sub_grams_added", 0)
        if billed_sub_id and grams_added:
            sub = db.subscriptions.get(billed_sub_id)
            if sub is not None:
                sub["cycle_wash_fold_grams_used"] = max(0, sub["cycle_wash_fold_grams_used"] - grams_added)
                H.touch(sub)
            order["_sub_id_billed"] = None
            order["_sub_grams_added"] = 0
        H.touch(inv)

    order["status"] = "CANCELLED"
    H.touch(order)
    return ok_object(V.order_view(order))


@app.route("/orders/<order_id>/invoice", methods=["GET"])
def get_order_invoice(order_id):
    H.require_auth(["PlatformAdmin", "Customer", "DispatchAgent"])
    order = find_order(order_id)
    recs = [inv for inv in db.invoices.values() if inv["order_id"] == order["id"]]
    page, limit, offset, total = H.paginate(recs)
    return ok_array([V.invoice_view(r) for r in page], limit, offset, total)


# ==========================================================================
# GarmentNote reads
# ==========================================================================
@app.route("/garment-notes", methods=["GET"])
def list_notes():
    H.require_auth(["PlatformAdmin", "PlantOperator", "ClaimsAdjuster"])
    recs = list(db.garment_notes.values())
    gid = request.args.get("garment_id")
    if gid is not None:
        recs = [r for r in recs if r["garment_id"] == gid]
    page, limit, offset, total = H.paginate(recs)
    return ok_array([V.garment_note_view(r) for r in page], limit, offset, total)


@app.route("/garment-notes/<note_id>", methods=["GET"])
def get_note(note_id):
    H.require_auth(["PlatformAdmin", "PlantOperator", "ClaimsAdjuster"])
    return ok_object(V.garment_note_view(find_note(note_id)))


# ==========================================================================
# LockerAssignment
# ==========================================================================
@app.route("/locker-assignments", methods=["POST"])
def create_assignment():
    H.require_auth(["PlatformAdmin", "DispatchAgent"])
    body = H.get_body()
    order_id = H.req_str(body, "order_id")
    locker_id = H.req_str(body, "locker_id")
    compartment_index = H.req_int(body, "compartment_index", minimum=1)
    hold_start = H.parse_dt(body, "hold_start_utc")
    hold_end = H.parse_dt(body, "hold_end_utc")

    # existence (priority 3)
    order = find_order(order_id)
    locker = find_locker(locker_id)

    # compartment range against locker
    if compartment_index > locker["compartment_count"]:
        raise err("ERR_INVALID_REQUEST", "compartment_index out of range")

    # interval validity (priority 5)
    if not (hold_end > hold_start):
        raise err("ERR_INVALID_INTERVAL")

    # compartment temporal overlap incl. buffer (priority 13)
    buffer = datetime.timedelta(minutes=locker["hold_buffer_minutes"])
    for la in db.locker_assignments.values():
        if la["locker_id"] != locker_id:
            continue
        if la["compartment_index"] != compartment_index:
            continue
        if la["status"] in ("RELEASED", "EXPIRED"):
            continue
        ex_start = la["_hold_start_dt"]
        ex_end = la["_hold_end_dt"] + buffer
        # overlap if new starts before existing(+buffer) ends and new ends after existing starts
        if hold_start < ex_end and hold_end > ex_start:
            raise err("ERR_LOCKER_COMPARTMENT_CONFLICT")

    rec = {
        "order_id": order_id,
        "locker_id": locker_id,
        "compartment_index": compartment_index,
        "hold_start_utc": db.format_ts(hold_start),
        "hold_end_utc": db.format_ts(hold_end),
        "status": "RESERVED",
        "_hold_start_dt": hold_start,
        "_hold_end_dt": hold_end,
    }
    H.stamp_new(rec)
    db.locker_assignments[rec["id"]] = rec
    return ok_object(V.locker_assignment_view(rec), 201)


@app.route("/locker-assignments", methods=["GET"])
def list_assignments():
    H.require_auth(["PlatformAdmin", "DispatchAgent"])
    recs = list(db.locker_assignments.values())
    oid = request.args.get("order_id")
    lid = request.args.get("locker_id")
    if oid is not None:
        recs = [r for r in recs if r["order_id"] == oid]
    if lid is not None:
        recs = [r for r in recs if r["locker_id"] == lid]
    page, limit, offset, total = H.paginate(recs)
    return ok_array([V.locker_assignment_view(r) for r in page], limit, offset, total)


@app.route("/locker-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    H.require_auth(["PlatformAdmin", "DispatchAgent"])
    return ok_object(V.locker_assignment_view(find_assignment(assignment_id)))


@app.route("/locker-assignments/<assignment_id>/occupy", methods=["POST"])
def occupy_assignment(assignment_id):
    H.require_auth(["DispatchAgent"])
    la = find_assignment(assignment_id)
    if la["status"] != "RESERVED":
        raise err("ERR_INVALID_ASSIGNMENT_STATE")
    order = db.orders.get(la["order_id"])
    if order is None or order["status"] != "READY":
        raise err("ERR_INVALID_ORDER_STATE")
    la["status"] = "OCCUPIED"
    H.touch(la)
    return ok_object(V.locker_assignment_view(la))


@app.route("/locker-assignments/<assignment_id>/release", methods=["POST"])
def release_assignment(assignment_id):
    H.require_auth(["DispatchAgent"])
    la = find_assignment(assignment_id)
    if la["status"] != "OCCUPIED":
        raise err("ERR_INVALID_ASSIGNMENT_STATE")
    la["status"] = "RELEASED"
    H.touch(la)
    return ok_object(V.locker_assignment_view(la))


@app.route("/locker-assignments/<assignment_id>/expire", methods=["POST"])
def expire_assignment(assignment_id):
    H.require_auth(["DispatchAgent"])
    la = find_assignment(assignment_id)
    if la["status"] not in ("RESERVED", "OCCUPIED"):
        raise err("ERR_INVALID_ASSIGNMENT_STATE")
    if db.now_dt() < la["_hold_end_dt"]:
        raise err("ERR_HOLD_NOT_EXPIRED")
    la["status"] = "EXPIRED"
    H.touch(la)
    return ok_object(V.locker_assignment_view(la))


# ==========================================================================
# Claim
# ==========================================================================
@app.route("/claims", methods=["POST"])
def create_claim():
    uid, role = H.require_auth(["PlatformAdmin", "Customer"])
    body = H.get_body()
    order_id = H.req_str(body, "order_id")
    subject_kind = H.req_enum(body, "subject_kind", ["ORDER", "GARMENT"])
    declared_value = H.req_int(body, "declared_value_cents", minimum=1)
    expected_version = H.req_int(body, "expected_order_version")
    garment_id = body.get("garment_id")
    if garment_id is not None and not isinstance(garment_id, str):
        raise err("ERR_INVALID_REQUEST", "garment_id must be a string")

    # existence (priority 3): order, then garment if provided
    order = find_order(order_id)
    garment = None
    if garment_id:
        garment = db.garments.get(garment_id)
        if garment is None:
            raise err("ERR_GARMENT_NOT_FOUND")

    # owner (priority 6) via order's customer
    assert_owner(role, uid, order["customer_id"])

    # claim subject integrity (priority 15, 422)
    if subject_kind == "GARMENT":
        if not garment_id:
            raise err("ERR_CLAIM_SUBJECT_MISMATCH")
        if garment is None or garment["order_id"] != order_id:
            raise err("ERR_CLAIM_SUBJECT_MISMATCH")
    else:  # ORDER
        if garment_id:
            raise err("ERR_CLAIM_SUBJECT_MISMATCH")

    # OCC (priority 16)
    if expected_version != order["version"]:
        raise err("ERR_STALE_ORDER_VERSION")

    rec = {
        "order_id": order_id,
        "subject_kind": subject_kind,
        "garment_id": garment_id if garment_id else None,
        "declared_value_cents": declared_value,
        "settlement_cents": 0,
        "appeal_count": 0,
        "status": "SUBMITTED",
    }
    H.stamp_new(rec)
    db.claims[rec["id"]] = rec
    return ok_object(V.claim_view(rec), 201)


@app.route("/claims", methods=["GET"])
def list_claims():
    uid, role = H.require_auth(["PlatformAdmin", "ClaimsAdjuster", "Customer"])
    recs = list(db.claims.values())
    oid = request.args.get("order_id")
    gid = request.args.get("garment_id")
    status = request.args.get("status")
    if oid is not None:
        recs = [r for r in recs if r["order_id"] == oid]
    if gid is not None:
        recs = [r for r in recs if r["garment_id"] == gid]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    # Customer sees only their own claims (PRD §2.1 ownership).
    if role == "Customer":
        recs = [r for r in recs if db.orders.get(r["order_id"], {}).get("customer_id") == uid]
    page, limit, offset, total = H.paginate(recs)
    return ok_array([V.claim_view(r) for r in page], limit, offset, total)


@app.route("/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    uid, role = H.require_auth(["PlatformAdmin", "ClaimsAdjuster", "Customer"])
    claim = find_claim(claim_id)
    if role == "Customer":
        order = db.orders.get(claim["order_id"])
        if order is None or order["customer_id"] != uid:
            raise err("ERR_NOT_RESOURCE_OWNER")
    return ok_object(V.claim_view(claim))


@app.route("/claims/<claim_id>/investigate", methods=["POST"])
def investigate_claim(claim_id):
    H.require_auth(["ClaimsAdjuster"])
    claim = find_claim(claim_id)
    if claim["status"] != "SUBMITTED":
        raise err("ERR_INVALID_CLAIM_STATE")
    claim["status"] = "INVESTIGATING"
    H.touch(claim)
    return ok_object(V.claim_view(claim))


@app.route("/claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    H.require_auth(["ClaimsAdjuster"])
    claim = find_claim(claim_id)
    if claim["status"] != "INVESTIGATING":
        raise err("ERR_INVALID_CLAIM_STATE")
    if claim["subject_kind"] == "GARMENT":
        garment = db.garments.get(claim["garment_id"])
        if garment is None or garment["status"] != "LOST":
            raise err("ERR_CLAIM_GARMENT_NOT_LOST")
    # settlement waterfall
    claim["settlement_cents"] = compute_settlement(claim)
    claim["status"] = "APPROVED"
    H.touch(claim)
    return ok_object(V.claim_view(claim))


def compute_settlement(claim):
    capped = min(claim["declared_value_cents"], C.PER_ITEM_CAP_CENTS)
    depreciated = H.round_half_up(Decimal(capped) * (Decimal(1) - Decimal(C.DEPRECIATION_PCT)))
    already_paid = sum(c["settlement_cents"] for c in db.claims.values()
                       if c["order_id"] == claim["order_id"]
                       and c["id"] != claim["id"]
                       and c["status"] in ("APPROVED", "SETTLED"))
    remaining_ceiling = max(0, C.ORDER_PAYOUT_CEILING_CENTS - already_paid)
    return min(depreciated, remaining_ceiling)


@app.route("/claims/<claim_id>/reject", methods=["POST"])
def reject_claim(claim_id):
    H.require_auth(["ClaimsAdjuster"])
    claim = find_claim(claim_id)
    if claim["status"] != "INVESTIGATING":
        raise err("ERR_INVALID_CLAIM_STATE")
    claim["settlement_cents"] = 0
    claim["status"] = "REJECTED"
    H.touch(claim)
    return ok_object(V.claim_view(claim))


@app.route("/claims/<claim_id>/appeal", methods=["POST"])
def appeal_claim(claim_id):
    uid, role = H.require_auth(["PlatformAdmin", "Customer"])
    claim = find_claim(claim_id)
    if role == "Customer":
        order = db.orders.get(claim["order_id"])
        if order is None or order["customer_id"] != uid:
            raise err("ERR_NOT_RESOURCE_OWNER")
    if claim["status"] != "REJECTED":
        raise err("ERR_INVALID_CLAIM_STATE")
    if claim["appeal_count"] >= C.MAX_APPEALS:
        raise err("ERR_APPEAL_LIMIT_REACHED")
    claim["appeal_count"] += 1
    claim["status"] = "INVESTIGATING"
    H.touch(claim)
    return ok_object(V.claim_view(claim))


@app.route("/claims/<claim_id>/finalize-denial", methods=["POST"])
def finalize_denial(claim_id):
    H.require_auth(["ClaimsAdjuster"])
    claim = find_claim(claim_id)
    if claim["status"] != "REJECTED":
        raise err("ERR_INVALID_CLAIM_STATE")
    if claim["appeal_count"] < C.MAX_APPEALS:
        raise err("ERR_APPEAL_LIMIT_NOT_REACHED")
    claim["status"] = "DENIED_FINAL"
    H.touch(claim)
    return ok_object(V.claim_view(claim))


@app.route("/claims/<claim_id>/settle", methods=["POST"])
def settle_claim(claim_id):
    H.require_auth(["ClaimsAdjuster"])
    claim = find_claim(claim_id)
    if claim["status"] != "APPROVED":
        raise err("ERR_INVALID_CLAIM_STATE")
    order = db.orders.get(claim["order_id"])
    customer = db.customers.get(order["customer_id"]) if order else None
    if customer is not None:
        customer["wallet_credit_cents"] = customer["wallet_credit_cents"] + claim["settlement_cents"]
        customer["risk_score"] = max(0, customer["risk_score"] + C.SETTLED_CLAIM_RISK_POINTS)
        H.touch(customer)
    claim["status"] = "SETTLED"
    H.touch(claim)
    return ok_object(V.claim_view(claim))


# ==========================================================================
# Clock (PRD §3.11)
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    H.require_auth(["PlatformAdmin"])
    body = H.get_body()
    iso = H.parse_dt(body, "to_iso8601")
    db.set_clock(iso)
    return ok_object({})


# ==========================================================================
# Entry point
# ==========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
