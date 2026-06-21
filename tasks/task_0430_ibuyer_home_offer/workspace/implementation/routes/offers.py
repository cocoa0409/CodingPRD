"""Offer endpoints: fetch, accept, decline, assessment lookup (PRD §3.3-§3.4)."""

from flask import Blueprint, request

from db import store
from errors import err
from helpers import (
    get_offer_or_404,
    pagination_params,
    paginate,
    require_property_owner,
)
from middleware import authenticate, require_role
from models import serialize, stamp_create, touch
from response import array_response, object_response

bp = Blueprint("offers", __name__)


@bp.route("/offers/<offer_id>", methods=["GET"])
def get_offer(offer_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst", "Seller"})
    rec = get_offer_or_404(offer_id)
    return object_response(serialize(rec), 200)


@bp.route("/offers/<offer_id>/accept", methods=["POST"])
def accept_offer(offer_id):
    uid, role = authenticate()
    require_role(role, {"Seller"})
    offer = get_offer_or_404(offer_id)
    prop = store.properties[offer["property_id"]]

    # Ownership (priority 4)
    require_property_owner(prop, role, uid)

    # State (priority 5): offer ISSUED, property UNDER_OFFER and active_offer_id == this
    if (
        offer["status"] != "ISSUED"
        or prop["status"] != "UNDER_OFFER"
        or prop["active_offer_id"] != offer["id"]
    ):
        raise err("ERR_INVALID_STATE", "Offer not in an acceptable state")

    # Expiry (priority 6): clock must be strictly before expires_at
    if store.now() >= offer["expires_at"]:
        raise err("ERR_OFFER_EXPIRED", "Offer has expired")

    # Transition
    offer["status"] = "ACCEPTED"
    touch(offer)
    prop["status"] = "IN_TRANSACTION"
    touch(prop)

    # Spawn Assessment (DRAFT) bound to the offer
    assessment = {
        "offer_id": offer["id"],
        "roof_condition": None,
        "hvac_condition": None,
        "foundation_condition": None,
        "questionnaire_flags": [],
        "condition_score": None,
        "status": "DRAFT",
    }
    stamp_create(assessment)
    store.assessments[assessment["id"]] = assessment

    # Spawn Transaction (PENDING_ASSESSMENT)
    tx = {
        "offer_id": offer["id"],
        "property_id": prop["id"],
        "repair_credit": 0.0,
        "final_concession": 0.0,
        "retrade_amount": 0.0,
        "close_date": None,
        "leaseback_days": 0,
        "leaseback_daily_rate": 0.0,
        "leaseback_total": 0.0,
        "final_net_proceeds": 0.0,
        "status": "PENDING_ASSESSMENT",
    }
    stamp_create(tx)
    store.transactions[tx["id"]] = tx

    return object_response(serialize(tx), 200)


@bp.route("/offers/<offer_id>/decline", methods=["POST"])
def decline_offer(offer_id):
    uid, role = authenticate()
    require_role(role, {"Seller"})
    offer = get_offer_or_404(offer_id)
    prop = store.properties[offer["property_id"]]
    require_property_owner(prop, role, uid)

    # Must be ISSUED to decline/expire (priority 5)
    if offer["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Offer is not ISSUED")

    # Lazy expiry: if clock >= expires_at, report expiry; else explicit decline.
    if store.now() >= offer["expires_at"]:
        offer["status"] = "EXPIRED"
    else:
        offer["status"] = "DECLINED"
    touch(offer)

    # If this was the property's active offer, clear it and return property to VALUED.
    if prop["active_offer_id"] == offer["id"]:
        prop["active_offer_id"] = None
        prop["status"] = "VALUED"
        touch(prop)

    return object_response(serialize(offer), 200)


@bp.route("/offers/<offer_id>/assessment", methods=["GET"])
def get_offer_assessment(offer_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst", "Seller"})
    get_offer_or_404(offer_id)
    records = [a for a in store.assessments.values() if a["offer_id"] == offer_id]
    limit, offset = pagination_params()
    page, total = paginate(records, limit, offset)
    return array_response([serialize(r) for r in page], limit, offset, total)
