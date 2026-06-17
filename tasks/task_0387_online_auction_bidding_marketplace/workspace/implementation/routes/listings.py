"""Listing endpoints. PRD §3.2 (create/publish/cancel), §3.6 (buy-now)."""
from flask import Blueprint

import db
import errors
import response
import constants as C
import middleware as mw
from services import core, sales
from services.auction import TERMINAL_LISTING_STATES
from routes.helpers import get_json_body, paginate_list, require_int

bp = Blueprint("listings", __name__)

VALID_FORMATS = {"AUCTION", "BUY_NOW", "HYBRID"}


@bp.route("/listings", methods=["POST"])
def create_listing():
    caller = mw.require_auth()                      # priority 1
    mw.require_role(caller, {"Seller"})             # priority 2
    mw.check_account_not_closed(caller)             # ERR_ACCOUNT_CLOSED
    body = get_json_body()

    seller_account_id = body.get("seller_account_id")
    title = body.get("title")
    fmt = body.get("format")

    # Ownership (priority 3): the seller_account_id must be the acting account.
    if not isinstance(seller_account_id, str) or seller_account_id == "":
        raise errors.invalid_request("seller_account_id is required.")
    if seller_account_id != caller.user_id:
        raise errors.not_owner("seller_account_id must be the acting seller account.")

    # Existence (priority 4): the seller account must exist.
    seller = db.accounts.get(seller_account_id)
    if seller is None:
        raise errors.not_found("Seller account not found.")

    # Field-shape validation (priority 17, ERR_INVALID_REQUEST).
    if not isinstance(title, str) or title == "":
        raise errors.invalid_request("title is required.")
    if fmt not in VALID_FORMATS:
        raise errors.invalid_request("format must be AUCTION, BUY_NOW, or HYBRID.")
    if "SELLER" not in seller.get("roles", []):
        raise errors.invalid_request("seller_account_id must hold the SELLER role.")

    start_price_cents = body.get("start_price_cents", None)
    buy_now_price_cents = body.get("buy_now_price_cents", None)
    reserve_price_cents = body.get("reserve_price_cents", None)
    accepts_offers = body.get("accepts_offers", False)
    scheduled_end_at = body.get("scheduled_end_at", None)

    if accepts_offers is None:
        accepts_offers = False
    if not isinstance(accepts_offers, bool):
        raise errors.invalid_request("accepts_offers must be a boolean.")

    # Validate numeric types where present.
    for fld, val in (("start_price_cents", start_price_cents),
                     ("buy_now_price_cents", buy_now_price_cents),
                     ("reserve_price_cents", reserve_price_cents)):
        if val is not None and (isinstance(val, bool) or not isinstance(val, int)):
            raise errors.invalid_request("%s must be an integer." % fld)

    created_at_dt = db.now_dt()

    if fmt in ("AUCTION", "HYBRID"):
        # start_price_cents >= 1 required.
        if start_price_cents is None:
            raise errors.invalid_request("start_price_cents is required for AUCTION/HYBRID.")
        if start_price_cents < 1:
            raise errors.invalid_request("start_price_cents must be >= 1.")
        # scheduled_end_at required and strictly after created_at.
        if not isinstance(scheduled_end_at, str) or scheduled_end_at == "":
            raise errors.invalid_request("scheduled_end_at is required for AUCTION/HYBRID.")
        try:
            end_dt = db.parse_iso(scheduled_end_at)
        except ValueError:
            raise errors.invalid_request("scheduled_end_at must be a valid ISO 8601 timestamp.")
        if not (end_dt > created_at_dt):
            raise errors.invalid_request("scheduled_end_at must be strictly after created_at.")
        # Normalize to the canonical ISO 8601 UTC form with three fractional
        # digits (PRD §2.4); this is a system-managed timestamp.
        scheduled_end_at = db.iso(end_dt)
    if fmt in ("BUY_NOW", "HYBRID"):
        # buy_now_price_cents required.
        if buy_now_price_cents is None:
            raise errors.invalid_request("buy_now_price_cents is required for BUY_NOW/HYBRID.")
        if buy_now_price_cents < 1:
            raise errors.invalid_request("buy_now_price_cents must be >= 1.")
    if fmt == "AUCTION":
        # buy_now_price_cents must be null for AUCTION.
        if buy_now_price_cents is not None:
            raise errors.invalid_request("buy_now_price_cents must be null for AUCTION.")
    if fmt == "HYBRID":
        # buy-now must be strictly greater than start price.
        if not (buy_now_price_cents > start_price_cents):
            raise errors.invalid_request("buy_now_price_cents must be strictly greater than start_price_cents for HYBRID.")
    if fmt == "BUY_NOW":
        # reserve forbidden on BUY_NOW.
        if reserve_price_cents is not None:
            raise errors.invalid_request("reserve_price_cents is forbidden on BUY_NOW.")

    # Reserve: when set must be >= start_price_cents (AUCTION/HYBRID).
    if reserve_price_cents is not None:
        if fmt in ("AUCTION", "HYBRID"):
            if reserve_price_cents < start_price_cents:
                raise errors.invalid_request("reserve_price_cents must be >= start_price_cents.")

    # accepts_offers only permitted on BUY_NOW/HYBRID.
    if accepts_offers and fmt == "AUCTION":
        raise errors.invalid_request("accepts_offers is permitted only on BUY_NOW or HYBRID.")

    # For a pure BUY_NOW, start_price_cents and scheduled_end_at are ignored.
    if fmt == "BUY_NOW":
        start_price_cents = None
        scheduled_end_at = None

    lid = db.new_id()
    listing = {
        "id": lid,
        "seller_account_id": seller_account_id,
        "title": title,
        "format": fmt,
        "start_price_cents": start_price_cents,
        "buy_now_price_cents": buy_now_price_cents if fmt in ("BUY_NOW", "HYBRID") else None,
        "reserve_price_cents": reserve_price_cents,
        "accepts_offers": accepts_offers,
        "scheduled_end_at": scheduled_end_at,
        "effective_end_at": None,
        "highest_bid_id": None,
        "current_price_cents": None,
        "bid_count": 0,
        "status": "DRAFT",
        "winner_account_id": None,
        "sold_price_cents": None,
    }
    core.stamp_new(listing)
    db.listings[lid] = listing
    return response.success(core.ser_listing(listing), status=201)


@bp.route("/listings/<listing_id>", methods=["GET"])
def get_listing(listing_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Anonymous", "Buyer", "Seller", "PlatformAdmin"})
    listing = db.listings.get(listing_id)
    if listing is None:
        raise errors.not_found("Listing not found.")
    return response.success(core.ser_listing(listing), status=200)


@bp.route("/listings", methods=["GET"])
def list_listings():
    caller = mw.require_auth()
    mw.require_role(caller, {"Anonymous", "Buyer", "Seller", "PlatformAdmin"})
    from flask import request
    seller_account_id = request.args.get("seller_account_id")
    status = request.args.get("status")
    items = list(db.listings.values())
    if seller_account_id is not None:
        items = [l for l in items if l["seller_account_id"] == seller_account_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return paginate_list(items, core.ser_listing)


@bp.route("/listings/<listing_id>/publish", methods=["POST"])
def publish_listing(listing_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Seller"})         # priority 2
    listing = db.listings.get(listing_id)       # existence (priority 4)
    if listing is None:
        raise errors.not_found("Listing not found.")
    # Ownership (priority 3): acting seller owns the listing.
    if listing["seller_account_id"] != caller.user_id:
        raise errors.not_owner("Only the listing's seller may publish it.")
    mw.check_account_not_closed(caller)

    # State (priority 6): publish is defined only from DRAFT.
    if listing["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT listing may be published.")

    seller = db.accounts.get(listing["seller_account_id"])
    if seller is None:
        raise errors.not_found("Seller account not found.")
    # Seller account must be ACTIVE.
    if seller["status"] != "ACTIVE":
        raise errors.invalid_state("Seller account is not ACTIVE.")

    # Seller standing gate (priority 10).
    if seller["standing"] == "SUSPENDED":
        raise errors.seller_suspended()

    fmt = listing["format"]
    if fmt in ("AUCTION", "HYBRID"):
        # scheduled_end_at must still be strictly after the current clock.
        end_dt = db.parse_iso(listing["scheduled_end_at"])
        if not (end_dt > db.now_dt()):
            raise errors.invalid_request("scheduled_end_at must be strictly after the current clock at publish time.")
        # effective_end_at is a system-managed timestamp; emit canonical 3-digit
        # ISO 8601 UTC (PRD §2.4) so it is consistent whether or not an
        # anti-sniping extension later rewrites it.
        listing["effective_end_at"] = db.iso(end_dt)
        listing["current_price_cents"] = listing["start_price_cents"]
    else:
        # BUY_NOW: effective_end_at stays null, current_price_cents null.
        listing["effective_end_at"] = None
        listing["current_price_cents"] = None

    listing["status"] = "ACTIVE"
    core.touch(listing)
    return response.success(core.ser_listing(listing), status=200)


@bp.route("/listings/<listing_id>/cancel", methods=["POST"])
def cancel_listing(listing_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Seller"})
    listing = db.listings.get(listing_id)
    if listing is None:
        raise errors.not_found("Listing not found.")
    if listing["seller_account_id"] != caller.user_id:
        raise errors.not_owner("Only the listing's seller may cancel it.")
    mw.check_account_not_closed(caller)

    status = listing["status"]
    if status == "DRAFT":
        listing["status"] = "CANCELLED"
        core.touch(listing)
        return response.success(core.ser_listing(listing), status=200)
    if status == "ACTIVE":
        # Cancelling an ACTIVE listing requires bid_count == 0.
        if listing["bid_count"] != 0:
            raise errors.invalid_state("An auction that already has bids cannot be cancelled.")
        # Cascade: PENDING/COUNTERED offers -> DECLINED.
        for o in db.offers.values():
            if o["listing_id"] == listing_id and o["status"] in ("PENDING", "COUNTERED"):
                o["status"] = "DECLINED"
                core.touch(o)
        listing["status"] = "CANCELLED"
        core.touch(listing)
        return response.success(core.ser_listing(listing), status=200)
    raise errors.invalid_state("This listing cannot be cancelled from its current state.")


@bp.route("/listings/<listing_id>/buy-now", methods=["POST"])
def buy_now(listing_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Buyer"})          # priority 2
    body = get_json_body()
    listing = db.listings.get(listing_id)       # existence (priority 4)
    if listing is None:
        raise errors.not_found("Listing not found.")

    buyer_account_id = body.get("buyer_account_id")
    if not isinstance(buyer_account_id, str) or buyer_account_id == "":
        raise errors.invalid_request("buyer_account_id is required.")
    # Ownership (priority 3): acting buyer must be the buyer.
    if buyer_account_id != caller.user_id:
        raise errors.not_owner("buyer_account_id must be the acting buyer account.")
    buyer = db.accounts.get(buyer_account_id)
    if buyer is None:
        raise errors.not_found("Buyer account not found.")
    mw.check_account_not_closed(caller)

    # State (priority 6): buy-now is defined only from ACTIVE on BUY_NOW/HYBRID.
    if listing["status"] in TERMINAL_LISTING_STATES:
        raise errors.auction_closed("The listing is terminal.")
    if listing["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE listing may be purchased.")
    if listing["format"] not in ("BUY_NOW", "HYBRID"):
        raise errors.invalid_state("Buy-now is only available for BUY_NOW or HYBRID listings.")

    # For HYBRID the buy-now option disappears after the first bid.
    if listing["format"] == "HYBRID" and listing["bid_count"] != 0:
        raise errors.invalid_state("The buy-now option disappears after the first bid on a HYBRID listing.")

    # Self-dealing (priority 9).
    if buyer_account_id == listing["seller_account_id"]:
        raise errors.self_trading()

    # Buyer must hold the BUYER role and have an ACTIVE account.
    if "BUYER" not in buyer.get("roles", []):
        raise errors.invalid_request("buyer must hold the BUYER role.")
    if buyer["status"] != "ACTIVE":
        raise errors.invalid_state("Buyer account is not ACTIVE.")

    shipping_cents = body.get("shipping_cents", 0)
    if shipping_cents is None:
        shipping_cents = 0
    if isinstance(shipping_cents, bool) or not isinstance(shipping_cents, int):
        raise errors.invalid_request("shipping_cents must be an integer.")
    if shipping_cents < 0:
        raise errors.invalid_request("shipping_cents must be >= 0.")

    # Move listing to SOLD; cascade order + invoice.
    listing["winner_account_id"] = buyer_account_id
    listing["sold_price_cents"] = listing["buy_now_price_cents"]
    listing["status"] = "SOLD"
    core.touch(listing)

    order = sales.create_order_and_invoice(
        listing,
        buyer_account_id=buyer_account_id,
        source="BUY_NOW",
        item_price_cents=listing["buy_now_price_cents"],
        shipping_cents=shipping_cents,
    )
    return response.success(core.ser_order(order), status=201)
