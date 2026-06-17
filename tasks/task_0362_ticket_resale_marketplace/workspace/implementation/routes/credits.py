from flask import Blueprint, request

import db
import response
import errors
from errors import err
from middleware import get_user_context, require_role, require_ownership
from services import lookup, serialize, paginate, recompute

bp = Blueprint("credits", __name__)

READ_ROLES = ("PlatformAdmin", "Buyer", "TrustSafety")


@bp.get("/event-credits/<credit_id>")
def get_credit(credit_id):
    user_id, role = get_user_context()
    require_role(role, READ_ROLES)
    credit = lookup.get_credit(credit_id)
    if role == "Buyer":
        require_ownership(role, user_id, credit["buyer_id"])
    return response.object_response(serialize.public(credit), 200)


@bp.get("/event-credits")
def list_credits():
    user_id, role = get_user_context()
    require_role(role, READ_ROLES)
    buyer_id = request.args.get("buyer_id")
    event_id = request.args.get("event_id")
    source_order_id = request.args.get("source_order_id")
    records = list(db.event_credits.values())
    if buyer_id is not None:
        records = [c for c in records if c["buyer_id"] == buyer_id]
    if event_id is not None:
        records = [c for c in records if c["event_id"] == event_id]
    if source_order_id is not None:
        records = [c for c in records if c["source_order_id"] == source_order_id]
    if role == "Buyer":
        records = [c for c in records if c["buyer_id"] == user_id]
    page, limit, offset, total = paginate.apply_pagination(records)
    return response.array_response(serialize.public_list(page), limit, offset, total)


@bp.post("/event-credits/<credit_id>/revoke")
def revoke(credit_id):
    _, role = get_user_context()
    require_role(role, ("TrustSafety",))
    credit = lookup.get_credit(credit_id)
    if credit["status"] != "ISSUED":
        raise err(errors.ERR_INVALID_STATE, "Credit is not ISSUED")
    credit["status"] = "REVOKED"
    db.touch(credit)
    buyer = db.buyers.get(credit["buyer_id"])
    if buyer is not None:
        recompute.recompute_buyer(buyer)
    return response.object_response(serialize.public(credit), 200)
