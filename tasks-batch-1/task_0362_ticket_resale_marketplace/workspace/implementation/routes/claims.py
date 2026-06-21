from flask import Blueprint, request

import db
import validate
import response
import errors
from errors import err
from middleware import get_user_context, require_role, require_ownership
from services import lookup, serialize, paginate, claim_ops

bp = Blueprint("claims", __name__)

READ_ROLES = ("PlatformAdmin", "Buyer", "Seller", "TrustSafety")
REASONS = {"NOT_DELIVERED", "INVALID_BARCODE", "DUPLICATE_SEAT", "EVENT_ISSUE"}


@bp.post("/guarantee-claims")
def create_claim():
    body = validate.get_json_body()
    order_id = validate.require_string(body, "order_id")
    reason = validate.require_enum(body, "reason", REASONS)
    user_id, role = get_user_context()
    require_role(role, ("Buyer",))

    order = lookup.get_order(order_id)
    require_ownership(role, user_id, order["buyer_id"])

    # one open claim per order
    if claim_ops.has_open_claim(order_id):
        raise err(errors.ERR_OPEN_CLAIM_EXISTS, "An open claim already exists for this order")

    claim = {
        "order_id": order_id,
        "reason": reason,
        "status": "FILED",
        "offered_listing_id": None,
        "replacement_order_id": None,
        "round_number": 0,
        "refund_amount_cents": None,
    }
    db.stamp_create(claim)
    db.guarantee_claims[claim["id"]] = claim
    return response.object_response(serialize.public(claim), 201)


@bp.get("/guarantee-claims/<claim_id>")
def get_claim(claim_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    claim = lookup.get_claim(claim_id)
    return response.object_response(serialize.public(claim), 200)


@bp.get("/guarantee-claims")
def list_claims():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    order_id = request.args.get("order_id")
    offered_listing_id = request.args.get("offered_listing_id")
    replacement_order_id = request.args.get("replacement_order_id")
    records = list(db.guarantee_claims.values())
    if order_id is not None:
        records = [c for c in records if c["order_id"] == order_id]
    if offered_listing_id is not None:
        records = [c for c in records if c.get("offered_listing_id") == offered_listing_id]
    if replacement_order_id is not None:
        records = [c for c in records if c.get("replacement_order_id") == replacement_order_id]
    page, limit, offset, total = paginate.apply_pagination(records)
    return response.array_response(serialize.public_list(page), limit, offset, total)


@bp.post("/guarantee-claims/<claim_id>/investigate")
def investigate(claim_id):
    _, role = get_user_context()
    require_role(role, ("TrustSafety",))
    claim = lookup.get_claim(claim_id)
    claim_ops.investigate(claim)
    return response.object_response(serialize.public(claim), 200)


@bp.post("/guarantee-claims/<claim_id>/offer-replacement")
def offer_replacement(claim_id):
    body = validate.get_json_body()
    offered_listing_id = validate.require_string(body, "offered_listing_id")
    _, role = get_user_context()
    require_role(role, ("TrustSafety",))
    claim = lookup.get_claim(claim_id)
    lookup.get_listing(offered_listing_id)
    claim_ops.offer_replacement(claim, offered_listing_id)
    return response.object_response(serialize.public(claim), 200)


@bp.post("/guarantee-claims/<claim_id>/reject-offer")
def reject_offer(claim_id):
    user_id, role = get_user_context()
    require_role(role, ("Buyer",))
    claim = lookup.get_claim(claim_id)
    order = db.orders.get(claim["order_id"])
    require_ownership(role, user_id, order["buyer_id"])
    claim_ops.reject_offer(claim)
    return response.object_response(serialize.public(claim), 200)


@bp.post("/guarantee-claims/<claim_id>/accept-offer")
def accept_offer(claim_id):
    body = validate.get_json_body()
    expected_listing_version = validate.require_int(body, "expected_listing_version", minimum=0)
    user_id, role = get_user_context()
    require_role(role, ("Buyer",))
    claim = lookup.get_claim(claim_id)
    order = db.orders.get(claim["order_id"])
    require_ownership(role, user_id, order["buyer_id"])
    claim_ops.accept_offer(claim, expected_listing_version)
    return response.object_response(serialize.public(claim), 200)


@bp.post("/guarantee-claims/<claim_id>/refund")
def refund(claim_id):
    _, role = get_user_context()
    require_role(role, ("TrustSafety",))
    claim = lookup.get_claim(claim_id)
    claim_ops.refund(claim)
    return response.object_response(serialize.public(claim), 200)


@bp.post("/guarantee-claims/<claim_id>/deny")
def deny(claim_id):
    _, role = get_user_context()
    require_role(role, ("TrustSafety",))
    claim = lookup.get_claim(claim_id)
    claim_ops.deny(claim)
    return response.object_response(serialize.public(claim), 200)
