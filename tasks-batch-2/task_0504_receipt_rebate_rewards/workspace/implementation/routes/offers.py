"""Offer endpoints (PRD §3.1)."""
from flask import Blueprint, request

from clock import parse_iso
from db import base_common_fields
from errors import err
from middleware import get_identity, require_roles
from response import object_response
from routes.common import list_response
from services.serialize import offer_out
from state import store
from validation import (
    get_json_body,
    require_string,
    require_enum,
    optional_int,
)

bp = Blueprint("offers", __name__)

ALL_ROLES = ["PlatformAdmin", "ReviewAgent", "FinanceAdmin", "Member"]


@bp.route("/offers", methods=["POST"])
def create_offer():
    _, role = get_identity()
    require_roles(role, ["PlatformAdmin"])
    body = get_json_body()

    # Body-FK resolution (ERR_REFERENCE_NOT_FOUND) precedes shape (ERR_VALIDATION)
    # only for the FK itself; merchant_id must be present and resolve.
    merchant_id = body.get("merchant_id")
    if merchant_id is None:
        raise err("ERR_VALIDATION", "Missing required field: merchant_id")
    if not isinstance(merchant_id, str) or merchant_id not in store.merchants:
        raise err("ERR_REFERENCE_NOT_FOUND", "merchant_id does not resolve.")

    offer_type = require_enum(body, "offer_type", {"LINKED", "RECEIPT_REBATE"})
    starts_at_raw = require_string(body, "starts_at")
    expires_at_raw = require_string(body, "expires_at")
    if parse_iso(starts_at_raw) is None:
        raise err("ERR_VALIDATION", "starts_at must be an ISO 8601 instant.")
    if parse_iso(expires_at_raw) is None:
        raise err("ERR_VALIDATION", "expires_at must be an ISO 8601 instant.")

    bonus_rate_bps = optional_int(body, "bonus_rate_bps", 0, minimum=0)
    rebate_cents = optional_int(body, "rebate_cents", 0, minimum=0)
    min_spend_cents = optional_int(body, "min_spend_cents", 0, minimum=0)
    if bonus_rate_bps > 10000:
        raise err("ERR_VALIDATION", "bonus_rate_bps must be 0..10000.")

    o = base_common_fields(store, full=True)
    o.update({
        "merchant_id": merchant_id,
        "offer_type": offer_type,
        "bonus_rate_bps": bonus_rate_bps,
        "rebate_cents": rebate_cents,
        "min_spend_cents": min_spend_cents,
        "starts_at": starts_at_raw,
        "expires_at": expires_at_raw,
        "status": "ACTIVE",
    })
    store.offers[o["id"]] = o
    return object_response(store.clock, offer_out(store, o), status=201)


@bp.route("/offers/<oid>", methods=["GET"])
def get_offer(oid):
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    o = store.offers.get(oid)
    if o is None:
        raise err("ERR_NOT_FOUND", "Offer not found.")
    return object_response(store.clock, offer_out(store, o))


@bp.route("/offers", methods=["GET"])
def list_offers():
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    items = list(store.offers.values())
    merchant_id = request.args.get("merchant_id")
    offer_type = request.args.get("offer_type")
    status = request.args.get("status")
    if merchant_id is not None:
        items = [o for o in items if o["merchant_id"] == merchant_id]
    if offer_type is not None:
        items = [o for o in items if o["offer_type"] == offer_type]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response(items, offer_out)
