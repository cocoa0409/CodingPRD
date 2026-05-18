from flask import Blueprint, request
from store import store
from models import serialize
from middleware import check_role_permission
from response import success_response
from pagination import get_pagination_params, paginate
from errors import raise_error, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_STATE
from services.computations import recompute_bonus_tier
from models import touch

bp = Blueprint("fines", __name__)


@bp.route("/api/fines/<fine_id>", methods=["GET"])
def get_fine(fine_id):
    check_role_permission({"PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer"})
    fine = store.fines.get(fine_id)
    if not fine:
        raise_error(ERR_NOT_FOUND, "Fine not found")

    if request.user_role in ("Rider", "Restaurant", "Customer"):
        if fine["subject_id"] != request.user_id:
            raise_error(ERR_FORBIDDEN, "Cannot view another subject's fine")

    return success_response(serialize(fine))


@bp.route("/api/fines", methods=["GET"])
def list_fines():
    check_role_permission({"PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer"})
    limit, offset = get_pagination_params()

    items = sorted(store.fines.values(), key=lambda f: f["created_at"])

    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    settlement_status = request.args.get("settlement_status")

    if subject_type:
        items = [f for f in items if f["subject_type"] == subject_type]
    if subject_id:
        items = [f for f in items if f["subject_id"] == subject_id]
    if settlement_status:
        items = [f for f in items if f["settlement_status"] == settlement_status]

    if request.user_role in ("Rider", "Restaurant", "Customer"):
        items = [f for f in items if f["subject_id"] == request.user_id]

    page, pagination_meta = paginate(items, limit, offset)
    return success_response([serialize(f) for f in page], 200, pagination_meta)


@bp.route("/api/fines/<fine_id>/waive", methods=["POST"])
def waive_fine(fine_id):
    check_role_permission({"CustomerService", "PlatformAdmin"})
    fine = store.fines.get(fine_id)
    if not fine:
        raise_error(ERR_NOT_FOUND, "Fine not found")

    if fine["settlement_status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "Fine must be PENDING to waive")

    fine["settlement_status"] = "WAIVED"

    if fine["subject_type"] == "RIDER":
        rider = store.riders.get(fine["subject_id"])
        if rider:
            rider["wallet_balance_cents"] += fine["amount_cents"]
            recompute_bonus_tier(rider)
            touch(rider)
    elif fine["subject_type"] == "CUSTOMER":
        customer = store.customers.get(fine["subject_id"])
        if customer:
            customer["credit_balance_cents"] += fine["amount_cents"]
            touch(customer)
    elif fine["subject_type"] == "RESTAURANT":
        restaurant = store.restaurants.get(fine["subject_id"])
        if restaurant:
            restaurant["pending_settlement_cents"] += fine["amount_cents"]
            touch(restaurant)

    return success_response(serialize(fine))
