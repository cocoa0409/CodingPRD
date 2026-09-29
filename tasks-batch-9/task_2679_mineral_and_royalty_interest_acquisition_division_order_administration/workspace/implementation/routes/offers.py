"""Offer negotiation: counter, revise, accept, reject and the lazy expiry
(PRD 3.3)."""

from flask import Blueprint

import calc
import response
import serializers
from db import clock_date, clock_iso, db, touch
from errors import ApiError
from guards import (authorize, body, get_offer, opt_str, parse_date_str,
                    req_date, req_num)

bp = Blueprint("offers", __name__)

LIVE_POSTURES = ("SENT", "COUNTERED", "REVISED")


def _interest_of(offer):
    return db.mineral_interests.get(offer["mineral_interest_id"])


def _require_owner(offer, user_id):
    """Rung 4: an owner may only act on its own interest."""
    interest = _interest_of(offer)
    if interest is None or interest["seller_owner_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return interest


def _live_valuation(interest_id):
    for row in db.valuations.values():
        if row["mineral_interest_id"] == interest_id and row["valuation_status"] == "CURRENT":
            return row
    return None


def _lazy_expire(offer):
    """Priority 60.  Expiry is lazy and durable: the letter really moves to
    EXPIRED and the interest is RELEASED before the triggering write fails."""
    if offer["offer_status"] not in LIVE_POSTURES:
        return
    expires = parse_date_str(offer["expires_on"])
    if expires is None or clock_date() <= expires:
        return
    offer["offer_status"] = "EXPIRED"
    touch(offer)
    interest = _interest_of(offer)
    if interest is not None:
        interest["interest_status"] = "RELEASED"
        touch(interest)
    raise ApiError("ERR_OFFER_EXPIRED")


@bp.route("/offer-letters/<offer_id>", methods=["GET"])
def read_offer(offer_id):
    authorize("AcquisitionManager", "RoyaltyOwner")
    row = get_offer(offer_id)
    return response.ok(serializers.offer_out(row))


@bp.route("/offer-letters/<offer_id>/counter", methods=["POST"])
def counter_offer(offer_id):
    user_id, _role = authorize("RoyaltyOwner")
    offer = get_offer(offer_id)
    _require_owner(offer, user_id)
    payload = body()
    counter_amount = req_num(payload, "counter_amount", 2, minimum=0, exclusive_min=True)

    if offer["offer_status"] not in ("SENT", "REVISED"):      # priority 25
        raise ApiError("ERR_OFFER_STATE_INVALID")
    _lazy_expire(offer)                                        # priority 60
    if offer["counter_round_count"] >= calc.MAX_COUNTER_ROUNDS:  # priority 67
        raise ApiError("ERR_COUNTER_ROUNDS_EXHAUSTED")

    offer["last_counter_amount"] = counter_amount
    offer["counter_round_count"] = offer["counter_round_count"] + 1
    offer["offer_status"] = "COUNTERED"
    touch(offer)
    return response.ok(serializers.offer_out(offer))


@bp.route("/offer-letters/<offer_id>/revise", methods=["POST"])
def revise_offer(offer_id):
    authorize("AcquisitionManager")
    offer = get_offer(offer_id)
    payload = body()
    revised_amount = req_num(payload, "revised_amount", 2, minimum=0, exclusive_min=True)
    expires_on, _parsed = req_date(payload, "expires_on")

    interest = _interest_of(offer)
    valuation = _live_valuation(offer["mineral_interest_id"])
    if valuation is None:                                      # priority 24
        raise ApiError("ERR_NO_CURRENT_VALUATION")
    if offer["offer_status"] != "COUNTERED":                    # priority 25
        raise ApiError("ERR_OFFER_STATE_INVALID")
    _lazy_expire(offer)                                        # priority 60
    if revised_amount < valuation["bid_floor"]:                 # priority 81
        raise ApiError("ERR_OFFER_BELOW_BID_FLOOR")
    if revised_amount > valuation["max_bid"]:                   # priority 82
        raise ApiError("ERR_OFFER_ABOVE_MAX_BID")

    offer["current_amount"] = revised_amount
    offer["expires_on"] = expires_on
    offer["offer_status"] = "REVISED"
    touch(offer)
    return response.ok(serializers.offer_out(offer))


@bp.route("/offer-letters/<offer_id>/accept", methods=["POST"])
def accept_offer(offer_id):
    user_id, _role = authorize("RoyaltyOwner")
    offer = get_offer(offer_id)
    _require_owner(offer, user_id)

    if offer["offer_status"] not in ("SENT", "REVISED"):        # priority 25
        raise ApiError("ERR_OFFER_STATE_INVALID")
    _lazy_expire(offer)                                        # priority 60

    offer["offer_status"] = "ACCEPTED"
    offer["accepted_at"] = clock_iso()
    touch(offer)
    return response.ok(serializers.offer_out(offer))


@bp.route("/offer-letters/<offer_id>/reject", methods=["POST"])
def reject_offer(offer_id):
    user_id, _role = authorize("RoyaltyOwner")
    offer = get_offer(offer_id)
    interest = _require_owner(offer, user_id)
    payload = body()
    rejection_reason = opt_str(payload, "rejection_reason")

    # rejection carries no expiry test: an owner may reject a lapsed offer
    if offer["offer_status"] not in ("SENT", "COUNTERED", "REVISED"):   # priority 25
        raise ApiError("ERR_OFFER_STATE_INVALID")

    offer["offer_status"] = "REJECTED"
    if rejection_reason is not None:
        offer["rejection_reason"] = rejection_reason
    touch(offer)
    interest["interest_status"] = "RELEASED"
    touch(interest)
    return response.ok(serializers.offer_out(offer))
