"""Listing creation and publication (PRD 3.3)."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.helpers import list_rows
from services import aggregates, calc, guards, lookups

bp = Blueprint("listings", __name__)

READ_ALL = (
    mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.SELLER_OPS, mw.TRUST_SAFETY, mw.BUYER,
)

FORMAT_PRICE_FIELD = {
    "AUCTION": "opening_bid_cents",
    "FIXED_PRICE": "ask_price_cents",
    "NEGOTIATED": "min_offer_cents",
}


@bp.post("/liquidation/lots/<lot_id>/listings")
def create_listing(lot_id):
    user_id, _role = mw.authenticate((mw.SELLER_OPS,))
    lot = lookups.lot(lot_id)
    guards.owns_lot(lot, user_id)
    payload = mw.body()
    if mw.present(payload, "lot_id"):
        lookups.lot(payload.get("lot_id"))

    listing_format = mw.req_enum(payload, "listing_format", mw.LISTING_FORMATS)
    resale_channel = mw.req_enum(payload, "resale_channel", mw.RESALE_CHANNELS)
    window_start_at = mw.req_datetime(payload, "window_start_at")
    window_end_at = mw.req_datetime(payload, "window_end_at")
    if window_end_at <= window_start_at:
        raise ApiError(
            "ERR_INVALID_REQUEST", "window_end_at must be strictly later than window_start_at."
        )
    required_price_field = FORMAT_PRICE_FIELD[listing_format]
    if not mw.present(payload, required_price_field):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "%s is required for a %s listing." % (required_price_field, listing_format),
        )
    opening_bid_cents = mw.opt_int(payload, "opening_bid_cents", None, minimum=0)
    ask_price_cents = mw.opt_int(payload, "ask_price_cents", None, minimum=0)
    min_offer_cents = mw.opt_int(payload, "min_offer_cents", None, minimum=0)
    reserve_price_cents = mw.opt_int(payload, "reserve_price_cents", None, minimum=0)
    bid_increment_cents = mw.opt_int(
        payload, "bid_increment_cents", calc.DEFAULT_BID_INCREMENT_CENTS, minimum=1
    )
    de_branding_attested = mw.opt_bool(payload, "de_branding_attested", False)

    # band 16: a reserve below the opening bid could never bind
    if (
        listing_format == "AUCTION"
        and reserve_price_cents is not None
        and opening_bid_cents is not None
        and reserve_price_cents < opening_bid_cents
    ):
        raise ApiError("ERR_RESERVE_BELOW_OPENING")

    row = db.new_row(
        lot_id=lot["id"],
        listing_format=listing_format,
        resale_channel=resale_channel,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        effective_close_at=window_end_at,
        extension_count=0,
        opening_bid_cents=opening_bid_cents,
        reserve_price_cents=reserve_price_cents,
        ask_price_cents=ask_price_cents,
        min_offer_cents=min_offer_cents,
        bid_increment_cents=bid_increment_cents,
        de_branding_attested=de_branding_attested,
        listing_status="DRAFT",
        bid_count=0,
        current_high_bid_cents=None,
        current_high_bidder_id=None,
        reserve_met=reserve_price_cents is None,
        min_next_bid_cents=opening_bid_cents if listing_format == "AUCTION" else None,
    )
    db.listings[row["id"]] = row
    return response.created(db.view("listing", row))


@bp.get("/liquidation/listings/<listing_id>")
def read_listing(listing_id):
    mw.authenticate(READ_ALL)
    return response.success(db.view("listing", lookups.listing(listing_id)))


@bp.get("/liquidation/listings")
def list_listings():
    mw.authenticate(READ_ALL)
    return list_rows(
        "listing",
        list(db.listings.values()),
        (
            ("lot_id", "lot_id"),
            ("listing_status", "listing_status"),
            ("listing_format", "listing_format"),
            ("resale_channel", "resale_channel"),
        ),
    )


@bp.get("/liquidation/lots/<lot_id>/listings")
def list_lot_listings(lot_id):
    mw.authenticate(READ_ALL)
    lot = lookups.lot(lot_id)
    rows = [r for r in db.listings.values() if r["lot_id"] == lot["id"]]
    return list_rows(
        "listing",
        rows,
        (("listing_status", "listing_status"), ("listing_format", "listing_format")),
    )


def _embargo_intersects(listing, policy):
    start = policy.get("embargo_start_at")
    end = policy.get("embargo_end_at")
    if start is None and end is None:
        return False
    if start is None:
        start = listing["window_start_at"]
    if end is None:
        end = listing["window_end_at"]
    # both intervals inclusive at both ends
    return listing["window_start_at"] <= end and start <= listing["window_end_at"]


@bp.post("/liquidation/listings/<listing_id>/publications")
def publish_listing(listing_id):
    user_id, _role = mw.authenticate((mw.SELLER_OPS,))
    listing = lookups.listing(listing_id)
    lot = lookups.lot_of_listing(listing)
    guards.owns_lot(lot, user_id)

    # band 9
    if listing["listing_status"] != "DRAFT":
        raise ApiError("ERR_LISTING_STATE_INVALID")
    # band 10
    if lot["lot_status"] not in ("MANIFEST_APPROVED", "RELIST_PENDING"):
        raise ApiError("ERR_LOT_MANIFEST_NOT_APPROVED")
    seller = lookups.seller_of_lot(lot)
    if seller["account_status"] != "ACTIVE":
        raise ApiError("ERR_SELLER_NOT_ACTIVE")
    # band 11
    policy = lookups.policy_of_lot(lot)
    if policy is not None:
        if listing["resale_channel"] not in (policy.get("permitted_channels") or []):
            raise ApiError("ERR_CHANNEL_NOT_PERMITTED")
    if lot.get("de_branding_required") and not listing.get("de_branding_attested"):
        raise ApiError("ERR_DEBRANDING_ATTESTATION_REQUIRED")
    # band 12
    if policy is not None and _embargo_intersects(listing, policy):
        raise ApiError("ERR_BRAND_EMBARGO_ACTIVE")
    # band 15
    for sibling in lookups.listings_of_lot(lot["id"]):
        if sibling["id"] != listing["id"] and sibling["listing_status"] == "OPEN":
            raise ApiError("ERR_LISTING_ALREADY_OPEN")

    listing["listing_status"] = "OPEN"
    listing["effective_close_at"] = listing["window_end_at"]
    listing["extension_count"] = 0
    db.touch(listing)

    lot["lot_status"] = "LISTED"
    db.touch(lot)

    aggregates.recompute_seller_recovery(seller)
    return response.success(db.view("listing", listing))
