"""Bid endpoints. PRD §3.3 (place/retract proxy bids), §3.4 (anti-sniping)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import response
import constants as C
import middleware as mw
from services import core, calc, auction
from services.auction import TERMINAL_LISTING_STATES
from routes.helpers import get_json_body, paginate_list, require_int

bp = Blueprint("bids", __name__)


@bp.route("/listings/<listing_id>/bids", methods=["POST"])
def place_bid(listing_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Buyer"})          # priority 2
    body = get_json_body()
    listing = db.listings.get(listing_id)       # existence (priority 4)
    if listing is None:
        raise errors.not_found("Listing not found.")

    bidder_account_id = body.get("bidder_account_id")
    if not isinstance(bidder_account_id, str) or bidder_account_id == "":
        raise errors.invalid_request("bidder_account_id is required.")
    # Ownership (priority 3): acting buyer must be the bidder.
    if bidder_account_id != caller.user_id:
        raise errors.not_owner("bidder_account_id must be the acting buyer account.")
    bidder = db.accounts.get(bidder_account_id)
    if bidder is None:
        raise errors.not_found("Bidder account not found.")
    mw.check_account_not_closed(caller)

    # State (priority 6): bidding is defined only on an ACTIVE auction.
    if listing["status"] in TERMINAL_LISTING_STATES:
        raise errors.auction_closed("The listing is terminal.")
    if listing["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE listing accepts bids.")
    if listing["format"] not in ("AUCTION", "HYBRID"):
        raise errors.invalid_state("Only AUCTION or HYBRID listings accept bids.")

    # Auction-window timing (priority 7): bids rejected once clock >= effective_end_at.
    if listing["effective_end_at"] is not None:
        end_dt = db.parse_iso(listing["effective_end_at"])
        if db.now_dt() >= end_dt:
            raise errors.auction_closed("The auction is closed.")

    # Self-dealing (priority 9).
    if bidder_account_id == listing["seller_account_id"]:
        raise errors.self_trading()

    if "BUYER" not in bidder.get("roles", []):
        raise errors.invalid_request("bidder must hold the BUYER role.")

    # Field-shape: max_proxy_cents (priority 17 vs 11 — type check is shape).
    max_proxy_cents = body.get("max_proxy_cents", None)
    if max_proxy_cents is None:
        raise errors.invalid_request("max_proxy_cents is required.")
    if isinstance(max_proxy_cents, bool) or not isinstance(max_proxy_cents, int):
        raise errors.invalid_request("max_proxy_cents must be an integer.")
    if max_proxy_cents < 1:
        raise errors.invalid_request("max_proxy_cents must be >= 1.")

    # Bid eligibility (priority 11, ERR_BID_TOO_LOW).
    if listing["highest_bid_id"] is None:
        # First bid: max_proxy_cents >= start_price_cents.
        if max_proxy_cents < listing["start_price_cents"]:
            raise errors.bid_too_low("First bid must be at least the start price.")
    else:
        current = listing["current_price_cents"]
        minimum = current + calc.bid_increment(current)
        if max_proxy_cents < minimum:
            raise errors.bid_too_low("Bid must be at least current price plus the minimum increment.")

    # Create the bid (ACCEPTED) and resolve.
    bid_id = db.new_id()
    bid = {
        "id": bid_id,
        "listing_id": listing_id,
        "bidder_account_id": bidder_account_id,
        "max_proxy_cents": max_proxy_cents,
        "current_price_cents": None,
        "is_winning": False,
        "status": "ACCEPTED",
    }
    core.stamp_new(bid)
    db.bids[bid_id] = bid

    auction.resolve_proxy(listing, bid)
    listing["bid_count"] = listing["bid_count"] + 1
    # Anti-sniping: only a still-accepted (qualifying) bid extends. Per PRD §3.4 an
    # accepted bid placed near close pushes the end forward.
    auction.apply_snipe_extension(listing)
    core.touch(listing)

    return response.success(core.ser_bid(bid), status=201)


@bp.route("/bids/<bid_id>", methods=["GET"])
def get_bid(bid_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Anonymous", "Buyer", "Seller", "PlatformAdmin"})
    bid = db.bids.get(bid_id)
    if bid is None:
        raise errors.not_found("Bid not found.")
    return response.success(core.ser_bid(bid), status=200)


@bp.route("/bids", methods=["GET"])
def list_bids():
    caller = mw.require_auth()
    mw.require_role(caller, {"Anonymous", "Buyer", "Seller", "PlatformAdmin"})
    listing_id = request.args.get("listing_id")
    bidder_account_id = request.args.get("bidder_account_id")
    items = list(db.bids.values())
    if listing_id is not None:
        items = [b for b in items if b["listing_id"] == listing_id]
    if bidder_account_id is not None:
        items = [b for b in items if b["bidder_account_id"] == bidder_account_id]
    return paginate_list(items, core.ser_bid)


@bp.route("/bids/<bid_id>/retract", methods=["POST"])
def retract_bid(bid_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Buyer"})          # priority 2
    bid = db.bids.get(bid_id)                    # existence (priority 4)
    if bid is None:
        raise errors.not_found("Bid not found.")
    # Ownership (priority 3): the acting buyer must be the bidder.
    if bid["bidder_account_id"] != caller.user_id:
        raise errors.not_owner("Only the bidder may retract this bid.")
    mw.check_account_not_closed(caller)

    listing = db.listings.get(bid["listing_id"])
    if listing is None:
        raise errors.not_found("Listing not found.")

    # State (priority 6): a RETRACTED bid cannot be retracted again. PRD §3.3
    # gates retraction only on the lockout window and the currently-winning rule,
    # so a non-winning ACCEPTED/OUTBID bid may proceed to those checks.
    if bid["status"] == "RETRACTED":
        raise errors.invalid_state("This bid has already been retracted.")

    # The auction must still be open to retract (PRD §3.3 — retraction acts on a
    # live auction's bid set). A terminal listing cannot have bids retracted.
    if listing["status"] != "ACTIVE":
        raise errors.invalid_state("Bids may only be retracted on an ACTIVE auction.")

    # Bid-retraction lockout (priority 14).
    # Allowed only > BID_RETRACT_LOCKOUT_SECONDS before effective_end_at, and only
    # if the bid is not currently winning.
    if bid["is_winning"]:
        raise errors.retract_not_allowed("A currently-winning bid cannot be retracted.")
    if listing["effective_end_at"] is not None:
        end_dt = db.parse_iso(listing["effective_end_at"])
        remaining = (end_dt - db.now_dt()).total_seconds()
        if remaining <= C.BID_RETRACT_LOCKOUT_SECONDS:
            raise errors.retract_not_allowed("Retraction is locked out within the final window.")

    bid["status"] = "RETRACTED"
    bid["is_winning"] = False
    core.touch(bid)

    # Re-run proxy resolution over the remaining ACCEPTED bids.
    auction.reresolve_after_retract(listing)
    core.touch(listing)

    return response.success(core.ser_bid(bid), status=200)
