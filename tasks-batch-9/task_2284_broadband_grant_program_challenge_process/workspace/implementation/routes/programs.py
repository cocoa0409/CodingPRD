"""GrantProgram endpoints (PRD section 3.1)."""

from flask import Blueprint, request

from db import db, new_record, now_ts, parse_ts, serialize
from errors import ApiError
from middleware import (authenticate, get_bool, get_cents, get_int, get_number,
                        get_pct, get_str, get_ts, json_body, pagination)
from records import assign, touch
from response import object_response
from routes.listing import paginated
from services import domain

bp = Blueprint("programs", __name__)

READ_ROLES = ("ProgramAdmin", "EligibilityAnalyst", "CapabilityReviewer", "ScoringOfficer",
              "EnvironmentalReviewer", "AuditOfficer", "Subgrantee", "Challenger", "Provider")
LIST_ROLES = ("ProgramAdmin", "EligibilityAnalyst", "ScoringOfficer", "Subgrantee")


@bp.post("/broadband/programs")
def create_program():
    authenticate("ProgramAdmin")
    body = json_body()

    name = get_str(body, "name")
    fiscal_year = get_int(body, "fiscal_year")
    total = get_int(body, "total_appropriation_cents", minimum=1)
    cw_start, cw_start_dt = get_ts(body, "challenge_window_start")
    cw_end, cw_end_dt = get_ts(body, "challenge_window_end")
    aw_start, aw_start_dt = get_ts(body, "application_window_start")
    aw_end, aw_end_dt = get_ts(body, "application_window_end")

    min_match_pct = get_pct(body, "min_match_pct", required=False, default=25.0)
    holdback_pct = get_pct(body, "holdback_pct", required=False, default=10.0)
    unserved_down = get_number(body, "unserved_down_mbps_threshold", required=False,
                              default=25, minimum=0)
    unserved_up = get_number(body, "unserved_up_mbps_threshold", required=False,
                             default=3, minimum=0)
    served_down = get_number(body, "served_down_mbps_threshold", required=False,
                             default=100, minimum=0)
    served_up = get_number(body, "served_up_mbps_threshold", required=False,
                           default=20, minimum=0)
    max_latency = get_int(body, "max_latency_ms", required=False, default=100, minimum=0)
    ehcl_threshold = get_cents(body, "ehcl_threshold_cents", required=False, default=2500000)
    ehcl_waiver = get_bool(body, "ehcl_waiver_enabled", required=False, default=True)

    # priority 70
    if not (cw_start_dt < cw_end_dt) or not (aw_start_dt < aw_end_dt):
        raise ApiError("ERR_WINDOW_ORDER_INVALID")

    program = new_record({
        "name": name,
        "fiscal_year": fiscal_year,
        "total_appropriation_cents": total,
        "min_match_pct": min_match_pct,
        "holdback_pct": holdback_pct,
        "unserved_down_mbps_threshold": unserved_down,
        "unserved_up_mbps_threshold": unserved_up,
        "served_down_mbps_threshold": served_down,
        "served_up_mbps_threshold": served_up,
        "max_latency_ms": max_latency,
        "ehcl_threshold_cents": ehcl_threshold,
        "ehcl_waiver_enabled": ehcl_waiver,
        "challenge_window_start": cw_start,
        "challenge_window_end": cw_end,
        "application_window_start": aw_start,
        "application_window_end": aw_end,
        "program_state": "DRAFT",
        "scoring_posture": "FROZEN",
        "stale_score_sheet_count": 0,
        "location_count_total": 0,
        "uncommitted_balance_cents": total,
        "obligated_balance_cents": 0,
        "disbursed_balance_cents": 0,
    })
    db.programs[program["id"]] = program
    return object_response(serialize(program), 201)


@bp.get("/broadband/programs/<program_id>")
def get_program(program_id):
    authenticate(*READ_ROLES)
    program = domain.require_program(program_id)
    return object_response(serialize(program))


@bp.get("/broadband/programs")
def list_programs():
    authenticate(*LIST_ROLES)
    limit, offset = pagination()
    rows = list(db.programs.values())
    fiscal_year = request.args.get("fiscal_year")
    if fiscal_year is not None:
        try:
            wanted = int(fiscal_year)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "fiscal_year filter must be an integer.")
        rows = [r for r in rows if r["fiscal_year"] == wanted]
    program_state = request.args.get("program_state")
    if program_state is not None:
        rows = [r for r in rows if r["program_state"] == program_state]
    return paginated(rows, limit, offset)


@bp.post("/broadband/programs/<program_id>/open-challenge-window")
def open_challenge_window(program_id):
    authenticate("ProgramAdmin")
    program = domain.require_program(program_id)
    if program["program_state"] != "DRAFT":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    now = db.now()
    start = parse_ts(program["challenge_window_start"])
    end = parse_ts(program["challenge_window_end"])
    if not (start <= now < end):
        raise ApiError("ERR_CHALLENGE_WINDOW_CLOSED")
    live_locations = len([l for l in db.locations.values()
                          if l["program_id"] == program["id"]])
    if live_locations < 1:
        raise ApiError("ERR_PROGRAM_STATE_INVALID",
                       "The program has no eligible locations to challenge.")
    assign(program, "program_state", "CHALLENGE_OPEN")
    touch(program)
    domain.refresh_program(program)
    return object_response(serialize(program))


@bp.post("/broadband/programs/<program_id>/close-challenge-window")
def close_challenge_window(program_id):
    authenticate("ProgramAdmin")
    program = domain.require_program(program_id)
    if program["program_state"] != "CHALLENGE_OPEN":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    now = db.now()
    if now < parse_ts(program["challenge_window_end"]):
        raise ApiError("ERR_PROGRAM_STATE_INVALID",
                       "The challenge window has not yet elapsed.")
    challenges = [c for c in db.challenges.values() if c["program_id"] == program["id"]]
    if any(c["challenge_state"] == "SUBMITTED" for c in challenges):
        raise ApiError("ERR_PROGRAM_STATE_INVALID",
                       "A challenge of this program is still SUBMITTED.")

    for challenge in challenges:
        if challenge["challenge_state"] == "REBUTTAL_OPEN":
            assign(challenge, "challenge_state", "UNDER_REVIEW")
            assign(challenge, "rebuttal_deadline", now_ts())
            touch(challenge)
    for location in db.locations.values():
        if (location["program_id"] == program["id"]
                and location["eligibility_state"] == "MAPPED"):
            assign(location, "eligibility_state", "AFFIRMED")
            touch(location)

    assign(program, "program_state", "CHALLENGE_CLOSED")
    touch(program)
    domain.refresh_program(program)
    return object_response(serialize(program))


@bp.post("/broadband/programs/<program_id>/open-scoring")
def open_scoring(program_id):
    authenticate("ProgramAdmin")
    program = domain.require_program(program_id)
    if program["program_state"] != "CHALLENGE_CLOSED":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    if db.now() < parse_ts(program["application_window_end"]):
        raise ApiError("ERR_PROGRAM_STATE_INVALID",
                       "The application window has not yet elapsed.")
    for challenge in db.challenges.values():
        if (challenge["program_id"] == program["id"]
                and challenge["challenge_state"] in ("SUBMITTED", "REBUTTAL_OPEN")):
            raise ApiError("ERR_PROGRAM_STATE_INVALID",
                           "A challenge of this program is still awaiting review.")
    assign(program, "program_state", "SCORING")
    touch(program)
    domain.refresh_program(program)
    return object_response(serialize(program))


@bp.post("/broadband/programs/<program_id>/close-allocation")
def close_allocation(program_id):
    authenticate("ProgramAdmin")
    program = domain.require_program(program_id)
    if program["program_state"] != "SCORING":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    applications = domain.applications_of_program(program["id"])
    if any(a["application_state"] == "SELECTED" for a in applications):
        raise ApiError("ERR_PROGRAM_STATE_INVALID",
                       "An application of this program is still SELECTED.")

    open_states = ("DRAFT", "SUBMITTED", "RETURNED_FOR_CURE", "SCORED", "RESCORE_REQUIRED")
    for application in applications:
        if application["application_state"] not in open_states:
            continue
        assign(application, "application_state", "NOT_SELECTED")
        for claim in domain.claims_of_application(application["id"]):
            if claim["claim_state"] in ("CLAIMED_ELIGIBLE", "CLAIMED_INELIGIBLE"):
                assign(claim, "claim_state", "RELEASED")
                touch(claim)
        domain.refresh_application(application)
        touch(application)

    assign(program, "program_state", "ALLOCATION_CLOSED")
    touch(program)
    domain.refresh_program(program)
    return object_response(serialize(program))
