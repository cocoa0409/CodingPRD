"""Offer endpoints: OCC-guarded create, negotiation cycle, acceptance, rescind."""
from flask import g

import db
import domain
from domain import offer_json, sort_entities, TERMINAL_LIFECYCLE, PENDING_OFFER_STATES, ROLE_RANK
from envelope import success
from errors import ApiError
from routes.common import (require_roles, body, req_str, req_num, opt_num, req_int, req_enum,
                           paginate, get_or_404)
from routes.properties import ALL_ROLES, request_arg

FINANCING_TYPES = ("CASH", "SELLER_FINANCED")


def create_offer():
    require_roles("OREOSpecialist")
    d = body()
    property_id = req_str(d, "property_id")
    buyer_name = req_str(d, "buyer_name")
    offer_price = req_num(d, "offer_price")
    if offer_price <= 0:
        raise ApiError("ERR_VALIDATION", 400, "offer_price must be greater than 0")
    financing_type = req_enum(d, "financing_type", FINANCING_TYPES)
    earnest_money = req_num(d, "earnest_money")
    if earnest_money < 0:
        raise ApiError("ERR_VALIDATION", 400, "earnest_money must be zero or greater")
    expected_version = req_int(d, "expected_property_version")
    listing_agreement_id = None
    if "listing_agreement_id" in d and d["listing_agreement_id"] is not None:
        listing_agreement_id = req_str(d, "listing_agreement_id")
    down_payment = opt_num(d, "down_payment")
    if financing_type == "SELLER_FINANCED":
        if down_payment is None:
            raise ApiError("ERR_VALIDATION", 400,
                           "down_payment is required for SELLER_FINANCED offers")
        if down_payment <= 0 or down_payment >= offer_price:
            raise ApiError("ERR_VALIDATION", 400,
                           "down_payment must be greater than 0 and less than offer_price")
    else:
        down_payment = None
    p = get_or_404(db.properties, property_id, "Property")
    listing = None
    if listing_agreement_id is not None:
        listing = get_or_404(db.listings, listing_agreement_id, "Listing agreement")
    if expected_version != p["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_property_version does not match the property's current version")
    if p["lifecycle_status"] in TERMINAL_LIFECYCLE:
        raise ApiError("ERR_PROPERTY_ALREADY_TERMINAL", 409, "Property is terminal")
    if p["lifecycle_status"] != "MARKETED":
        raise ApiError("ERR_PROPERTY_NOT_MARKETABLE", 409,
                       "Offer creation requires the property to be MARKETED")
    if domain.appraisal_status(p) not in ("CURRENT", "DUE_SOON"):
        raise ApiError("ERR_APPRAISAL_OVERDUE", 409,
                       "Property appraisal is UNAPPRAISED or OVERDUE")
    if listing is not None and (listing["status"] != "ACTIVE" or listing["property_id"] != property_id):
        raise ApiError("ERR_LISTING_NOT_ACTIVE", 409,
                       "Referenced listing agreement is not ACTIVE on this property")
    o = domain.base_entity()
    o.update({
        "property_id": property_id,
        "listing_agreement_id": listing_agreement_id,
        "buyer_name": buyer_name,
        "offer_price": offer_price,
        "financing_type": financing_type,
        "down_payment": down_payment,
        "earnest_money": earnest_money,
        "status": "RECEIVED",
        "current_price": offer_price,
        "counter_round": 0,
        "rejection_reason": None,
    })
    db.offers[o["id"]] = o
    domain.bump(p)
    return success(offer_json(o), 201)


def list_offers():
    require_roles(*ALL_ROLES)
    pid = request_arg("property_id")
    lid = request_arg("listing_agreement_id")
    status = request_arg("status")
    ftype = request_arg("financing_type")
    items = [o for o in db.offers.values()
             if (pid is None or o["property_id"] == pid)
             and (lid is None or o["listing_agreement_id"] == lid)
             and (status is None or o["status"] == status)
             and (ftype is None or o["financing_type"] == ftype)]
    return paginate(sort_entities(items), offer_json)


def get_offer(entity_id):
    require_roles(*ALL_ROLES)
    return success(offer_json(get_or_404(db.offers, entity_id, "Offer")))


def _offer_in_states(o, states):
    if o["status"] not in states:
        raise ApiError("ERR_OFFER_NOT_REVIEWABLE", 409,
                       "Offer is in status %s, not legal for this action" % o["status"])


def submit_review(entity_id):
    require_roles("OREOSpecialist")
    o = get_or_404(db.offers, entity_id, "Offer")
    _offer_in_states(o, ("RECEIVED",))
    o["status"] = "UNDER_REVIEW"
    domain.bump(o)
    return success(offer_json(o), 200)


def counter_offer(entity_id):
    require_roles("OREOSpecialist")
    d = body()
    counter_price = req_num(d, "counter_price")
    if counter_price <= 0:
        raise ApiError("ERR_VALIDATION", 400, "counter_price must be greater than 0")
    o = get_or_404(db.offers, entity_id, "Offer")
    _offer_in_states(o, ("UNDER_REVIEW",))
    o["status"] = "COUNTERED"
    o["current_price"] = counter_price
    o["counter_round"] += 1
    domain.bump(o)
    return success(offer_json(o), 200)


def resume_offer(entity_id):
    require_roles("OREOSpecialist")
    o = get_or_404(db.offers, entity_id, "Offer")
    _offer_in_states(o, ("COUNTERED",))
    o["status"] = "UNDER_REVIEW"
    domain.bump(o)
    return success(offer_json(o), 200)


def accept_offer(entity_id):
    require_roles("OREOSpecialist", "CreditOfficer", "OREOCommittee")
    o = get_or_404(db.offers, entity_id, "Offer")
    _offer_in_states(o, ("UNDER_REVIEW", "COUNTERED"))
    p = db.properties[o["property_id"]]
    if p["lifecycle_status"] in TERMINAL_LIFECYCLE:
        raise ApiError("ERR_PROPERTY_ALREADY_TERMINAL", 409, "Property is terminal")
    if p["lifecycle_status"] != "MARKETED":
        raise ApiError("ERR_PROPERTY_NOT_MARKETABLE", 409,
                       "Offer acceptance requires the property to be MARKETED")
    if domain.appraisal_status(p) not in ("CURRENT", "DUE_SOON"):
        raise ApiError("ERR_APPRAISAL_OVERDUE", 409,
                       "Property appraisal is UNAPPRAISED or OVERDUE")
    env_open, _ = domain.issue_counts(p["id"])
    if env_open > 0:
        raise ApiError("ERR_ENVIRONMENTAL_ISSUE_OPEN", 409,
                       "An open environmental issue blocks offer acceptance")
    # Fiscal gates, in declared sub-order.
    if domain.pending_wd_count(p["id"]) > 0:
        raise ApiError("ERR_WRITE_DOWN_PENDING", 409,
                       "A PROPOSED write-down on the property blocks acceptance")
    net, _commission = domain.net_proceeds_of(o["current_price"], p["property_type"], o["financing_type"])
    if net <= 0:
        raise ApiError("ERR_BELOW_MIN_PROCEEDS", 422, "Projected net_proceeds must be greater than 0")
    carrying = domain.carrying_value(p)
    required_rank = domain.required_rank_for(net, carrying)
    caller_rank = ROLE_RANK[g.user_role]
    if caller_rank < required_rank:
        raise ApiError("ERR_APPROVAL_AUTHORITY_EXCEEDED", 403,
                       "Caller rank %d is below required rank %d" % (caller_rank, required_rank))
    o["status"] = "ACCEPTED"
    domain.bump(o)
    for l in db.listings.values():
        if l["property_id"] == p["id"] and l["status"] == "ACTIVE":
            l["status"] = "TERMINATED"
            l["termination_reason"] = "UNDER_CONTRACT"
            domain.bump(l)
    for other in db.offers.values():
        if other["id"] != o["id"] and other["property_id"] == p["id"] \
                and other["status"] in PENDING_OFFER_STATES:
            other["status"] = "REJECTED"
            other["rejection_reason"] = "SUPERSEDED"
            domain.bump(other)
    p["lifecycle_status"] = "UNDER_CONTRACT"
    domain.bump(p)
    return success(offer_json(o), 200)


def reject_offer(entity_id):
    require_roles("OREOSpecialist", "CreditOfficer")
    o = get_or_404(db.offers, entity_id, "Offer")
    _offer_in_states(o, PENDING_OFFER_STATES)
    o["status"] = "REJECTED"
    o["rejection_reason"] = "MANUAL"
    domain.bump(o)
    return success(offer_json(o), 200)


def withdraw_offer(entity_id):
    require_roles("OREOSpecialist")
    o = get_or_404(db.offers, entity_id, "Offer")
    _offer_in_states(o, PENDING_OFFER_STATES)
    o["status"] = "WITHDRAWN"
    domain.bump(o)
    return success(offer_json(o), 200)


def rescind_offer(entity_id):
    require_roles("OREOSpecialist", "CreditOfficer")
    o = get_or_404(db.offers, entity_id, "Offer")
    if o["status"] != "ACCEPTED":
        raise ApiError("ERR_OFFER_NOT_ACCEPTED", 409, "Only an ACCEPTED offer can be rescinded")
    blocking = any(c["offer_id"] == o["id"] and c["status"] in ("DRAFT", "SETTLED")
                   for c in db.closings.values())
    if blocking:
        raise ApiError("ERR_CLOSING_INVALID_STATE", 409,
                       "A DRAFT or SETTLED closing statement exists for this offer")
    o["status"] = "RESCINDED"
    domain.bump(o)
    p = db.properties[o["property_id"]]
    p["lifecycle_status"] = "MARKETED"
    domain.bump(p)
    return success(offer_json(o), 200)
