"""Reseller listings and card validation (PRD 3.8)."""
from flask import Blueprint

import db as dbm
import response
import validate
from db import db
from errors import fail
from routes.common import (READ_ROLES, authenticate, filter_by, listing_response,
                           require_card, require_listing)
from services import listings as listing_svc
from services.listings import LISTING_STATES

bp = Blueprint("listings", __name__)


@bp.post("/reseller-listings")
def submit_listing():
    caller = authenticate(["ResellerPartner"])
    body = validate.body()
    card_id = validate.string(body, "card_id", min_len=1)
    marketplace_name = validate.string(body, "marketplace_name", min_len=1, max_len=80)
    asking_price = validate.integer(body, "asking_price_cents", minimum=1)
    listed_balance = validate.integer(body, "listed_balance_cents", minimum=0)
    card = require_card(card_id)

    for existing in db.listings.values():
        if (existing["card_id"] == card_id
                and existing["marketplace_name"] == marketplace_name
                and existing["state"] in ("SUBMITTED", "VALIDATED")):
            fail("ERR_DUPLICATE_LISTING")

    rec = dbm.record({
        "card_id": card_id,
        "reseller_partner_id": caller.user_id,
        "marketplace_name": marketplace_name,
        "asking_price_cents": asking_price,
        "listed_balance_cents": listed_balance,
        "state": "SUBMITTED",
        "block_reason": None,
        "validation_note": None,
        "validated_by_user_id": None,
    })
    db.listings[rec["id"]] = rec
    return response.created(rec)


@bp.get("/reseller-listings")
def list_listings():
    authenticate(READ_ROLES)
    card_id = validate.query_str("card_id")
    state = validate.query_enum("state", LISTING_STATES)
    marketplace_name = validate.query_str("marketplace_name")
    rows = list(db.listings.values())
    rows = filter_by(rows, "card_id", card_id)
    rows = filter_by(rows, "state", state)
    rows = filter_by(rows, "marketplace_name", marketplace_name)
    return listing_response(rows)


@bp.get("/reseller-listings/<listing_id>")
def get_listing(listing_id):
    authenticate(READ_ROLES)
    return response.ok(require_listing(listing_id))


@bp.post("/reseller-listings/<listing_id>/validate")
def validate_listing(listing_id):
    caller = authenticate(["FraudAnalyst"])
    body = validate.body()
    note = validate.string(body, "validation_note", required=False, min_len=None)
    listing = require_listing(listing_id)
    if listing["state"] != "SUBMITTED":
        fail("ERR_INVALID_LISTING_STATE")
    card = db.cards.get(listing["card_id"])
    policy = dbm.policy()
    state, block_reason = listing_svc.validation_decision(listing, card, policy)
    listing["state"] = state
    listing["block_reason"] = block_reason
    listing["validation_note"] = note
    listing["validated_by_user_id"] = caller.user_id
    dbm.touch(listing)
    return response.ok(listing)
