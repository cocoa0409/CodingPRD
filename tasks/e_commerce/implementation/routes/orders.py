"""Order routes: Flask Blueprint for /orders endpoints."""

from flask import Blueprint, request, g

from middleware import require_auth, require_role, require_order_owner, require_shop_owner
from response import success, success_list, parse_pagination
from services import order as order_svc
from services import shop as shop_svc

orders_bp = Blueprint("orders", __name__)


@orders_bp.before_request
def _auth():
    require_auth()


# ---------------------------------------------------------------------------
# POST /orders — Create order (Customer)
# ---------------------------------------------------------------------------
@orders_bp.route("/orders", methods=["POST"])
def create_order():
    require_role("Customer")
    data = request.get_json(force=True)
    result = order_svc.create_order(data, g.user_id)
    return success(result, 201)


# ---------------------------------------------------------------------------
# GET /orders — List orders
# ---------------------------------------------------------------------------
@orders_bp.route("/orders", methods=["GET"])
def list_orders():
    limit, offset = parse_pagination(request.args)
    filters = {}
    if g.role == "Customer":
        filters["customer_id"] = g.user_id
    elif g.role == "Seller":
        shop_id = request.args.get("shop_id")
        if shop_id:
            filters["shop_id"] = shop_id
    # PlatformAdmin sees all
    items, total = order_svc.list_orders(filters, limit, offset)
    return success_list(items, total, limit, offset)


# ---------------------------------------------------------------------------
# GET /orders/<order_id> — Get order
# ---------------------------------------------------------------------------
@orders_bp.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    order = order_svc.get_order(order_id)
    if g.role == "Customer":
        require_order_owner(order)
    return success(order)


# ---------------------------------------------------------------------------
# POST /orders/<order_id>/pay — Initiate payment (Customer)
# ---------------------------------------------------------------------------
@orders_bp.route("/orders/<order_id>/pay", methods=["POST"])
def pay_order(order_id):
    require_role("Customer")
    order = order_svc.get_order(order_id)
    require_order_owner(order)
    data = request.get_json(force=True) if request.data else {}
    result = order_svc.pay_order(order_id, data, g.user_id)
    return success(result)


# ---------------------------------------------------------------------------
# POST /orders/<order_id>/confirm-payment — Confirm payment (PlatformAdmin)
# ---------------------------------------------------------------------------
@orders_bp.route("/orders/<order_id>/confirm-payment", methods=["POST"])
def confirm_payment(order_id):
    require_role("PlatformAdmin")
    result = order_svc.confirm_payment(order_id)
    return success(result)


# ---------------------------------------------------------------------------
# POST /orders/<order_id>/payment-failed — Payment failed (PlatformAdmin)
# ---------------------------------------------------------------------------
@orders_bp.route("/orders/<order_id>/payment-failed", methods=["POST"])
def payment_failed(order_id):
    require_role("PlatformAdmin")
    result = order_svc.payment_failed(order_id)
    return success(result)


# ---------------------------------------------------------------------------
# POST /orders/<order_id>/cancel — Cancel order (Customer)
# ---------------------------------------------------------------------------
@orders_bp.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    require_role("Customer")
    order = order_svc.get_order(order_id)
    require_order_owner(order)
    result = order_svc.cancel_order(order_id, g.user_id)
    return success(result)


# ---------------------------------------------------------------------------
# POST /orders/<order_id>/process — Start processing (Seller)
# ---------------------------------------------------------------------------
@orders_bp.route("/orders/<order_id>/start-processing", methods=["POST"])
def start_processing(order_id):
    require_role("Seller")
    order = order_svc.get_order(order_id)
    shop = shop_svc.get_shop(order["shop_id"])
    require_shop_owner(shop)
    result = order_svc.start_processing(order_id)
    return success(result)


# ---------------------------------------------------------------------------
# POST /orders/<order_id>/ship — Ship order (Seller)
# ---------------------------------------------------------------------------
@orders_bp.route("/orders/<order_id>/ship", methods=["POST"])
def ship_order(order_id):
    require_role("Seller")
    result = order_svc.ship_order(order_id)
    return success(result)


# ---------------------------------------------------------------------------
# POST /orders/<order_id>/deliver — Deliver order (Seller / PlatformAdmin)
# ---------------------------------------------------------------------------
@orders_bp.route("/orders/<order_id>/deliver", methods=["POST"])
def deliver_order(order_id):
    require_role("Seller", "PlatformAdmin")
    result = order_svc.deliver_order(order_id)
    return success(result)
