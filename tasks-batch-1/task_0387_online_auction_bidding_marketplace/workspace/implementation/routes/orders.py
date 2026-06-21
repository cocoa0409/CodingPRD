"""Order endpoints. PRD §3.8 (pay/ship/deliver/cancel), §3.9 (returns)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import response
import constants as C
import middleware as mw
from services import core, sales
from services.auction import TERMINAL_LISTING_STATES
from routes.helpers import get_json_body, paginate_list

bp = Blueprint("orders", __name__)


@bp.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Buyer", "Seller", "PlatformAdmin"})
    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found("Order not found.")
    return response.success(core.ser_order(order), status=200)


@bp.route("/orders", methods=["GET"])
def list_orders():
    caller = mw.require_auth()
    mw.require_role(caller, {"Buyer", "Seller", "PlatformAdmin"})
    listing_id = request.args.get("listing_id")
    buyer_account_id = request.args.get("buyer_account_id")
    seller_account_id = request.args.get("seller_account_id")
    items = list(db.orders.values())
    if listing_id is not None:
        items = [o for o in items if o["listing_id"] == listing_id]
    if buyer_account_id is not None:
        items = [o for o in items if o["buyer_account_id"] == buyer_account_id]
    if seller_account_id is not None:
        items = [o for o in items if o["seller_account_id"] == seller_account_id]
    return paginate_list(items, core.ser_order)


@bp.route("/orders/<order_id>/pay", methods=["POST"])
def pay_order(order_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Buyer"})          # priority 2
    body = get_json_body()
    order = db.orders.get(order_id)             # existence (priority 4)
    if order is None:
        raise errors.not_found("Order not found.")
    # Ownership (priority 3): the acting buyer owns the order.
    if order["buyer_account_id"] != caller.user_id:
        raise errors.not_owner("Only the order's buyer may pay it.")
    mw.check_account_not_closed(caller)

    # OCC (priority 5): expected_order_version must match.
    expected = body.get("expected_order_version", None)
    if expected is None:
        raise errors.invalid_request("expected_order_version is required.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_order_version must be an integer.")
    if expected != order["version"]:
        raise errors.stale_version()

    # State (priority 6): pay defined only from payment_status == UNPAID.
    if order["payment_status"] != "UNPAID":
        raise errors.invalid_state("Only an UNPAID order may be paid.")

    # Append CHARGE; set paid_amount; PAID; fulfillment AWAITING_PAYMENT -> READY_TO_SHIP.
    sales.append_payment(order["id"], "CHARGE", order["total_cents"])
    order["paid_amount_cents"] = order["total_cents"]
    order["payment_status"] = "PAID"
    if order["fulfillment_status"] == "AWAITING_PAYMENT":
        order["fulfillment_status"] = "READY_TO_SHIP"
    core.touch(order)
    return response.success(core.ser_order(order), status=200)


@bp.route("/orders/<order_id>/ship", methods=["POST"])
def ship_order(order_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Seller"})         # priority 2
    order = db.orders.get(order_id)             # existence (priority 4)
    if order is None:
        raise errors.not_found("Order not found.")
    # Ownership (priority 3): the acting seller owns the order.
    if order["seller_account_id"] != caller.user_id:
        raise errors.not_owner("Only the order's seller may ship it.")
    mw.check_account_not_closed(caller)

    # State (priority 6): ship requires payment PAID and fulfillment READY_TO_SHIP.
    if order["payment_status"] != "PAID" or order["fulfillment_status"] != "READY_TO_SHIP":
        raise errors.invalid_state("Order must be PAID and READY_TO_SHIP to ship.")

    order["fulfillment_status"] = "SHIPPED"
    core.touch(order)
    return response.success(core.ser_order(order), status=200)


@bp.route("/orders/<order_id>/deliver", methods=["POST"])
def deliver_order(order_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Buyer"})          # priority 2
    order = db.orders.get(order_id)             # existence (priority 4)
    if order is None:
        raise errors.not_found("Order not found.")
    # Ownership (priority 3): the acting buyer owns the order.
    if order["buyer_account_id"] != caller.user_id:
        raise errors.not_owner("Only the order's buyer may confirm delivery.")
    mw.check_account_not_closed(caller)

    # State (priority 6): deliver defined from fulfillment SHIPPED.
    if order["fulfillment_status"] != "SHIPPED":
        raise errors.invalid_state("Only a SHIPPED order may be delivered.")

    order["fulfillment_status"] = "DELIVERED"
    order["delivered_at"] = db.now_iso()   # record delivery time for the return window
    core.touch(order)
    return response.success(core.ser_order(order), status=200)


@bp.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Seller"})         # priority 2
    order = db.orders.get(order_id)             # existence (priority 4)
    if order is None:
        raise errors.not_found("Order not found.")
    # Ownership (priority 3): the acting seller owns the order.
    if order["seller_account_id"] != caller.user_id:
        raise errors.not_owner("Only the order's seller may cancel it.")
    mw.check_account_not_closed(caller)

    # State (priority 6): cancel defined only while UNPAID/AWAITING_PAYMENT.
    if order["payment_status"] != "UNPAID" or order["fulfillment_status"] != "AWAITING_PAYMENT":
        raise errors.invalid_state("Only an unpaid order may be cancelled.")

    order["fulfillment_status"] = "CANCELLED"
    # Cascade: credit the order's fee invoice (no sale).
    sales.credit_invoice(order)
    # Cascade: cancel the originating listing if not already terminal.
    listing = db.listings.get(order["listing_id"])
    if listing is not None and listing["status"] not in TERMINAL_LISTING_STATES:
        listing["status"] = "CANCELLED"
        core.touch(listing)
    core.touch(order)
    return response.success(core.ser_order(order), status=200)


@bp.route("/orders/<order_id>/complete-return", methods=["POST"])
def complete_return(order_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Seller"})         # priority 2
    order = db.orders.get(order_id)             # existence (priority 4)
    if order is None:
        raise errors.not_found("Order not found.")
    # Ownership (priority 3): the acting seller owns the order.
    if order["seller_account_id"] != caller.user_id:
        raise errors.not_owner("Only the order's seller may complete a return.")
    mw.check_account_not_closed(caller)

    # State (priority 6): return defined only from fulfillment DELIVERED.
    if order["fulfillment_status"] != "DELIVERED":
        raise errors.invalid_state("Only a DELIVERED order may be returned.")

    # Return window (priority 8): clock <= delivered_at + RETURN_WINDOW_SECONDS.
    delivered_at = order.get("delivered_at")
    if delivered_at is not None:
        deadline = db.parse_iso(delivered_at) + timedelta(seconds=C.RETURN_WINDOW_SECONDS)
        if db.now_dt() > deadline:
            raise errors.window_expired("The return window has expired.")

    order["fulfillment_status"] = "RETURNED"
    core.touch(order)   # version bump for the RETURNED transition
    # Cascade: full refund of paid_amount_cents (-> REFUNDED) + credit fee invoice.
    sales.apply_refund(order, order["paid_amount_cents"])
    return response.success(core.ser_order(order), status=200)


@bp.route("/orders/<order_id>/invoice", methods=["GET"])
def get_order_invoice(order_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Seller", "PlatformAdmin"})
    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found("Order not found.")
    # Ownership for Seller: must be the order's seller (admins exempt).
    if caller.role == "Seller" and order["seller_account_id"] != caller.user_id:
        raise errors.not_owner("Only the order's seller may view its invoice.")
    inv = sales.invoice_for_order(order_id)
    if inv is None:
        raise errors.not_found("Invoice not found for this order.")
    return response.success(core.ser_invoice(inv), status=200)


@bp.route("/orders/<order_id>/payments", methods=["GET"])
def list_order_payments(order_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Buyer", "Seller", "PlatformAdmin"})
    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found("Order not found.")
    items = [p for p in db.payments.values() if p["order_id"] == order_id]
    return paginate_list(items, core.ser_payment)
