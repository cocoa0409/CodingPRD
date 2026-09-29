"""LocationClaim endpoints (PRD section 3.5)."""

from flask import Blueprint

from db import db, new_record, parse_ts, serialize
from errors import ApiError
from middleware import authenticate, get_int, get_str, json_body
from records import touch
from response import object_response
from services import domain

bp = Blueprint("location_claims", __name__)

CLAIM_PROGRAM_STATES = ("CHALLENGE_OPEN", "CHALLENGE_CLOSED", "SCORING")


@bp.post("/broadband/location-claims")
def create_claim():
    user_id, _role = authenticate("Subgrantee")
    body = json_body()

    application_id = get_str(body, "application_id")
    location_id = get_str(body, "location_id")
    claimed_cost = get_int(body, "claimed_cost_cents", minimum=1)

    location = domain.require_location(location_id)                    # priority 21
    application = domain.require_application(application_id)           # priority 24
    program = domain.program_of_application(application)

    if user_id != application["subgrantee_id"]:                        # priority 30
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if program["program_state"] not in CLAIM_PROGRAM_STATES:            # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if application["application_state"] not in ("DRAFT", "RETURNED_FOR_CURE"):  # priority 43
        raise ApiError("ERR_APPLICATION_STATE_INVALID")
    if location["program_id"] != application["program_id"]:             # priority 61
        raise ApiError("ERR_PROGRAM_SCOPE_MISMATCH")

    new_start = parse_ts(application["proposed_construction_start"])
    new_end = parse_ts(application["proposed_construction_end"])
    for other in domain.claims_of_location(location["id"]):             # priority 69
        if other["claim_state"] == "RELEASED":
            continue
        if other["application_id"] == application["id"]:
            continue
        other_application = db.applications.get(other["application_id"])
        if other_application is None:
            continue
        other_start = parse_ts(other_application["proposed_construction_start"])
        other_end = parse_ts(other_application["proposed_construction_end"])
        if new_start < other_end and other_start < new_end:
            raise ApiError("ERR_LOCATION_CLAIM_WINDOW_CONFLICT")

    for other in domain.claims_of_application(application["id"]):       # priority 84
        if other["location_id"] == location["id"]:
            raise ApiError("ERR_DUPLICATE_LOCATION_ADDRESS")

    eligible = location["classification_status"] in ("UNSERVED", "UNDERSERVED")
    claim = new_record({
        "application_id": application["id"],
        "location_id": location["id"],
        "claimed_cost_cents": claimed_cost,
        "claim_state": "CLAIMED_ELIGIBLE" if eligible else "CLAIMED_INELIGIBLE",
        "is_ehcl": False,
        "match_share_cents": None,
    })
    db.claims[claim["id"]] = claim

    if domain.refresh_application(application):
        touch(application)
    return object_response(serialize(claim), 201)
