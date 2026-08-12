"""ListingAgreement endpoints: draft creation, activation gates, termination."""
import db
import domain
from domain import listing_json, sort_entities, TERMINAL_LIFECYCLE
from envelope import success
from errors import ApiError
from routes.common import (require_roles, body, req_str, req_num, req_date, paginate, get_or_404)
from routes.properties import ALL_ROLES, request_arg
from util import pdate


def _broker_eligible(b, p):
    return b["status"] == "ACTIVE" and p["state_code"] in b["coverage_states"]


def create_listing():
    require_roles("PropertyManager", "OREOSpecialist")
    d = body()
    property_id = req_str(d, "property_id")
    broker_id = req_str(d, "broker_id")
    start_date = req_date(d, "start_date")
    end_date = req_date(d, "end_date")
    listing_price = req_num(d, "listing_price")
    start = pdate(start_date)
    end = pdate(end_date)
    if end <= start:
        raise ApiError("ERR_VALIDATION", 400, "end_date must be after start_date")
    p = get_or_404(db.properties, property_id, "Property")
    b = get_or_404(db.brokers, broker_id, "Broker")
    if p["lifecycle_status"] in TERMINAL_LIFECYCLE:
        raise ApiError("ERR_PROPERTY_ALREADY_TERMINAL", 409, "Property is terminal")
    # Half-open [start, end) overlap against DRAFT/ACTIVE agreements; adjacency allowed.
    for l in db.listings.values():
        if l["property_id"] != property_id or l["status"] not in ("DRAFT", "ACTIVE"):
            continue
        if start < pdate(l["end_date"]) and pdate(l["start_date"]) < end:
            raise ApiError("ERR_LISTING_OVERLAP", 409,
                           "Listing interval overlaps an existing DRAFT/ACTIVE agreement")
    if not _broker_eligible(b, p):
        raise ApiError("ERR_BROKER_NOT_ELIGIBLE", 422,
                       "Broker is SUSPENDED or does not cover the property's state")
    l = domain.base_entity()
    l.update({
        "property_id": property_id,
        "broker_id": broker_id,
        "start_date": start_date,
        "end_date": end_date,
        "listing_price": listing_price,
        "status": "DRAFT",
        "termination_reason": None,
    })
    db.listings[l["id"]] = l
    return success(listing_json(l), 201)


def list_listings():
    require_roles(*ALL_ROLES)
    pid = request_arg("property_id")
    bid = request_arg("broker_id")
    status = request_arg("status")
    items = [l for l in db.listings.values()
             if (pid is None or l["property_id"] == pid)
             and (bid is None or l["broker_id"] == bid)
             and (status is None or l["status"] == status)]
    return paginate(sort_entities(items), listing_json)


def get_listing(entity_id):
    require_roles(*ALL_ROLES)
    return success(listing_json(get_or_404(db.listings, entity_id, "Listing agreement")))


def activate_listing(entity_id):
    require_roles("OREOSpecialist")
    l = get_or_404(db.listings, entity_id, "Listing agreement")
    if l["status"] != "DRAFT":
        raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "Only a DRAFT listing can be activated")
    p = db.properties[l["property_id"]]
    if p["lifecycle_status"] in TERMINAL_LIFECYCLE:
        raise ApiError("ERR_PROPERTY_ALREADY_TERMINAL", 409, "Property is terminal")
    if p["lifecycle_status"] != "HELD":
        raise ApiError("ERR_PROPERTY_NOT_MARKETABLE", 409,
                       "Listing activation requires the property to be HELD")
    if domain.appraisal_status(p) not in ("CURRENT", "DUE_SOON"):
        raise ApiError("ERR_APPRAISAL_OVERDUE", 409,
                       "Property appraisal is UNAPPRAISED or OVERDUE")
    env_open, _ = domain.issue_counts(p["id"])
    if env_open > 0:
        raise ApiError("ERR_ENVIRONMENTAL_ISSUE_OPEN", 409,
                       "An open environmental issue blocks listing activation")
    b = db.brokers[l["broker_id"]]
    if not _broker_eligible(b, p):
        raise ApiError("ERR_BROKER_NOT_ELIGIBLE", 422,
                       "Broker is SUSPENDED or does not cover the property's state")
    l["status"] = "ACTIVE"
    domain.bump(l)
    p["lifecycle_status"] = "MARKETED"
    domain.bump(p)
    return success(listing_json(l), 200)


def terminate_listing(entity_id):
    require_roles("OREOSpecialist")
    l = get_or_404(db.listings, entity_id, "Listing agreement")
    if l["status"] != "ACTIVE":
        raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "Only an ACTIVE listing can be terminated")
    l["status"] = "TERMINATED"
    l["termination_reason"] = "MANUAL"
    domain.bump(l)
    p = db.properties[l["property_id"]]
    if domain.active_listing_count(p["id"]) == 0 and p["lifecycle_status"] == "MARKETED":
        p["lifecycle_status"] = "HELD"
    domain.bump(p)
    return success(listing_json(l), 200)
