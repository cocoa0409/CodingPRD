from datetime import timedelta

import db
from errors import raise_error
from flask import Blueprint, request
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from serializers import serialize
from services import calculations as calc
from services.clock import now
from util import (apply_filters, get_json_body, get_pagination, paginate,
                  req_enum, req_int, req_number, sorted_by_created, stamp_new, touch)

bp = Blueprint("renewals", __name__)

OFFER_SOURCES = {"INCUMBENT_BROADCASTER", "THIRD_PARTY_BIDDER"}


def _get_deal_or_404(deal_id):
    d = db.deals.get(deal_id)
    if d is None:
        raise_error("ERR_DEAL_NOT_FOUND")
    return d


def _get_offer_scoped(deal_id, offer_id):
    _get_deal_or_404(deal_id)
    o = db.renewal_offers.get(offer_id)
    if o is None or o["deal_id"] != deal_id:
        raise_error("ERR_RENEWAL_OFFER_NOT_FOUND")
    return o


@bp.route("/deals/<dealId>/renewal-offers", methods=["POST"])
def create_offer(dealId):
    require_roles({"BidCoordinator"})
    deal = _get_deal_or_404(dealId)
    if deal["status"] != "RENEWAL_OPEN":
        raise_error("ERR_DEAL_NOT_ACTIVE", "Renewal offers may only be filed while deal is RENEWAL_OPEN")
    body = get_json_body()
    offer_source = req_enum(body, "offer_source", OFFER_SOURCES)
    offeror_broadcaster_id = body.get("offeror_broadcaster_id")
    if not isinstance(offeror_broadcaster_id, str) or offeror_broadcaster_id not in db.broadcasters:
        raise_error("ERR_BROADCASTER_NOT_FOUND")
    offered_fee_cents = req_int(body, "offered_fee_cents", minimum=0)
    escalator_rate_pct = req_number(body, "escalator_rate_pct")
    if not (0.0 < escalator_rate_pct <= 0.25):
        raise_error("ERR_INVALID_REQUEST", "escalator_rate_pct must be within (0.0, 0.25]")
    offer = {
        "deal_id": dealId,
        "offer_source": offer_source,
        "offeror_broadcaster_id": offeror_broadcaster_id,
        "offered_fee_cents": offered_fee_cents,
        "escalator_rate_pct": escalator_rate_pct,
        "matching_window_end": now() + timedelta(days=calc.MATCHING_WINDOW_DAYS),
        "matched_by_incumbent": False,
        "status": "OPEN",
    }
    stamp_new(offer)
    db.renewal_offers[offer["id"]] = offer
    return success_object(serialize(offer), status_code=201)


@bp.route("/deals/<dealId>/renewal-offers", methods=["GET"])
def list_offers(dealId):
    require_roles(ALL_ROLES)
    _get_deal_or_404(dealId)
    limit, offset = get_pagination()
    items = [o for o in db.renewal_offers.values() if o["deal_id"] == dealId]
    items = sorted_by_created(items)
    items = apply_filters(items, [
        ("status", request.args.get("status")),
        ("offer_source", request.args.get("offer_source")),
        ("deal_id", request.args.get("deal_id")),
        ("offeror_broadcaster_id", request.args.get("offeror_broadcaster_id")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(o) for o in page], limit, offset, total)


@bp.route("/deals/<dealId>/renewal-offers/<offerId>", methods=["GET"])
def get_offer(dealId, offerId):
    require_roles(ALL_ROLES)
    return success_object(serialize(_get_offer_scoped(dealId, offerId)))


@bp.route("/renewal-offers", methods=["GET"])
def list_offers_flat():
    require_roles(ALL_ROLES)
    limit, offset = get_pagination()
    items = sorted_by_created(list(db.renewal_offers.values()))
    items = apply_filters(items, [
        ("deal_id", request.args.get("deal_id")),
        ("offeror_broadcaster_id", request.args.get("offeror_broadcaster_id")),
        ("status", request.args.get("status")),
        ("offer_source", request.args.get("offer_source")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(o) for o in page], limit, offset, total)


@bp.route("/renewal-offers/<offerId>", methods=["GET"])
def get_offer_flat(offerId):
    require_roles(ALL_ROLES)
    o = db.renewal_offers.get(offerId)
    if o is None:
        raise_error("ERR_RENEWAL_OFFER_NOT_FOUND")
    return success_object(serialize(o))


@bp.route("/deals/<dealId>/renewal-offers/<offerId>/match", methods=["POST"])
def match_offer(dealId, offerId):
    user_id, _ = require_roles({"BidCoordinator"})
    offer = _get_offer_scoped(dealId, offerId)
    deal = db.deals[dealId]
    if offer["status"] != "OPEN":
        raise_error("ERR_INVALID_REQUEST", "Match requires offer OPEN")
    if offer["offer_source"] != "THIRD_PARTY_BIDDER":
        raise_error("ERR_INVALID_REQUEST", "Only THIRD_PARTY_BIDDER offers can be matched")
    if user_id != deal["broadcaster_id"]:
        raise_error("ERR_INSUFFICIENT_PERMISSIONS", "Only the incumbent broadcaster may match")
    if now() > offer["matching_window_end"]:
        raise_error("ERR_MATCHING_WINDOW_EXPIRED")
    offer["status"] = "MATCHED"
    offer["matched_by_incumbent"] = True
    touch(offer)
    return success_object(serialize(offer))


@bp.route("/deals/<dealId>/renewal-offers/<offerId>/exercise", methods=["POST"])
def exercise_offer(dealId, offerId):
    require_roles({"RightsManager"})
    offer = _get_offer_scoped(dealId, offerId)
    deal = db.deals[dealId]
    if deal["status"] != "RENEWAL_OPEN":
        raise_error("ERR_DEAL_NOT_ACTIVE", "Exercise requires deal RENEWAL_OPEN")
    if offer["status"] not in ("OPEN", "MATCHED"):
        raise_error("ERR_INVALID_REQUEST", "Exercise requires offer OPEN or MATCHED")
    # From the deal's side: MATCHED, or OPEN with offer_source INCUMBENT_BROADCASTER.
    deal_side_ok = (
        offer["status"] == "MATCHED"
        or (offer["status"] == "OPEN" and offer["offer_source"] == "INCUMBENT_BROADCASTER")
    )
    if offer["status"] == "OPEN" and offer["offer_source"] == "THIRD_PARTY_BIDDER":
        # Exercisable only once the matching window has passed.
        if now() <= offer["matching_window_end"]:
            raise_error("ERR_MATCHING_WINDOW_ACTIVE")
        deal_side_ok = True
    if not deal_side_ok:
        raise_error("ERR_MATCHING_WINDOW_ACTIVE")

    # Cascade: deal RENEWAL_OPEN → RENEWED, term extended, base fee reset.
    offer["status"] = "EXERCISED"
    touch(offer)
    deal["status"] = "RENEWED"
    deal["term_end"] = deal["term_end"] + timedelta(days=365 * calc.RENEWAL_TERM_YEARS)
    deal["base_fee_cents"] = offer["offered_fee_cents"]
    deal["escalator_rate_pct"] = offer["escalator_rate_pct"]
    touch(deal)
    for other in db.renewal_offers.values():
        if other["deal_id"] == dealId and other["id"] != offer["id"] and other["status"] in ("OPEN", "MATCHED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    calc.recompute_all_allocations(deal)
    deal["total_contracted_fee_cents"] = calc.total_contracted_fee(deal)
    return success_object(serialize(offer))


@bp.route("/deals/<dealId>/renewal-offers/<offerId>/withdraw", methods=["POST"])
def withdraw_offer(dealId, offerId):
    user_id, _ = require_roles({"BidCoordinator"})
    offer = _get_offer_scoped(dealId, offerId)
    if offer["status"] != "OPEN":
        raise_error("ERR_INVALID_REQUEST", "Withdraw requires offer OPEN")
    if user_id != offer["offeror_broadcaster_id"]:
        raise_error("ERR_INSUFFICIENT_PERMISSIONS", "Only the offeror may withdraw")
    offer["status"] = "WITHDRAWN"
    touch(offer)
    return success_object(serialize(offer))


# --- Rights conflicts ----------------------------------------------------------

@bp.route("/rights-conflicts", methods=["GET"])
def list_conflicts():
    require_roles(ALL_ROLES)
    limit, offset = get_pagination()
    items = sorted_by_created(list(db.rights_conflicts.values()))
    items = apply_filters(items, [
        ("conflict_type", request.args.get("conflict_type")),
        ("left_entity_id", request.args.get("left_entity_id")),
        ("right_entity_id", request.args.get("right_entity_id")),
        ("asset_id", request.args.get("asset_id")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(c) for c in page], limit, offset, total)


@bp.route("/rights-conflicts/<conflictId>", methods=["GET"])
def get_conflict(conflictId):
    require_roles(ALL_ROLES)
    c = db.rights_conflicts.get(conflictId)
    if c is None:
        raise_error("ERR_RIGHTS_CONFLICT_NOT_FOUND")
    return success_object(serialize(c))
