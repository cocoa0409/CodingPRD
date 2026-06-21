"""Offer endpoints. PRD §3.5 (negotiation loop), §3.6 (offer acceptance -> sale)."""
from flask import Blueprint, request

import db
import errors
import response
import constants as C
import middleware as mw
from services import core, sales
from services.auction import TERMINAL_LISTING_STATES
from routes.helpers import get_json_body, paginate_list

bp = Blueprint("offers", __name__)


def _listing_terminal_or_closed(listing):
    """True when offers/buy-now should be rejected with ERR_AUCTION_CLOSED."""
    if listing["status"] in TERMINAL_LISTING_STATES:
        return True
    if listing.get("effective_end_at") is not None:
        end_dt = db.parse_iso(listing["effective_end_at"])
        if db.now_dt() >= end_dt:
            return True
    return False


@bp.route("/listings/<listing_id>/offers", methods=["POST"])
def submit_offer(listing_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Buyer"})          # priority 2
    body = get_json_body()
    listing = db.listings.get(listing_id)       # existence (priority 4)
    if listing is None:
        raise errors.not_found("Listing not found.")

    buyer_account_id = body.get("buyer_account_id")
    if not isinstance(buyer_account_id, str) or buyer_account_id == "":
        raise errors.invalid_request("buyer_account_id is required.")
    # Ownership (priority 3).
    if buyer_account_id != caller.user_id:
        raise errors.not_owner("buyer_account_id must be the acting buyer account.")
    buyer = db.accounts.get(buyer_account_id)
    if buyer is None:
        raise errors.not_found("Buyer account not found.")
    mw.check_account_not_closed(caller)

    # State (priority 6): submitting requires an ACTIVE listing.
    if _listing_terminal_or_closed(listing):
        raise errors.auction_closed("The listing is closed or terminal.")
    if listing["status"] != "ACTIVE":
        raise errors.invalid_state("Offers may only be submitted on an ACTIVE listing.")

    # Self-dealing (priority 9).
    if buyer_account_id == listing["seller_account_id"]:
        raise errors.self_trading()

    if "BUYER" not in buyer.get("roles", []):
        raise errors.invalid_request("buyer must hold the BUYER role.")

    amount_cents = body.get("amount_cents", None)
    if amount_cents is None:
        raise errors.invalid_request("amount_cents is required.")
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        raise errors.invalid_request("amount_cents must be an integer.")

    # Offer-amount eligibility (priority 12, ERR_OFFER_INVALID).
    if not listing["accepts_offers"]:
        raise errors.offer_invalid("This listing does not accept offers.")
    if listing["buy_now_price_cents"] is None:
        raise errors.offer_invalid("This listing does not support offers.")
    if not (amount_cents >= 1 and amount_cents < listing["buy_now_price_cents"]):
        raise errors.offer_invalid("amount_cents must be >= 1 and < buy_now_price_cents.")

    oid = db.new_id()
    offer = {
        "id": oid,
        "listing_id": listing_id,
        "buyer_account_id": buyer_account_id,
        "amount_cents": amount_cents,
        "round_no": 1,
        "last_actor": "BUYER",
        "status": "PENDING",
    }
    core.stamp_new(offer)
    db.offers[oid] = offer
    return response.success(core.ser_offer(offer), status=201)


@bp.route("/offers/<offer_id>", methods=["GET"])
def get_offer(offer_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Buyer", "Seller", "PlatformAdmin"})
    offer = db.offers.get(offer_id)
    if offer is None:
        raise errors.not_found("Offer not found.")
    return response.success(core.ser_offer(offer), status=200)


@bp.route("/offers", methods=["GET"])
def list_offers():
    caller = mw.require_auth()
    mw.require_role(caller, {"Buyer", "Seller", "PlatformAdmin"})
    listing_id = request.args.get("listing_id")
    buyer_account_id = request.args.get("buyer_account_id")
    items = list(db.offers.values())
    if listing_id is not None:
        items = [o for o in items if o["listing_id"] == listing_id]
    if buyer_account_id is not None:
        items = [o for o in items if o["buyer_account_id"] == buyer_account_id]
    return paginate_list(items, core.ser_offer)


def _is_seller_of(caller, listing):
    return caller.role == "Seller" and listing["seller_account_id"] == caller.user_id


def _is_buyer_of(caller, offer):
    return caller.role == "Buyer" and offer["buyer_account_id"] == caller.user_id


@bp.route("/offers/<offer_id>/counter", methods=["POST"])
def counter_offer(offer_id):
    caller = mw.require_auth()                          # priority 1
    mw.require_role(caller, {"Buyer", "Seller"})        # priority 2
    body = get_json_body()
    offer = db.offers.get(offer_id)                     # existence (priority 4)
    if offer is None:
        raise errors.not_found("Offer not found.")
    listing = db.listings.get(offer["listing_id"])
    if listing is None:
        raise errors.not_found("Listing not found.")

    # Ownership (priority 3): seller of the listing or buyer of the offer.
    is_seller = _is_seller_of(caller, listing)
    is_buyer = _is_buyer_of(caller, offer)
    if not (is_seller or is_buyer):
        raise errors.not_owner("Only the offer's buyer or the listing's seller may counter.")
    mw.check_account_not_closed(caller)

    # OCC (priority 5): expected_offer_version must match.
    expected = body.get("expected_offer_version", None)
    if expected is None:
        raise errors.invalid_request("expected_offer_version is required.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_offer_version must be an integer.")
    if expected != offer["version"]:
        raise errors.stale_version()

    # State (priority 6): counter is defined from PENDING or COUNTERED with the
    # correct standing actor.
    if offer["status"] not in ("PENDING", "COUNTERED"):
        raise errors.invalid_state("Only a PENDING or COUNTERED offer may be countered.")
    # A seller may counter only when last_actor == BUYER; a buyer only when SELLER.
    if is_seller and offer["last_actor"] != "BUYER":
        raise errors.invalid_state("A seller may counter only when the buyer set the standing amount.")
    if is_buyer and offer["last_actor"] != "SELLER":
        raise errors.invalid_state("A buyer may counter only when the seller set the standing amount.")

    # Offer round cap (priority 13): counter rejected when round_no >= OFFER_MAX_ROUNDS.
    if offer["round_no"] >= C.OFFER_MAX_ROUNDS:
        raise errors.offer_round_limit()

    amount_cents = body.get("amount_cents", None)
    if amount_cents is None:
        raise errors.invalid_request("amount_cents is required.")
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        raise errors.invalid_request("amount_cents must be an integer.")

    # Offer-amount eligibility (priority 12).
    if not listing["accepts_offers"] or listing["buy_now_price_cents"] is None:
        raise errors.offer_invalid("This listing does not accept offers.")
    if not (amount_cents >= 1 and amount_cents < listing["buy_now_price_cents"]):
        raise errors.offer_invalid("amount_cents must be >= 1 and < buy_now_price_cents.")

    offer["amount_cents"] = amount_cents
    offer["last_actor"] = "SELLER" if is_seller else "BUYER"
    offer["round_no"] = offer["round_no"] + 1
    offer["status"] = "COUNTERED"
    core.touch(offer)
    return response.success(core.ser_offer(offer), status=200)


@bp.route("/offers/<offer_id>/accept", methods=["POST"])
def accept_offer(offer_id):
    caller = mw.require_auth()                          # priority 1
    mw.require_role(caller, {"Buyer", "Seller"})        # priority 2
    body = get_json_body()
    offer = db.offers.get(offer_id)                     # existence (priority 4)
    if offer is None:
        raise errors.not_found("Offer not found.")
    listing = db.listings.get(offer["listing_id"])
    if listing is None:
        raise errors.not_found("Listing not found.")

    is_seller = _is_seller_of(caller, listing)
    is_buyer = _is_buyer_of(caller, offer)
    if not (is_seller or is_buyer):
        raise errors.not_owner("Only the offer's buyer or the listing's seller may accept.")
    mw.check_account_not_closed(caller)

    # State (priority 6): accept defined from PENDING or COUNTERED.
    if offer["status"] not in ("PENDING", "COUNTERED"):
        raise errors.invalid_state("Only a PENDING or COUNTERED offer may be accepted.")
    # Accepted by the party who did NOT set the standing amount.
    if is_seller and offer["last_actor"] != "BUYER":
        raise errors.invalid_state("A seller accepts only when the buyer set the standing amount.")
    if is_buyer and offer["last_actor"] != "SELLER":
        raise errors.invalid_state("A buyer accepts only when the seller set the standing amount.")

    # The listing must still be ACTIVE and accept offers (PRD §3.6).
    if listing["status"] != "ACTIVE":
        raise errors.invalid_state("The listing is no longer ACTIVE.")
    if not listing["accepts_offers"]:
        raise errors.offer_invalid("This listing does not accept offers.")

    shipping_cents = body.get("shipping_cents", 0)
    if shipping_cents is None:
        shipping_cents = 0
    if isinstance(shipping_cents, bool) or not isinstance(shipping_cents, int):
        raise errors.invalid_request("shipping_cents must be an integer.")
    if shipping_cents < 0:
        raise errors.invalid_request("shipping_cents must be >= 0.")

    # Cascade: offer -> ACCEPTED; listing -> SOLD; create Order(OFFER_ACCEPT)
    # -> SellerFeeInvoice; other open offers -> DECLINED.
    offer["status"] = "ACCEPTED"
    core.touch(offer)

    listing["winner_account_id"] = offer["buyer_account_id"]
    listing["sold_price_cents"] = offer["amount_cents"]
    listing["status"] = "SOLD"
    core.touch(listing)

    sales.create_order_and_invoice(
        listing,
        buyer_account_id=offer["buyer_account_id"],
        source="OFFER_ACCEPT",
        item_price_cents=offer["amount_cents"],
        shipping_cents=shipping_cents,
    )

    # Every other PENDING/COUNTERED offer on this listing -> DECLINED.
    for o in db.offers.values():
        if o["id"] == offer["id"]:
            continue
        if o["listing_id"] == listing["id"] and o["status"] in ("PENDING", "COUNTERED"):
            o["status"] = "DECLINED"
            core.touch(o)

    return response.success(core.ser_offer(offer), status=200)


@bp.route("/offers/<offer_id>/decline", methods=["POST"])
def decline_offer(offer_id):
    caller = mw.require_auth()                          # priority 1
    mw.require_role(caller, {"Buyer", "Seller"})        # priority 2
    offer = db.offers.get(offer_id)                     # existence (priority 4)
    if offer is None:
        raise errors.not_found("Offer not found.")
    listing = db.listings.get(offer["listing_id"])
    if listing is None:
        raise errors.not_found("Listing not found.")

    is_seller = _is_seller_of(caller, listing)
    is_buyer = _is_buyer_of(caller, offer)
    if not (is_seller or is_buyer):
        raise errors.not_owner("Only the offer's buyer or the listing's seller may decline.")
    mw.check_account_not_closed(caller)

    if offer["status"] not in ("PENDING", "COUNTERED"):
        raise errors.invalid_state("Only a PENDING or COUNTERED offer may be declined.")
    if offer["status"] == "PENDING":
        # Declined by the seller who owns the listing.
        if not is_seller:
            raise errors.invalid_state("A PENDING offer is declined by the listing's seller.")
    else:
        # COUNTERED: declined by whichever party did NOT make the standing amount.
        if offer["last_actor"] == "BUYER" and not is_seller:
            raise errors.invalid_state("The party who did not make the standing amount declines.")
        if offer["last_actor"] == "SELLER" and not is_buyer:
            raise errors.invalid_state("The party who did not make the standing amount declines.")

    offer["status"] = "DECLINED"
    core.touch(offer)
    return response.success(core.ser_offer(offer), status=200)


@bp.route("/offers/<offer_id>/withdraw", methods=["POST"])
def withdraw_offer(offer_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"Buyer"})          # priority 2
    offer = db.offers.get(offer_id)             # existence (priority 4)
    if offer is None:
        raise errors.not_found("Offer not found.")
    # Ownership (priority 3): the acting buyer is the offer's buyer.
    if offer["buyer_account_id"] != caller.user_id:
        raise errors.not_owner("Only the offer's buyer may withdraw it.")
    mw.check_account_not_closed(caller)

    # State (priority 6): withdraw is defined from PENDING with last_actor BUYER.
    if offer["status"] != "PENDING" or offer["last_actor"] != "BUYER":
        raise errors.invalid_state("Only a PENDING offer whose last actor is the buyer may be withdrawn.")

    offer["status"] = "WITHDRAWN"
    core.touch(offer)
    return response.success(core.ser_offer(offer), status=200)
