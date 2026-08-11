"""ResaleListing endpoints and the sales cycle (PRD §3.6)."""

from flask import Blueprint

import db
import serialize
import utils
from errors import (ApiError, ERR_DATA_SANITIZATION_UNVERIFIED,
                    ERR_FLOOR_PRICE_VIOLATION, ERR_INVALID_STATE,
                    ERR_ITEM_NOT_FOUND, ERR_LISTING_NOT_ACTIVE,
                    ERR_LISTING_NOT_FOUND, ERR_SETTLEMENT_ALREADY_FINALIZED,
                    ERR_VALIDATION)
from middleware import require_roles
from response import ok_object
from services import calculations as calc
from services import workflow

bp = Blueprint("listings", __name__)

CHANNELS = {"B2B_AUCTION", "RETAIL"}


def get_listing_or_404(listing_id):
    listing = db.listings.get(listing_id)
    if listing is None:
        raise ApiError(ERR_LISTING_NOT_FOUND, 404, "no ResaleListing with the given id")
    return listing


def _resale_data_gate(item):
    """Listing gate (priority 13): data-bearing items need VERIFIED under a
    strict policy flag (also the default when no policy is active), else
    SANITIZED or VERIFIED."""
    if not item["data_bearing"]:
        return
    policy = calc.active_policy()
    strict = True if policy is None else bool(policy["resale_requires_verified_sanitization"])
    if strict:
        ok = item["data_status"] == "VERIFIED"
    else:
        ok = item["data_status"] in ("SANITIZED", "VERIFIED")
    if not ok:
        raise ApiError(ERR_DATA_SANITIZATION_UNVERIFIED, 422,
                       "listing a data-bearing item requires verified sanitization")


@bp.post("/itad/listings")
def create_listing():
    uid, role = require_roles("IntakeOperator")
    data = utils.body_json()
    item_id = utils.req_str(data, "item_id")
    asking = utils.req_int(data, "asking_price_cents")
    floor = utils.req_int(data, "floor_price_cents")
    channel = utils.req_enum(data, "channel", CHANNELS)
    if floor < 0:
        raise ApiError(ERR_VALIDATION, 400, "floor_price_cents must be >= 0")
    if asking < floor:
        raise ApiError(ERR_VALIDATION, 400,
                       "asking_price_cents must be >= floor_price_cents")
    item = db.items.get(item_id)
    if item is None:
        raise ApiError(ERR_ITEM_NOT_FOUND, 404, "no Item with the given id")
    if item["processing_status"] != "FOR_RESALE":
        raise ApiError(ERR_INVALID_STATE, 409, "only FOR_RESALE items can be listed")
    _resale_data_gate(item)
    listing = {
        "id": utils.new_id(),
        "item_id": item["id"],
        "asking_price_cents": asking,
        "floor_price_cents": floor,
        "channel": channel,
        "sale_price_cents": None,
        "status": "ACTIVE",
    }
    utils.stamp_new(listing)
    db.listings[listing["id"]] = listing
    item["processing_status"] = "LISTED"
    utils.touch(item)
    return ok_object(serialize.listing(listing), code=201)


@bp.post("/itad/listings/<listing_id>/sell")
def sell_listing(listing_id):
    uid, role = require_roles("IntakeOperator")
    listing = get_listing_or_404(listing_id)
    data = utils.body_json()
    sale_price = utils.req_int(data, "sale_price_cents")
    if sale_price < 0:
        raise ApiError(ERR_VALIDATION, 400, "sale_price_cents must be >= 0")
    if listing["status"] != "ACTIVE":
        raise ApiError(ERR_LISTING_NOT_ACTIVE, 409, "listing is not ACTIVE")
    if sale_price < listing["floor_price_cents"]:
        raise ApiError(ERR_FLOOR_PRICE_VIOLATION, 422,
                       "sale_price_cents is below floor_price_cents")
    item = db.items[listing["item_id"]]
    manifest = db.manifests[item["manifest_id"]]
    account = db.accounts[manifest["account_id"]]
    listing["status"] = "SOLD"
    listing["sale_price_cents"] = sale_price
    utils.touch(listing)
    item["processing_status"] = "SOLD"
    item["final_value_cents"] = calc.final_net_proceeds(sale_price, account["tier"])
    utils.touch(item)
    return ok_object(serialize.listing(listing))


@bp.post("/itad/listings/<listing_id>/return")
def return_listing(listing_id):
    uid, role = require_roles("IntakeOperator")
    listing = get_listing_or_404(listing_id)
    if listing["status"] != "SOLD":
        raise ApiError(ERR_INVALID_STATE, 409, "only SOLD listings can be returned")
    item = db.items[listing["item_id"]]
    manifest = db.manifests[item["manifest_id"]]
    if any(s["status"] in ("FINALIZED", "PAID")
           for s in workflow.manifest_settlements(manifest["id"])):
        raise ApiError(ERR_SETTLEMENT_ALREADY_FINALIZED, 422,
                       "a settlement of this manifest is already FINALIZED or PAID")
    # Return cascade: listing RETURNED; item back to FOR_RESALE with zeroed
    # final value; any QUOTE_OPEN settlement recomputed.
    listing["status"] = "RETURNED"
    utils.touch(listing)
    item["processing_status"] = "FOR_RESALE"
    item["final_value_cents"] = 0
    utils.touch(item)
    workflow.recompute_quote_open(manifest)
    return ok_object(serialize.listing(listing))


@bp.post("/itad/listings/<listing_id>/relist")
def relist_listing(listing_id):
    uid, role = require_roles("IntakeOperator")
    listing = get_listing_or_404(listing_id)
    if listing["status"] != "RETURNED":
        raise ApiError(ERR_INVALID_STATE, 409, "only RETURNED listings can be relisted")
    item = db.items[listing["item_id"]]
    if item["processing_status"] != "FOR_RESALE":
        raise ApiError(ERR_INVALID_STATE, 409, "item must be FOR_RESALE to relist")
    listing["status"] = "ACTIVE"
    utils.touch(listing)
    item["processing_status"] = "LISTED"
    utils.touch(item)
    return ok_object(serialize.listing(listing))


@bp.post("/itad/listings/<listing_id>/withdraw")
def withdraw_listing(listing_id):
    uid, role = require_roles("IntakeOperator")
    listing = get_listing_or_404(listing_id)
    if listing["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "only ACTIVE listings can be withdrawn")
    item = db.items[listing["item_id"]]
    listing["status"] = "WITHDRAWN"
    utils.touch(listing)
    item["processing_status"] = "FOR_RESALE"
    utils.touch(item)
    return ok_object(serialize.listing(listing))
