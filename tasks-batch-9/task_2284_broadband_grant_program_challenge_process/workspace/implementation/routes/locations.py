"""EligibleLocation endpoints (PRD section 3.1)."""

from flask import Blueprint, request

from db import db, new_record, serialize
from errors import ApiError
from middleware import (authenticate, get_enum, get_int, get_number, get_str,
                        json_body, pagination)
from response import object_response
from routes.listing import paginated
from services import calculations as calc
from services import domain

bp = Blueprint("locations", __name__)

READ_ROLES = ("ProgramAdmin", "EligibilityAnalyst", "ScoringOfficer", "AuditOfficer",
              "Subgrantee", "Challenger", "Provider")
CLAIM_READ_ROLES = ("ProgramAdmin", "EligibilityAnalyst", "ScoringOfficer", "AuditOfficer")


@bp.post("/broadband/locations")
def create_location():
    authenticate("ProgramAdmin", "EligibilityAnalyst")
    body = json_body()

    program_id = get_str(body, "program_id")
    address_id = get_str(body, "address_id")
    down = get_number(body, "reported_down_mbps", minimum=0)
    up = get_number(body, "reported_up_mbps", minimum=0)
    latency = get_int(body, "reported_latency_ms", minimum=0)
    technology = get_enum(body, "reported_technology", calc.TECHNOLOGIES)
    provider_id = get_str(body, "reporting_provider_user_id")

    program = domain.require_program(program_id)                      # priority 20
    if program["program_state"] not in ("DRAFT", "CHALLENGE_OPEN"):   # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    for existing in db.locations.values():                            # priority 84
        if existing["program_id"] == program["id"] and existing["address_id"] == address_id:
            raise ApiError("ERR_DUPLICATE_LOCATION_ADDRESS")

    classification = calc.classify_location(program, technology, down, up, latency)
    location = new_record({
        "program_id": program["id"],
        "address_id": address_id,
        "reported_down_mbps": down,
        "reported_up_mbps": up,
        "reported_latency_ms": latency,
        "reported_technology": technology,
        "reporting_provider_user_id": provider_id,
        "classification_status": classification,
        "classification_source": "NATIONAL_MAP",
        "eligibility_state": "MAPPED",
        "service_state": "NOT_BUILT",
        "awarded_award_id": None,
        "challenge_count": 0,
        "certified_at": None,
    })
    db.locations[location["id"]] = location
    domain.refresh_program(program)
    return object_response(serialize(location), 201)


@bp.get("/broadband/locations/<location_id>")
def get_location(location_id):
    authenticate(*READ_ROLES)
    location = domain.require_location(location_id)
    return object_response(serialize(location))


@bp.get("/broadband/locations")
def list_locations():
    authenticate(*READ_ROLES)
    limit, offset = pagination()
    rows = list(db.locations.values())
    for field in ("program_id", "classification_status", "eligibility_state",
                  "service_state", "awarded_award_id"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r.get(field) == wanted]
    return paginated(rows, limit, offset)


@bp.get("/broadband/locations/<location_id>/location-claims")
def list_location_claims(location_id):
    authenticate(*CLAIM_READ_ROLES)
    limit, offset = pagination()
    location = domain.require_location(location_id)
    return paginated(domain.claims_of_location(location["id"]), limit, offset)
