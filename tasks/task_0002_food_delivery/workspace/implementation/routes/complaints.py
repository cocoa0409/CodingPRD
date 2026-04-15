"""Complaint routes."""

from flask import Blueprint, request as req
import db
from errors import raise_error, ERR_ORDER_NOT_FOUND, ERR_COMPLAINT_NOT_FOUND, \
    ERR_ORDER_NOT_ELIGIBLE_FOR_COMPLAINT, ERR_MAX_COMPLAINTS_REACHED, \
    ERR_INVALID_STATE, ERR_RESOLUTION_EXCEEDS_ORDER
from middleware import require_roles
from response import success_response, list_response
from services.calculations import create_wallet_transaction, add_penalty

bp = Blueprint("complaints", __name__)

ELIGIBLE_STATUSES = {"DELIVERED", "CANCELLED_BY_CUSTOMER", "CANCELLED_BY_RESTAURANT", "CANCELLED_BY_PLATFORM"}


def _get_order_or_404(oid):
    o = db.orders.get(oid)
    if not o:
        raise_error(ERR_ORDER_NOT_FOUND, "The referenced order does not exist.")
    return o


def _get_complaint_or_404(order_id, complaint_id):
    _get_order_or_404(order_id)
    c = db.complaints.get(complaint_id)
    if not c or c["order_id"] != order_id:
        raise_error(ERR_COMPLAINT_NOT_FOUND, "The referenced complaint does not exist.")
    return c


def _paginate(request):
    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    return limit, offset


@bp.route("/platform/orders/<order_id>/complaints", methods=["POST"])
def file_complaint(order_id):
    require_roles("customer", "restaurant", "rider")
    order = _get_order_or_404(order_id)
    if order["status"] not in ELIGIBLE_STATUSES:
        raise_error(ERR_ORDER_NOT_ELIGIBLE_FOR_COMPLAINT, "Order not eligible for complaint.")
    # Max 2 complaints per order
    count = sum(1 for c in db.complaints.values() if c["order_id"] == order_id)
    if count >= 2:
        raise_error(ERR_MAX_COMPLAINTS_REACHED, "Maximum 2 complaints per order.")

    body = req.get_json(force=True, silent=True) or {}
    now = db.now_iso()
    complaint = {
        "id": db.new_id(),
        "order_id": order_id,
        "filed_by": body.get("filed_by"),
        "filer_id": body.get("filer_id"),
        "category": body.get("category"),
        "description": body.get("description"),
        "status": "FILED",
        "resolution_amount_cents": None,
        "assigned_agent_id": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.complaints[complaint["id"]] = complaint
    return success_response(complaint, 201)


@bp.route("/platform/orders/<order_id>/complaints", methods=["GET"])
def list_complaints(order_id):
    require_roles("customer", "restaurant", "rider", "platform_admin", "customer_service")
    _get_order_or_404(order_id)
    limit, offset = _paginate(req)
    items = sorted(
        [c for c in db.complaints.values() if c["order_id"] == order_id],
        key=lambda x: x["created_at"],
    )
    total = len(items)
    page = items[offset:offset + limit]
    return list_response(page, total, limit, offset)


@bp.route("/platform/orders/<order_id>/complaints/<complaint_id>/assign", methods=["POST"])
def assign_complaint(order_id, complaint_id):
    require_roles("customer_service", "platform_admin")
    c = _get_complaint_or_404(order_id, complaint_id)
    if c["status"] not in ("FILED", "ESCALATED"):
        raise_error(ERR_INVALID_STATE, "Complaint must be FILED or ESCALATED to assign.")
    body = req.get_json(force=True, silent=True) or {}
    c["assigned_agent_id"] = body.get("assigned_agent_id")
    c["status"] = "UNDER_REVIEW"
    c["updated_at"] = db.now_iso()
    c["version"] += 1
    return success_response(c)


@bp.route("/platform/orders/<order_id>/complaints/<complaint_id>/escalate", methods=["POST"])
def escalate_complaint(order_id, complaint_id):
    require_roles("customer_service")
    c = _get_complaint_or_404(order_id, complaint_id)
    if c["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Complaint must be UNDER_REVIEW to escalate.")
    c["status"] = "ESCALATED"
    c["updated_at"] = db.now_iso()
    c["version"] += 1
    return success_response(c)


@bp.route("/platform/orders/<order_id>/complaints/<complaint_id>/resolve", methods=["POST"])
def resolve_complaint(order_id, complaint_id):
    require_roles("customer_service", "platform_admin")
    c = _get_complaint_or_404(order_id, complaint_id)
    if c["status"] not in ("UNDER_REVIEW", "ESCALATED"):
        raise_error(ERR_INVALID_STATE, "Complaint must be UNDER_REVIEW or ESCALATED to resolve.")

    body = req.get_json(force=True, silent=True) or {}
    resolution_type = body.get("resolution_type")
    resolution_amount = body.get("resolution_amount_cents", 0)

    order = db.orders[order_id]

    if resolution_type == "REFUND":
        if resolution_amount > order["total_cents"]:
            raise_error(ERR_RESOLUTION_EXCEEDS_ORDER, "Resolution amount exceeds order total.")
        c["resolution_amount_cents"] = resolution_amount
        c["status"] = "RESOLVED_REFUND"

        # Wallet refund
        create_wallet_transaction(order["customer_id"], "REFUND", resolution_amount, reference_id=order_id)

        # Payment status
        if resolution_amount >= order["total_cents"]:
            order["payment_status"] = "REFUNDED"
            # Clawback from restaurant
            restaurant = db.restaurants.get(order["restaurant_id"])
            if restaurant:
                restaurant["balance_pending_cents"] -= order["restaurant_payout_cents"]
                restaurant["updated_at"] = db.now_iso()
                restaurant["version"] += 1
        else:
            order["payment_status"] = "PARTIALLY_REFUNDED"

        order["updated_at"] = db.now_iso()
        order["version"] += 1

        # If complaint against rider, penalty
        if c["filed_by"] == "CUSTOMER" or c["filed_by"] == "RESTAURANT":
            # check if there's a rider associated via delivery
            for d in db.deliveries.values():
                if d["order_id"] == order_id and d["status"] == "DELIVERED":
                    rider = db.riders.get(d["rider_id"])
                    if rider:
                        add_penalty(rider, 15, "COMPLAINT_UPHELD", complaint_id=complaint_id)
                    break

    elif resolution_type == "CREDIT":
        if resolution_amount > order["total_cents"]:
            raise_error(ERR_RESOLUTION_EXCEEDS_ORDER, "Resolution amount exceeds order total.")
        c["resolution_amount_cents"] = resolution_amount
        c["status"] = "RESOLVED_CREDIT"
        create_wallet_transaction(order["customer_id"], "CREDIT", resolution_amount, reference_id=order_id)

    elif resolution_type == "NO_ACTION":
        c["status"] = "RESOLVED_NO_ACTION"

    c["updated_at"] = db.now_iso()
    c["version"] += 1
    return success_response(c)
