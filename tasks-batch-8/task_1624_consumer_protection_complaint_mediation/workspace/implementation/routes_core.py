"""Core routes: logical clock, consumers, businesses (directory, rating,
statistics, rating-method), mediators, mediation rooms."""

from decimal import Decimal

from flask import Blueprint, request

import domain
from domain import (
    business_view, consumer_view, mediator_view, recompute_rating, room_view,
    run_clock_sweep,
)
from helpers import (
    auth, fail, fmt_clock, json_body, list_response, new_record, ok_object,
    opt_enum, opt_int, opt_string, opt_string_list, parse_datetime_iso,
    req_enum, req_int, req_string, round_half_up_int, touch,
)
from store import db

bp = Blueprint("core", __name__)

ALL = (
    "Anonymous", "Consumer", "Business", "IntakeOfficer", "Mediator",
    "EnforcementAttorney", "UnitDirector",
)
STAFF = ("IntakeOfficer", "Mediator", "EnforcementAttorney", "UnitDirector")


# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.6)
# ---------------------------------------------------------------------------

@bp.post("/consumer-protection/_clock/set_current_utc")
def set_clock():
    auth("UnitDirector")
    data = json_body()
    to = data.get("to_iso8601")
    if to is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 is required and must be an ISO 8601 timestamp")
    db.now = parse_datetime_iso(to, "to_iso8601")
    run_clock_sweep()
    return ok_object({"current_utc": fmt_clock(db.now)})


# ---------------------------------------------------------------------------
# Consumers (PRD section 3.1)
# ---------------------------------------------------------------------------

@bp.post("/consumer-protection/consumers")
def create_consumer():
    auth("Anonymous")
    data = json_body()
    full_name = req_string(data, "full_name")
    email = req_string(data, "email")
    state_code = req_string(data, "state_code")
    phone = opt_string(data, "phone")
    for c in db.consumers.values():
        if c["email"] == email:
            fail("ERR_UNIQUENESS_VIOLATION", "email is already registered")
    rec = new_record()
    rec.update({
        "full_name": full_name,
        "email": email,
        "state_code": state_code,
        "phone": phone,
    })
    db.consumers[rec["id"]] = rec
    return ok_object(consumer_view(rec), 201)


@bp.get("/consumer-protection/consumers/<consumerId>")
def get_consumer(consumerId):
    uid = auth("Consumer", "IntakeOfficer", "Mediator", "EnforcementAttorney", "UnitDirector")
    # Ownership (priority 3): a Consumer caller reads only its own record.
    if request.headers.get("X-User-Role") == "Consumer" and consumerId != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "Consumer callers read only their own record")
    rec = db.consumers.get(consumerId)
    if rec is None:
        fail("ERR_CONSUMER_NOT_FOUND", "consumer does not exist")
    return ok_object(consumer_view(rec))


# ---------------------------------------------------------------------------
# Businesses (PRD sections 3.1 / 3.9)
# ---------------------------------------------------------------------------

@bp.post("/consumer-protection/businesses")
def create_business():
    auth("Anonymous")
    data = json_body()
    legal_name = req_string(data, "legal_name")
    home_state = req_string(data, "home_state")
    operates_in_states = data.get("operates_in_states")
    if not isinstance(operates_in_states, list) or any(
        not isinstance(x, str) for x in operates_in_states
    ):
        fail("ERR_INVALID_REQUEST", "operates_in_states is required and must be an array of strings")
    naics_code = req_string(data, "naics_code")
    dba_name = opt_string(data, "dba_name")
    size_tier = opt_enum(data, "size_tier", domain.SIZE_TIERS, "SMALL")
    rating_method = opt_enum(data, "rating_method", domain.RATING_METHODS, "LIFETIME")
    for b in db.businesses.values():
        if b["legal_name"] == legal_name and b["home_state"] == home_state:
            fail("ERR_UNIQUENESS_VIOLATION", "legal_name already registered in home_state")
    rec = new_record()
    rec.update({
        "legal_name": legal_name,
        "dba_name": dba_name,
        "home_state": home_state,
        "operates_in_states": list(operates_in_states),
        "naics_code": naics_code,
        "size_tier": size_tier,
        "rating_method": rating_method,
        "watch_status": "CLEAR",
        "pattern_score": 0,
        "published_complaint_count": 0,
        "rating_score": 100,
        "rating_tier": "A",
        "overdue_response_count": 0,
        "next_filing_seq": 1,
    })
    db.businesses[rec["id"]] = rec
    return ok_object(business_view(rec), 201)


@bp.get("/consumer-protection/businesses")
def list_businesses():
    auth(*ALL)
    return list_response(list(db.businesses.values()), business_view)


def _get_business(businessId):
    rec = db.businesses.get(businessId)
    if rec is None:
        fail("ERR_BUSINESS_NOT_FOUND", "business does not exist")
    return rec


@bp.get("/consumer-protection/businesses/<businessId>")
def get_business(businessId):
    auth(*ALL)
    return ok_object(business_view(_get_business(businessId)))


@bp.post("/consumer-protection/businesses/<businessId>/rating-method")
def switch_rating_method(businessId):
    auth("UnitDirector")
    rec = _get_business(businessId)
    data = json_body()
    method = req_enum(data, "rating_method", domain.RATING_METHODS)
    rec["rating_method"] = method
    touch(rec)
    recompute_rating(rec)
    return ok_object(business_view(rec))


@bp.get("/consumer-protection/businesses/<businessId>/rating")
def get_rating(businessId):
    auth(*ALL)
    rec = _get_business(businessId)
    return ok_object({
        "rating_score": rec["rating_score"],
        "rating_tier": rec["rating_tier"],
        "rating_method": rec["rating_method"],
        "published_complaint_count": rec["published_complaint_count"],
        "pattern_score": rec["pattern_score"],
        "watch_status": rec["watch_status"],
    })


@bp.get("/consumer-protection/businesses/<businessId>/complaint-statistics")
def get_complaint_statistics(businessId):
    auth(*ALL)
    rec = _get_business(businessId)
    published = [
        c for c in db.complaints.values()
        if c["business_id"] == rec["id"] and c["publication_status"] == "PUBLISHED"
    ]
    total = len(published)
    settled = sum(1 for c in published if c["case_status"] == "SETTLED")
    unresolved = sum(1 for c in published if c["case_status"] == "CLOSED_UNRESOLVED")
    referred = sum(1 for c in published if c["case_status"] == "REFERRED_ENFORCEMENT")
    if total:
        days = sum((c["closed_at"] - c["filed_at"]).days for c in published)
        avg = round_half_up_int(Decimal(days) / Decimal(total))
    else:
        avg = 0
    return ok_object({
        "published_total": total,
        "settled_count": settled,
        "unresolved_count": unresolved,
        "referred_count": referred,
        "average_days_to_close": avg,
    })


# ---------------------------------------------------------------------------
# Mediators (PRD section 3.1)
# ---------------------------------------------------------------------------

@bp.post("/consumer-protection/mediators")
def create_mediator():
    auth("UnitDirector")
    data = json_body()
    full_name = req_string(data, "full_name")
    employee_ref = req_string(data, "employee_ref")
    max_concurrent_cases = opt_int(data, "max_concurrent_cases", 10)
    conflicted_business_ids = opt_string_list(data, "conflicted_business_ids", [])
    for m in db.mediators.values():
        if m["employee_ref"] == employee_ref:
            fail("ERR_UNIQUENESS_VIOLATION", "employee_ref is already registered")
    rec = new_record()
    rec.update({
        "full_name": full_name,
        "employee_ref": employee_ref,
        "mediator_status": "ACTIVE",
        "conflicted_business_ids": list(conflicted_business_ids),
        "max_concurrent_cases": max_concurrent_cases,
        "active_case_count": 0,
    })
    db.mediators[rec["id"]] = rec
    return ok_object(mediator_view(rec), 201)


def _get_mediator(mediatorId):
    rec = db.mediators.get(mediatorId)
    if rec is None:
        fail("ERR_MEDIATOR_NOT_FOUND", "mediator does not exist")
    return rec


@bp.get("/consumer-protection/mediators/<mediatorId>")
def get_mediator(mediatorId):
    auth("Mediator", "IntakeOfficer", "EnforcementAttorney", "UnitDirector")
    return ok_object(mediator_view(_get_mediator(mediatorId)))


@bp.post("/consumer-protection/mediators/<mediatorId>/deactivate")
def deactivate_mediator(mediatorId):
    auth("UnitDirector")
    rec = _get_mediator(mediatorId)
    if rec["mediator_status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "mediator is not ACTIVE")
    rec["mediator_status"] = "INACTIVE"
    touch(rec)
    return ok_object(mediator_view(rec))


# ---------------------------------------------------------------------------
# Mediation rooms (PRD section 3.1)
# ---------------------------------------------------------------------------

@bp.get("/consumer-protection/mediation-rooms")
def list_rooms():
    auth("Mediator", "IntakeOfficer", "UnitDirector")
    return list_response(list(db.rooms.values()), room_view)


@bp.post("/consumer-protection/mediation-rooms")
def create_room():
    auth("UnitDirector")
    data = json_body()
    room_name = req_string(data, "room_name")
    capacity = req_int(data, "capacity")
    location = req_string(data, "location")
    for r in db.rooms.values():
        if r["room_name"] == room_name:
            fail("ERR_UNIQUENESS_VIOLATION", "room_name is already registered")
    rec = new_record()
    rec.update({
        "room_name": room_name,
        "capacity": capacity,
        "location": location,
        "room_status": "OPERATIONAL",
    })
    db.rooms[rec["id"]] = rec
    return ok_object(room_view(rec), 201)


def _get_room(roomId):
    rec = db.rooms.get(roomId)
    if rec is None:
        fail("ERR_ROOM_NOT_FOUND", "room does not exist")
    return rec


@bp.get("/consumer-protection/mediation-rooms/<roomId>")
def get_room(roomId):
    auth("Mediator", "IntakeOfficer", "UnitDirector")
    return ok_object(room_view(_get_room(roomId)))


@bp.post("/consumer-protection/mediation-rooms/<roomId>/take-out-of-service")
def take_room_out_of_service(roomId):
    auth("UnitDirector")
    rec = _get_room(roomId)
    if rec["room_status"] != "OPERATIONAL":
        fail("ERR_INVALID_STATE", "room is not OPERATIONAL")
    rec["room_status"] = "OUT_OF_SERVICE"
    touch(rec)
    return ok_object(room_view(rec))
