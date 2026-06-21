"""Order endpoints incl. fulfillment/payment transitions (PRD §3.1, §3.4, §3.11)."""
from flask import Blueprint, request

import db
import helpers
import response
from errors import err
from middleware import get_auth, require_role
from services import domain, serializers

bp = Blueprint("orders", __name__)

DELIVERY_TIERS = {"THRESHOLD", "WHITE_GLOVE"}


# ---------------------------------------------------------------------------
# Create / read
# ---------------------------------------------------------------------------
@bp.post("/orders")
def create_order():
    user_id, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager"})
    body = helpers.get_body()

    customer_id = helpers.require_str(body, "customer_id")
    delivery_tier = helpers.optional_enum(body, "delivery_tier", DELIVERY_TIERS, default="THRESHOLD")
    helpers.fetch(db.customers, customer_id)

    rec = {
        "customer_id": customer_id,
        "sales_associate_user_id": user_id,
        "payment_status": "UNPAID",
        "fulfillment_status": "DRAFT",
        "merchandise_subtotal_cents": 0,
        "service_total_cents": 0,
        "order_total_cents": 0,
        "amount_refunded_cents": 0,
        "delivery_tier": delivery_tier,
        "earliest_schedulable_date": None,
    }
    helpers.stamp_create(rec)
    db.orders[rec["id"]] = rec
    return response.object_response(serializers.order(rec), status=201)


@bp.get("/orders/<oid>")
def get_order(oid):
    user_id, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    rec = helpers.fetch(db.orders, oid)
    if role == "Customer" and user_id != rec["customer_id"]:
        raise err("ERR_FORBIDDEN_NOT_OWNER", "Not the owning customer.")
    return response.object_response(serializers.order(rec))


@bp.get("/orders")
def list_orders():
    _, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager"})
    limit, offset = helpers.get_pagination()
    customer_id = request.args.get("customer_id")
    rows = list(db.orders.values())
    if customer_id:
        rows = [o for o in rows if o["customer_id"] == customer_id]
    page, total = helpers.paginate(rows, limit, offset)
    return response.array_response(
        [serializers.order(o) for o in page], limit, offset, total)


# ---------------------------------------------------------------------------
# FK reverse-reachability lists
# ---------------------------------------------------------------------------
def _customer_owns(order, user_id, role):
    if role == "Customer" and user_id != order["customer_id"]:
        raise err("ERR_FORBIDDEN_NOT_OWNER", "Not the owning customer.")


@bp.get("/orders/<oid>/lines")
def list_order_lines(oid):
    user_id, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    order = helpers.fetch(db.orders, oid)
    _customer_owns(order, user_id, role)
    limit, offset = helpers.get_pagination()
    page, total = helpers.paginate(domain.lines_for_order(oid), limit, offset)
    return response.array_response(
        [serializers.order_line(ln) for ln in page], limit, offset, total)


@bp.get("/orders/<oid>/financing-plans")
def list_order_financing(oid):
    user_id, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    order = helpers.fetch(db.orders, oid)
    _customer_owns(order, user_id, role)
    limit, offset = helpers.get_pagination()
    page, total = helpers.paginate(domain.financing_plans_for_order(oid), limit, offset)
    return response.array_response(
        [serializers.financing_plan(p) for p in page], limit, offset, total)


@bp.get("/orders/<oid>/delivery-stops")
def list_order_stops(oid):
    user_id, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager", "DeliveryDispatcher", "Customer"})
    order = helpers.fetch(db.orders, oid)
    _customer_owns(order, user_id, role)
    limit, offset = helpers.get_pagination()
    page, total = helpers.paginate(domain.stops_for_order(oid), limit, offset)
    return response.array_response(
        [serializers.delivery_stop(s) for s in page], limit, offset, total)


@bp.get("/orders/<oid>/return-requests")
def list_order_returns(oid):
    user_id, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    order = helpers.fetch(db.orders, oid)
    _customer_owns(order, user_id, role)
    limit, offset = helpers.get_pagination()
    page, total = helpers.paginate(domain.returns_for_order(oid), limit, offset)
    return response.array_response(
        [serializers.return_request(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------
@bp.post("/orders/<oid>/confirm")
def confirm_order(oid):
    _, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager"})
    order = helpers.fetch(db.orders, oid)

    if order["fulfillment_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Order is not in DRAFT.")
    if not domain.active_lines_for_order(oid):
        raise err("ERR_EMPTY_ORDER", "Order has no ACTIVE lines.")
    if order["payment_status"] not in ("FINANCED", "PAID_IN_FULL"):
        raise err("ERR_ORDER_NOT_SETTLED", "Order must be settled before confirmation.")

    domain.recompute_order_totals(order)
    order["earliest_schedulable_date"] = domain.compute_earliest_schedulable_date(order)
    order["fulfillment_status"] = "CONFIRMED"
    helpers.touch(order)
    return response.object_response(serializers.order(order))


@bp.post("/orders/<oid>/pay-in-full")
def pay_in_full(oid):
    _, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager"})
    order = helpers.fetch(db.orders, oid)

    if order["payment_status"] != "UNPAID":
        raise err("ERR_ALREADY_SETTLED", "Order payment is not UNPAID.")
    if not domain.active_lines_for_order(oid):
        raise err("ERR_EMPTY_ORDER", "Order has no ACTIVE lines.")
    if domain.open_financing_plans_for_order(oid):
        raise err("ERR_FINANCING_EXISTS", "An open financing plan exists for this order.")

    domain.recompute_order_totals(order)
    order["payment_status"] = "PAID_IN_FULL"
    helpers.touch(order)
    return response.object_response(serializers.order(order))


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    _, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager"})
    order = helpers.fetch(db.orders, oid)

    # PRD §3.11: "cancel while DRAFT or CONFIRMED, provided the order has no
    # DeliveryStop in BOOKED or DISPATCHED status; an active stop blocks the
    # cancellation with ERR_STOP_ACTIVE, and a cancellation attempted from any other
    # state is rejected with ERR_INVALID_STATE."
    # Booking a stop moves the order CONFIRMED -> SCHEDULED (§3.8), so an order that
    # carries an active stop is always SCHEDULED — never DRAFT/CONFIRMED. The
    # stop-active guard must therefore be evaluated before the state gate, otherwise
    # ERR_STOP_ACTIVE (an outcome the PRD explicitly names) is unreachable: every
    # active-stop order would short-circuit on the "any other state" -> ERR_INVALID_STATE
    # branch. A DELIVERED order has no BOOKED/DISPATCHED stop (completion moved it to
    # COMPLETED), so it correctly falls through to ERR_INVALID_STATE below.
    if domain.active_stops_for_order(oid):
        raise err("ERR_STOP_ACTIVE", "Order has an active delivery stop.")
    if order["fulfillment_status"] not in ("DRAFT", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Order is not cancellable from its current state.")

    # CASCADE: cancel every ACTIVE line.
    for ln in domain.active_lines_for_order(oid):
        ln["status"] = "CANCELLED"
        helpers.touch(ln)
    # CASCADE: decline open financing plan(s).
    affected_customers = set()
    for plan in domain.open_financing_plans_for_order(oid):
        plan["status"] = "DECLINED"
        helpers.touch(plan)
        affected_customers.add(plan["customer_id"])
    for cid in affected_customers:
        domain.recompute_open_financing_count(cid)

    order["fulfillment_status"] = "CANCELLED"
    helpers.touch(order)
    return response.object_response(serializers.order(order))


@bp.post("/orders/<oid>/close")
def close_order(oid):
    _, role = get_auth()
    require_role(role, {"StoreManager"})
    order = helpers.fetch(db.orders, oid)

    if order["fulfillment_status"] != "DELIVERED":
        raise err("ERR_INVALID_STATE", "Order is not DELIVERED.")
    open_returns = [r for r in domain.returns_for_order(oid)
                    if r["status"] in ("REQUESTED", "APPROVED")]
    if open_returns:
        raise err("ERR_OPEN_RETURNS_EXIST", "Order has open return requests.")

    order["fulfillment_status"] = "CLOSED"
    helpers.touch(order)
    return response.object_response(serializers.order(order))
