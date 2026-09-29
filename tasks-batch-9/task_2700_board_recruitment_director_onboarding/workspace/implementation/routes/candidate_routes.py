"""Candidate sourcing and the pipeline actions that do not touch a screen."""

from flask import Blueprint

from authz import (
    COMMITTEE_CHAIR,
    COMMITTEE_MEMBER,
    CORPORATE_SECRETARY,
    GOVERNANCE_STAFF,
    require,
)
from calc import (
    candidate_board_set,
    dec,
    governing_policy,
    interlock_evaluation,
    overboarding_limit,
    parse_iso_date,
    require_policy,
    whole_years,
)
from derive import (
    _apply,
    cancel_scheduled_interviews,
    new_screen,
    recompute_readiness,
    void_live_nominees_of_candidate,
    void_open_screens,
)
from errors import fail
from payload import body, check_enum, check_min, optional, parse_date, required
from store import clock_date, db, new_row, touch
from vocab import CANDIDATE_STATUS, SOURCE_CHANNEL

from routes.common import apply_filters, by_created_at, emit, emit_list, need

bp = Blueprint("candidate", __name__)

READ_ROLES = (GOVERNANCE_STAFF, CORPORATE_SECRETARY, COMMITTEE_CHAIR, COMMITTEE_MEMBER)
STAFF = (GOVERNANCE_STAFF, CORPORATE_SECRETARY)

WITHDRAWABLE = ("SOURCED", "SCREENING", "SCREEN_PASSED", "INTERVIEWING", "REFERENCE_CHECK",
                "SLATE_ELIGIBLE")


@bp.post("/candidates")
def source_candidate():
    require(*STAFF)
    b = body()
    full_name = required(b, "full_name", "string")
    email = required(b, "email", "string")
    birth_date = required(b, "birth_date", "string")
    channel = required(b, "source_channel", "string")
    firm_id = optional(b, "search_firm_id", "string")
    referrer_id = optional(b, "referring_director_id", "string")
    proponent = optional(b, "shareholder_proponent_name", "string")
    is_sitting_ceo = optional(b, "is_sitting_ceo", "boolean", False)
    target_comp = optional(b, "target_annual_comp_cents", "integer", 0)
    check_enum("source_channel", channel, SOURCE_CHANNEL)
    check_min("target_annual_comp_cents", target_comp, 0)
    parse_date(birth_date, "birth_date")

    if channel == "SEARCH_FIRM":
        if firm_id is None or referrer_id is not None:
            fail("ERR_SOURCE_CHANNEL_MISMATCH",
                 "SEARCH_FIRM requires search_firm_id and forbids referring_director_id.")
    elif channel == "NETWORK_REFERRAL":
        if referrer_id is None or firm_id is not None:
            fail("ERR_SOURCE_CHANNEL_MISMATCH",
                 "NETWORK_REFERRAL requires referring_director_id and forbids search_firm_id.")
    else:
        if proponent is None or firm_id is not None or referrer_id is not None:
            fail("ERR_SOURCE_CHANNEL_MISMATCH",
                 "%s requires shareholder_proponent_name and forbids both identifier fields."
                 % channel)

    if firm_id is not None:
        need("search_firm", firm_id)
    if referrer_id is not None:
        need("director", referrer_id)

    row = new_row({
        "full_name": full_name,
        "email": email,
        "birth_date": birth_date,
        "source_channel": channel,
        "search_firm_id": firm_id,
        "referring_director_id": referrer_id,
        "shareholder_proponent_name": proponent,
        "is_sitting_ceo": is_sitting_ceo,
        "target_annual_comp_cents": target_comp,
        "status": "SOURCED",
        "rejection_reason_code": None,
        "independence_result": "PENDING",
        "completed_interview_count": 0,
        "interview_score_avg": 0.00,
        "external_public_board_count": 0,
        "interlock_shared_board_count": 0,
        "readiness_score": 0.00,
        "reference_check_count": 0,
        "adverse_reference_found": False,
        "deferred_cycle_year": None,
        "interview_round": 0,
    })
    db.candidates[row["id"]] = row
    return emit(row, 201)


@bp.get("/candidates/<candidate_id>")
def read_candidate(candidate_id):
    require(*READ_ROLES)
    return emit(need("candidate", candidate_id))


@bp.get("/candidates")
def list_candidates():
    require(*READ_ROLES)
    rows = apply_filters(list(db.candidates.values()), {
        "status": ("status", "str"),
        "source_channel": ("source_channel", "str"),
        "search_firm_id": ("search_firm_id", "str"),
        "referring_director_id": ("referring_director_id", "str"),
    })
    return emit_list(by_created_at(rows))


@bp.post("/candidates/<candidate_id>/reference-check")
def reference_check(candidate_id):
    require(*STAFF)
    b = body()
    reference_count = required(b, "reference_count", "integer")
    adverse = optional(b, "adverse_findings", "boolean", False)
    candidate = need("candidate", candidate_id)
    policy = governing_policy()
    if candidate["status"] != "INTERVIEWING":
        fail("ERR_CANDIDATE_STATE_INVALID",
             "A reference check may only close an INTERVIEWING candidate; this one is %s."
             % candidate["status"])
    if policy is not None:
        completed = sum(1 for s in db.interviews.values()
                        if s["candidate_id"] == candidate_id and s["status"] == "COMPLETED")
        if completed < policy["min_completed_interviews"]:
            fail("ERR_INSUFFICIENT_INTERVIEWS",
                 "The candidate holds %s completed interviews; %s are required."
                 % (completed, policy["min_completed_interviews"]))
    candidate["reference_check_count"] = reference_count
    candidate["adverse_reference_found"] = adverse
    if adverse:
        candidate["status"] = "REJECTED"
        candidate["rejection_reason_code"] = "ADVERSE_REFERENCE"
    else:
        candidate["status"] = "REFERENCE_CHECK"
    touch(candidate)
    if adverse:
        void_live_nominees_of_candidate(candidate, policy)
    recompute_readiness(candidate)
    return emit(candidate)


@bp.post("/candidates/<candidate_id>/reopen-interviews")
def reopen_interviews(candidate_id):
    require(COMMITTEE_CHAIR)
    candidate = need("candidate", candidate_id)
    if candidate["status"] != "REFERENCE_CHECK":
        fail("ERR_CANDIDATE_STATE_INVALID",
             "Interviews may only reopen from REFERENCE_CHECK; this candidate is %s."
             % candidate["status"])
    if candidate["interview_round"] >= 3:
        fail("ERR_CANDIDATE_STATE_INVALID",
             "The interview loop is bounded at three rounds; this candidate is at round %s."
             % candidate["interview_round"])
    candidate["status"] = "INTERVIEWING"
    candidate["interview_round"] = candidate["interview_round"] + 1
    candidate["reference_check_count"] = 0
    touch(candidate)
    return emit(candidate)


@bp.post("/candidates/<candidate_id>/conflict-clearance")
def conflict_clearance(candidate_id):
    require(COMMITTEE_CHAIR)
    candidate = need("candidate", candidate_id)
    policy = require_policy()
    if candidate["status"] != "REFERENCE_CHECK":
        fail("ERR_CANDIDATE_STATE_INVALID",
             "Conflict clearance runs only from REFERENCE_CHECK; this candidate is %s."
             % candidate["status"])
    board_set = candidate_board_set(candidate_id)
    shared, competitor = interlock_evaluation(board_set)
    reason = None
    if shared >= policy["interlock_max_shared_boards"] or competitor:
        reason = "INTERLOCK_LIMIT"
    elif len(board_set) + 1 > overboarding_limit(policy, candidate["is_sitting_ceo"]):
        reason = "OVERBOARDING"
    elif whole_years(parse_iso_date(candidate["birth_date"]), clock_date()) \
            >= policy["mandatory_retirement_age"]:
        reason = "RETIREMENT_AGE"
    candidate["interlock_shared_board_count"] = shared
    candidate["external_public_board_count"] = len(board_set)
    if reason is None:
        candidate["status"] = "SLATE_ELIGIBLE"
    else:
        candidate["status"] = "REJECTED"
        candidate["rejection_reason_code"] = reason
    touch(candidate)
    recompute_readiness(candidate)
    return emit(candidate)


@bp.post("/candidates/<candidate_id>/reopen-screening")
def reopen_screening(candidate_id):
    require(*STAFF)
    candidate = need("candidate", candidate_id)
    if candidate["status"] != "DEFERRED":
        fail("ERR_CANDIDATE_STATE_INVALID",
             "Only a DEFERRED candidate may reopen screening; this one is %s."
             % candidate["status"])
    policy = governing_policy()
    deferred_year = candidate["deferred_cycle_year"]
    if policy is None or deferred_year is None \
            or not policy["cycle_year"] > deferred_year:
        fail("ERR_CANDIDATE_STATE_INVALID",
             "Screening may only reopen in a cycle later than %s." % deferred_year)
    candidate["status"] = "SCREENING"
    candidate["independence_result"] = "PENDING"
    candidate["interview_round"] = 0
    touch(candidate)
    new_screen(candidate_id)
    return emit(candidate)


@bp.post("/candidates/<candidate_id>/withdraw")
def withdraw_candidate(candidate_id):
    require(*STAFF)
    candidate = need("candidate", candidate_id)
    if candidate["status"] not in WITHDRAWABLE:
        fail("ERR_CANDIDATE_STATE_INVALID",
             "A candidate at %s may not withdraw." % candidate["status"])
    candidate["status"] = "WITHDRAWN"
    touch(candidate)
    void_open_screens(candidate)
    cancel_scheduled_interviews(candidate)
    return emit(candidate)
