"""Application endpoints (PRD section 3.5)."""

from flask import Blueprint, request

from db import db, new_record, parse_ts, serialize
from errors import ApiError
from middleware import (authenticate, get_bool, get_cents, get_int, get_number,
                        get_pct, get_str, get_ts, json_body, pagination)
from records import assign, touch
from response import object_response
from routes.listing import paginated
from services import calculations as calc
from services import domain

bp = Blueprint("applications", __name__)

READ_ROLES = ("ProgramAdmin", "ScoringOfficer", "CapabilityReviewer", "AuditOfficer", "Subgrantee")
CLAIM_READ_ROLES = ("ProgramAdmin", "ScoringOfficer", "AuditOfficer", "Subgrantee")
SHEET_READ_ROLES = ("ProgramAdmin", "ScoringOfficer", "AuditOfficer")
AWARD_READ_ROLES = ("ProgramAdmin", "ScoringOfficer", "AuditOfficer", "Subgrantee")
APPLICATION_PROGRAM_STATES = ("CHALLENGE_OPEN", "CHALLENGE_CLOSED", "SCORING")


@bp.post("/broadband/applications")
def create_application():
    user_id, role = authenticate("Subgrantee", "ProgramAdmin")
    body = json_body()

    program_id = get_str(body, "program_id")
    subgrantee_id = get_str(body, "subgrantee_id")
    match_offer_pct = get_pct(body, "match_offer_pct")
    down = get_number(body, "committed_down_mbps", minimum=0)
    up = get_number(body, "committed_up_mbps", minimum=0)
    latency = get_int(body, "committed_latency_ms", minimum=0)
    price = get_cents(body, "low_cost_plan_price_cents")
    participates = get_bool(body, "participates_in_state_affordability_program",
                            required=False, default=False)
    has_dbe = get_bool(body, "has_dbe_plan", required=False, default=False)
    has_union = get_bool(body, "has_union_agreement", required=False, default=False)
    local_hire = get_pct(body, "local_hire_pct", required=False, default=0)
    start_raw, start_dt = get_ts(body, "proposed_construction_start")
    end_raw, end_dt = get_ts(body, "proposed_construction_end")

    program = domain.require_program(program_id)                      # priority 20
    subgrantee = domain.require_subgrantee(subgrantee_id)             # priority 23
    if role == "Subgrantee" and user_id != subgrantee["id"]:          # priority 30
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if program["program_state"] not in APPLICATION_PROGRAM_STATES:     # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if not (start_dt < end_dt):                                       # priority 70
        raise ApiError("ERR_WINDOW_ORDER_INVALID")

    application = new_record({
        "program_id": program["id"],
        "subgrantee_id": subgrantee["id"],
        "match_offer_pct": match_offer_pct,
        "committed_down_mbps": down,
        "committed_up_mbps": up,
        "committed_latency_ms": latency,
        "low_cost_plan_price_cents": price,
        "participates_in_state_affordability_program": participates,
        "has_dbe_plan": has_dbe,
        "has_union_agreement": has_union,
        "local_hire_pct": local_hire,
        "proposed_construction_start": start_raw,
        "proposed_construction_end": end_raw,
        "application_state": "DRAFT",
        "claim_count": 0,
        "confirmed_location_count": 0,
        "total_project_cost_cents": 0,
        "eligible_project_cost_cents": 0,
        "preliminary_cost_per_location_cents": None,
        "final_cost_per_location_cents": None,
        "current_total_score": None,
        "returned_for_cure_count": 0,
        "rescore_required_reason": None,
    })
    db.applications[application["id"]] = application
    return object_response(serialize(application), 201)


@bp.get("/broadband/applications/<application_id>")
def get_application(application_id):
    authenticate(*READ_ROLES)
    application = domain.require_application(application_id)
    return object_response(serialize(application))


@bp.get("/broadband/applications")
def list_applications():
    authenticate(*READ_ROLES)
    limit, offset = pagination()
    rows = list(db.applications.values())
    for field in ("program_id", "subgrantee_id", "application_state"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r.get(field) == wanted]
    return paginated(rows, limit, offset)


@bp.post("/broadband/applications/<application_id>/submit")
def submit_application(application_id):
    user_id, _role = authenticate("Subgrantee")
    application = domain.require_application(application_id)          # priority 24
    program = domain.program_of_application(application)

    if user_id != application["subgrantee_id"]:                       # priority 30
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if program["program_state"] not in ("CHALLENGE_OPEN", "CHALLENGE_CLOSED"):  # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if application["application_state"] not in ("DRAFT", "RETURNED_FOR_CURE"):  # priority 43
        raise ApiError("ERR_APPLICATION_STATE_INVALID")
    now = db.now()
    if not (parse_ts(program["application_window_start"]) <= now
            < parse_ts(program["application_window_end"])):            # priority 66
        raise ApiError("ERR_APPLICATION_WINDOW_CLOSED")
    if int(application["claim_count"]) < 1:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The application has no location claims to submit.")
    if int(application["returned_for_cure_count"]) >= calc.MAX_APPLICATION_CURES:  # priority 79
        raise ApiError("ERR_RESUBMISSION_LIMIT_REACHED")
    if (calc.D(application["committed_down_mbps"]) < calc.D(program["served_down_mbps_threshold"])
            or calc.D(application["committed_up_mbps"]) < calc.D(program["served_up_mbps_threshold"])
            or calc.D(application["committed_down_mbps"]) < 100
            or calc.D(application["committed_up_mbps"]) < 20):         # priority 80
        raise ApiError("ERR_SPEED_COMMITMENT_BELOW_MINIMUM")
    if calc.D(application["match_offer_pct"]) < calc.D(program["min_match_pct"]):  # priority 81
        raise ApiError("ERR_MATCH_BELOW_MINIMUM")

    assign(application, "application_state", "SUBMITTED")
    domain.refresh_application(application, stamp_costs=True)
    touch(application)
    return object_response(serialize(application))


@bp.post("/broadband/applications/<application_id>/return-for-cure")
def return_for_cure(application_id):
    authenticate("ScoringOfficer", "ProgramAdmin")
    body = json_body()
    get_str(body, "cure_reason")                                       # priority 14

    application = domain.require_application(application_id)           # priority 24
    program = domain.program_of_application(application)
    if program["program_state"] not in APPLICATION_PROGRAM_STATES:      # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if application["application_state"] != "SUBMITTED":                # priority 43
        raise ApiError("ERR_APPLICATION_STATE_INVALID")
    if int(application["returned_for_cure_count"]) != 0:               # priority 79
        raise ApiError("ERR_RESUBMISSION_LIMIT_REACHED")

    assign(application, "application_state", "RETURNED_FOR_CURE")
    assign(application, "returned_for_cure_count", 1)
    touch(application)
    return object_response(serialize(application))


@bp.post("/broadband/applications/<application_id>/select")
def select_application(application_id):
    authenticate("ProgramAdmin")
    application = domain.require_application(application_id)           # priority 24
    program = domain.program_of_application(application)
    if program["program_state"] != "SCORING":                          # priority 40
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if application["application_state"] != "SCORED":                   # priority 43
        raise ApiError("ERR_APPLICATION_STATE_INVALID")
    if program["scoring_posture"] != "OPEN":                           # priority 49
        raise ApiError("ERR_SCORING_POSTURE_RESTRICTED")

    assign(application, "application_state", "SELECTED")
    touch(application)
    return object_response(serialize(application))


@bp.get("/broadband/applications/<application_id>/location-claims")
def list_application_claims(application_id):
    authenticate(*CLAIM_READ_ROLES)
    limit, offset = pagination()
    application = domain.require_application(application_id)
    return paginated(domain.claims_of_application(application["id"]), limit, offset)


@bp.get("/broadband/applications/<application_id>/score-sheets")
def list_application_score_sheets(application_id):
    authenticate(*SHEET_READ_ROLES)
    limit, offset = pagination()
    application = domain.require_application(application_id)
    return paginated(domain.score_sheets_of_application(application["id"]), limit, offset)


@bp.get("/broadband/applications/<application_id>/awards")
def list_application_awards(application_id):
    authenticate(*AWARD_READ_ROLES)
    limit, offset = pagination()
    application = domain.require_application(application_id)
    return paginated(domain.awards_of_application(application["id"]), limit, offset)
