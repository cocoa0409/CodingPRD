"""Negotiated terms: openings, counter-offers, acceptances and offers (PRD 3.5)."""

from flask import Blueprint, request

import db
import middleware as mw
import response
from errors import ApiError
from routes.helpers import list_rows
from services import aggregates, calc, guards, lookups, orders
from util import clock, plus_hours

bp = Blueprint("negotiations", __name__)

READ_ALL = (
    mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.SELLER_OPS, mw.TRUST_SAFETY, mw.BUYER,
)
LIVE_NEGOTIATION_STATES = ("AWAITING_SELLER", "AWAITING_BUYER")
AWAITED_SIDE = {"AWAITING_SELLER": "SELLER", "AWAITING_BUYER": "BUYER"}
ROLE_SIDE = {mw.SELLER_OPS: "SELLER", mw.BUYER: "BUYER"}


@bp.post("/liquidation/listings/<listing_id>/negotiations")
def open_negotiation(listing_id):
    user_id, _role = mw.authenticate((mw.BUYER,))
    listing = lookups.listing(listing_id)
    payload = mw.body()
    if mw.present(payload, "buyer_id"):
        guards.own_or_403(payload.get("buyer_id"), user_id)
        buyer = lookups.buyer(payload.get("buyer_id"))
    else:
        raise ApiError("ERR_INVALID_REQUEST", "buyer_id is required.")
    opening_offer_cents = mw.req_int(payload, "opening_offer_cents", minimum=1)

    # band 9
    if listing["listing_status"] != "OPEN" or listing["listing_format"] != "NEGOTIATED":
        raise ApiError("ERR_LISTING_STATE_INVALID")
    # band 10
    guards.require_qualified(buyer)
    # band 11
    lot = lookups.lot_of_listing(listing)
    guards.check_buyer_geography(lot, buyer)
    guards.check_anti_shill(lot, buyer)
    # band 12
    guards.require_window_open(listing)
    # band 15: one live negotiation per buyer per listing
    for sibling in lookups.negotiations_of_listing(listing["id"]):
        if (
            sibling["buyer_id"] == buyer["id"]
            and sibling["negotiation_status"] in LIVE_NEGOTIATION_STATES
        ):
            raise ApiError("ERR_DUPLICATE_NEGOTIATION")
    # band 16
    if opening_offer_cents < int(listing["min_offer_cents"]):
        raise ApiError("ERR_OFFER_BELOW_MINIMUM")
    guards.admit_exposure(buyer, aggregates.exposure_of(buyer["id"]))

    expires_at = plus_hours(clock.now(), calc.OFFER_TTL_HOURS)
    negotiation = db.new_row(
        listing_id=listing["id"],
        buyer_id=buyer["id"],
        negotiation_status="AWAITING_SELLER",
        round_number=1,
        current_offer_cents=opening_offer_cents,
        current_offer_side="BUYER",
        current_offer_expires_at=expires_at,
        accepted_price_cents=None,
    )
    db.negotiations[negotiation["id"]] = negotiation
    offer = db.new_offer_row(
        negotiation_id=negotiation["id"],
        offer_side="BUYER",
        amount_cents=opening_offer_cents,
        round_number=1,
        expires_at=expires_at,
    )
    db.offers[offer["id"]] = offer
    aggregates.recompute_buyer_exposure(buyer)
    return response.created(db.view("negotiation", negotiation))


@bp.get("/liquidation/negotiations/<negotiation_id>")
def read_negotiation(negotiation_id):
    mw.authenticate(READ_ALL)
    return response.success(db.view("negotiation", lookups.negotiation(negotiation_id)))


@bp.get("/liquidation/negotiations")
def list_negotiations():
    mw.authenticate(READ_ALL)
    return list_rows(
        "negotiation",
        list(db.negotiations.values()),
        (
            ("listing_id", "listing_id"),
            ("buyer_id", "buyer_id"),
            ("negotiation_status", "negotiation_status"),
        ),
    )


def _check_negotiation_ownership(negotiation, user_id, role):
    if role == mw.BUYER:
        guards.own_or_403(negotiation["buyer_id"], user_id)
    else:
        listing = lookups.listing(negotiation["listing_id"])
        guards.owns_listing(listing, user_id)


@bp.post("/liquidation/negotiations/<negotiation_id>/counter-offers")
def counter_offer(negotiation_id):
    user_id, role = mw.authenticate((mw.BUYER, mw.SELLER_OPS))
    negotiation = lookups.negotiation(negotiation_id)
    _check_negotiation_ownership(negotiation, user_id, role)
    payload = mw.body()
    amount_cents = mw.req_int(payload, "amount_cents", minimum=1)
    expected_version = mw.req_int(payload, "expected_negotiation_version")

    # band 8
    if expected_version != int(negotiation["version"]):
        raise ApiError("ERR_STALE_NEGOTIATION_VERSION")
    # band 9
    if negotiation["negotiation_status"] not in LIVE_NEGOTIATION_STATES:
        raise ApiError("ERR_NEGOTIATION_STATE_INVALID")
    acting_side = ROLE_SIDE[role]
    if AWAITED_SIDE[negotiation["negotiation_status"]] != acting_side:
        raise ApiError("ERR_NOT_YOUR_TURN")
    # band 10
    buyer = lookups.buyer(negotiation["buyer_id"])
    guards.require_qualified(buyer)
    # band 11
    listing = lookups.listing(negotiation["listing_id"])
    lot = lookups.lot_of_listing(listing)
    guards.check_buyer_geography(lot, buyer)
    # band 12
    if clock.now() >= negotiation["current_offer_expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED")
    # band 15
    next_round = int(negotiation["round_number"]) + 1
    if next_round > calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT")
    # band 16
    if amount_cents < int(listing["min_offer_cents"]):
        raise ApiError("ERR_OFFER_BELOW_MINIMUM")

    expires_at = plus_hours(clock.now(), calc.OFFER_TTL_HOURS)
    offer = db.new_offer_row(
        negotiation_id=negotiation["id"],
        offer_side=acting_side,
        amount_cents=amount_cents,
        round_number=next_round,
        expires_at=expires_at,
    )
    db.offers[offer["id"]] = offer
    negotiation["round_number"] = next_round
    negotiation["current_offer_cents"] = amount_cents
    negotiation["current_offer_side"] = acting_side
    negotiation["current_offer_expires_at"] = expires_at
    negotiation["negotiation_status"] = (
        "AWAITING_BUYER" if acting_side == "SELLER" else "AWAITING_SELLER"
    )
    db.touch(negotiation)
    if acting_side == "BUYER":
        aggregates.recompute_buyer_exposure(buyer)
    return response.success(db.view("negotiation", negotiation))


@bp.post("/liquidation/negotiations/<negotiation_id>/acceptances")
def accept_negotiation(negotiation_id):
    user_id, role = mw.authenticate((mw.BUYER, mw.SELLER_OPS))
    negotiation = lookups.negotiation(negotiation_id)
    _check_negotiation_ownership(negotiation, user_id, role)

    # band 9
    if negotiation["negotiation_status"] not in LIVE_NEGOTIATION_STATES:
        raise ApiError("ERR_NEGOTIATION_STATE_INVALID")
    if AWAITED_SIDE[negotiation["negotiation_status"]] != ROLE_SIDE[role]:
        raise ApiError("ERR_NOT_YOUR_TURN")
    # band 12
    if clock.now() >= negotiation["current_offer_expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED")

    listing = lookups.listing(negotiation["listing_id"])
    lot = lookups.lot_of_listing(listing)
    accepted_price = int(negotiation["current_offer_cents"])
    negotiation["negotiation_status"] = "ACCEPTED"
    negotiation["accepted_price_cents"] = accepted_price
    db.touch(negotiation)

    for sibling in lookups.negotiations_of_listing(listing["id"]):
        if sibling["id"] == negotiation["id"]:
            continue
        if sibling["negotiation_status"] in LIVE_NEGOTIATION_STATES:
            sibling["negotiation_status"] = "DECLINED"
            db.touch(sibling)

    listing["listing_status"] = "CLOSED_SOLD"
    db.touch(listing)
    lot["lot_status"] = "SOLD"
    db.touch(lot)
    orders.create_sale_order(
        listing, negotiation["buyer_id"], "NEGOTIATED_ACCEPTANCE", accepted_price
    )
    aggregates.recompute_seller_recovery(lookups.seller_of_lot(lot))
    buyer = db.buyers.get(negotiation["buyer_id"])
    if buyer is not None:
        aggregates.recompute_buyer_exposure(buyer)
    return response.success(db.view("negotiation", negotiation))


@bp.get("/liquidation/negotiations/<negotiation_id>/offers")
def list_negotiation_offers(negotiation_id):
    mw.authenticate(READ_ALL)
    negotiation = lookups.negotiation(negotiation_id)
    limit, offset = response.pagination_params()
    rows = lookups.offers_of_negotiation(negotiation["id"])
    total = len(rows)
    page = response.window(rows, limit, offset)
    return response.collection(db.views("offer", page), limit, offset, total)


@bp.get("/liquidation/offers/<offer_id>")
def read_offer(offer_id):
    mw.authenticate(READ_ALL)
    return response.success(db.view("offer", lookups.offer(offer_id)))


@bp.get("/liquidation/offers")
def list_offers():
    mw.authenticate(READ_ALL)
    limit, offset = response.pagination_params()
    rows = list(db.offers.values())
    negotiation_id = request.args.get("negotiation_id")
    if negotiation_id is not None:
        rows = [row for row in rows if row["negotiation_id"] == negotiation_id]
    offer_side = request.args.get("offer_side")
    if offer_side is not None:
        rows = [row for row in rows if row["offer_side"] == offer_side]
    rows = db.ordered(rows)
    total = len(rows)
    page = response.window(rows, limit, offset)
    return response.collection(db.views("offer", page), limit, offset, total)
