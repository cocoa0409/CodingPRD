"""DeliveryOrder endpoints (PRD §3.6)."""
from flask import Blueprint, request

import db
import errors
from clock import clock_now, clock_now_iso
from common import (parse_pagination, paginate, sort_by_created,
                    require_int, require_enum, optional_enum)
from middleware import require_auth, require_role, check_owner, get_json_body
from response import object_response, array_response
from services import lookups as L
from services import calculations as C
from routes.tanks import recompute_reorder

bp = Blueprint("orders", __name__)

PRIORITIES = {"STANDARD", "EMERGENCY"}
READ_ROLES = {"AccountManager", "Dispatcher", "Driver", "Customer"}


def _order_under_account(account_id, order_id):
    """Resolve account then order, validating left-to-right + ownership of order."""
    acc = L.get_account(account_id)
    order = L.get_order(order_id)
    if order["account_id"] != acc["id"]:
        raise errors.ApiError(errors.ERR_NOT_FOUND, 404, "Order not under account")
    return acc, order


def _maybe_autocomplete_route(route):
    """If a DISPATCHED route has no SCHEDULED orders left, auto-complete it."""
    if route is None or route["status"] != "DISPATCHED":
        return
    has_scheduled = any(
        o.get("route_id") == route["id"] and o["status"] == "SCHEDULED"
        for o in db.delivery_orders.values())
    if not has_scheduled:
        route["status"] = "COMPLETED"
        db.touch(route)


@bp.post("/accounts/<account_id>/delivery-orders")
def create_order(account_id):
    user_id, role = require_auth()
    require_role(role, {"Customer", "Dispatcher"})
    acc = L.get_account(account_id)
    check_owner(role, user_id, acc["id"])
    body = get_json_body()

    tank_id = body.get("tank_id")
    if not isinstance(tank_id, str) or not tank_id.strip():
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400,
                              "tank_id is required")
    requested = require_int(body, "requested_gallons", minimum=1)
    priority = optional_enum(body, "priority", PRIORITIES, default="STANDARD")

    # Body well-formedness includes that the referenced tank exists and belongs
    # to this account (a malformed referential body). Validate after the simple
    # field checks.
    tank = db.tanks.get(tank_id)
    if tank is None or tank["account_id"] != acc["id"]:
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400,
                              "tank_id does not reference a tank on this account")

    rec = {
        "account_id": acc["id"],
        "tank_id": tank_id,
        "route_id": None,
        "origin": "WILL_CALL",
        "requested_gallons": requested,
        "priority": priority,
        "status": "CREATED",
        "delivered_gallons": None,
        "price_cents_per_gallon": None,
        "invoice_total_cents": None,
        "budget_plan_id": None,
    }
    db.stamp_create_full(rec)
    db.delivery_orders[rec["id"]] = rec
    return object_response(L.serialize_order(rec), 201)


@bp.get("/delivery-orders/<order_id>")
def get_order(order_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    order = L.get_order(order_id)
    check_owner(role, user_id, order["account_id"])
    return object_response(L.serialize_order(order), 200)


@bp.get("/delivery-orders")
def list_orders():
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    tank_id = request.args.get("tank_id")
    route_id = request.args.get("route_id")
    budget_plan_id = request.args.get("budget_plan_id")
    status = request.args.get("status")
    origin = request.args.get("origin")

    items = list(db.delivery_orders.values())
    if role == "Customer":
        items = [o for o in items if o.get("account_id") == user_id]
    if account_id is not None:
        items = [o for o in items if o.get("account_id") == account_id]
    if tank_id is not None:
        items = [o for o in items if o.get("tank_id") == tank_id]
    if route_id is not None:
        items = [o for o in items if o.get("route_id") == route_id]
    if budget_plan_id is not None:
        items = [o for o in items if o.get("budget_plan_id") == budget_plan_id]
    if status is not None:
        items = [o for o in items if o.get("status") == status]
    if origin is not None:
        items = [o for o in items if o.get("origin") == origin]

    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([L.serialize_order(o) for o in page], limit, offset, total)


@bp.post("/accounts/<account_id>/delivery-orders/<order_id>/assign")
def assign_order(account_id, order_id):
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    acc, order = _order_under_account(account_id, order_id)
    body = get_json_body()

    route_id = body.get("route_id")
    if not isinstance(route_id, str) or not route_id.strip():
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400, "route_id is required")

    # State legality first (priority 6).
    if order["status"] != "CREATED":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Order is not CREATED")

    route = db.routes.get(route_id)
    if route is None:
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400,
                              "route_id does not reference a route")

    # Referential: route must be PLANNING.
    if route["status"] != "PLANNING":
        raise errors.ApiError(errors.ERR_ROUTE_NOT_PLANNING, 409,
                              "Target route is not PLANNING")

    tank = db.tanks.get(order["tank_id"])
    # Safety: tank must be IN_SERVICE.
    if tank is None or tank["service_status"] != "IN_SERVICE":
        raise errors.ApiError(errors.ERR_TANK_NOT_IN_SERVICE, 409,
                              "Tank is not IN_SERVICE")
    # Safety: most recent inspection must be PASSED.
    insp = L.latest_inspection(tank["id"])
    if insp is None or insp["result"] != "PASSED":
        raise errors.ApiError(errors.ERR_SAFETY_CHECK_REQUIRED, 409,
                              "Tank requires a passed safety inspection")

    # Fiscal: capacity.
    truck = db.trucks.get(route["truck_id"])
    if route["reserved_gallons"] + order["requested_gallons"] > truck["daily_capacity_gallons"]:
        raise errors.ApiError(errors.ERR_ROUTE_CAPACITY_EXCEEDED, 409,
                              "Route capacity exceeded")

    order["status"] = "SCHEDULED"
    order["route_id"] = route["id"]
    db.touch(order)
    route["reserved_gallons"] += order["requested_gallons"]
    db.touch(route)

    return object_response(L.serialize_order(order), 200)


@bp.post("/accounts/<account_id>/delivery-orders/<order_id>/unassign")
def unassign_order(account_id, order_id):
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    acc, order = _order_under_account(account_id, order_id)

    if order["status"] != "SCHEDULED":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Order is not SCHEDULED")
    route = db.routes.get(order.get("route_id"))
    if route is not None and route["status"] == "DISPATCHED":
        raise errors.ApiError(errors.ERR_ROUTE_ALREADY_DISPATCHED, 409,
                              "Route already dispatched")

    order["status"] = "CREATED"
    if route is not None:
        route["reserved_gallons"] -= order["requested_gallons"]
        db.touch(route)
    order["route_id"] = None
    db.touch(order)

    return object_response(L.serialize_order(order), 200)


@bp.post("/accounts/<account_id>/delivery-orders/<order_id>/hold")
def hold_order(account_id, order_id):
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    acc, order = _order_under_account(account_id, order_id)

    if order["status"] != "SCHEDULED":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Order is not SCHEDULED")
    route = db.routes.get(order.get("route_id"))

    order["status"] = "HOLD"
    if route is not None:
        route["reserved_gallons"] -= order["requested_gallons"]
        db.touch(route)
    # route_id retained for later resume.
    db.touch(order)

    return object_response(L.serialize_order(order), 200)


@bp.post("/accounts/<account_id>/delivery-orders/<order_id>/resume")
def resume_order(account_id, order_id):
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    acc, order = _order_under_account(account_id, order_id)

    if order["status"] != "HOLD":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Order is not HOLD")
    route = db.routes.get(order.get("route_id"))
    if route is None or route["status"] != "PLANNING":
        raise errors.ApiError(errors.ERR_ROUTE_NOT_PLANNING, 409,
                              "Retained route is not PLANNING")
    truck = db.trucks.get(route["truck_id"])
    if route["reserved_gallons"] + order["requested_gallons"] > truck["daily_capacity_gallons"]:
        raise errors.ApiError(errors.ERR_ROUTE_CAPACITY_EXCEEDED, 409,
                              "Route capacity exceeded")

    order["status"] = "SCHEDULED"
    db.touch(order)
    route["reserved_gallons"] += order["requested_gallons"]
    db.touch(route)

    return object_response(L.serialize_order(order), 200)


@bp.post("/accounts/<account_id>/delivery-orders/<order_id>/deliver")
def deliver_order(account_id, order_id):
    _, role = require_auth()
    require_role(role, {"Driver"})
    acc, order = _order_under_account(account_id, order_id)
    body = get_json_body()

    delivered_gallons = require_int(body, "delivered_gallons", minimum=1)
    expected_version = require_int(body, "expected_account_version")

    # State legality (priority 6).
    if order["status"] != "SCHEDULED":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Order is not SCHEDULED")

    # Route phase (referential).
    route = db.routes.get(order.get("route_id"))
    if route is None or route["status"] != "DISPATCHED":
        raise errors.ApiError(errors.ERR_ROUTE_NOT_DISPATCHED, 409,
                              "Route is not DISPATCHED")

    # Tank in service (safety).
    tank = db.tanks.get(order["tank_id"])
    if tank is None or tank["service_status"] != "IN_SERVICE":
        raise errors.ApiError(errors.ERR_TANK_NOT_IN_SERVICE, 409,
                              "Tank is not IN_SERVICE")

    # Pricing availability (business).
    plan = L.active_price_plan(acc["id"])
    if plan is None:
        raise errors.ApiError(errors.ERR_NO_ACTIVE_PRICE_PLAN, 409,
                              "Account has no ACTIVE price plan")
    market_price_cpg = None
    if plan["plan_type"] in ("MARKET", "CAP"):
        mp = L.active_market_price(acc["region_code"], acc["fuel_type"])
        if mp is None:
            raise errors.ApiError(errors.ERR_NO_MARKET_PRICE, 409,
                                  "No ACTIVE market price for region/fuel")
        market_price_cpg = mp["market_price_cents_per_gallon"]

    # Overfill (fiscal).
    if tank["current_gallons"] + delivered_gallons > tank["capacity_gallons"]:
        raise errors.ApiError(errors.ERR_DELIVERY_OVERFILL, 409,
                              "Delivery would overfill the tank")

    # OCC (priority 14 — last).
    if expected_version != acc["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412,
                              "expected_account_version does not match account version")

    # --- All checks passed; apply. ---
    price_cpg = C.delivery_price(plan, market_price_cpg, delivered_gallons)
    invoice = C.invoice_total(delivered_gallons, price_cpg, order["priority"], order["origin"])

    order["status"] = "DELIVERED"
    order["delivered_gallons"] = delivered_gallons
    order["price_cents_per_gallon"] = price_cpg
    order["invoice_total_cents"] = invoice

    # CASCADE step 1: tank level + last_delivery_at.
    tank["current_gallons"] += delivered_gallons
    tank["last_delivery_at"] = clock_now_iso()
    # CASCADE step 2: recompute reorder_status from the new level.
    recompute_reorder(tank)
    db.touch(tank)

    # CASCADE step 3: ledger debit + budget actuals.
    acc["credit_balance_cents"] -= invoice
    budget = L.active_budget_plan(acc["id"])
    if budget is not None:
        budget["actual_cost_to_date_cents"] += invoice
        budget["settlement_balance_cents"] = C.settlement_balance(
            budget["installments_paid_count"],
            budget["monthly_installment_cents"],
            budget["actual_cost_to_date_cents"])
        db.touch(budget)
        order["budget_plan_id"] = budget["id"]

    # Release reservation (reservation consumed).
    route["reserved_gallons"] -= order["requested_gallons"]
    db.touch(route)

    db.touch(order)

    # Account version bump (and updated_at refresh) for this ledger mutation.
    db.touch(acc)

    # Route may auto-complete now.
    _maybe_autocomplete_route(route)

    return object_response(L.serialize_order(order), 200)


@bp.post("/accounts/<account_id>/delivery-orders/<order_id>/cancel")
def cancel_order(account_id, order_id):
    user_id, role = require_auth()
    require_role(role, {"Dispatcher", "Customer"})
    acc, order = _order_under_account(account_id, order_id)
    check_owner(role, user_id, order["account_id"])

    status = order["status"]
    if status == "CREATED":
        order["status"] = "CANCELLED"
        db.touch(order)
    elif status == "HOLD":
        order["status"] = "CANCELLED"
        order["route_id"] = None  # no reservation held while on HOLD
        db.touch(order)
    else:
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409,
                              "Order cannot be cancelled from its current state")

    return object_response(L.serialize_order(order), 200)


@bp.post("/accounts/<account_id>/delivery-orders/<order_id>/reverse")
def reverse_order(account_id, order_id):
    _, role = require_auth()
    require_role(role, {"AccountManager"})
    acc, order = _order_under_account(account_id, order_id)
    body = get_json_body()

    expected_version = require_int(body, "expected_account_version")

    if order["status"] != "DELIVERED":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Order is not DELIVERED")
    if expected_version != acc["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412,
                              "expected_account_version does not match account version")

    order["status"] = "CANCELLED"

    # COMPENSATION: tank level back, reorder recompute.
    tank = db.tanks.get(order["tank_id"])
    if tank is not None:
        tank["current_gallons"] -= order["delivered_gallons"]
        recompute_reorder(tank)
        db.touch(tank)

    # Ledger credit back.
    acc["credit_balance_cents"] += order["invoice_total_cents"]

    # Budget actuals backed out.
    if order.get("budget_plan_id"):
        budget = db.budget_plans.get(order["budget_plan_id"])
        if budget is not None:
            budget["actual_cost_to_date_cents"] -= order["invoice_total_cents"]
            budget["settlement_balance_cents"] = C.settlement_balance(
                budget["installments_paid_count"],
                budget["monthly_installment_cents"],
                budget["actual_cost_to_date_cents"])
            db.touch(budget)

    db.touch(order)
    db.touch(acc)

    return object_response(L.serialize_order(order), 200)
