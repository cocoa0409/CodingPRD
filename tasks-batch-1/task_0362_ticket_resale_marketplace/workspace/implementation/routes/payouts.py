from flask import Blueprint, request

import db
import validate
import response
import errors
from errors import err
from middleware import get_user_context, require_role, require_ownership
from services import lookup, serialize, paginate, recompute

bp = Blueprint("payouts", __name__)

READ_ROLES = ("PlatformAdmin", "Seller", "TrustSafety")


@bp.get("/payouts/<payout_id>")
def get_payout(payout_id):
    user_id, role = get_user_context()
    require_role(role, READ_ROLES)
    payout = lookup.get_payout(payout_id)
    if role == "Seller":
        require_ownership(role, user_id, payout["seller_id"])
    return response.object_response(serialize.public(payout), 200)


@bp.get("/payouts")
def list_payouts():
    user_id, role = get_user_context()
    require_role(role, READ_ROLES)
    order_id = request.args.get("order_id")
    seller_id = request.args.get("seller_id")
    records = list(db.payouts.values())
    if order_id is not None:
        records = [p for p in records if p["order_id"] == order_id]
    if seller_id is not None:
        records = [p for p in records if p["seller_id"] == seller_id]
    if role == "Seller":
        records = [p for p in records if p["seller_id"] == user_id]
    page, limit, offset, total = paginate.apply_pagination(records)
    return response.array_response(serialize.public_list(page), limit, offset, total)


@bp.post("/payouts/<payout_id>/pay")
def pay(payout_id):
    body = validate.get_json_body()
    expected_payout_version = validate.require_int(body, "expected_payout_version", minimum=0)
    _, role = get_user_context()
    require_role(role, ("PlatformAdmin",))
    payout = lookup.get_payout(payout_id)

    # state: must be RELEASABLE
    if payout["status"] != "RELEASABLE":
        raise err(errors.ERR_PAYOUT_NOT_RELEASABLE, "Payout is not releasable")

    # OCC (evaluated last)
    if expected_payout_version != payout["version"]:
        raise err(errors.ERR_STALE_PAYOUT_VERSION, "Payout version is stale")

    payout["status"] = "PAID"
    db.touch(payout)
    seller = db.sellers.get(payout["seller_id"])
    if seller is not None:
        recompute.recompute_seller(seller)
    return response.object_response(serialize.public(payout), 200)
