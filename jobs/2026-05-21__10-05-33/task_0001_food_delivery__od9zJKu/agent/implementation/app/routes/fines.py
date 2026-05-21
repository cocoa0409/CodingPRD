from __future__ import annotations

from flask import Blueprint, g, request

from .. import metrics, projections, resolvers
from ..auth import require_role
from ..clock import iso_now
from ..envelope import err_forbidden, err_invalid_state, success, success_list
from ..store import store
from ..validators import pagination_params

bp = Blueprint("fines", __name__)


VALID_SUBJECT_TYPES = {"RIDER", "RESTAURANT", "CUSTOMER"}
VALID_SETTLEMENT_STATUSES = {"PENDING", "SETTLED", "WAIVED"}


def _can_view(f: dict) -> bool:
    if g.user_role in ("PlatformAdmin", "CustomerService"):
        return True
    if g.user_role == "Rider":
        return f["subject_type"] == "RIDER" and g.user_id == f["subject_id"]
    if g.user_role == "Restaurant":
        return f["subject_type"] == "RESTAURANT" and g.user_id == f["subject_id"]
    if g.user_role == "Customer":
        return f["subject_type"] == "CUSTOMER" and g.user_id == f["subject_id"]
    return False


@bp.route("/api/fines/<fid>", methods=["GET"])
def read_fine(fid: str):
    require_role("PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer")
    f = resolvers.fine(fid)
    if not _can_view(f):
        raise err_forbidden("Cannot view this fine")
    return success(projections.fine(f))


@bp.route("/api/fines", methods=["GET"])
def list_fines():
    require_role("PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer")
    limit, offset = pagination_params()
    f_type = request.args.get("subject_type")
    f_id = request.args.get("subject_id")
    f_status = request.args.get("settlement_status")
    # Non-CS / non-Admin: must specify subject_id == their own id and subject_type matches their role
    if g.user_role in ("Rider", "Restaurant", "Customer"):
        expected_type = {"Rider": "RIDER", "Restaurant": "RESTAURANT", "Customer": "CUSTOMER"}[g.user_role]
        if f_id and f_id != g.user_id:
            raise err_forbidden("Can only query own fines")
        if f_type and f_type != expected_type:
            raise err_forbidden("Can only query own fines")
        # Even if filter is missing, scope to own
        f_id = g.user_id
        f_type = expected_type
    items = list(store.fines.values())
    if f_type:
        items = [f for f in items if f["subject_type"] == f_type]
    if f_id:
        items = [f for f in items if f["subject_id"] == f_id]
    if f_status:
        items = [f for f in items if f["settlement_status"] == f_status]
    items.sort(key=lambda f: f["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([projections.fine(f) for f in page], limit, offset, total)


@bp.route("/api/fines/<fid>/waive", methods=["POST"])
def waive_fine(fid: str):
    require_role("CustomerService", "PlatformAdmin")
    f = resolvers.fine(fid)
    if f["settlement_status"] != "PENDING":
        raise err_invalid_state(f"Fine settlement_status is {f['settlement_status']}; cannot waive")
    f["settlement_status"] = "WAIVED"
    # Reverse ledger effects
    if f["subject_type"] == "RIDER":
        rider = store.riders.get(f["subject_id"])
        if rider:
            rider["wallet_balance_cents"] = rider.get("wallet_balance_cents", 0) + f["amount_cents"]
            metrics.recompute_all(rider)
            from ..entities import bump
            bump(rider)
    elif f["subject_type"] == "CUSTOMER":
        customer = store.customers.get(f["subject_id"])
        if customer:
            customer["credit_balance_cents"] = customer.get("credit_balance_cents", 0) + f["amount_cents"]
            from ..entities import bump
            bump(customer)
    elif f["subject_type"] == "RESTAURANT":
        restaurant = store.restaurants.get(f["subject_id"])
        if restaurant:
            restaurant["pending_settlement_cents"] = (
                restaurant.get("pending_settlement_cents", 0) + f["amount_cents"]
            )
            from ..entities import bump
            bump(restaurant)
    return success(projections.fine(f))
