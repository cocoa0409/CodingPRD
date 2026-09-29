"""Live bids, proxy bids and auction closure (PRD 3.4, 3.5)."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.helpers import list_rows
from services import aggregates, bidding, guards, lookups, orders
from util import clock

bp = Blueprint("bids", __name__)

READ_ALL = (
    mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.SELLER_OPS, mw.TRUST_SAFETY, mw.BUYER,
)


def _resolve_buyer_from_body(payload, user_id):
    """Band 4 then band 6 for the body's buyer_id."""
    if mw.present(payload, "buyer_id"):
        guards.own_or_403(payload.get("buyer_id"), user_id)
        return lookups.buyer(payload.get("buyer_id"))
    return None


def _minimum_next(listing):
    if listing.get("min_next_bid_cents") is not None:
        return int(listing["min_next_bid_cents"])
    return int(listing.get("opening_bid_cents") or 0)


@bp.post("/liquidation/listings/<listing_id>/bids")
def place_live_bid(listing_id):
    user_id, _role = mw.authenticate((mw.BUYER,))
    listing = lookups.listing(listing_id)
    payload = mw.body()
    buyer = _resolve_buyer_from_body(payload, user_id)
    if buyer is None:
        raise ApiError("ERR_INVALID_REQUEST", "buyer_id is required.")
    amount_cents = mw.req_int(payload, "amount_cents", minimum=1)

    # band 9
    if listing["listing_status"] != "OPEN":
        raise ApiError("ERR_LISTING_STATE_INVALID")
    if listing["listing_format"] not in ("AUCTION", "FIXED_PRICE"):
        raise ApiError("ERR_LISTING_STATE_INVALID")
    # band 10
    guards.require_qualified(buyer)
    # band 11
    lot = lookups.lot_of_listing(listing)
    guards.check_buyer_geography(lot, buyer)
    guards.check_anti_shill(lot, buyer)
    # band 12
    guards.require_window_open(listing)
    # band 16
    if listing["listing_format"] == "AUCTION":
        if amount_cents < _minimum_next(listing):
            raise ApiError("ERR_BID_BELOW_MINIMUM")
    else:
        if amount_cents != int(listing["ask_price_cents"]):
            raise ApiError("ERR_FIXED_PRICE_MISMATCH")
    guards.admit_exposure(
        buyer,
        aggregates.prospective_exposure_with_bid(buyer, listing["id"], amount_cents),
    )

    if listing["listing_format"] == "AUCTION":
        bidding.supersede_previous(listing["id"], buyer["id"])
        bid = db.new_row(
            listing_id=listing["id"],
            buyer_id=buyer["id"],
            bid_type="LIVE",
            amount_cents=amount_cents,
            max_amount_cents=None,
            ceiling_cents=amount_cents,
            bid_status="STANDING",
            placed_at=clock.now(),
            meets_reserve=False,
        )
        db.bids[bid["id"]] = bid
        bidding.resolve(listing, fresh_bid_id=bid["id"])
        bidding.apply_anti_sniping(listing)
        db.touch(listing)
        aggregates.recompute_buyer_exposure(buyer)
        return response.created(db.view("bid", bid))

    # FIXED_PRICE: the purchase closes the listing immediately
    bid = db.new_row(
        listing_id=listing["id"],
        buyer_id=buyer["id"],
        bid_type="LIVE",
        amount_cents=amount_cents,
        max_amount_cents=None,
        ceiling_cents=amount_cents,
        bid_status="WON",
        placed_at=clock.now(),
        meets_reserve=False,
    )
    db.bids[bid["id"]] = bid
    listing["listing_status"] = "CLOSED_SOLD"
    bidding.recount(listing)
    db.touch(listing)
    lot["lot_status"] = "SOLD"
    db.touch(lot)
    orders.create_sale_order(
        listing, buyer["id"], "FIXED_PRICE_PURCHASE", int(listing["ask_price_cents"])
    )
    aggregates.recompute_seller_recovery(lookups.seller_of_lot(lot))
    aggregates.recompute_buyer_exposure(buyer)
    return response.created(db.view("bid", bid))


@bp.post("/liquidation/listings/<listing_id>/proxy-bids")
def place_proxy_bid(listing_id):
    user_id, _role = mw.authenticate((mw.BUYER,))
    listing = lookups.listing(listing_id)
    payload = mw.body()
    buyer = _resolve_buyer_from_body(payload, user_id)
    if buyer is None:
        raise ApiError("ERR_INVALID_REQUEST", "buyer_id is required.")
    max_amount_cents = mw.req_int(payload, "max_amount_cents", minimum=1)
    expected_version = mw.req_int(payload, "expected_listing_version")

    # band 8
    if expected_version != int(listing["version"]):
        raise ApiError("ERR_STALE_LISTING_VERSION")
    # band 9
    if listing["listing_status"] != "OPEN" or listing["listing_format"] != "AUCTION":
        raise ApiError("ERR_LISTING_STATE_INVALID")
    # band 10
    guards.require_qualified(buyer)
    # band 11
    lot = lookups.lot_of_listing(listing)
    guards.check_buyer_geography(lot, buyer)
    guards.check_anti_shill(lot, buyer)
    # band 12
    guards.require_window_open(listing)
    # band 16
    if max_amount_cents < _minimum_next(listing):
        raise ApiError("ERR_PROXY_MAX_BELOW_MINIMUM")
    guards.admit_exposure(
        buyer,
        aggregates.prospective_exposure_with_bid(buyer, listing["id"], max_amount_cents),
    )

    bidding.supersede_previous(listing["id"], buyer["id"])
    bid = db.new_row(
        listing_id=listing["id"],
        buyer_id=buyer["id"],
        bid_type="PROXY",
        amount_cents=None,
        max_amount_cents=max_amount_cents,
        ceiling_cents=max_amount_cents,
        bid_status="STANDING",
        placed_at=clock.now(),
        meets_reserve=False,
    )
    db.bids[bid["id"]] = bid
    bidding.resolve(listing, fresh_bid_id=bid["id"])
    bid["amount_cents"] = listing["current_high_bid_cents"]
    bidding.apply_anti_sniping(listing)
    db.touch(listing)
    aggregates.recompute_buyer_exposure(buyer)
    return response.created(db.view("bid", bid))


@bp.get("/liquidation/bids/<bid_id>")
def read_bid(bid_id):
    mw.authenticate(READ_ALL)
    return response.success(db.view("bid", lookups.bid(bid_id)))


@bp.get("/liquidation/bids")
def list_bids():
    mw.authenticate(READ_ALL)
    return list_rows(
        "bid",
        list(db.bids.values()),
        (
            ("listing_id", "listing_id"),
            ("buyer_id", "buyer_id"),
            ("bid_status", "bid_status"),
            ("bid_type", "bid_type"),
        ),
    )


@bp.post("/liquidation/listings/<listing_id>/closures")
def close_auction(listing_id):
    mw.authenticate((mw.MARKETPLACE_OPS,))
    listing = lookups.listing(listing_id)
    lot = lookups.lot_of_listing(listing)

    # band 9
    if listing["listing_status"] != "OPEN" or listing["listing_format"] != "AUCTION":
        raise ApiError("ERR_LISTING_STATE_INVALID")
    # band 11: the geographic rule runs once more against the prospective winner
    if listing.get("current_high_bidder_id"):
        prospective = db.buyers.get(listing["current_high_bidder_id"])
        if prospective is not None:
            guards.check_buyer_geography(lot, prospective)
    # band 12
    if clock.now() < listing["effective_close_at"]:
        raise ApiError("ERR_AUCTION_NOT_CLOSABLE")

    pool = bidding.qualifying_bids(listing["id"])
    seller = lookups.seller_of_lot(lot)

    if not pool or not listing["reserve_met"]:
        for bid in pool:
            bid["bid_status"] = "LOST"
            db.touch(bid)
        listing["listing_status"] = "CLOSED_NO_SALE"
        bidding.recount(listing)
        db.touch(listing)
        if lot["lot_status"] == "LISTED":
            lot["lot_status"] = "RELIST_PENDING"
            db.touch(lot)
        for buyer_id in bidding.bidders_of(listing["id"]):
            buyer = db.buyers.get(buyer_id)
            if buyer is not None:
                aggregates.recompute_buyer_exposure(buyer)
        aggregates.recompute_seller_recovery(seller)
        return response.success(db.view("listing", listing))

    winner = None
    for bid in pool:
        if bid["bid_status"] == "WINNING":
            winner = bid
    hammer = int(listing["current_high_bid_cents"])
    for bid in pool:
        bid["bid_status"] = "WON" if winner is not None and bid["id"] == winner["id"] else "LOST"
        db.touch(bid)
    listing["listing_status"] = "CLOSED_SOLD"
    bidding.recount(listing)
    db.touch(listing)
    lot["lot_status"] = "SOLD"
    db.touch(lot)
    orders.create_sale_order(listing, winner["buyer_id"], "AUCTION_CLOSE", hammer)
    winning_buyer = db.buyers.get(winner["buyer_id"])
    if winning_buyer is not None:
        aggregates.recompute_buyer_exposure(winning_buyer)
    aggregates.recompute_seller_recovery(seller)
    return response.success(db.view("listing", listing))
