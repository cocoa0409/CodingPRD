"""Permits, animal ambassadors and trail segments."""

from flask import Blueprint

import derive
import flows
from envelope import array_response, object_response
from errors import ApiError
from schema import (body_json, lookup, opt_int, opt_str, pagination, paginate,
                    query_enum, query_str, req_dt, req_enum, req_int, req_num,
                    req_str)
from security import authorize, naturalist_scope_self
from store import db, new_entity, public, set_dt, sorted_rows, touch

bp = Blueprint("stewardship", __name__)

AGENCIES = ("USFWS", "STATE_DNR", "USDA")
PERMIT_STATUSES = ("ACTIVE", "SUSPENDED", "LAPSED", "REVOKED")
PERMIT_TRANSITIONS = {
    "ACTIVE": ("SUSPENDED", "LAPSED", "REVOKED"),
    "SUSPENDED": ("ACTIVE",),
    "LAPSED": ("ACTIVE",),
    "REVOKED": (),
}
HANDLING_TIERS = ("TIER_1", "TIER_2")
CONTACT_RULES = ("NO_PUBLIC_CONTACT", "VIEW_ONLY", "SUPERVISED_TOUCH")
CARE_STATUSES = ("AVAILABLE", "RESTING", "VET_HOLD", "RETIRED")
CARE_TRANSITIONS = {
    "AVAILABLE": ("RESTING", "VET_HOLD", "RETIRED"),
    "RESTING": ("AVAILABLE", "RETIRED"),
    "VET_HOLD": ("AVAILABLE", "RETIRED"),
    "RETIRED": (),
}
POSTURES = ("OPEN", "RESTRICTED", "BLOCKED")
SENSITIVITIES = ("LOW", "MODERATE", "HIGH")
TRAIL_STATUSES = ("OPEN", "RESTORATION_REST", "CLOSED")
TRAIL_TRANSITIONS = {
    "OPEN": ("RESTORATION_REST", "CLOSED"),
    "RESTORATION_REST": ("OPEN",),
    "CLOSED": ("OPEN",),
}

ANIMAL_READERS = ("StewardshipManager", "EducationDirector", "BookingCoordinator", "Naturalist")


# ------------------------------------------------------------------ permits
@bp.post("/permits")
def create_permit():
    authorize(("StewardshipManager",))
    body = body_json()
    agency = req_enum(body, "agency", AGENCIES)
    permit_number = req_str(body, "permit_number")
    valid_from_raw, valid_from = req_dt(body, "valid_from")
    valid_to_raw, valid_to = req_dt(body, "valid_to")
    if valid_to <= valid_from:
        raise ApiError("ERR_INVALID_TIME_RANGE")

    permit = new_entity()
    permit.update({
        "agency": agency,
        "permit_number": permit_number,
        "status": "ACTIVE",
    })
    set_dt(permit, "valid_from", valid_from_raw, valid_from)
    set_dt(permit, "valid_to", valid_to_raw, valid_to)
    db.permits[permit["id"]] = permit
    derive.sync()
    return object_response(public(permit), 201)


@bp.get("/permits/<permit_id>")
def read_permit(permit_id):
    authorize(("StewardshipManager", "EducationDirector"))
    permit = lookup("permit", permit_id)
    return object_response(public(permit))


@bp.post("/permits/<permit_id>/set-status")
def set_permit_status(permit_id):
    authorize(("StewardshipManager",))
    body = body_json()
    target = req_enum(body, "status", PERMIT_STATUSES)
    opt_str(body, "note")
    permit = lookup("permit", permit_id)

    if target not in PERMIT_TRANSITIONS.get(permit["status"], ()):
        raise ApiError("ERR_INVALID_PERMIT_STATE")

    permit["status"] = target
    touch(permit)

    covered = [a for a in db.animals.values() if a["permit_id"] == permit["id"]]
    if target == "REVOKED":
        for animal in covered:
            if animal["status"] != "RETIRED":
                animal["status"] = "RETIRED"
                touch(animal)
            flows.release_bookings_for_animal(animal)
    elif target in ("SUSPENDED", "LAPSED"):
        for animal in covered:
            flows.release_bookings_for_animal(animal)
    derive.sync()
    return object_response(public(permit))


# ------------------------------------------------------------------ animals
@bp.post("/animals")
def create_animal():
    authorize(("StewardshipManager",))
    body = body_json()
    common_name = req_str(body, "common_name")
    species_code = req_str(body, "species_code")
    permit_id = req_str(body, "permit_id")
    handling_tier_required = req_enum(body, "handling_tier_required", HANDLING_TIERS)
    contact_rule = req_enum(body, "contact_rule", CONTACT_RULES)
    cap = req_int(body, "weekly_exposure_cap_minutes", high=1200)
    if cap <= 0:
        raise ApiError("ERR_INVALID_REQUEST")
    permit = lookup("permit", permit_id)

    animal = new_entity()
    animal.update({
        "common_name": common_name,
        "species_code": species_code,
        "permit_id": permit["id"],
        "handling_tier_required": handling_tier_required,
        "contact_rule": contact_rule,
        "weekly_exposure_cap_minutes": cap,
        "status": "AVAILABLE",
        "projected_exposure_minutes_7d": 0,
        "realized_exposure_minutes_7d": 0,
        "welfare_posture": "OPEN",
        "effective_contact_rule": contact_rule,
    })
    db.animals[animal["id"]] = animal
    derive.sync()
    return object_response(public(animal), 201)


@bp.get("/animals")
def list_animals():
    actor = authorize(ANIMAL_READERS)
    limit, offset = pagination()
    permit_id = query_str("permit_id")
    status = query_enum("status", CARE_STATUSES)
    posture = query_enum("welfare_posture", POSTURES)
    naturalist_scope_self(actor)

    rows = sorted_rows(db.animals.values())
    if permit_id is not None:
        rows = [r for r in rows if r["permit_id"] == permit_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if posture is not None:
        rows = [r for r in rows if r["welfare_posture"] == posture]
    page, total = paginate(rows, limit, offset)
    return array_response([public(r) for r in page], limit, offset, total)


@bp.get("/animals/<animal_id>")
def read_animal(animal_id):
    actor = authorize(ANIMAL_READERS)
    animal = lookup("animal", animal_id)
    naturalist_scope_self(actor)
    return object_response(public(animal))


@bp.post("/animals/<animal_id>/set-care-status")
def set_care_status(animal_id):
    authorize(("StewardshipManager",))
    body = body_json()
    target = req_enum(body, "status", CARE_STATUSES)
    opt_str(body, "note")
    animal = lookup("animal", animal_id)

    if target not in CARE_TRANSITIONS.get(animal["status"], ()):
        raise ApiError("ERR_INVALID_ANIMAL_STATE")

    animal["status"] = target
    touch(animal)
    if target in ("VET_HOLD", "RETIRED"):
        flows.release_bookings_for_animal(animal)
    derive.sync()
    return object_response(public(animal))


# ----------------------------------------------------------- trail segments
@bp.post("/trail-segments")
def create_trail():
    authorize(("StewardshipManager",))
    body = body_json()
    name = req_str(body, "name")
    capacity_persons = req_int(body, "capacity_persons", 1, 400)
    habitat_sensitivity = req_enum(body, "habitat_sensitivity", SENSITIVITIES)
    weekly_budget = req_int(body, "weekly_visitor_budget_persons", 1, 5000)
    recovery_buffer = opt_int(body, "recovery_buffer_minutes", 0, 240, 30)

    trail = new_entity()
    trail.update({
        "name": name,
        "capacity_persons": capacity_persons,
        "habitat_sensitivity": habitat_sensitivity,
        "weekly_visitor_budget_persons": weekly_budget,
        "recovery_buffer_minutes": recovery_buffer,
        "status": "OPEN",
        "visitors_this_week": 0,
    })
    db.trails[trail["id"]] = trail
    derive.sync()
    return object_response(public(trail), 201)


@bp.get("/trail-segments/<trail_id>")
def read_trail(trail_id):
    authorize(("StewardshipManager", "EducationDirector", "BookingCoordinator"))
    trail = lookup("trail", trail_id)
    return object_response(public(trail))


@bp.post("/trail-segments/<trail_id>/set-status")
def set_trail_status(trail_id):
    authorize(("StewardshipManager",))
    body = body_json()
    target = req_enum(body, "status", TRAIL_STATUSES)
    opt_str(body, "note")
    trail = lookup("trail", trail_id)

    if target not in TRAIL_TRANSITIONS.get(trail["status"], ()):
        raise ApiError("ERR_INVALID_TRAIL_STATE")

    trail["status"] = target
    touch(trail)
    if target == "CLOSED":
        flows.release_bookings_for_trail(trail)
    derive.sync()
    return object_response(public(trail))
