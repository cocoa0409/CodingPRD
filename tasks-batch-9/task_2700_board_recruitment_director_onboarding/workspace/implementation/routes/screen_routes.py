"""Independence screens: opening, submission, determination and the reads."""

from flask import Blueprint

from authz import (
    COMMITTEE_CHAIR,
    COMMITTEE_MEMBER,
    CORPORATE_SECRETARY,
    GOVERNANCE_STAFF,
    require,
)
from calc import (
    deciding_fail_count,
    disqualifying_factor,
    require_policy,
    screen_factor_results,
)
from derive import (
    _apply,
    cancel_scheduled_interviews,
    new_screen,
    recompute_readiness,
    void_live_nominees_of_candidate,
)
from errors import fail
from payload import body, optional, parse_date
from store import clock_instant, db, touch

from routes.common import apply_filters, by_created_desc, emit, emit_list, need

bp = Blueprint("screen", __name__)

READ_ROLES = (GOVERNANCE_STAFF, CORPORATE_SECRETARY, COMMITTEE_CHAIR, COMMITTEE_MEMBER)
STAFF = (GOVERNANCE_STAFF, CORPORATE_SECRETARY)

OPEN_SCREEN = ("DRAFT", "SUBMITTED")
SCREENABLE = ("SOURCED", "NOMINATED")
SUBMITTABLE = ("SCREENING", "NOMINATED")


@bp.post("/candidates/<candidate_id>/screens")
def open_screen(candidate_id):
    require(*STAFF)
    b = body()
    supplied = {
        "payments_to_company_cents": optional(b, "payments_to_company_cents", "integer"),
        "recipient_gross_revenue_cents": optional(b, "recipient_gross_revenue_cents", "integer"),
        "prior_employment_end_on": optional(b, "prior_employment_end_on", "string"),
        "family_member_employed": optional(b, "family_member_employed", "boolean"),
        "auditor_affiliation": optional(b, "auditor_affiliation", "boolean"),
        "charitable_contributions_cents": optional(b, "charitable_contributions_cents", "integer"),
        "company_gross_revenue_cents": optional(b, "company_gross_revenue_cents", "integer"),
    }
    parse_date(supplied["prior_employment_end_on"], "prior_employment_end_on")
    candidate = need("candidate", candidate_id)
    if candidate["status"] not in SCREENABLE:
        fail("ERR_CANDIDATE_STATE_INVALID",
             "A screen may only be opened from SOURCED or NOMINATED; this candidate is %s."
             % candidate["status"])
    for row in db.screens.values():
        if row["candidate_id"] == candidate_id and row["status"] in OPEN_SCREEN:
            fail("ERR_DUPLICATE_RESOURCE",
                 "This candidate already has an open independence screen.")
    row = new_screen(candidate_id, supplied)
    if candidate["status"] == "SOURCED":
        _apply(candidate, {"status": "SCREENING"})
    return emit(row, 201)


@bp.get("/candidates/<candidate_id>/screens")
def list_candidate_screens(candidate_id):
    require(*READ_ROLES)
    need("candidate", candidate_id)
    rows = [s for s in db.screens.values() if s["candidate_id"] == candidate_id]
    rows = apply_filters(rows, {"status": ("status", "str")})
    return emit_list(by_created_desc(rows))


@bp.get("/screens/<screen_id>")
def read_screen(screen_id):
    require(*READ_ROLES)
    return emit(need("screen", screen_id))


@bp.get("/screens")
def list_screens():
    require(*READ_ROLES)
    rows = apply_filters(list(db.screens.values()), {
        "candidate_id": ("candidate_id", "str"),
        "status": ("status", "str"),
        "standard_applied": ("standard_applied", "str"),
    })
    return emit_list(by_created_desc(rows))


@bp.post("/screens/<screen_id>/submit")
def submit_screen(screen_id):
    require(*STAFF)
    screen = need("screen", screen_id)
    policy = require_policy()
    if screen["status"] != "DRAFT":
        fail("ERR_SCREEN_STATE_INVALID",
             "Only a DRAFT screen may be submitted; this one is %s." % screen["status"])
    candidate = db.candidates.get(screen["candidate_id"])
    if candidate is None or candidate["status"] not in SUBMITTABLE:
        fail("ERR_CANDIDATE_STATE_INVALID",
             "The screened candidate must be at SCREENING or NOMINATED.")
    standard = policy["independence_standard"]
    results = screen_factor_results(screen, policy)
    screen["standard_applied"] = standard
    screen["bright_line_fail_count"] = results["bright_line_fail_count"]
    screen["qualitative_fail_count"] = results["qualitative_fail_count"]
    screen["disqualifying_factor_code"] = disqualifying_factor(results, standard)
    screen["submitted_at"] = clock_instant()
    screen["status"] = "SUBMITTED"
    touch(screen)
    return emit(screen)


@bp.post("/screens/<screen_id>/determine")
def determine_screen(screen_id):
    require(COMMITTEE_CHAIR)
    screen = need("screen", screen_id)
    if screen["status"] != "SUBMITTED":
        fail("ERR_SCREEN_STATE_INVALID",
             "Only a SUBMITTED screen may be determined; this one is %s." % screen["status"])
    adverse = deciding_fail_count(screen) >= 1
    screen["determination"] = "NOT_INDEPENDENT" if adverse else "INDEPENDENT"
    screen["status"] = "DETERMINED_NOT_INDEPENDENT" if adverse else "DETERMINED_INDEPENDENT"
    screen["determined_at"] = clock_instant()
    touch(screen)

    candidate = db.candidates.get(screen["candidate_id"])
    if candidate is None:
        return emit(screen)
    origin = candidate["status"]
    if not adverse:
        changes = {"independence_result": "INDEPENDENT"}
        if origin == "SCREENING":
            changes["status"] = "SCREEN_PASSED"
        _apply(candidate, changes)
        recompute_readiness(candidate)
        return emit(screen)

    changes = {"independence_result": "NOT_INDEPENDENT"}
    if origin in ("SCREENING", "NOMINATED"):
        changes["status"] = "REJECTED"
        changes["rejection_reason_code"] = "INDEPENDENCE_FAILED"
    _apply(candidate, changes)
    if origin == "SCREENING":
        cancel_scheduled_interviews(candidate)
    void_live_nominees_of_candidate(candidate)
    recompute_readiness(candidate)
    return emit(screen)
