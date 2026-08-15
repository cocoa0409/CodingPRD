"""TenureCase endpoints (PRD §3.1–§3.9)."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_CASE_NOT_FOUND,
    ERR_CANDIDATE_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_CASE_STAGE_FORBIDDEN,
    ERR_REVIEW_CLOCK_EXPIRED,
    ERR_DOSSIER_INCOMPLETE,
    ERR_OPEN_INVITATIONS_EXIST,
    ERR_INSUFFICIENT_EXTERNAL_LETTERS,
    ERR_MIDTERM_REVIEW_MISSING,
    ERR_MIDTERM_OUTCOME_BLOCKS,
    ERR_ROUND_NOT_CERTIFIED,
    ERR_DECISION_NOT_FOUND,
    ERR_NOTIFICATION_WINDOW_LAPSED,
    ERR_APPEAL_WINDOW_OPEN,
    ERR_APPEAL_PENDING,
    ERR_RETENTION_NOT_EXPIRED,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services import calculations as calc
from services.core import (
    new_record, touch, get_candidate, create_round, lazy_expire_case_invitations,
    withdraw_case_cascade, recorded_decision_for_case,
)
from util import CLOCK, fmt_dt, parse_dt
from validate import (
    get_body, req_str, req_enum, req_bool, opt_bool, require_path,
    raw_str, body_ref_exists,
)

bp = Blueprint("cases", __name__)

TARGET_RANKS = {"ASSOCIATE_PROFESSOR", "FULL_PROFESSOR"}
CLOCK_POLICIES = {"ANNIVERSARY", "DAY_COUNT"}

# Stages from which the candidate may withdraw (PRD §3.9: pre-decision only).
WITHDRAWABLE_STAGES = {
    "DOSSIER_ASSEMBLY",
    "EXTERNAL_REVIEW",
    "RETURNED_FOR_REVISION",
    "DEPT_COMMITTEE",
    "COLLEGE_COMMITTEE",
    "UNIVERSITY_COMMITTEE",
    "PROVOST_REVIEW",
}


def _own_case_or_403(caller, case):
    """Priority 5 ownership: the acting Candidate must own the case."""
    if caller.user_id != case["candidate_id"]:
        raise_error(ERR_OWNERSHIP_MISMATCH, "acting user does not own this case")


def _require_stage(case, stage):
    if case["stage"] != stage:
        raise_error(ERR_CASE_STAGE_FORBIDDEN,
                    f"case stage {case['stage']} does not permit this operation")


@bp.post("/cases")
def create_case():
    caller = authorized(["ProvostOfficer"])
    body = get_body()
    # Priority 4: body FK existence.
    candidate_id_raw = raw_str(body, "candidate_id")
    candidate = None
    if candidate_id_raw is not None:
        candidate = db["candidates"].get(candidate_id_raw)
        if candidate is None:
            raise_error(ERR_CANDIDATE_NOT_FOUND, "candidate_id does not resolve")
    # Priority 9: shape.
    candidate_id = req_str(body, "candidate_id")
    review_cycle = req_str(body, "review_cycle")
    target_rank = req_enum(body, "target_rank", TARGET_RANKS)
    seeking_tenure = req_bool(body, "seeking_tenure")
    clock_policy = req_enum(body, "clock_policy", CLOCK_POLICIES)
    waiver_signed = opt_bool(body, "waiver_signed", True)
    mrd = calc.compute_mandatory_review_date(candidate["tenure_clock_start"], clock_policy, 0)
    rec = new_record("cases", {
        "candidate_id": candidate_id,
        "review_cycle": review_cycle,
        "target_rank": target_rank,
        "seeking_tenure": seeking_tenure,
        "clock_policy": clock_policy,
        "waiver_signed": waiver_signed,
        "created_by_user_id": caller.user_id,
        "stage": "DOSSIER_ASSEMBLY",
        "dossier_submitted_at": None,
        "extension_days": 0,
        "mandatory_review_date": fmt_dt(mrd),
        "dossier_strength_index": None,
        "recommendation_score": None,
        "appeal_filing_deadline": None,
        "closed_at": None,
        "retention_until": None,
        "purged_at": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/cases")
def list_cases():
    return list_response("cases", {
        "candidate_id": request.args.get("candidate_id"),
        "stage": request.args.get("stage"),
    })


@bp.get("/cases/<rid>")
def get_case_route(rid):
    return get_one("cases", rid, ERR_CASE_NOT_FOUND)


@bp.post("/cases/<rid>/submit-dossier")
def submit_dossier(rid):
    caller = authorized(["Candidate"])
    case = require_path("cases", rid, ERR_CASE_NOT_FOUND)
    _own_case_or_403(caller, case)
    _require_stage(case, "DOSSIER_ASSEMBLY")
    # Priority 10 temporal gate before the priority-11 completeness gate.
    if CLOCK.now() > parse_dt(case["mandatory_review_date"]):
        raise_error(ERR_REVIEW_CLOCK_EXPIRED, "mandatory review date has passed")
    if not calc.dossier_complete(case["id"]):
        raise_error(ERR_DOSSIER_INCOMPLETE, "dossier category minima unmet")
    case["dossier_submitted_at"] = CLOCK.now_iso()
    case["dossier_strength_index"] = calc.dossier_strength_index(case["id"])
    case["stage"] = "EXTERNAL_REVIEW"
    touch(case)
    return success_object(public(case))


@bp.post("/cases/<rid>/return-for-revision")
def return_for_revision(rid):
    authorized(["ProvostOfficer"])
    case = require_path("cases", rid, ERR_CASE_NOT_FOUND)
    _require_stage(case, "EXTERNAL_REVIEW")
    # Priority 11: ACCEPTED invitations block the return.
    for inv in db["invitations"].values():
        if inv["case_id"] == case["id"] and inv["status"] == "ACCEPTED":
            raise_error(ERR_OPEN_INVITATIONS_EXIST,
                        "ACCEPTED invitations must be withdrawn or receive letters first")
    for inv in db["invitations"].values():
        if inv["case_id"] == case["id"] and inv["status"] == "SOLICITED":
            inv["status"] = "WITHDRAWN"
            touch(inv)
    case["stage"] = "RETURNED_FOR_REVISION"
    touch(case)
    return success_object(public(case))


@bp.post("/cases/<rid>/resume-assembly")
def resume_assembly(rid):
    caller = authorized(["Candidate"])
    case = require_path("cases", rid, ERR_CASE_NOT_FOUND)
    _own_case_or_403(caller, case)
    _require_stage(case, "RETURNED_FOR_REVISION")
    case["stage"] = "DOSSIER_ASSEMBLY"
    touch(case)
    return success_object(public(case))


@bp.post("/cases/<rid>/close-solicitation")
def close_solicitation(rid):
    authorized(["ProvostOfficer"])
    case = require_path("cases", rid, ERR_CASE_NOT_FOUND)
    _require_stage(case, "EXTERNAL_REVIEW")
    # Lazy expiry sweep runs first and persists even when a later gate fails.
    lazy_expire_case_invitations(case["id"])
    # Priority 11 gates in the state machine's listed order.
    for inv in db["invitations"].values():
        if inv["case_id"] == case["id"] and inv["status"] == "SOLICITED":
            raise_error(ERR_OPEN_INVITATIONS_EXIST, "SOLICITED invitations remain")
    if calc.usable_letter_count(case["id"]) < calc.MIN_EXTERNAL_LETTERS:
        raise_error(ERR_INSUFFICIENT_EXTERNAL_LETTERS, "fewer than 3 letters received")
    midterms = [
        m for m in db["midterm_reviews"].values()
        if m["case_id"] == case["id"] and m["status"] == "COMPLETED"
    ]
    if not midterms:
        raise_error(ERR_MIDTERM_REVIEW_MISSING, "no COMPLETED mid-tenure review")
    if any(m["outcome"] == "UNSATISFACTORY" for m in midterms):
        raise_error(ERR_MIDTERM_OUTCOME_BLOCKS, "UNSATISFACTORY mid-tenure outcome blocks review")
    create_round(case, "DEPARTMENT")  # selector raises ERR_NO_ELIGIBLE_COMMITTEE
    case["stage"] = "DEPT_COMMITTEE"
    touch(case)
    return success_object(public(case))


@bp.post("/cases/<rid>/advance-stage")
def advance_stage(rid):
    authorized(["ProvostOfficer"])
    case = require_path("cases", rid, ERR_CASE_NOT_FOUND)
    stage = case["stage"]
    if stage not in ("DEPT_COMMITTEE", "COLLEGE_COMMITTEE", "UNIVERSITY_COMMITTEE"):
        raise_error(ERR_CASE_STAGE_FORBIDDEN,
                    f"case stage {stage} does not permit advancement")
    current_level = {
        "DEPT_COMMITTEE": "DEPARTMENT",
        "COLLEGE_COMMITTEE": "COLLEGE",
        "UNIVERSITY_COMMITTEE": "UNIVERSITY",
    }[stage]
    latest = calc.latest_round_at_level(case["id"], current_level)
    if latest is None or latest["status"] != "COMPLETED":
        raise_error(ERR_ROUND_NOT_CERTIFIED,
                    f"the case's latest {current_level} round is not COMPLETED")
    if stage == "DEPT_COMMITTEE":
        create_round(case, "COLLEGE")
        case["stage"] = "COLLEGE_COMMITTEE"
    elif stage == "COLLEGE_COMMITTEE":
        create_round(case, "UNIVERSITY")
        case["stage"] = "UNIVERSITY_COMMITTEE"
    else:
        case["recommendation_score"] = calc.compute_recommendation_score(case)
        case["stage"] = "PROVOST_REVIEW"
    touch(case)
    return success_object(public(case))


@bp.post("/cases/<rid>/withdraw")
def withdraw_case(rid):
    caller = authorized(["Candidate"])
    case = require_path("cases", rid, ERR_CASE_NOT_FOUND)
    _own_case_or_403(caller, case)
    if case["stage"] not in WITHDRAWABLE_STAGES:
        raise_error(ERR_CASE_STAGE_FORBIDDEN,
                    f"case stage {case['stage']} does not permit withdrawal")
    withdraw_case_cascade(case, case["stage"])
    return success_object(public(case))


@bp.post("/cases/<rid>/notify")
def notify_case(rid):
    authorized(["ProvostOfficer"])
    case = require_path("cases", rid, ERR_CASE_NOT_FOUND)
    _require_stage(case, "DECIDED")
    decision = recorded_decision_for_case(case["id"])
    if decision is None:
        raise_error(ERR_DECISION_NOT_FOUND, "no RECORDED decision exists for the case")
    if CLOCK.now() > parse_dt(decision["notification_deadline"]):
        raise_error(ERR_NOTIFICATION_WINDOW_LAPSED, "notification deadline has passed")
    now = CLOCK.now()
    decision["notification_sent_at"] = fmt_dt(now)
    touch(decision)
    case["appeal_filing_deadline"] = fmt_dt(now + timedelta(days=calc.APPEAL_WINDOW_DAYS))
    case["stage"] = "NOTIFIED"
    touch(case)
    return success_object(public(case))


@bp.post("/cases/<rid>/close")
def close_case(rid):
    authorized(["ProvostOfficer"])
    case = require_path("cases", rid, ERR_CASE_NOT_FOUND)
    _require_stage(case, "NOTIFIED")
    if not (CLOCK.now() > parse_dt(case["appeal_filing_deadline"])):
        raise_error(ERR_APPEAL_WINDOW_OPEN, "the appeal window has not lapsed")
    for a in db["appeals"].values():
        if a["case_id"] == case["id"] and a["status"] in ("FILED", "UNDER_REVIEW"):
            raise_error(ERR_APPEAL_PENDING, "an appeal is still open for the case")
    now = CLOCK.now()
    case["closed_at"] = fmt_dt(now)
    case["retention_until"] = fmt_dt(now + timedelta(days=calc.RETENTION_DAYS))
    case["stage"] = "CLOSED"
    touch(case)
    return success_object(public(case))


@bp.post("/cases/<rid>/archive")
def archive_case(rid):
    authorized(["RecordsOfficer"])
    case = require_path("cases", rid, ERR_CASE_NOT_FOUND)
    _require_stage(case, "CLOSED")
    case["stage"] = "ARCHIVED"
    touch(case)
    return success_object(public(case))


@bp.post("/cases/<rid>/purge")
def purge_case(rid):
    authorized(["RecordsOfficer"])
    case = require_path("cases", rid, ERR_CASE_NOT_FOUND)
    _require_stage(case, "ARCHIVED")
    if CLOCK.now() < parse_dt(case["retention_until"]):
        raise_error(ERR_RETENTION_NOT_EXPIRED, "retention period has not expired")
    case["purged_at"] = CLOCK.now_iso()
    case["stage"] = "PURGED"
    touch(case)
    return success_object(public(case))
