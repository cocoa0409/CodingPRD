"""PCB Fabrication API — Flask application entry point."""

import os
import math
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

from db import store, new_store
from errors import *
from response import success_object, success_list, error_response
from middleware import get_auth, require_roles, check_customer_ownership
import services as svc

app = Flask(__name__)


# ---- Error handler ----

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response(ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(500)
def handle_internal_error(e):
    return error_response("ERR_INTERNAL", str(e), 500)


# ---- Pagination helper ----

def parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


# ---- Validation helpers ----

def require_fields(body, *fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(ERR_VALIDATION, f"Missing required field: {f}", 400)


def optional_field(body, field, default=None):
    return body.get(field, default)


def validate_enum(value, allowed, field_name):
    if value not in allowed:
        raise ApiError(ERR_VALIDATION, f"Invalid {field_name}: {value}", 400)
    return value


def validate_int(value, field_name, min_val=None, max_val=None):
    try:
        v = int(value)
    except (ValueError, TypeError):
        raise ApiError(ERR_VALIDATION, f"Invalid integer for {field_name}", 400)
    if min_val is not None and v < min_val:
        raise ApiError(ERR_VALIDATION, f"{field_name} must be >= {min_val}", 400)
    if max_val is not None and v > max_val:
        raise ApiError(ERR_VALIDATION, f"{field_name} must be <= {max_val}", 400)
    return v


def validate_float(value, field_name, min_val=None):
    try:
        v = float(value)
    except (ValueError, TypeError):
        raise ApiError(ERR_VALIDATION, f"Invalid number for {field_name}", 400)
    if min_val is not None and v < min_val:
        raise ApiError(ERR_VALIDATION, f"{field_name} must be >= {min_val}", 400)
    return v


def validate_positive_number(value, field_name):
    try:
        v = float(value)
    except (ValueError, TypeError):
        raise ApiError(ERR_VALIDATION, f"Invalid number for {field_name}", 400)
    if v <= 0:
        raise ApiError(ERR_VALIDATION, f"{field_name} must be > 0", 400)
    return v


def validate_bool(value, field_name):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
    raise ApiError(ERR_VALIDATION, f"Invalid boolean for {field_name}", 400)


# ==============================================================================
# Clock
# ==============================================================================

@app.route("/pcb/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = require_roles("FabAdmin")
    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "to_iso8601")
    try:
        new_clock = svc.parse_iso(body["to_iso8601"])
    except Exception:
        raise ApiError(ERR_VALIDATION, "Invalid to_iso8601", 400)
    store.logical_clock = new_clock
    # Evaluate all lot expirations
    for lot in list(store.laminate_lots.values()):
        svc.recompute_lot_status(lot)
    return success_object({"current_utc": svc.iso_str(store.logical_clock)})


# ==============================================================================
# Customers
# ==============================================================================

@app.route("/pcb/customers", methods=["POST"])
def create_customer():
    user_id, role = require_roles("FabAdmin")
    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "company_name", "contact_email", "credit_limit_cents")

    email = body["contact_email"]
    for c in store.customers.values():
        if c["contact_email"] == email:
            raise ApiError(ERR_DUPLICATE_EMAIL, "contact_email already registered", 409)

    credit_limit = validate_int(body["credit_limit_cents"], "credit_limit_cents", min_val=0)
    tax_exempt = optional_field(body, "tax_exempt", False)
    if not isinstance(tax_exempt, bool):
        tax_exempt = validate_bool(tax_exempt, "tax_exempt")

    fields = svc.make_common_fields()
    customer = {
        **fields,
        "company_name": body["company_name"],
        "contact_email": email,
        "credit_limit_cents": credit_limit,
        "tax_exempt": tax_exempt,
    }
    store.customers[customer["id"]] = customer
    return success_object(svc.serialize_customer(customer), 201)


@app.route("/pcb/customers/<cid>", methods=["GET"])
def get_customer(cid):
    user_id, role = require_roles(
        "FabAdmin", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "Customer"
    )
    c = svc.get_customer(cid)
    check_customer_ownership(user_id, role, c["id"])
    return success_object(svc.serialize_customer(c))


@app.route("/pcb/customers", methods=["GET"])
def list_customers():
    user_id, role = require_roles("FabAdmin", "SalesEngineer")
    limit, offset = parse_pagination()
    items = sorted(store.customers.values(), key=lambda c: c["created_at"])
    page, total = paginate([svc.serialize_customer(c) for c in items], limit, offset)
    return success_list(page, limit, offset, total)


# ==============================================================================
# Quick-Turn Lanes
# ==============================================================================

@app.route("/pcb/quick-turn-lanes", methods=["POST"])
def create_lane():
    user_id, role = require_roles("FabAdmin")
    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "lane_code", "turn_days", "capacity_boards_per_day", "premium_multiplier")

    turn_days = validate_int(body["turn_days"], "turn_days", min_val=1)
    capacity = validate_int(body["capacity_boards_per_day"], "capacity_boards_per_day", min_val=1)
    premium = validate_float(body["premium_multiplier"], "premium_multiplier", min_val=1.0)
    active = optional_field(body, "active", True)
    if not isinstance(active, bool):
        active = validate_bool(active, "active")

    # Check unique lane_code
    for l in store.quick_turn_lanes.values():
        if l["lane_code"] == body["lane_code"]:
            raise ApiError(ERR_VALIDATION, "lane_code already exists", 400)

    fields = svc.make_common_fields()
    lane = {
        **fields,
        "lane_code": body["lane_code"],
        "turn_days": turn_days,
        "capacity_boards_per_day": capacity,
        "premium_multiplier": premium,
        "active": active,
    }
    store.quick_turn_lanes[lane["id"]] = lane
    return success_object(svc.serialize_quick_turn_lane(lane), 201)


@app.route("/pcb/quick-turn-lanes", methods=["GET"])
def list_lanes():
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    limit, offset = parse_pagination()
    items = sorted(store.quick_turn_lanes.values(), key=lambda l: l["created_at"])
    page, total = paginate([svc.serialize_quick_turn_lane(l) for l in items], limit, offset)
    return success_list(page, limit, offset, total)


@app.route("/pcb/quick-turn-lanes/<lid>", methods=["GET"])
def get_lane(lid):
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    lane = svc.get_lane(lid)
    return success_object(svc.serialize_quick_turn_lane(lane))


@app.route("/pcb/quick-turn-lanes/<lid>/slots", methods=["GET"])
def list_lane_slots(lid):
    user_id, role = require_roles(
        "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    lane = svc.get_lane(lid)
    limit, offset = parse_pagination()

    ship_date_filter = request.args.get("ship_date")
    items = []
    for c in store.lane_slot_commitments.values():
        if c["lane_id"] != lid:
            continue
        if ship_date_filter:
            try:
                fdt = svc._ship_date_key(svc.parse_iso(ship_date_filter))
                if c["ship_date"] != fdt:
                    continue
            except Exception:
                continue
        items.append(c)
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate([svc.serialize_lane_slot_commitment(c) for c in items], limit, offset)
    return success_list(page, limit, offset, total)


# ==============================================================================
# Fab Orders
# ==============================================================================

@app.route("/pcb/fab-orders", methods=["POST"])
def create_fab_order():
    user_id, role = require_roles("Customer", "SalesEngineer")
    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "customer_id", "service_lane", "board_x_mils", "board_y_mils",
                   "layer_count", "surface_finish", "quantity_boards", "requested_ship_date")

    customer_id = body["customer_id"]
    service_lane = validate_enum(body["service_lane"], ["STANDARD", "QUICK_TURN"], "service_lane")

    # Existence: customer
    if customer_id not in store.customers:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "customer_id not found", 422)

    # Customer ownership
    if role == "Customer" and user_id != customer_id:
        raise ApiError(ERR_NOT_OWNER, "Customer can only create orders for itself", 403)

    quick_turn_lane_id = optional_field(body, "quick_turn_lane_id")
    if service_lane == "QUICK_TURN":
        if not quick_turn_lane_id:
            raise ApiError(ERR_VALIDATION, "quick_turn_lane_id required for QUICK_TURN", 400)
        if quick_turn_lane_id not in store.quick_turn_lanes:
            raise ApiError(ERR_REFERENCE_NOT_FOUND, "quick_turn_lane_id not found", 422)
    else:
        if quick_turn_lane_id is not None:
            raise ApiError(ERR_VALIDATION, "quick_turn_lane_id must be null for STANDARD", 400)
        quick_turn_lane_id = None

    # Lane active check
    if quick_turn_lane_id:
        lane = store.quick_turn_lanes[quick_turn_lane_id]
        if not lane["active"]:
            raise ApiError(ERR_LANE_INACTIVE, "Lane is not active", 409)

    surface_finish = validate_enum(body["surface_finish"],
                                   ["HASL", "OSP", "ENIG", "IMMERSION_SILVER", "HARD_GOLD"],
                                   "surface_finish")

    # Finish-lane incompatibility
    if surface_finish == "IMMERSION_SILVER" and quick_turn_lane_id:
        lane = store.quick_turn_lanes[quick_turn_lane_id]
        if lane["turn_days"] <= 3:
            raise ApiError(ERR_FINISH_LANE_INCOMPATIBLE,
                           "IMMERSION_SILVER incompatible with turn_days <= 3", 422)

    # Ship date check
    try:
        ship_date = svc.parse_iso(body["requested_ship_date"])
    except Exception:
        raise ApiError(ERR_VALIDATION, "Invalid requested_ship_date", 400)
    if ship_date <= store.logical_clock:
        raise ApiError(ERR_SHIP_DATE_IN_PAST, "requested_ship_date must be strictly after the logical clock", 422)

    # Field validation
    board_x = validate_int(body["board_x_mils"], "board_x_mils", min_val=1)
    board_y = validate_int(body["board_y_mils"], "board_y_mils", min_val=1)
    layer_count = validate_int(body["layer_count"], "layer_count")
    if layer_count not in (2, 4, 6, 8):
        raise ApiError(ERR_VALIDATION, "layer_count must be one of 2, 4, 6, 8", 400)
    quantity = validate_int(body["quantity_boards"], "quantity_boards", min_val=1)

    store.order_number_seq += 1
    order_number = f"PCB-{store.order_number_seq:06d}"

    fields = svc.make_common_fields()
    order = {
        **fields,
        "customer_id": customer_id,
        "order_number": order_number,
        "service_lane": service_lane,
        "quick_turn_lane_id": quick_turn_lane_id,
        "board_x_mils": board_x,
        "board_y_mils": board_y,
        "layer_count": layer_count,
        "surface_finish": surface_finish,
        "quantity_boards": quantity,
        "requested_ship_date": ship_date,
        "fab_status": "QUOTED",
        "quality_disposition": "PENDING",
        "boards_scrapped": 0,
        "provisional_total_cents": None,
    }
    store.fab_orders[order["id"]] = order
    return success_object(svc.serialize_fab_order(order), 201)


@app.route("/pcb/fab-orders/<oid>", methods=["GET"])
def get_fab_order(oid):
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    order = svc.get_order(oid)
    check_customer_ownership(user_id, role, order["customer_id"])
    return success_object(svc.serialize_fab_order(order))


@app.route("/pcb/fab-orders", methods=["GET"])
def list_fab_orders():
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    limit, offset = parse_pagination()
    customer_filter = request.args.get("customer_id")
    lane_filter = request.args.get("quick_turn_lane_id")
    status_filter = request.args.get("fab_status")

    items = list(store.fab_orders.values())
    if role == "Customer":
        items = [o for o in items if o["customer_id"] == user_id]
    if customer_filter:
        items = [o for o in items if o["customer_id"] == customer_filter]
    if lane_filter:
        items = [o for o in items if o["quick_turn_lane_id"] == lane_filter]
    if status_filter:
        items = [o for o in items if o["fab_status"] == status_filter]

    items.sort(key=lambda o: o["created_at"])
    page, total = paginate([svc.serialize_fab_order(o) for o in items], limit, offset)
    return success_list(page, limit, offset, total)


# ---- Order state transitions ----

@app.route("/pcb/fab-orders/<oid>/submit-dfm", methods=["POST"])
def submit_dfm(oid):
    user_id, role = require_roles("Customer", "SalesEngineer")
    order = svc.get_order(oid)
    check_customer_ownership(user_id, role, order["customer_id"])

    if order["fab_status"] != "QUOTED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot submit-dfm from {order['fab_status']}", 409)

    locked = svc._find_locked_stackup(oid)
    if not locked:
        raise ApiError(ERR_STACKUP_NOT_LOCKED, "No LOCKED stackup on order", 409)

    order["fab_status"] = "DFM_REVIEW"
    svc.touch(order)
    return success_object(svc.serialize_fab_order(order))


@app.route("/pcb/fab-orders/<oid>/dfm-approve", methods=["POST"])
def dfm_approve(oid):
    user_id, role = require_roles("ProcessEngineer")
    order = svc.get_order(oid)
    if order["fab_status"] != "DFM_REVIEW":
        raise ApiError(ERR_INVALID_STATE, f"Cannot dfm-approve from {order['fab_status']}", 409)
    order["fab_status"] = "AWAITING_LAMINATE"
    svc.touch(order)
    return success_object(svc.serialize_fab_order(order))


@app.route("/pcb/fab-orders/<oid>/dfm-reject", methods=["POST"])
def dfm_reject(oid):
    user_id, role = require_roles("ProcessEngineer")
    order = svc.get_order(oid)
    if order["fab_status"] != "DFM_REVIEW":
        raise ApiError(ERR_INVALID_STATE, f"Cannot dfm-reject from {order['fab_status']}", 409)
    order["fab_status"] = "QUOTED"
    svc.touch(order)
    return success_object(svc.serialize_fab_order(order))


@app.route("/pcb/fab-orders/<oid>/release", methods=["POST"])
def release_order(oid):
    user_id, role = require_roles("ProductionPlanner")
    order = svc.get_order(oid)

    if order["fab_status"] != "AWAITING_LAMINATE":
        raise ApiError(ERR_INVALID_STATE, f"Cannot release from {order['fab_status']}", 409)

    # Guard chain in precedence order:
    # 1. Drill approved (latest by revision)
    drill_programs = [dp for dp in store.drill_programs.values() if dp["fab_order_id"] == oid]
    if not drill_programs:
        raise ApiError(ERR_DRILL_NOT_APPROVED, "No drill program exists", 409)
    latest_dp = max(drill_programs, key=lambda dp: dp["revision"])
    if latest_dp["status"] != "APPROVED":
        raise ApiError(ERR_DRILL_NOT_APPROVED, "Latest drill program not APPROVED", 409)

    # 2. Panel array released
    released_array = svc._find_released_array(oid)
    if not released_array:
        raise ApiError(ERR_PANEL_NOT_RELEASED, "No RELEASED panel array", 409)

    # 3. All RESERVED reservation lots QUALIFIED
    reserved_reservations = [r for r in store.laminate_reservations.values()
                             if r["fab_order_id"] == oid and r["status"] == "RESERVED"]
    for r in reserved_reservations:
        lot = store.laminate_lots.get(r["laminate_lot_id"])
        if lot:
            svc.recompute_lot_status(lot)
            if lot["status"] != "QUALIFIED":
                raise ApiError(ERR_LOT_NOT_QUALIFIED, f"Lot {lot['lot_code']} is not QUALIFIED", 409)

    # 4. Lane active (quick-turn only)
    if order["service_lane"] == "QUICK_TURN" and order["quick_turn_lane_id"]:
        lane = store.quick_turn_lanes.get(order["quick_turn_lane_id"])
        if not lane or not lane["active"]:
            raise ApiError(ERR_LANE_INACTIVE, "Lane is not active", 409)

    # 5. Sufficient laminate coverage
    total_reserved = sum(r["panels_allocated"] for r in reserved_reservations)
    if total_reserved < released_array["panels_required"]:
        raise ApiError(ERR_INSUFFICIENT_LAMINATE,
                       f"Reserved {total_reserved} < required {released_array['panels_required']}", 409)

    # 6. Lane capacity (quick-turn only)
    if order["service_lane"] == "QUICK_TURN" and order["quick_turn_lane_id"]:
        lane = store.quick_turn_lanes[order["quick_turn_lane_id"]]
        sdk = svc._ship_date_key(order["requested_ship_date"])
        committed = svc.get_committed_boards(lane["id"], sdk)
        if committed + order["quantity_boards"] > lane["capacity_boards_per_day"]:
            raise ApiError(ERR_LANE_CAPACITY_EXCEEDED, "Lane capacity exceeded", 409)

    # 7. Credit check
    customer = store.customers.get(order["customer_id"])
    if customer:
        prov = order["provisional_total_cents"]
        if prov is not None and prov > customer["credit_limit_cents"]:
            raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, "Provisional total exceeds credit limit", 402)

    # Side effects
    if order["service_lane"] == "QUICK_TURN" and order["quick_turn_lane_id"]:
        sdk = svc._ship_date_key(order["requested_ship_date"])
        svc.upsert_lane_commitment(order["quick_turn_lane_id"], sdk, order["quantity_boards"])

    order["fab_status"] = "RELEASED"
    svc.touch(order)
    return success_object(svc.serialize_fab_order(order))


@app.route("/pcb/fab-orders/<oid>/start-production", methods=["POST"])
def start_production(oid):
    user_id, role = require_roles("ProductionPlanner")
    order = svc.get_order(oid)
    if order["fab_status"] != "RELEASED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot start-production from {order['fab_status']}", 409)
    svc.start_production_cascade(order)
    order["fab_status"] = "IN_PRODUCTION"
    svc.touch(order)
    return success_object(svc.serialize_fab_order(order))


@app.route("/pcb/fab-orders/<oid>/hold", methods=["POST"])
def hold_order(oid):
    user_id, role = require_roles("ProductionPlanner")
    order = svc.get_order(oid)
    if order["fab_status"] != "IN_PRODUCTION":
        raise ApiError(ERR_INVALID_STATE, f"Cannot hold from {order['fab_status']}", 409)
    order["fab_status"] = "ON_HOLD"
    svc.touch(order)
    return success_object(svc.serialize_fab_order(order))


@app.route("/pcb/fab-orders/<oid>/unhold", methods=["POST"])
def unhold_order(oid):
    user_id, role = require_roles("ProductionPlanner")
    order = svc.get_order(oid)
    if order["fab_status"] != "ON_HOLD":
        raise ApiError(ERR_INVALID_STATE, f"Cannot unhold from {order['fab_status']}", 409)

    consumed = [r for r in store.laminate_reservations.values()
                if r["fab_order_id"] == oid and r["status"] == "CONSUMED"]
    if consumed:
        order["fab_status"] = "IN_PRODUCTION"
    else:
        # Check RESERVED coverage
        released_array = svc._find_released_array(oid)
        if released_array:
            reserved_cov = sum(r["panels_allocated"] for r in store.laminate_reservations.values()
                               if r["fab_order_id"] == oid and r["status"] == "RESERVED")
            if reserved_cov < released_array["panels_required"]:
                raise ApiError(ERR_INSUFFICIENT_LAMINATE, "Reserved coverage insufficient", 409)
        order["fab_status"] = "AWAITING_LAMINATE"
    svc.touch(order)
    return success_object(svc.serialize_fab_order(order))


@app.route("/pcb/fab-orders/<oid>/complete-fab", methods=["POST"])
def complete_fab(oid):
    user_id, role = require_roles("ProductionPlanner")
    order = svc.get_order(oid)
    if order["fab_status"] != "IN_PRODUCTION":
        raise ApiError(ERR_INVALID_STATE, f"Cannot complete-fab from {order['fab_status']}", 409)

    # Coupon gate first
    locked = svc._find_locked_stackup(oid)
    if locked:
        spec_lines = svc._get_spec_lines(locked["id"])
        for sl in spec_lines:
            if sl["coupon_required"]:
                passed = any(
                    c["spec_line_id"] == sl["id"] and c["status"] == "PASSED"
                    for c in store.impedance_coupons.values()
                    if c["fab_order_id"] == oid
                )
                if not passed:
                    raise ApiError(ERR_COUPON_NOT_PASSED,
                                   f"Spec line {sl['layer_name']} lacks a PASSED coupon", 409)

    # Disposition gate
    if order["quality_disposition"] not in ("PENDING", "PASSED"):
        raise ApiError(ERR_DISPOSITION_FAILED,
                       f"quality_disposition is {order['quality_disposition']}", 409)

    order["fab_status"] = "AWAITING_ETEST"
    order["quality_disposition"] = "PASSED"
    svc.touch(order)
    return success_object(svc.serialize_fab_order(order))


@app.route("/pcb/fab-orders/<oid>/ship", methods=["POST"])
def ship_order(oid):
    user_id, role = require_roles("ProductionPlanner")
    order = svc.get_order(oid)
    if order["fab_status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot ship from {order['fab_status']}", 409)
    if order["quality_disposition"] != "PASSED":
        raise ApiError(ERR_DISPOSITION_FAILED, "Disposition not PASSED", 409)
    inv = None
    for i in store.invoices.values():
        if i["fab_order_id"] == oid:
            inv = i
            break
    if not inv or inv["status"] not in ("ISSUED", "PAID"):
        raise ApiError(ERR_INVOICE_NOT_ISSUED, "Invoice not ISSUED or PAID", 409)
    order["fab_status"] = "SHIPPED"
    svc.touch(order)
    return success_object(svc.serialize_fab_order(order))


@app.route("/pcb/fab-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = require_roles("Customer", "ProductionPlanner", "FabAdmin")
    order = svc.get_order(oid)
    check_customer_ownership(user_id, role, order["customer_id"])

    cancellable = {"QUOTED", "DFM_REVIEW", "AWAITING_LAMINATE", "RELEASED", "ON_HOLD"}
    if order["fab_status"] not in cancellable:
        raise ApiError(ERR_ORDER_NOT_CANCELLABLE,
                       f"Cannot cancel from {order['fab_status']}", 409)

    svc.cancel_order_cascade(order)
    return success_object(svc.serialize_fab_order(order))


@app.route("/pcb/fab-orders/<oid>/concede", methods=["POST"])
def concede_order(oid):
    user_id, role = require_roles("FabAdmin")
    order = svc.get_order(oid)
    if order["quality_disposition"] != "FAILED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot concede from disposition {order['quality_disposition']}", 409)
    body = request.get_json(force=True, silent=True) or {}
    note = body.get("concession_note", "")
    if not note or not note.strip():
        raise ApiError(ERR_VALIDATION, "concession_note must be non-empty", 400)
    order["quality_disposition"] = "CONDITIONAL"
    svc.touch(order)
    return success_object(svc.serialize_fab_order(order))


@app.route("/pcb/fab-orders/<oid>/requalify", methods=["POST"])
def requalify_order(oid):
    user_id, role = require_roles("QualityInspector")
    order = svc.get_order(oid)
    if order["quality_disposition"] != "CONDITIONAL":
        raise ApiError(ERR_INVALID_STATE, f"Cannot requalify from disposition {order['quality_disposition']}", 409)
    body = request.get_json(force=True, silent=True) or {}
    note = body.get("requalification_note", "")
    if not note or not note.strip():
        raise ApiError(ERR_VALIDATION, "requalification_note must be non-empty", 400)
    order["quality_disposition"] = "PASSED"
    svc.touch(order)
    return success_object(svc.serialize_fab_order(order))


# ==============================================================================
# Stackups
# ==============================================================================

@app.route("/pcb/fab-orders/<oid>/stackups", methods=["POST"])
def create_stackup(oid):
    user_id, role = require_roles("Customer", "SalesEngineer", "CAMOperator")
    order = svc.get_order(oid)
    check_customer_ownership(user_id, role, order["customer_id"])

    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "revision", "total_thickness_mils", "dielectric_material", "copper_weight_oz")

    revision = validate_int(body["revision"], "revision", min_val=1)
    thickness = validate_positive_number(body["total_thickness_mils"], "total_thickness_mils")
    material = validate_enum(body["dielectric_material"],
                             ["FR4_TG135", "FR4_TG170", "ROGERS_4350"], "dielectric_material")
    copper = validate_int(body["copper_weight_oz"], "copper_weight_oz")
    if copper not in (1, 2):
        raise ApiError(ERR_VALIDATION, "copper_weight_oz must be 1 or 2", 400)
    imp_controlled = optional_field(body, "impedance_controlled", False)
    if not isinstance(imp_controlled, bool):
        imp_controlled = validate_bool(imp_controlled, "impedance_controlled")

    fields = svc.make_common_fields()
    stackup = {
        **fields,
        "fab_order_id": oid,
        "revision": revision,
        "total_thickness_mils": thickness,
        "dielectric_material": material,
        "copper_weight_oz": copper,
        "impedance_controlled": imp_controlled,
        "status": "DRAFT",
    }
    store.stackups[stackup["id"]] = stackup
    return success_object(svc.serialize_stackup(stackup), 201)


@app.route("/pcb/fab-orders/<oid>/stackups", methods=["GET"])
def list_stackups(oid):
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    order = svc.get_order(oid)
    check_customer_ownership(user_id, role, order["customer_id"])
    limit, offset = parse_pagination()
    items = sorted(
        [s for s in store.stackups.values() if s["fab_order_id"] == oid],
        key=lambda s: s["created_at"]
    )
    page, total = paginate([svc.serialize_stackup(s) for s in items], limit, offset)
    return success_list(page, limit, offset, total)


@app.route("/pcb/stackups/<sid>", methods=["GET"])
def get_stackup(sid):
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    s = svc.get_stackup(sid)
    order = store.fab_orders.get(s["fab_order_id"])
    if order:
        check_customer_ownership(user_id, role, order["customer_id"])
    return success_object(svc.serialize_stackup(s))


@app.route("/pcb/stackups/<sid>/lock", methods=["POST"])
def lock_stackup(sid):
    user_id, role = require_roles("ProcessEngineer")
    stackup = svc.get_stackup(sid)

    if stackup["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, f"Cannot lock from {stackup['status']}", 409)

    order = svc.get_order(stackup["fab_order_id"])
    if order["fab_status"] not in ("QUOTED", "DFM_REVIEW"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Order in {order['fab_status']}, stackup lock requires QUOTED or DFM_REVIEW", 409)

    if stackup["impedance_controlled"]:
        spec_lines = svc._get_spec_lines(sid)
        if len(spec_lines) == 0:
            raise ApiError(ERR_IMPEDANCE_SPEC_MISSING,
                           "impedance_controlled stackup requires >= 1 spec line", 422)

    # Supersede other LOCKED stackups of the same order
    for s in store.stackups.values():
        if s["fab_order_id"] == stackup["fab_order_id"] and s["status"] == "LOCKED" and s["id"] != sid:
            s["status"] = "SUPERSEDED"
            svc.touch(s)

    stackup["status"] = "LOCKED"
    svc.touch(stackup)

    # Recompute provisional pricing if a RELEASED array exists
    released_array = svc._find_released_array(stackup["fab_order_id"])
    if released_array:
        price = svc.compute_provisional_pricing(order)
        if price:
            order["provisional_total_cents"] = price["total_cents"]
        svc.touch(order)

    return success_object(svc.serialize_stackup(stackup))


# ==============================================================================
# Impedance Spec Lines
# ==============================================================================

@app.route("/pcb/stackups/<sid>/spec-lines", methods=["POST"])
def create_spec_line(sid):
    user_id, role = require_roles("CAMOperator")
    stackup = svc.get_stackup(sid)

    if stackup["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, f"Cannot add spec line to {stackup['status']} stackup", 409)

    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "layer_name", "target_ohms", "tolerance_plus_ohms",
                   "tolerance_minus_ohms", "line_type")

    target = validate_positive_number(body["target_ohms"], "target_ohms")
    tol_plus = validate_float(body["tolerance_plus_ohms"], "tolerance_plus_ohms", min_val=0)
    tol_minus = validate_float(body["tolerance_minus_ohms"], "tolerance_minus_ohms", min_val=0)
    line_type = validate_enum(body["line_type"], ["SINGLE_ENDED", "DIFFERENTIAL"], "line_type")
    coupon_required = optional_field(body, "coupon_required", True)
    if not isinstance(coupon_required, bool):
        coupon_required = validate_bool(coupon_required, "coupon_required")

    fields = svc.make_common_fields()
    sl = {
        **fields,
        "stackup_id": sid,
        "layer_name": body["layer_name"],
        "target_ohms": target,
        "tolerance_plus_ohms": tol_plus,
        "tolerance_minus_ohms": tol_minus,
        "line_type": line_type,
        "coupon_required": coupon_required,
    }
    store.impedance_spec_lines[sl["id"]] = sl
    return success_object(svc.serialize_spec_line(sl), 201)


@app.route("/pcb/stackups/<sid>/spec-lines", methods=["GET"])
def list_spec_lines(sid):
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    stackup = svc.get_stackup(sid)
    order = store.fab_orders.get(stackup["fab_order_id"])
    if order:
        check_customer_ownership(user_id, role, order["customer_id"])
    limit, offset = parse_pagination()
    items = sorted(svc._get_spec_lines(sid), key=lambda s: s["created_at"])
    page, total = paginate([svc.serialize_spec_line(s) for s in items], limit, offset)
    return success_list(page, limit, offset, total)


# ==============================================================================
# Panel Arrays
# ==============================================================================

@app.route("/pcb/fab-orders/<oid>/panel-arrays", methods=["POST"])
def create_panel_array(oid):
    user_id, role = require_roles("CAMOperator")
    order = svc.get_order(oid)

    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "array_x", "array_y", "panel_width_mils", "panel_height_mils",
                   "expected_fab_order_version")

    # OCC check
    expected_version = body["expected_fab_order_version"]
    if expected_version != order["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       f"Expected version {expected_version}, current {order['version']}", 412)

    array_x = validate_int(body["array_x"], "array_x", min_val=1)
    array_y = validate_int(body["array_y"], "array_y", min_val=1)
    pw = validate_int(body["panel_width_mils"], "panel_width_mils", min_val=1)
    ph = validate_int(body["panel_height_mils"], "panel_height_mils", min_val=1)

    # Compute yield fields
    yield_fields = svc.compute_array_yield_fields(order, array_x, array_y, pw, ph)

    # Supersede all existing arrays (DRAFT or RELEASED) of the same order
    for pa in store.panel_arrays.values():
        if pa["fab_order_id"] == oid and pa["status"] in ("DRAFT", "RELEASED"):
            pa["status"] = "SUPERSEDED"
            svc.touch(pa)

    fields = svc.make_common_fields()
    panel_array = {
        **fields,
        "fab_order_id": oid,
        "array_x": array_x,
        "array_y": array_y,
        "panel_width_mils": pw,
        "panel_height_mils": ph,
        "boards_per_panel": yield_fields["boards_per_panel"],
        "array_yield": yield_fields["array_yield"],
        "good_boards_per_panel": yield_fields["good_boards_per_panel"],
        "panels_required": yield_fields["panels_required"],
        "utilization_pct": yield_fields["utilization_pct"],
        "status": "DRAFT",
    }
    store.panel_arrays[panel_array["id"]] = panel_array

    # Bump order version
    svc.touch(order)

    return success_object(svc.serialize_panel_array(panel_array), 201)


@app.route("/pcb/fab-orders/<oid>/panel-arrays", methods=["GET"])
def list_panel_arrays(oid):
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    order = svc.get_order(oid)
    check_customer_ownership(user_id, role, order["customer_id"])
    limit, offset = parse_pagination()
    items = sorted(
        [pa for pa in store.panel_arrays.values() if pa["fab_order_id"] == oid],
        key=lambda pa: pa["created_at"]
    )
    page, total = paginate([svc.serialize_panel_array(pa) for pa in items], limit, offset)
    return success_list(page, limit, offset, total)


@app.route("/pcb/panel-arrays/<paid>", methods=["GET"])
def get_panel_array(paid):
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    pa = svc.get_panel_array(paid)
    order = store.fab_orders.get(pa["fab_order_id"])
    if order:
        check_customer_ownership(user_id, role, order["customer_id"])
    return success_object(svc.serialize_panel_array(pa))


@app.route("/pcb/panel-arrays/<paid>/release", methods=["POST"])
def release_panel_array(paid):
    user_id, role = require_roles("CAMOperator")
    pa = svc.get_panel_array(paid)

    if pa["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, f"Cannot release from {pa['status']}", 409)

    order = svc.get_order(pa["fab_order_id"])
    if order["fab_status"] not in ("QUOTED", "DFM_REVIEW", "AWAITING_LAMINATE"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Order in {order['fab_status']}, array release requires QUOTED/DFM_REVIEW/AWAITING_LAMINATE", 409)

    if pa["good_boards_per_panel"] < 1:
        raise ApiError(ERR_ARRAY_YIELD_ZERO, "good_boards_per_panel is 0", 422)

    # Supersede other RELEASED arrays
    for other in store.panel_arrays.values():
        if other["fab_order_id"] == pa["fab_order_id"] and other["status"] == "RELEASED" and other["id"] != paid:
            other["status"] = "SUPERSEDED"
            svc.touch(other)

    pa["status"] = "RELEASED"
    svc.touch(pa)

    # Recompute provisional pricing
    price = svc.compute_provisional_pricing(order)
    if price:
        order["provisional_total_cents"] = price["total_cents"]
    svc.touch(order)

    return success_object(svc.serialize_panel_array(pa))


# ==============================================================================
# Drill Programs
# ==============================================================================

@app.route("/pcb/fab-orders/<oid>/drill-programs", methods=["POST"])
def create_drill_program(oid):
    user_id, role = require_roles("CAMOperator")
    order = svc.get_order(oid)
    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "revision", "min_hole_mils", "hole_count")

    revision = validate_int(body["revision"], "revision", min_val=1)
    min_hole = validate_positive_number(body["min_hole_mils"], "min_hole_mils")
    hole_count = validate_int(body["hole_count"], "hole_count", min_val=1)

    fields = svc.make_common_fields()
    dp = {
        **fields,
        "fab_order_id": oid,
        "revision": revision,
        "min_hole_mils": min_hole,
        "hole_count": hole_count,
        "plated_aspect_ratio": None,
        "created_by_user_id": user_id,
        "rejection_reason": None,
        "status": "DRAFT",
    }
    store.drill_programs[dp["id"]] = dp
    return success_object(svc.serialize_drill_program(dp), 201)


@app.route("/pcb/fab-orders/<oid>/drill-programs", methods=["GET"])
def list_drill_programs(oid):
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    order = svc.get_order(oid)
    check_customer_ownership(user_id, role, order["customer_id"])
    limit, offset = parse_pagination()
    items = sorted(
        [dp for dp in store.drill_programs.values() if dp["fab_order_id"] == oid],
        key=lambda dp: dp["created_at"]
    )
    page, total = paginate([svc.serialize_drill_program(dp) for dp in items], limit, offset)
    return success_list(page, limit, offset, total)


@app.route("/pcb/drill-programs/<dpid>/submit", methods=["POST"])
def submit_drill_program(dpid):
    user_id, role = require_roles("CAMOperator")
    dp = svc.get_drill_program(dpid)
    if dp["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, f"Cannot submit from {dp['status']}", 409)
    dp["status"] = "UNDER_REVIEW"
    svc.touch(dp)
    return success_object(svc.serialize_drill_program(dp))


@app.route("/pcb/drill-programs/<dpid>/approve", methods=["POST"])
def approve_drill_program(dpid):
    user_id, role = require_roles("ProcessEngineer")
    dp = svc.get_drill_program(dpid)
    if dp["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, f"Cannot approve from {dp['status']}", 409)

    # SoD check
    if user_id == dp["created_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, "Approver cannot be the creator", 403)

    # Hole minimum
    if dp["min_hole_mils"] < 6:
        raise ApiError(ERR_HOLE_BELOW_MIN, f"min_hole_mils {dp['min_hole_mils']} < 6", 422)

    # Aspect ratio
    order = svc.get_order(dp["fab_order_id"])
    locked = svc._find_locked_stackup(dp["fab_order_id"])
    if not locked:
        raise ApiError(ERR_ASPECT_RATIO_EXCEEDED, "No LOCKED stackup for aspect ratio check", 422)

    ratio = locked["total_thickness_mils"] / dp["min_hole_mils"]
    ceiling = 8.0 if locked["copper_weight_oz"] == 1 else 6.0
    dp["plated_aspect_ratio"] = ratio

    if ratio > ceiling:
        raise ApiError(ERR_ASPECT_RATIO_EXCEEDED,
                       f"Aspect ratio {ratio} > {ceiling}", 422)

    dp["status"] = "APPROVED"
    svc.touch(dp)
    return success_object(svc.serialize_drill_program(dp))


@app.route("/pcb/drill-programs/<dpid>/reject", methods=["POST"])
def reject_drill_program(dpid):
    user_id, role = require_roles("ProcessEngineer")
    dp = svc.get_drill_program(dpid)
    if dp["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, f"Cannot reject from {dp['status']}", 409)
    body = request.get_json(force=True, silent=True) or {}
    reason = body.get("reason", "")
    if not reason or not reason.strip():
        raise ApiError(ERR_VALIDATION, "reason must be non-empty", 400)
    dp["status"] = "REJECTED"
    dp["rejection_reason"] = reason
    svc.touch(dp)
    return success_object(svc.serialize_drill_program(dp))


@app.route("/pcb/drill-programs/<dpid>/revise", methods=["POST"])
def revise_drill_program(dpid):
    user_id, role = require_roles("CAMOperator")
    dp = svc.get_drill_program(dpid)
    if dp["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot revise from {dp['status']}", 409)
    body = request.get_json(force=True, silent=True) or {}
    if "min_hole_mils" in body and body["min_hole_mils"] is not None:
        dp["min_hole_mils"] = validate_positive_number(body["min_hole_mils"], "min_hole_mils")
    if "hole_count" in body and body["hole_count"] is not None:
        dp["hole_count"] = validate_int(body["hole_count"], "hole_count", min_val=1)
    dp["revision"] += 1
    dp["rejection_reason"] = None
    dp["status"] = "DRAFT"
    svc.touch(dp)
    return success_object(svc.serialize_drill_program(dp))


# ==============================================================================
# Laminate Lots
# ==============================================================================

@app.route("/pcb/laminate-lots", methods=["POST"])
def create_laminate_lot():
    user_id, role = require_roles("ProcessEngineer")
    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "material_code", "lot_code", "manufacture_date", "panels_total")

    material = validate_enum(body["material_code"],
                             ["FR4_TG135", "FR4_TG170", "ROGERS_4350"], "material_code")

    for lot in store.laminate_lots.values():
        if lot["lot_code"] == body["lot_code"]:
            raise ApiError(ERR_DUPLICATE_LOT_CODE, "lot_code already registered", 409)

    try:
        mfg_date = svc.parse_iso(body["manufacture_date"])
    except Exception:
        raise ApiError(ERR_VALIDATION, "Invalid manufacture_date", 400)

    panels_total = validate_int(body["panels_total"], "panels_total", min_val=1)

    fields = svc.make_common_fields()
    lot = {
        **fields,
        "material_code": material,
        "lot_code": body["lot_code"],
        "manufacture_date": mfg_date,
        "panels_total": panels_total,
        "panels_reserved": 0,
        "panels_consumed": 0,
        "expiry_date": svc.compute_expiry(mfg_date),
        "status": "RECEIVED",
        "qualified_at": None,
    }
    store.laminate_lots[lot["id"]] = lot
    # The lot "opens in RECEIVED status" (PRD §3.5): do not lazily expire it in
    # the create response — expiry is re-evaluated on subsequent accesses.
    return success_object(svc.serialize_laminate_lot(lot, recompute=False), 201)


@app.route("/pcb/laminate-lots/<lid>", methods=["GET"])
def get_laminate_lot(lid):
    user_id, role = require_roles(
        "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    lot = svc.get_lot(lid)
    return success_object(svc.serialize_laminate_lot(lot))


@app.route("/pcb/laminate-lots", methods=["GET"])
def list_laminate_lots():
    user_id, role = require_roles(
        "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    material_filter = request.args.get("material_code")

    items = []
    for lot in store.laminate_lots.values():
        svc.recompute_lot_status(lot)
        if status_filter and lot["status"] != status_filter:
            continue
        if material_filter and lot["material_code"] != material_filter:
            continue
        items.append(lot)
    items.sort(key=lambda l: l["created_at"])
    page, total = paginate([svc.serialize_laminate_lot(l) for l in items], limit, offset)
    return success_list(page, limit, offset, total)


@app.route("/pcb/laminate-lots/<lid>/qualify", methods=["POST"])
def qualify_lot(lid):
    user_id, role = require_roles("QualityInspector")
    # NOTE: fetch the lot WITHOUT the lazy expiry re-evaluation that
    # svc.get_lot performs. PRD §3.5: "Qualification is refused when the clock
    # has reached the lot's expiry_date ... surfacing ERR_LOT_NOT_QUALIFIED;
    # the state guard (lot not in RECEIVED) takes precedence when both apply."
    # The guard chain therefore evaluates the lot's stored status first, then
    # the expiry instant — a lazy flip to EXPIRED inside this handler would
    # make ERR_LOT_NOT_QUALIFIED unreachable. Plain reads (GET) still
    # re-evaluate expiry lazily.
    lot = store.laminate_lots.get(lid)
    if not lot:
        raise ApiError(ERR_NOT_FOUND, "LaminateLot not found", 404)
    if lot["status"] != "RECEIVED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot qualify from {lot['status']}", 409)

    expiry = lot["expiry_date"]
    if isinstance(expiry, str):
        expiry = svc.parse_iso(expiry)
    if store.logical_clock >= expiry:
        raise ApiError(ERR_LOT_NOT_QUALIFIED, "Lot has expired", 409)

    lot["status"] = "QUALIFIED"
    lot["qualified_at"] = store.logical_clock
    svc.touch(lot)
    return success_object(svc.serialize_laminate_lot(lot))


@app.route("/pcb/laminate-lots/<lid>/quarantine", methods=["POST"])
def quarantine_lot(lid):
    user_id, role = require_roles("QualityInspector")
    lot = svc.get_lot(lid)
    svc.recompute_lot_status(lot)

    if lot["status"] not in ("RECEIVED", "QUALIFIED"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot quarantine from {lot['status']}", 409)

    if lot["status"] == "QUALIFIED":
        has_reserved = any(
            r["laminate_lot_id"] == lid and r["status"] == "RESERVED"
            for r in store.laminate_reservations.values()
        )
        if has_reserved:
            raise ApiError(ERR_INVALID_STATE, "Cannot quarantine lot with RESERVED reservations", 409)

    lot["status"] = "QUARANTINED"
    svc.touch(lot)
    return success_object(svc.serialize_laminate_lot(lot))


# ==============================================================================
# Laminate Reservations
# ==============================================================================

@app.route("/pcb/laminate-reservations", methods=["POST"])
def create_reservation():
    user_id, role = require_roles("ProductionPlanner")
    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "fab_order_id", "panel_array_id", "laminate_lot_id",
                   "panels_allocated", "expected_laminate_lot_version")

    # Body FK existence
    order = store.fab_orders.get(body["fab_order_id"])
    if not order:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "fab_order_id not found", 422)
    pa = store.panel_arrays.get(body["panel_array_id"])
    if not pa:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "panel_array_id not found", 422)
    if pa["fab_order_id"] != body["fab_order_id"]:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "panel_array_id belongs to a different order", 422)
    lot = store.laminate_lots.get(body["laminate_lot_id"])
    if not lot:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "laminate_lot_id not found", 422)

    # Order state
    if order["fab_status"] not in ("AWAITING_LAMINATE", "RELEASED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Order in {order['fab_status']}, reservation requires AWAITING_LAMINATE or RELEASED", 409)

    # Lot status
    svc.recompute_lot_status(lot)
    if lot["status"] != "QUALIFIED":
        raise ApiError(ERR_LOT_NOT_QUALIFIED, f"Lot is {lot['status']}, not QUALIFIED", 409)

    # Expiry vs ship date
    if lot["expiry_date"] <= order["requested_ship_date"]:
        raise ApiError(ERR_LOT_EXPIRES_BEFORE_SHIP,
                       "Lot expiry_date <= requested_ship_date", 422)

    panels_allocated = validate_int(body["panels_allocated"], "panels_allocated", min_val=1)

    # Availability
    avail = lot["panels_total"] - lot["panels_reserved"] - lot["panels_consumed"]
    if panels_allocated > avail:
        raise ApiError(ERR_INSUFFICIENT_LAMINATE,
                       f"panels_allocated {panels_allocated} > available {avail}", 409)

    # OCC
    expected_version = body["expected_laminate_lot_version"]
    if expected_version != lot["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       f"Expected lot version {expected_version}, current {lot['version']}", 412)

    fields = svc.make_common_fields()
    reservation = {
        **fields,
        "fab_order_id": body["fab_order_id"],
        "panel_array_id": body["panel_array_id"],
        "laminate_lot_id": body["laminate_lot_id"],
        "panels_allocated": panels_allocated,
        "status": "RESERVED",
    }
    store.laminate_reservations[reservation["id"]] = reservation

    lot["panels_reserved"] += panels_allocated
    svc.touch(lot)
    svc.recompute_lot_status(lot)

    return success_object(svc.serialize_laminate_reservation(reservation), 201)


@app.route("/pcb/laminate-reservations", methods=["GET"])
def list_reservations():
    user_id, role = require_roles(
        "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    limit, offset = parse_pagination()
    items = list(store.laminate_reservations.values())

    for param in ("fab_order_id", "panel_array_id", "laminate_lot_id", "status"):
        val = request.args.get(param)
        if val:
            items = [r for r in items if r.get(param) == val]

    items.sort(key=lambda r: r["created_at"])
    page, total = paginate([svc.serialize_laminate_reservation(r) for r in items], limit, offset)
    return success_list(page, limit, offset, total)


@app.route("/pcb/laminate-reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    user_id, role = require_roles(
        "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    r = svc.get_reservation(rid)
    return success_object(svc.serialize_laminate_reservation(r))


@app.route("/pcb/laminate-reservations/<rid>/release", methods=["POST"])
def release_reservation(rid):
    user_id, role = require_roles("ProductionPlanner")
    r = svc.get_reservation(rid)
    if r["status"] != "RESERVED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot release from {r['status']}", 409)
    svc._release_reservation(r)
    return success_object(svc.serialize_laminate_reservation(r))


# ==============================================================================
# Impedance Coupons
# ==============================================================================

@app.route("/pcb/fab-orders/<oid>/coupons", methods=["POST"])
def create_coupon(oid):
    user_id, role = require_roles("QualityInspector")
    order = svc.get_order(oid)

    if order["fab_status"] not in ("IN_PRODUCTION", "AWAITING_ETEST"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot create coupon in {order['fab_status']}", 409)

    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "spec_line_id", "panel_ref")

    spec_line = store.impedance_spec_lines.get(body["spec_line_id"])
    if not spec_line:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "spec_line_id not found", 422)

    # At most one non-CANCELLED coupon per spec line
    for c in store.impedance_coupons.values():
        if c["spec_line_id"] == body["spec_line_id"] and c["status"] != "CANCELLED":
            raise ApiError(ERR_COUPON_EXISTS, "A non-CANCELLED coupon already exists for this spec line", 409)

    fields = svc.make_common_fields()
    coupon = {
        **fields,
        "fab_order_id": oid,
        "spec_line_id": body["spec_line_id"],
        "panel_ref": body["panel_ref"],
        "status": "AWAITING_MEASURE",
        "retest_count": 0,
        "latest_measured_ohms": None,
        "disposition_basis": None,
    }
    store.impedance_coupons[coupon["id"]] = coupon
    return success_object(svc.serialize_coupon(coupon), 201)


@app.route("/pcb/fab-orders/<oid>/coupons", methods=["GET"])
def list_order_coupons(oid):
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    order = svc.get_order(oid)
    check_customer_ownership(user_id, role, order["customer_id"])
    limit, offset = parse_pagination()
    items = sorted(
        [c for c in store.impedance_coupons.values() if c["fab_order_id"] == oid],
        key=lambda c: c["created_at"]
    )
    page, total = paginate([svc.serialize_coupon(c) for c in items], limit, offset)
    return success_list(page, limit, offset, total)


@app.route("/pcb/coupons", methods=["GET"])
def list_coupons():
    user_id, role = require_roles(
        "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    limit, offset = parse_pagination()
    items = list(store.impedance_coupons.values())
    for param in ("fab_order_id", "spec_line_id", "status"):
        val = request.args.get(param)
        if val:
            items = [c for c in items if c.get(param) == val]
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate([svc.serialize_coupon(c) for c in items], limit, offset)
    return success_list(page, limit, offset, total)


@app.route("/pcb/coupons/<cid>", methods=["GET"])
def get_coupon(cid):
    user_id, role = require_roles(
        "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    c = svc.get_coupon(cid)
    return success_object(svc.serialize_coupon(c))


@app.route("/pcb/coupons/<cid>/retest", methods=["POST"])
def retest_coupon(cid):
    user_id, role = require_roles("QualityInspector")
    coupon = svc.get_coupon(cid)
    if coupon["status"] != "FAILED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot retest from {coupon['status']}", 409)
    if coupon["retest_count"] >= svc.MAX_RETESTS:
        raise ApiError(ERR_RETEST_LIMIT_REACHED, "Retest limit reached", 409)
    coupon["retest_count"] += 1
    coupon["status"] = "AWAITING_MEASURE"
    svc.touch(coupon)
    return success_object(svc.serialize_coupon(coupon))


@app.route("/pcb/coupons/<cid>/measurements", methods=["POST"])
def create_measurement(cid):
    user_id, role = require_roles("QualityInspector")
    coupon = svc.get_coupon(cid)

    # Order state check
    order = svc.get_order(coupon["fab_order_id"])
    if order["fab_status"] not in ("IN_PRODUCTION", "AWAITING_ETEST"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Order in {order['fab_status']}, measurement requires IN_PRODUCTION or AWAITING_ETEST", 409)

    # Booking coverage check
    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "measured_ohms", "lab_slot_booking_id")

    booking = store.lab_slot_bookings.get(body["lab_slot_booking_id"])
    if not booking or booking["coupon_id"] != cid or booking["status"] != "BOOKED":
        raise ApiError(ERR_NO_ACTIVE_LAB_BOOKING, "No BOOKED booking for this coupon", 409)

    starts = booking["starts_at"] if isinstance(booking["starts_at"], datetime) else svc.parse_iso(booking["starts_at"])
    ends = booking["ends_at"] if isinstance(booking["ends_at"], datetime) else svc.parse_iso(booking["ends_at"])
    if not (starts <= store.logical_clock < ends):
        raise ApiError(ERR_NO_ACTIVE_LAB_BOOKING, "Booking does not cover the logical clock", 409)

    # Payload shape
    measured_ohms = validate_positive_number(body["measured_ohms"], "measured_ohms")

    spec_line = store.impedance_spec_lines.get(coupon["spec_line_id"])
    if not spec_line:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "Spec line not found", 422)

    measured_ohms_b = optional_field(body, "measured_ohms_b")
    if spec_line["line_type"] == "DIFFERENTIAL":
        if measured_ohms_b is None:
            raise ApiError(ERR_VALIDATION, "measured_ohms_b required for DIFFERENTIAL line", 400)
        measured_ohms_b = validate_positive_number(measured_ohms_b, "measured_ohms_b")
    else:
        measured_ohms_b = None

    # Evaluate PASS/FAIL
    band_lo = Decimal(str(spec_line["target_ohms"])) - Decimal(str(spec_line["tolerance_minus_ohms"]))
    band_hi = Decimal(str(spec_line["target_ohms"])) + Decimal(str(spec_line["tolerance_plus_ohms"]))
    m = Decimal(str(measured_ohms))

    if spec_line["line_type"] == "SINGLE_ENDED":
        passed = band_lo <= m <= band_hi
        disposition_basis = "SINGLE"
    else:
        mb = Decimal(str(measured_ohms_b))
        in_band = (band_lo <= m <= band_hi) and (band_lo <= mb <= band_hi)
        spread = abs(m - mb)
        passed = in_band and spread <= svc.MAX_SPREAD_OHMS
        disposition_basis = "STATISTICAL"

    result = "PASS" if passed else "FAIL"

    # Create measurement record
    fields = svc.make_append_only_fields()
    measurement = {
        **fields,
        "coupon_id": cid,
        "lab_slot_booking_id": body["lab_slot_booking_id"],
        "measured_ohms": measured_ohms,
        "measured_ohms_b": measured_ohms_b,
        "measured_at": svc.now_iso(),
        "result": result,
    }
    store.coupon_measurements[measurement["id"]] = measurement

    # Transition booking
    booking["status"] = "COMPLETED"
    svc.touch(booking)

    # Update coupon
    coupon["latest_measured_ohms"] = measured_ohms
    coupon["disposition_basis"] = disposition_basis

    if passed:
        coupon["status"] = "PASSED"
    else:
        coupon["status"] = "FAILED"
        # Final failure check
        if coupon["retest_count"] >= svc.MAX_RETESTS:
            # Final failure: cascade to order
            order["quality_disposition"] = "FAILED"
            released_array = svc._find_released_array(order["id"])
            boards_per_panel = released_array["boards_per_panel"] if released_array else 0
            order["boards_scrapped"] += boards_per_panel
            svc.touch(order)

            # Auto-create defect record
            defect_fields = svc.make_append_only_fields()
            defect = {
                **defect_fields,
                "fab_order_id": order["id"],
                "panel_array_id": released_array["id"] if released_array else None,
                "defect_code": "IMPEDANCE",
                "severity": "SCRAP",
                "boards_affected": boards_per_panel,
                "detected_at": store.logical_clock,
                "source": "MANUAL",
            }
            store.defect_records[defect["id"]] = defect

    svc.touch(coupon)
    return success_object(svc.serialize_coupon_measurement(measurement), 201)


@app.route("/pcb/coupons/<cid>/measurements", methods=["GET"])
def list_coupon_measurements(cid):
    user_id, role = require_roles(
        "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    coupon = svc.get_coupon(cid)
    limit, offset = parse_pagination()
    items = sorted(
        [m for m in store.coupon_measurements.values() if m["coupon_id"] == cid],
        key=lambda m: m["created_at"]
    )
    page, total = paginate([svc.serialize_coupon_measurement(m) for m in items], limit, offset)
    return success_list(page, limit, offset, total)


# ==============================================================================
# Lab Slot Bookings
# ==============================================================================

@app.route("/pcb/lab-slot-bookings", methods=["POST"])
def create_booking():
    user_id, role = require_roles("QualityInspector")
    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "coupon_id", "station", "starts_at", "ends_at")

    coupon = store.impedance_coupons.get(body["coupon_id"])
    if not coupon:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "coupon_id not found", 422)

    station = validate_enum(body["station"], ["MICROSECTION_A"], "station")

    try:
        starts = svc.parse_iso(body["starts_at"])
        ends = svc.parse_iso(body["ends_at"])
    except Exception:
        raise ApiError(ERR_VALIDATION, "Invalid starts_at or ends_at", 400)

    # Window validity
    if ends <= starts:
        raise ApiError(ERR_BOOKING_WINDOW_INVALID, "ends_at must be after starts_at", 422)
    duration_minutes = (ends - starts).total_seconds() / 60
    if duration_minutes > 120:
        raise ApiError(ERR_BOOKING_WINDOW_INVALID, "Duration exceeds 120 minutes", 422)

    # Overlap check: half-open intervals with 15-minute gap requirement
    # Two windows [s1,e1) and [s2,e2) need: s1 >= e2 + 15min OR s2 >= e1 + 15min
    gap_delta = timedelta(minutes=15)
    for existing in store.lab_slot_bookings.values():
        if existing["station"] != station or existing["status"] != "BOOKED":
            continue
        es = existing["starts_at"] if isinstance(existing["starts_at"], datetime) else svc.parse_iso(existing["starts_at"])
        ee = existing["ends_at"] if isinstance(existing["ends_at"], datetime) else svc.parse_iso(existing["ends_at"])
        # Sufficient gap in either direction?
        if starts >= ee + gap_delta or es >= ends + gap_delta:
            continue  # OK, enough clearance
        raise ApiError(ERR_LAB_SLOT_CONFLICT,
                       "Gap to existing booking is less than 15 minutes", 409)

    fields = svc.make_common_fields()
    booking = {
        **fields,
        "coupon_id": body["coupon_id"],
        "station": station,
        "starts_at": starts,
        "ends_at": ends,
        "status": "BOOKED",
    }
    store.lab_slot_bookings[booking["id"]] = booking
    return success_object(svc.serialize_lab_slot_booking(booking), 201)


@app.route("/pcb/lab-slot-bookings", methods=["GET"])
def list_bookings():
    user_id, role = require_roles("QualityInspector", "ProcessEngineer", "FabAdmin")
    limit, offset = parse_pagination()
    items = list(store.lab_slot_bookings.values())
    for param in ("coupon_id", "station", "status"):
        val = request.args.get(param)
        if val:
            items = [b for b in items if b.get(param) == val]
    items.sort(key=lambda b: b["created_at"])
    page, total = paginate([svc.serialize_lab_slot_booking(b) for b in items], limit, offset)
    return success_list(page, limit, offset, total)


@app.route("/pcb/lab-slot-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    user_id, role = require_roles("QualityInspector", "ProcessEngineer", "FabAdmin")
    b = svc.get_booking(bid)
    return success_object(svc.serialize_lab_slot_booking(b))


@app.route("/pcb/lab-slot-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    user_id, role = require_roles("QualityInspector")
    b = svc.get_booking(bid)
    if b["status"] != "BOOKED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot cancel from {b['status']}", 409)
    b["status"] = "CANCELLED"
    svc.touch(b)
    return success_object(svc.serialize_lab_slot_booking(b))


@app.route("/pcb/lab-slot-bookings/<bid>/measurements", methods=["GET"])
def list_booking_measurements(bid):
    user_id, role = require_roles("QualityInspector", "ProcessEngineer", "FabAdmin")
    b = svc.get_booking(bid)
    limit, offset = parse_pagination()
    items = sorted(
        [m for m in store.coupon_measurements.values() if m["lab_slot_booking_id"] == bid],
        key=lambda m: m["created_at"]
    )
    page, total = paginate([svc.serialize_coupon_measurement(m) for m in items], limit, offset)
    return success_list(page, limit, offset, total)


# ==============================================================================
# Electrical Test Runs
# ==============================================================================

@app.route("/pcb/fab-orders/<oid>/etest-runs", methods=["POST"])
def create_etest_run(oid):
    user_id, role = require_roles("QualityInspector")
    order = svc.get_order(oid)
    if order["fab_status"] != "AWAITING_ETEST":
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot schedule e-test in {order['fab_status']}", 409)

    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "fixture_id", "test_voltage")
    voltage = validate_positive_number(body["test_voltage"], "test_voltage")

    fields = svc.make_common_fields()
    run = {
        **fields,
        "fab_order_id": oid,
        "fixture_id": body["fixture_id"],
        "test_voltage": voltage,
        "status": "SCHEDULED",
        "boards_tested": 0,
        "boards_failed": 0,
        "opens_found": 0,
        "shorts_found": 0,
    }
    store.elec_test_runs[run["id"]] = run
    return success_object(svc.serialize_elec_test_run(run), 201)


@app.route("/pcb/fab-orders/<oid>/etest-runs", methods=["GET"])
def list_etest_runs(oid):
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    order = svc.get_order(oid)
    check_customer_ownership(user_id, role, order["customer_id"])
    limit, offset = parse_pagination()
    items = sorted(
        [r for r in store.elec_test_runs.values() if r["fab_order_id"] == oid],
        key=lambda r: r["created_at"]
    )
    page, total = paginate([svc.serialize_elec_test_run(r) for r in items], limit, offset)
    return success_list(page, limit, offset, total)


@app.route("/pcb/etest-runs/<rid>/start", methods=["POST"])
def start_etest_run(rid):
    user_id, role = require_roles("QualityInspector")
    run = svc.get_etest_run(rid)
    if run["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot start from {run['status']}", 409)
    run["status"] = "RUNNING"
    svc.touch(run)
    return success_object(svc.serialize_elec_test_run(run))


@app.route("/pcb/etest-runs/<rid>/complete", methods=["POST"])
def complete_etest_run(rid):
    user_id, role = require_roles("QualityInspector")
    run = svc.get_etest_run(rid)
    if run["status"] != "RUNNING":
        raise ApiError(ERR_INVALID_STATE, f"Cannot complete from {run['status']}", 409)

    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "outcome", "boards_tested", "boards_failed", "opens_found", "shorts_found")

    outcome = validate_enum(body["outcome"], ["PASS", "FAIL"], "outcome")
    boards_tested = validate_int(body["boards_tested"], "boards_tested", min_val=0)
    boards_failed = validate_int(body["boards_failed"], "boards_failed", min_val=0)
    opens_found = validate_int(body["opens_found"], "opens_found", min_val=0)
    shorts_found = validate_int(body["shorts_found"], "shorts_found", min_val=0)

    if outcome == "PASS":
        if boards_failed != 0 or opens_found != 0 or shorts_found != 0:
            raise ApiError(ERR_VALIDATION,
                           "PASS outcome requires boards_failed=0, opens_found=0, shorts_found=0", 400)

    run["boards_tested"] = boards_tested
    run["boards_failed"] = boards_failed
    run["opens_found"] = opens_found
    run["shorts_found"] = shorts_found

    if outcome == "PASS":
        run["status"] = "COMPLETED_PASS"
        # Advance order
        order = store.fab_orders.get(run["fab_order_id"])
        if order and order["fab_status"] == "AWAITING_ETEST":
            order["fab_status"] = "COMPLETED"
            svc.touch(order)
    else:
        run["status"] = "COMPLETED_FAIL"

    svc.touch(run)
    return success_object(svc.serialize_elec_test_run(run))


# ==============================================================================
# Defect Records
# ==============================================================================

@app.route("/pcb/fab-orders/<oid>/defects", methods=["POST"])
def create_defect(oid):
    user_id, role = require_roles("QualityInspector")
    order = svc.get_order(oid)

    if order["fab_status"] not in ("IN_PRODUCTION", "AWAITING_ETEST"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot log defect in {order['fab_status']}", 409)

    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "panel_array_id", "defect_code", "severity", "boards_affected",
                   "detected_at", "source")

    pa = store.panel_arrays.get(body["panel_array_id"])
    if not pa:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "panel_array_id not found", 422)
    if pa["fab_order_id"] != oid:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "panel_array_id belongs to a different order", 422)

    defect_code = validate_enum(body["defect_code"],
                                ["OPEN", "SHORT", "SPACING", "DRILL_BREAKOUT", "PLATING_VOID",
                                 "SOLDERMASK", "CONTAMINATION", "OVERETCH"],
                                "defect_code")
    if body["defect_code"] == "IMPEDANCE":
        raise ApiError(ERR_VALIDATION, "IMPEDANCE defect_code is reserved for system auto-records", 400)

    severity = validate_enum(body["severity"], ["COSMETIC", "MINOR", "MAJOR", "SCRAP"], "severity")
    boards_affected = validate_int(body["boards_affected"], "boards_affected", min_val=1)
    source = validate_enum(body["source"], ["AOI", "MANUAL", "ETEST"], "source")

    try:
        detected_at = svc.parse_iso(body["detected_at"])
    except Exception:
        raise ApiError(ERR_VALIDATION, "Invalid detected_at", 400)

    fields = svc.make_append_only_fields()
    defect = {
        **fields,
        "fab_order_id": oid,
        "panel_array_id": body["panel_array_id"],
        "defect_code": defect_code,
        "severity": severity,
        "boards_affected": boards_affected,
        "detected_at": detected_at,
        "source": source,
    }
    store.defect_records[defect["id"]] = defect
    return success_object(svc.serialize_defect_record(defect), 201)


@app.route("/pcb/fab-orders/<oid>/defects", methods=["GET"])
def list_order_defects(oid):
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    order = svc.get_order(oid)
    check_customer_ownership(user_id, role, order["customer_id"])
    limit, offset = parse_pagination()
    items = sorted(
        [d for d in store.defect_records.values() if d["fab_order_id"] == oid],
        key=lambda d: d["created_at"]
    )
    page, total = paginate([svc.serialize_defect_record(d) for d in items], limit, offset)
    return success_list(page, limit, offset, total)


@app.route("/pcb/panel-arrays/<paid>/defects", methods=["GET"])
def list_array_defects(paid):
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    pa = svc.get_panel_array(paid)
    order = store.fab_orders.get(pa["fab_order_id"])
    if order:
        check_customer_ownership(user_id, role, order["customer_id"])
    limit, offset = parse_pagination()
    items = sorted(
        [d for d in store.defect_records.values() if d["panel_array_id"] == paid],
        key=lambda d: d["created_at"]
    )
    page, total = paginate([svc.serialize_defect_record(d) for d in items], limit, offset)
    return success_list(page, limit, offset, total)


@app.route("/pcb/defects/pareto", methods=["GET"])
def defect_pareto():
    user_id, role = require_roles("QualityInspector", "ProcessEngineer", "FabAdmin")

    from_iso_str = request.args.get("from_iso")
    to_iso_str = request.args.get("to_iso")

    if from_iso_str:
        try:
            from_dt = svc.parse_iso(from_iso_str)
        except Exception:
            raise ApiError(ERR_VALIDATION, "Invalid from_iso", 400)
    else:
        from_dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    if to_iso_str:
        try:
            to_dt = svc.parse_iso(to_iso_str)
        except Exception:
            raise ApiError(ERR_VALIDATION, "Invalid to_iso", 400)
    else:
        to_dt = store.logical_clock

    # Collect matching defects
    boards_by_code = defaultdict(int)
    for d in store.defect_records.values():
        det = d["detected_at"] if isinstance(d["detected_at"], datetime) else svc.parse_iso(d["detected_at"])
        if not (from_dt <= det < to_dt):
            continue
        if d["severity"] not in ("MAJOR", "SCRAP"):
            continue
        boards_by_code[d["defect_code"]] += d["boards_affected"]

    total_boards = sum(boards_by_code.values())

    # Sort: boards DESC, defect_code ASC
    sorted_codes = sorted(boards_by_code.items(), key=lambda x: (-x[1], x[0]))

    rows = []
    cumulative_boards = 0
    for i, (code, boards) in enumerate(sorted_codes):
        pct = round_half_up_decimal_pub(Decimal(100) * Decimal(boards) / Decimal(total_boards), 2)
        cum_before = Decimal(cumulative_boards) / Decimal(total_boards) * 100
        cumulative_boards += boards
        cum_pct = round_half_up_decimal_pub(Decimal(cumulative_boards) / Decimal(total_boards) * 100, 2)
        vital_few = cum_before < Decimal("80.0")
        rows.append({
            "defect_code": code,
            "boards": boards,
            "pct": float(pct),
            "cumulative_pct": float(cum_pct),
            "vital_few": vital_few,
        })

    return success_object({
        "window_start": svc.iso_str(from_dt),
        "window_end": svc.iso_str(to_dt),
        "total_boards": total_boards,
        "rows": rows,
    })


def round_half_up_decimal_pub(value, places):
    """Public wrapper for rounding in pareto calculation."""
    return svc.round_half_up_decimal(value, places)


# ==============================================================================
# Invoices
# ==============================================================================

@app.route("/pcb/fab-orders/<oid>/invoices/final", methods=["POST"])
def create_invoice(oid):
    user_id, role = require_roles("ProductionPlanner")
    order = svc.get_order(oid)

    if order["fab_status"] not in ("AWAITING_ETEST", "COMPLETED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot create invoice in {order['fab_status']}", 409)

    # At most one invoice per order
    for inv in store.invoices.values():
        if inv["fab_order_id"] == oid:
            raise ApiError(ERR_INVOICE_EXISTS, "Order already has an invoice", 409)

    body = request.get_json(force=True, silent=True) or {}
    require_fields(body, "actual_panels_run")
    actual_panels = validate_int(body["actual_panels_run"], "actual_panels_run", min_val=1)

    pricing = svc.compute_final_pricing(order, actual_panels)
    if not pricing:
        raise ApiError(ERR_INVALID_STATE, "Cannot compute pricing without a released array", 409)

    fields = svc.make_common_fields()
    invoice = {
        **fields,
        "fab_order_id": oid,
        "actual_panels_run": actual_panels,
        "line_items": pricing["line_items"],
        "retest_fees_cents": pricing["retest_fees_cents"],
        "total_cents": pricing["total_cents"],
        "status": "DRAFT",
    }
    store.invoices[invoice["id"]] = invoice
    return success_object(svc.serialize_invoice(invoice), 201)


@app.route("/pcb/fab-orders/<oid>/invoices", methods=["GET"])
def list_order_invoices(oid):
    user_id, role = require_roles(
        "Customer", "SalesEngineer", "CAMOperator", "ProcessEngineer",
        "QualityInspector", "ProductionPlanner", "FabAdmin"
    )
    order = svc.get_order(oid)
    check_customer_ownership(user_id, role, order["customer_id"])
    limit, offset = parse_pagination()
    items = sorted(
        [i for i in store.invoices.values() if i["fab_order_id"] == oid],
        key=lambda i: i["created_at"]
    )
    page, total = paginate([svc.serialize_invoice(i) for i in items], limit, offset)
    return success_list(page, limit, offset, total)


@app.route("/pcb/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    user_id, role = require_roles("Customer", "SalesEngineer", "ProductionPlanner", "FabAdmin")
    inv = svc.get_invoice(iid)
    order = store.fab_orders.get(inv["fab_order_id"])
    if order:
        check_customer_ownership(user_id, role, order["customer_id"])
    return success_object(svc.serialize_invoice(inv))


@app.route("/pcb/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    user_id, role = require_roles("SalesEngineer")
    inv = svc.get_invoice(iid)
    if inv["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, f"Cannot issue from {inv['status']}", 409)
    inv["status"] = "ISSUED"
    svc.touch(inv)
    return success_object(svc.serialize_invoice(inv))


@app.route("/pcb/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    user_id, role = require_roles("Customer")
    inv = svc.get_invoice(iid)
    order = store.fab_orders.get(inv["fab_order_id"])
    if not order:
        raise ApiError(ERR_NOT_FOUND, "Order not found", 404)
    check_customer_ownership(user_id, role, order["customer_id"])
    if inv["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot pay from {inv['status']}", 409)
    inv["status"] = "PAID"
    svc.touch(inv)
    return success_object(svc.serialize_invoice(inv))


# ==============================================================================
# Startup
# ==============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
