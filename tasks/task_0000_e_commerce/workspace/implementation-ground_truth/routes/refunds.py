"""Refund routes: Flask Blueprint for /orders/<order_id>/refunds endpoints."""

from flask import Blueprint, request, g

from middleware import require_auth, require_role, require_order_owner
from response import success, success_list, parse_pagination
from services import order as order_svc
from services import refund as refund_svc

refunds_bp = Blueprint("refunds", __name__)


@refunds_bp.before_request
def _auth():
    require_auth()


# ---------------------------------------------------------------------------
# POST /orders/<order_id>/refunds — Request refund (Customer)
# ---------------------------------------------------------------------------
@refunds_bp.route("/orders/<order_id>/refunds", methods=["POST"])
def create_refund(order_id):
    require_role("Customer")
    order = order_svc.get_order(order_id)
    require_order_owner(order)
    data = request.get_json(force=True)
    result = refund_svc.create_refund(order_id, data, g.user_id)
    return success(result, 201)


# ---------------------------------------------------------------------------
# GET /orders/<order_id>/refunds — List refunds
# ---------------------------------------------------------------------------
@refunds_bp.route("/orders/<order_id>/refunds", methods=["GET"])
def list_refunds(order_id):
    order = order_svc.get_order(order_id)
    if g.role == "Customer":
        require_order_owner(order)
    limit, offset = parse_pagination(request.args)
    items, total = refund_svc.list_refunds(order_id, limit, offset)
    return success_list(items, total, limit, offset)


# ---------------------------------------------------------------------------
# GET /orders/<order_id>/refunds/<refund_id> — Get refund
# ---------------------------------------------------------------------------
@refunds_bp.route("/orders/<order_id>/refunds/<refund_id>", methods=["GET"])
def get_refund(order_id, refund_id):
    order = order_svc.get_order(order_id)
    if g.role == "Customer":
        require_order_owner(order)
    result = refund_svc.get_refund(order_id, refund_id)
    return success(result)


# ---------------------------------------------------------------------------
# POST /orders/<order_id>/refunds/<refund_id>/approve — Approve (Seller/Admin)
# ---------------------------------------------------------------------------
@refunds_bp.route("/orders/<order_id>/refunds/<refund_id>/approve", methods=["POST"])
def approve_refund(order_id, refund_id):
    require_role("Seller", "PlatformAdmin")
    result = refund_svc.approve_refund(order_id, refund_id)
    return success(result)


# ---------------------------------------------------------------------------
# POST /orders/<order_id>/refunds/<refund_id>/reject — Reject (Seller/Admin)
# ---------------------------------------------------------------------------
@refunds_bp.route("/orders/<order_id>/refunds/<refund_id>/reject", methods=["POST"])
def reject_refund(order_id, refund_id):
    require_role("Seller", "PlatformAdmin")
    result = refund_svc.reject_refund(order_id, refund_id)
    return success(result)


# ---------------------------------------------------------------------------
# POST /orders/<order_id>/refunds/<refund_id>/process — Process (PlatformAdmin)
# ---------------------------------------------------------------------------
@refunds_bp.route("/orders/<order_id>/refunds/<refund_id>/process", methods=["POST"])
def process_refund(order_id, refund_id):
    require_role("PlatformAdmin")
    result = refund_svc.process_refund(order_id, refund_id)
    return success(result)
