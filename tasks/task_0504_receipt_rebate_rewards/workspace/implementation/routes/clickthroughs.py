"""ClickThrough endpoints (PRD §3.3). Append-only event."""
from flask import Blueprint, request

from clock import format_iso
from db import base_common_fields
from errors import err
from middleware import get_identity, require_roles
from response import object_response
from routes.common import list_response, member_owns
from services.serialize import clickthrough_out
from state import store
from validation import get_json_body

bp = Blueprint("clickthroughs", __name__)


@bp.route("/clickthroughs", methods=["POST"])
def create_clickthrough():
    user_id, role = get_identity()
    require_roles(role, ["Member", "PlatformAdmin"])
    body = get_json_body()

    member_id = body.get("member_id")
    merchant_id = body.get("merchant_id")
    offer_id = body.get("offer_id")

    # Body-FK resolution (priority 4) before shape (priority 5) — but missing
    # required fields are a shape error. Required: member_id, merchant_id.
    if member_id is None:
        raise err("ERR_VALIDATION", "Missing required field: member_id")
    if merchant_id is None:
        raise err("ERR_VALIDATION", "Missing required field: merchant_id")

    if not isinstance(member_id, str) or member_id not in store.members:
        raise err("ERR_REFERENCE_NOT_FOUND", "member_id does not resolve.")
    if not isinstance(merchant_id, str) or merchant_id not in store.merchants:
        raise err("ERR_REFERENCE_NOT_FOUND", "merchant_id does not resolve.")
    if offer_id is not None:
        if not isinstance(offer_id, str) or offer_id not in store.offers:
            raise err("ERR_REFERENCE_NOT_FOUND", "offer_id does not resolve.")

    if role == "Member" and not member_owns(user_id, member_id):
        raise err("ERR_FORBIDDEN", "A member may only act on their own member_id.")

    merchant = store.merchants[merchant_id]
    if merchant["status"] == "DISABLED":
        raise err("ERR_MERCHANT_DISABLED", "Merchant is disabled.")

    c = base_common_fields(store, full=False)
    c.update({
        "member_id": member_id,
        "merchant_id": merchant_id,
        "offer_id": offer_id,
        "clicked_at": format_iso(store.clock.get()),
    })
    store.clickthroughs[c["id"]] = c
    return object_response(store.clock, clickthrough_out(store, c), status=201)


@bp.route("/clickthroughs/<cid>", methods=["GET"])
def get_clickthrough(cid):
    user_id, role = get_identity()
    require_roles(role, ["PlatformAdmin", "FinanceAdmin", "Member"])
    c = store.clickthroughs.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Click-through not found.")
    if role == "Member" and not member_owns(user_id, c["member_id"]):
        raise err("ERR_FORBIDDEN", "A member may only read their own click-throughs.")
    return object_response(store.clock, clickthrough_out(store, c))


@bp.route("/clickthroughs", methods=["GET"])
def list_clickthroughs():
    user_id, role = get_identity()
    require_roles(role, ["PlatformAdmin", "FinanceAdmin", "Member"])
    items = list(store.clickthroughs.values())
    if role == "Member":
        items = [c for c in items if c["member_id"] == user_id]
    member_id = request.args.get("member_id")
    merchant_id = request.args.get("merchant_id")
    offer_id = request.args.get("offer_id")
    if member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    if merchant_id is not None:
        items = [c for c in items if c["merchant_id"] == merchant_id]
    if offer_id is not None:
        items = [c for c in items if c.get("offer_id") == offer_id]
    return list_response(items, clickthrough_out)
