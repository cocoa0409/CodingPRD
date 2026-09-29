"""Mineral interests, decline-curve valuations and offer issuance
(PRD 3.2, 3.3)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import guards
import response
import serializers
from db import db, stamp_new, touch
from errors import ApiError
from guards import (authorize, body, body_ref, get_interest, get_valuation,
                    pagination, paginate, req_date, req_num)

bp = Blueprint("interests", __name__)


def _live_valuation(interest_id):
    for row in db.valuations.values():
        if row["mineral_interest_id"] == interest_id and row["valuation_status"] == "CURRENT":
            return row
    return None


@bp.route("/mineral-interests", methods=["POST"])
def create_interest():
    authorize("AcquisitionManager")
    payload = body()
    # rung 6: body references resolve before any business rule
    tract = body_ref(payload, "tract_id", db.tracts, "ERR_TRACT_NOT_FOUND")
    owner = body_ref(payload, "seller_owner_id", db.royalty_owners,
                     "ERR_ROYALTY_OWNER_NOT_FOUND")
    # rung 7
    if tract is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'tract_id' is required.")
    if owner is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'seller_owner_id' is required.")
    seller_share_fraction = req_num(payload, "seller_share_fraction", 6,
                                    minimum=0, maximum=1, exclusive_min=True)
    lease_royalty_rate = req_num(payload, "lease_royalty_rate", 6,
                                 minimum=0, maximum=1, exclusive_min=True)
    undeveloped_net_acres = req_num(payload, "undeveloped_net_acres", 4, minimum=0)
    # priority 20
    if tract["title_status"] != "CERTIFIED":
        raise ApiError("ERR_TRACT_NOT_CERTIFIED")

    row = {
        "tract_id": tract["id"],
        "seller_owner_id": owner["id"],
        "seller_share_fraction": seller_share_fraction,
        "lease_royalty_rate": lease_royalty_rate,
        "undeveloped_net_acres": undeveloped_net_acres,
        "net_mineral_acres": calc.q4(
            tract["net_mineral_acres_certified"] * seller_share_fraction),
        "existing_burden_fraction": calc.q4(tract["existing_burden_fraction"]),
        "interest_status": "PROSPECT",
        "current_valuation_id": None,
        "acquiring_deed_book_page": None,
    }
    stamp_new(row)
    db.mineral_interests[row["id"]] = row
    return response.created(serializers.interest_out(row))


@bp.route("/mineral-interests/<interest_id>", methods=["GET"])
def read_interest(interest_id):
    authorize("TitleAnalyst", "AcquisitionManager", "DivisionOrderAdmin")
    row = get_interest(interest_id)
    return response.ok(serializers.interest_out(row))


@bp.route("/mineral-interests", methods=["GET"])
def list_interests():
    authorize("TitleAnalyst", "AcquisitionManager", "DivisionOrderAdmin")
    limit, offset = pagination()
    tract_id = request.args.get("tract_id")
    seller_owner_id = request.args.get("seller_owner_id")
    interest_status = request.args.get("interest_status")
    rows = list(db.mineral_interests.values())
    if tract_id is not None:
        rows = [r for r in rows if r["tract_id"] == tract_id]
    if seller_owner_id is not None:
        rows = [r for r in rows if r["seller_owner_id"] == seller_owner_id]
    if interest_status is not None:
        rows = [r for r in rows if r["interest_status"] == interest_status]
    rows.sort(key=lambda r: r["_seq"])
    page, total = paginate(rows, limit, offset)
    return response.listing([serializers.interest_out(r) for r in page],
                            limit, offset, total)


# --------------------------------------------------------------------------
# valuations
# --------------------------------------------------------------------------
@bp.route("/mineral-interests/<interest_id>/valuations", methods=["POST"])
def create_valuation(interest_id):
    user_id, _role = authorize("AcquisitionManager")
    interest = get_interest(interest_id)
    payload = body()
    current_monthly_net_revenue = req_num(payload, "current_monthly_net_revenue", 2, minimum=0)
    annual_decline_rate = req_num(payload, "annual_decline_rate", 6,
                                  minimum=0, maximum=1, exclusive_max=True)
    undeveloped_net_acres = req_num(payload, "undeveloped_net_acres", 4, minimum=0)

    tract = db.tracts[interest["tract_id"]]
    # priority 20
    if tract["title_status"] != "CERTIFIED":
        raise ApiError("ERR_TRACT_NOT_CERTIFIED")

    tier = tract["operator_activity_tier"]
    pdp_pv, undeveloped_pv, bid_floor, max_bid = calc.valuation_bid_band(
        current_monthly_net_revenue, annual_decline_rate, undeveloped_net_acres,
        tier, interest["existing_burden_fraction"])

    row = {
        "mineral_interest_id": interest["id"],
        "current_monthly_net_revenue": current_monthly_net_revenue,
        "annual_decline_rate": annual_decline_rate,
        "undeveloped_net_acres": undeveloped_net_acres,
        "operator_activity_tier": tier,
        "pdp_pv": pdp_pv,
        "undeveloped_pv": undeveloped_pv,
        "bid_floor": bid_floor,
        "max_bid": max_bid,
        "valuation_status": "CURRENT",
        "approved_by_user_id": user_id,
    }
    stamp_new(row)

    for prior in db.valuations.values():
        if (prior["mineral_interest_id"] == interest["id"]
                and prior["valuation_status"] == "CURRENT"):
            prior["valuation_status"] = "SUPERSEDED"
            touch(prior)
    db.valuations[row["id"]] = row
    interest["current_valuation_id"] = row["id"]
    touch(interest)
    return response.created(serializers.valuation_out(row))


@bp.route("/mineral-interests/<interest_id>/valuations", methods=["GET"])
def list_valuations(interest_id):
    authorize("AcquisitionManager", "DivisionOrderAdmin")
    interest = get_interest(interest_id)
    limit, offset = pagination()
    valuation_status = request.args.get("valuation_status")
    rows = [v for v in db.valuations.values()
            if v["mineral_interest_id"] == interest["id"]]
    if valuation_status is not None:
        rows = [v for v in rows if v["valuation_status"] == valuation_status]
    rows.sort(key=lambda v: v["_seq"], reverse=True)   # newest first (PRD 2.3)
    page, total = paginate(rows, limit, offset)
    return response.listing([serializers.valuation_out(r) for r in page],
                            limit, offset, total)


@bp.route("/valuations/<valuation_id>", methods=["GET"])
def read_valuation(valuation_id):
    authorize("AcquisitionManager", "DivisionOrderAdmin")
    row = get_valuation(valuation_id)
    return response.ok(serializers.valuation_out(row))


# --------------------------------------------------------------------------
# offer issuance
# --------------------------------------------------------------------------
@bp.route("/mineral-interests/<interest_id>/offer-letters", methods=["POST"])
def create_offer(interest_id):
    user_id, _role = authorize("AcquisitionManager")
    interest = get_interest(interest_id)
    payload = body()
    offer_amount = req_num(payload, "offer_amount", 2, minimum=0, exclusive_min=True)
    expires_on, _parsed = req_date(payload, "expires_on")

    tract = db.tracts[interest["tract_id"]]
    if tract["title_status"] != "CERTIFIED":          # priority 20
        raise ApiError("ERR_TRACT_NOT_CERTIFIED")
    if interest["interest_status"] != "PROSPECT":     # priority 23
        raise ApiError("ERR_INTEREST_STATE_INVALID")
    valuation = _live_valuation(interest["id"])
    if valuation is None:                            # priority 24
        raise ApiError("ERR_NO_CURRENT_VALUATION")
    if user_id == valuation["approved_by_user_id"]:   # priority 50
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if offer_amount < valuation["bid_floor"]:         # priority 81
        raise ApiError("ERR_OFFER_BELOW_BID_FLOOR")
    if offer_amount > valuation["max_bid"]:           # priority 82
        raise ApiError("ERR_OFFER_ABOVE_MAX_BID")

    row = {
        "mineral_interest_id": interest["id"],
        "offer_amount": offer_amount,
        "expires_on": expires_on,
        "current_amount": offer_amount,
        "last_counter_amount": None,
        "counter_round_count": 0,
        "offer_status": "SENT",
        "issued_by_user_id": user_id,
        "accepted_at": None,
        "rejection_reason": None,
    }
    stamp_new(row)
    db.offer_letters[row["id"]] = row
    interest["interest_status"] = "OFFERED"
    touch(interest)
    return response.created(serializers.offer_out(row))


@bp.route("/mineral-interests/<interest_id>/offer-letters", methods=["GET"])
def list_offers(interest_id):
    authorize("AcquisitionManager", "RoyaltyOwner")
    interest = get_interest(interest_id)
    limit, offset = pagination()
    offer_status = request.args.get("offer_status")
    rows = [o for o in db.offer_letters.values()
            if o["mineral_interest_id"] == interest["id"]]
    if offer_status is not None:
        rows = [o for o in rows if o["offer_status"] == offer_status]
    rows.sort(key=lambda o: o["_seq"])
    page, total = paginate(rows, limit, offset)
    return response.listing([serializers.offer_out(r) for r in page],
                            limit, offset, total)
