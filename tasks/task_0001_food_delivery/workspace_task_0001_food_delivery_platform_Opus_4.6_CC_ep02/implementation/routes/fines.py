from flask import Blueprint, request
from auth import require_roles, check_ownership
from errors import APIError
from models import fines, riders, customers, restaurants, touch
from response_envelope import success_response
from pagination import parse_pagination_params, paginate
from calculations import recompute_rider_bonus

bp = Blueprint("fines", __name__)


def fine_dict(f):
    return {
        "id": f["id"],
        "subject_type": f["subject_type"],
        "subject_id": f["subject_id"],
        "reason": f["reason"],
        "amount_cents": f["amount_cents"],
        "settlement_status": f["settlement_status"],
        "order_id": f.get("order_id"),
        "created_at": f["created_at"],
    }


@bp.route("/api/fines/<fine_id>", methods=["GET"])
@require_roles("PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer")
def get_fine(fine_id):
    f = fines.get(fine_id)
    if not f:
        raise APIError("ERR_NOT_FOUND", "Fine not found")

    if request.user_role in ("Rider", "Customer", "Restaurant"):
        if f["subject_id"] != request.user_id:
            raise APIError("ERR_FORBIDDEN", "Access denied: identity mismatch")

    return success_response(fine_dict(f))


@bp.route("/api/fines", methods=["GET"])
@require_roles("PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer")
def list_fines():
    limit, offset = parse_pagination_params(request.args)

    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    settlement_status = request.args.get("settlement_status")

    if request.user_role in ("Rider", "Customer", "Restaurant"):
        if subject_id and subject_id != request.user_id:
            raise APIError("ERR_FORBIDDEN", "Access denied: identity mismatch")
        subject_id = request.user_id

    items = sorted(fines.values(), key=lambda x: x["created_at"])

    if subject_type:
        items = [f for f in items if f["subject_type"] == subject_type]
    if subject_id:
        items = [f for f in items if f["subject_id"] == subject_id]
    if settlement_status:
        items = [f for f in items if f["settlement_status"] == settlement_status]

    page, pagination = paginate(items, limit, offset)
    return success_response([fine_dict(f) for f in page], 200, "array", pagination)


@bp.route("/api/fines/<fine_id>/waive", methods=["POST"])
@require_roles("CustomerService", "PlatformAdmin")
def waive_fine(fine_id):
    f = fines.get(fine_id)
    if not f:
        raise APIError("ERR_NOT_FOUND", "Fine not found")

    if f["settlement_status"] != "PENDING":
        raise APIError("ERR_INVALID_STATE", "Fine must be in PENDING to waive")

    f["settlement_status"] = "WAIVED"

    if f["subject_type"] == "RIDER":
        rider = riders.get(f["subject_id"])
        if rider:
            rider["wallet_balance_cents"] += f["amount_cents"]
            recompute_rider_bonus(rider)
            touch(rider)
    elif f["subject_type"] == "CUSTOMER":
        customer = customers.get(f["subject_id"])
        if customer:
            customer["credit_balance_cents"] += f["amount_cents"]
            touch(customer)
    elif f["subject_type"] == "RESTAURANT":
        restaurant = restaurants.get(f["subject_id"])
        if restaurant:
            restaurant["pending_settlement_cents"] += f["amount_cents"]
            touch(restaurant)

    return success_response(fine_dict(f))
