"""ScoreSheet endpoints (PRD section 3.6)."""

from flask import Blueprint

from db import db, new_record, serialize
from errors import ApiError
from middleware import authenticate, get_int, get_str, json_body
from records import assign, touch
from response import object_response
from services import calculations as calc
from services import domain

bp = Blueprint("score_sheets", __name__)


@bp.post("/broadband/score-sheets")
def create_score_sheet():
    user_id, _role = authenticate("ScoringOfficer")
    body = json_body()

    application_id = get_str(body, "application_id")
    expected_version = get_int(body, "expected_application_version")

    application = domain.require_application(application_id)           # priority 24
    program = domain.program_of_application(application)
    subgrantee = db.subgrantees.get(application["subgrantee_id"])

    if (subgrantee is not None                                         # priority 32
            and subgrantee.get("capability_reviewer_user_id")
            and subgrantee["capability_reviewer_user_id"] == user_id):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if program["program_state"] != "SCORING":                           # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if application["application_state"] not in ("SUBMITTED", "RESCORE_REQUIRED"):  # priority 43
        raise ApiError("ERR_APPLICATION_STATE_INVALID")
    if expected_version != int(application["version"]):                # priority 51
        raise ApiError("ERR_STALE_APPLICATION_VERSION")
    if subgrantee is None or subgrantee["capability_state"] != "QUALIFIED":  # priority 82
        raise ApiError("ERR_SUBGRANTEE_NOT_QUALIFIED")
    eligible_claims = [c for c in domain.claims_of_application(application["id"])
                       if c["claim_state"] == "CLAIMED_ELIGIBLE"]
    if not eligible_claims:                                            # priority 83
        raise ApiError("ERR_NO_ELIGIBLE_LOCATIONS")

    cost, speed, afford, workforce, multiplier, total = calc.application_total_score(
        application, subgrantee.get("capability_index"))

    for prior in domain.score_sheets_of_application(application["id"]):
        if prior["score_state"] in ("FINAL", "STALE"):
            assign(prior, "score_state", "SUPERSEDED")
            touch(prior)

    sheet = new_record({
        "application_id": application["id"],
        "scored_by_user_id": user_id,
        "cost_points": float(cost),
        "speed_points": float(speed),
        "affordability_points": float(afford),
        "workforce_points": float(workforce),
        "capability_multiplier": float(multiplier),
        "total_score": float(total),
        "basis_final_cost_per_location_cents": application["final_cost_per_location_cents"],
        "basis_confirmed_location_count": application["confirmed_location_count"],
        "score_state": "FINAL",
    })
    db.score_sheets[sheet["id"]] = sheet

    assign(application, "application_state", "SCORED")
    assign(application, "current_total_score", float(total))
    assign(application, "rescore_required_reason", None)
    touch(application)
    domain.refresh_program(program)
    return object_response(serialize(sheet), 201)
