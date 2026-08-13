"""Business operations: duty-hour logs, violations, moonlighting, milestone
evaluations, CCC reviews, procedure case logs, case requirements, remediation
plans, probation cases, accreditation citations, annual surveys, logical clock.
"""
from datetime import timedelta
from decimal import Decimal

import calc
import core
from core import (
    get_program, get_year, get_resident, get_rotation, get_duty_log,
    get_violation, get_moonlighting, get_evaluation, get_ccc_review,
    get_case_log, get_requirement, get_plan, get_probation, get_citation,
    get_survey,
)
from db import DB, CLOCK, new_id, clock_dt, clock_date_str, fmt_clock
from errors import ApiError
from middleware import RESIDENT
from util import parse_dt, round2, dec

COMPETENCIES = calc.COMPETENCIES
MOONLIGHTING_TYPES = ["INTERNAL", "EXTERNAL"]
PROCEDURE_CATEGORIES = [
    "MAJOR_SURGERY", "ENDOSCOPY", "TRAUMA_CARE", "DELIVERIES", "AMBULATORY_PROCEDURE",
]
CASE_ROLES = ["SURGEON", "ASSIST"]
REPORTING_PERIODS = ["H1", "H2"]
SEVERITIES = ["WARNING", "SERIOUS"]
AREA_CODES = [
    "DUTY_HOURS", "EVALUATION", "CASE_LOGS", "SUPERVISION", "RESPONSE_RATE", "OTHER",
]
CCC_OUTCOMES = ["SATISFACTORY", "NEEDS_IMPROVEMENT", "UNSATISFACTORY"]
PLAN_OUTCOMES = ["SUCCESS", "FAILURE"]


def conflict(error_id, message):
    return ApiError(error_id, 409, message)


def _ownership_check(role, user_id, resident_id):
    """Pipeline stage 4: Resident-role calls may only touch rows whose resident
    FK equals X-User-ID."""
    if role == RESIDENT and resident_id != user_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403,
                       "Resident-role calls may only touch their own records")


def _inside_active_year(resident, dt):
    for y in DB["academic_years"].values():
        if (
            y["program_id"] == resident["program_id"]
            and y["status"] == "ACTIVE"
            and y["_start"] <= dt < y["_end"]
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Logical clock (test-driving; fires time-driven moonlighting transitions).
# ---------------------------------------------------------------------------

def set_clock(data):
    to_dt = parse_dt(data["to_iso8601"])
    CLOCK["dt"] = to_dt
    CLOCK["raw"] = fmt_clock(to_dt)
    # Time-driven moonlighting transitions (PRD section 3.6).
    for req in sorted(DB["moonlighting_requests"].values(), key=lambda m: m["_seq"]):
        if req["status"] == "APPROVED":
            if to_dt >= req["_end"]:
                req["status"] = "COMPLETED"
                core.touch(req)
            elif req["_start"] <= to_dt < req["_end"]:
                req["status"] = "ACTIVE"
                core.touch(req)
        elif req["status"] == "ACTIVE":
            if to_dt >= req["_end"]:
                req["status"] = "COMPLETED"
                core.touch(req)
    return {"current_utc": CLOCK["raw"]}


# ---------------------------------------------------------------------------
# DutyHourLog
# ---------------------------------------------------------------------------

def create_duty_log(data, user_id, role):
    # Ownership precedes existence for body-level references (pipeline stage 4).
    _ownership_check(role, user_id, data["resident_id"])
    resident = get_resident(data["resident_id"])
    started = parse_dt(data["started_at"])
    ended = parse_dt(data["ended_at"])
    if ended <= started:
        raise ApiError("ERR_INVALID_REQUEST", 400, "ended_at must be after started_at")
    # Safety: duration must not exceed 28.00 hours.
    duration = round2(Decimal(str((ended - started).total_seconds())) / Decimal(3600))
    if duration > Decimal("28.00"):
        raise ApiError("ERR_SHIFT_LENGTH_VIOLATION", 422,
                       "Duty log duration must not exceed 28.00 hours")
    # Temporal: started_at must fall inside an ACTIVE year of the program.
    if not _inside_active_year(resident, started):
        raise ApiError("ERR_DATE_OUT_OF_ACTIVE_YEAR", 422,
                       "started_at is not inside an ACTIVE academic year of the program")
    # Constraint: no overlap with another non-VOID log of the same resident.
    for other in DB["duty_hour_logs"].values():
        if other["resident_id"] != resident["id"] or other["status"] == "VOID":
            continue
        if started < other["_ended"] and other["_started"] < ended:
            raise conflict("ERR_LOG_TIME_OVERLAP",
                           "Duty log overlaps another non-VOID log of the same resident")
    rec = {
        "id": new_id(),
        "resident_id": resident["id"],
        "started_at": data["started_at"],
        "ended_at": data["ended_at"],
        "_started": started,
        "_ended": ended,
        "_duration": duration,
        "status": "SUBMITTED",
        "void_reason": None,
    }
    core.stamp(rec)
    DB["duty_hour_logs"][rec["id"]] = rec
    return core.pub_duty_log(rec)


def list_duty_logs(args):
    items = list(DB["duty_hour_logs"].values())
    if args.get("resident_id") is not None:
        items = [l for l in items if l["resident_id"] == args.get("resident_id")]
    if args.get("status") is not None:
        items = [l for l in items if l["status"] == args.get("status")]
    items.sort(key=lambda l: l["_seq"])
    return [core.pub_duty_log(l) for l in items]


def get_duty_log_view(lid):
    return core.pub_duty_log(get_duty_log(lid))


def attest_duty_log(lid, user_id, role):
    log = get_duty_log(lid)
    # Ownership (stage 4 semantics) precedes the state precondition.
    _ownership_check(role, user_id, log["resident_id"])
    if log["status"] != "SUBMITTED":
        raise conflict("ERR_LOG_NOT_SUBMITTED", "Attest requires status SUBMITTED")
    log["status"] = "ATTESTED"
    core.touch(log)
    # Surveillance pass, then the auto-remediation aftermath.
    calc.run_violation_detection(log)
    resident = get_resident(log["resident_id"])
    calc.maybe_auto_remediate(resident)
    return core.pub_duty_log(log)


def void_duty_log(lid, data, user_id, role):
    log = get_duty_log(lid)
    _ownership_check(role, user_id, log["resident_id"])
    if log["status"] not in ("SUBMITTED", "ATTESTED"):
        raise conflict("ERR_LOG_NOT_VOIDABLE",
                       "Void requires status SUBMITTED or ATTESTED")
    log["status"] = "VOID"
    log["void_reason"] = data["void_reason"]
    core.touch(log)
    return core.pub_duty_log(log)


# ---------------------------------------------------------------------------
# DutyHourViolation
# ---------------------------------------------------------------------------

def list_violations(args):
    items = list(DB["duty_hour_violations"].values())
    if args.get("resident_id") is not None:
        items = [v for v in items if v["resident_id"] == args.get("resident_id")]
    if args.get("duty_hour_log_id") is not None:
        items = [v for v in items if v["duty_hour_log_id"] == args.get("duty_hour_log_id")]
    if args.get("status") is not None:
        items = [v for v in items if v["status"] == args.get("status")]
    items.sort(key=lambda v: v["_seq"])
    return [core.pub_violation(v) for v in items]


def get_violation_view(vid):
    return core.pub_violation(get_violation(vid))


def acknowledge_violation(vid):
    v = get_violation(vid)
    if v["status"] != "FLAGGED":
        raise conflict("ERR_VIOLATION_NOT_OPEN", "Acknowledge requires status FLAGGED")
    v["status"] = "ACKNOWLEDGED"
    core.touch(v)
    return core.pub_violation(v)


def resolve_violation(vid, data):
    v = get_violation(vid)
    if v["status"] not in ("FLAGGED", "ACKNOWLEDGED"):
        raise conflict("ERR_VIOLATION_NOT_OPEN",
                       "Resolve requires status FLAGGED or ACKNOWLEDGED")
    v["status"] = "RESOLVED"
    v["resolution_note"] = data["resolution_note"]
    core.touch(v)
    return core.pub_violation(v)


def dismiss_violation(vid, data):
    v = get_violation(vid)
    if v["status"] not in ("FLAGGED", "ACKNOWLEDGED"):
        raise conflict("ERR_VIOLATION_NOT_OPEN",
                       "Dismiss requires status FLAGGED or ACKNOWLEDGED")
    justification = data["justification"]
    if len(justification) < 10:
        raise ApiError("ERR_JUSTIFICATION_REQUIRED", 400,
                       "Dismiss justification must be at least 10 characters")
    v["status"] = "DISMISSED"
    v["resolution_note"] = justification
    core.touch(v)
    return core.pub_violation(v)


# ---------------------------------------------------------------------------
# MoonlightingRequest
# ---------------------------------------------------------------------------

def create_moonlighting(data, user_id, role):
    _ownership_check(role, user_id, data["resident_id"])
    resident = get_resident(data["resident_id"])
    # State: the resident must be ACTIVE.
    if resident["lifecycle_status"] != "ACTIVE":
        raise conflict("ERR_RESIDENT_NOT_ACTIVE",
                       "Moonlighting requires an ACTIVE resident")
    # Safety: creation requires GOOD_STANDING.
    if resident["standing_status"] != "GOOD_STANDING":
        raise ApiError("ERR_STANDING_BLOCKS_MOONLIGHTING", 403,
                       "Moonlighting creation requires standing GOOD_STANDING")
    start = parse_dt(data["start_date"])
    end = parse_dt(data["end_date"])
    # Temporal: half-open [start_date, end_date), start strictly before end.
    if not start < end:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422,
                       "start_date must be strictly before end_date")
    # Constraint: no overlap with another SUBMITTED/APPROVED/ACTIVE request;
    # adjacency (end == other start) is NOT an overlap.
    for other in DB["moonlighting_requests"].values():
        if other["resident_id"] != resident["id"]:
            continue
        if other["status"] not in ("SUBMITTED", "APPROVED", "ACTIVE"):
            continue
        if start < other["_end"] and other["_start"] < end:
            raise conflict("ERR_MOONLIGHTING_OVERLAP",
                           "Date range overlaps another SUBMITTED/APPROVED/ACTIVE request")
    rec = {
        "id": new_id(),
        "resident_id": resident["id"],
        "type": data["type"],
        "site_name": data["site_name"],
        "start_date": data["start_date"],
        "end_date": data["end_date"],
        "_start": start,
        "_end": end,
        "_hpw": dec(data["hours_per_week"]),
        "status": "DRAFT",
        "decision_reason": None,
    }
    core.stamp(rec)
    DB["moonlighting_requests"][rec["id"]] = rec
    return core.pub_moonlighting(rec)


def list_moonlighting(args):
    items = list(DB["moonlighting_requests"].values())
    if args.get("resident_id") is not None:
        items = [m for m in items if m["resident_id"] == args.get("resident_id")]
    if args.get("status") is not None:
        items = [m for m in items if m["status"] == args.get("status")]
    items.sort(key=lambda m: m["_seq"])
    return [core.pub_moonlighting(m) for m in items]


def get_moonlighting_view(mid):
    return core.pub_moonlighting(get_moonlighting(mid))


def submit_moonlighting(mid, user_id, role):
    req = get_moonlighting(mid)
    _ownership_check(role, user_id, req["resident_id"])
    if req["status"] != "DRAFT":
        raise conflict("ERR_MOONLIGHTING_NOT_SUBMITTABLE", "Submit requires status DRAFT")
    req["status"] = "SUBMITTED"
    core.touch(req)
    return core.pub_moonlighting(req)


def approve_moonlighting(mid):
    req = get_moonlighting(mid)
    if req["status"] != "SUBMITTED":
        raise conflict("ERR_MOONLIGHTING_NOT_APPROVABLE", "Approve requires status SUBMITTED")
    resident = get_resident(req["resident_id"])
    # Safety: the standing gate re-reads the resident at approval time.
    if resident["standing_status"] != "GOOD_STANDING":
        raise ApiError("ERR_STANDING_BLOCKS_MOONLIGHTING", 403,
                       "Moonlighting approval requires standing GOOD_STANDING")
    # Headroom check (pinned order: base excludes the candidate; the candidate
    # is added exactly once; equality passes).
    decision = calc.headroom_decision_value(req)
    if decision > calc.HOURS_LIMIT:
        raise ApiError("ERR_PROJECTED_HOURS_EXCEED_80", 422,
                       "Rolling projected average plus candidate hours exceeds 80.00")
    req["status"] = "APPROVED"
    core.touch(req)
    return core.pub_moonlighting(req)


def deny_moonlighting(mid, data):
    req = get_moonlighting(mid)
    if req["status"] != "SUBMITTED":
        raise conflict("ERR_MOONLIGHTING_NOT_DENIABLE", "Deny requires status SUBMITTED")
    req["status"] = "DENIED"
    req["decision_reason"] = data["denial_reason"]
    core.touch(req)
    return core.pub_moonlighting(req)


def withdraw_moonlighting(mid, user_id, role):
    req = get_moonlighting(mid)
    _ownership_check(role, user_id, req["resident_id"])
    if req["status"] not in ("DRAFT", "SUBMITTED"):
        raise conflict("ERR_MOONLIGHTING_NOT_WITHDRAWABLE",
                       "Withdraw requires status DRAFT or SUBMITTED")
    req["status"] = "WITHDRAWN"
    core.touch(req)
    return core.pub_moonlighting(req)


def revoke_moonlighting(mid, data):
    req = get_moonlighting(mid)
    if req["status"] not in ("APPROVED", "ACTIVE"):
        raise conflict("ERR_MOONLIGHTING_NOT_REVOKABLE",
                       "Revoke requires status APPROVED or ACTIVE")
    req["status"] = "REVOKED"
    req["decision_reason"] = data["revocation_reason"]
    core.touch(req)
    return core.pub_moonlighting(req)


# ---------------------------------------------------------------------------
# MilestoneEvaluation (immutable; common_fields false)
# ---------------------------------------------------------------------------

def _validate_ratings(entries):
    """Exactly the 6 competencies, each with an integer level 1..5."""
    if not isinstance(entries, list) or len(entries) != 6:
        raise ApiError("ERR_INCOMPLETE_RATINGS", 422,
                       "Ratings must cover exactly the 6 competencies with levels 1..5")
    seen = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INCOMPLETE_RATINGS", 422,
                           "Each rating must be an object with competency and level")
        comp = entry.get("competency")
        level = entry.get("level")
        if comp not in COMPETENCIES or comp in seen:
            raise ApiError("ERR_INCOMPLETE_RATINGS", 422,
                           "Ratings must cover exactly the 6 competencies")
        if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 5:
            raise ApiError("ERR_INCOMPLETE_RATINGS", 422,
                           "Each rating level must be an integer from 1 through 5")
        seen[comp] = level
    if set(seen) != set(COMPETENCIES):
        raise ApiError("ERR_INCOMPLETE_RATINGS", 422,
                       "Ratings must cover exactly the 6 competencies")
    return seen


def create_evaluation(data, user_id, role):
    resident = get_resident(data["resident_id"])
    year = get_year(data["academic_year_id"])
    ratings = _validate_ratings(data["competency_ratings"])
    # Cross-aggregate: the year must belong to the resident's program.
    if year["program_id"] != resident["program_id"]:
        raise ApiError("ERR_CROSS_PROGRAM_REFERENCE", 400,
                       "The academic year must belong to the resident's program")
    rec = {
        "id": new_id(),
        "resident_id": resident["id"],
        "academic_year_id": year["id"],
        "reporting_period": data["reporting_period"],
        "evaluator_id": user_id,
        "evaluator_role": "PROGRAM_DIRECTOR" if role == "ProgramDirector" else "FACULTY",
        "competency_ratings": data["competency_ratings"],
        "_ratings": ratings,
    }
    core.stamp_immutable(rec)
    DB["milestone_evaluations"][rec["id"]] = rec
    return core.pub_evaluation(rec)


def list_evaluations(args):
    items = list(DB["milestone_evaluations"].values())
    if args.get("resident_id") is not None:
        items = [e for e in items if e["resident_id"] == args.get("resident_id")]
    if args.get("academic_year_id") is not None:
        items = [e for e in items if e["academic_year_id"] == args.get("academic_year_id")]
    if args.get("reporting_period") is not None:
        items = [e for e in items if e["reporting_period"] == args.get("reporting_period")]
    items.sort(key=lambda e: e["_seq"])
    return [core.pub_evaluation(e) for e in items]


def get_evaluation_view(eid):
    return core.pub_evaluation(get_evaluation(eid))


# ---------------------------------------------------------------------------
# CCCReview
# ---------------------------------------------------------------------------

def create_ccc_review(data):
    resident = get_resident(data["resident_id"])
    year = get_year(data["academic_year_id"])
    # Constraint: one non-FINALIZED review per (resident, year, period).
    for other in DB["ccc_reviews"].values():
        if (
            other["resident_id"] == resident["id"]
            and other["academic_year_id"] == year["id"]
            and other["reporting_period"] == data["reporting_period"]
            and other["status"] != "FINALIZED"
        ):
            raise conflict("ERR_CCC_REVIEW_EXISTS",
                           "A non-FINALIZED CCC review already exists for this triple")
    # Cross-aggregate: the year must belong to the resident's program.
    if year["program_id"] != resident["program_id"]:
        raise ApiError("ERR_CROSS_PROGRAM_REFERENCE", 400,
                       "The academic year must belong to the resident's program")
    rec = {
        "id": new_id(),
        "resident_id": resident["id"],
        "academic_year_id": year["id"],
        "reporting_period": data["reporting_period"],
        "status": "OPEN",
        "outcome": None,
        "milestone_levels": None,
        "composite_snapshot": None,
    }
    core.stamp(rec)
    DB["ccc_reviews"][rec["id"]] = rec
    return core.pub_ccc_review(rec)


def list_ccc_reviews(args):
    items = list(DB["ccc_reviews"].values())
    if args.get("resident_id") is not None:
        items = [c for c in items if c["resident_id"] == args.get("resident_id")]
    if args.get("academic_year_id") is not None:
        items = [c for c in items if c["academic_year_id"] == args.get("academic_year_id")]
    if args.get("status") is not None:
        items = [c for c in items if c["status"] == args.get("status")]
    items.sort(key=lambda c: c["_seq"])
    return [core.pub_ccc_review(c) for c in items]


def get_ccc_review_view(cid):
    return core.pub_ccc_review(get_ccc_review(cid))


def begin_deliberation(cid):
    c = get_ccc_review(cid)
    if c["status"] != "OPEN":
        raise conflict("ERR_CCC_NOT_OPEN", "Begin-deliberation requires status OPEN")
    c["status"] = "IN_DELIBERATION"
    core.touch(c)
    return core.pub_ccc_review(c)


def reopen_ccc_review(cid):
    c = get_ccc_review(cid)
    if c["status"] != "IN_DELIBERATION":
        raise conflict("ERR_CCC_NOT_IN_DELIBERATION",
                       "Reopen requires status IN_DELIBERATION")
    c["status"] = "OPEN"
    core.touch(c)
    return core.pub_ccc_review(c)


def finalize_ccc_review(cid, data, user_id):
    c = get_ccc_review(cid)
    # Gate order (PRD section 3.7): state, quorum, segregation of duties,
    # outcome enum, ratings completeness.
    if c["status"] != "IN_DELIBERATION":
        raise conflict("ERR_CCC_NOT_IN_DELIBERATION",
                       "Finalize requires status IN_DELIBERATION")
    evals = [
        e for e in DB["milestone_evaluations"].values()
        if e["resident_id"] == c["resident_id"]
        and e["academic_year_id"] == c["academic_year_id"]
        and e["reporting_period"] == c["reporting_period"]
    ]
    if len(evals) < 3:
        raise conflict("ERR_INSUFFICIENT_EVALUATIONS",
                       "Finalize requires at least 3 milestone evaluations for the triple")
    if any(e["evaluator_id"] == user_id for e in evals):
        raise ApiError("ERR_COMMITTEE_ROLE_CONFLICT", 403,
                       "The finalizing chair must not be an evaluator of this period")
    if data["outcome"] not in CCC_OUTCOMES:
        raise ApiError("ERR_INVALID_OUTCOME", 422,
                       "outcome must be SATISFACTORY, NEEDS_IMPROVEMENT, or UNSATISFACTORY")
    _validate_ratings(data["milestone_levels"])
    c["status"] = "FINALIZED"
    c["outcome"] = data["outcome"]
    c["milestone_levels"] = data["milestone_levels"]
    c["composite_snapshot"] = calc.milestone_composite_snapshot(
        c["resident_id"], c["academic_year_id"], c["reporting_period"]
    )
    core.touch(c)
    # Outcome cascades (PRD sections 3.7 and 3.8).
    resident = get_resident(c["resident_id"])
    if c["outcome"] == "NEEDS_IMPROVEMENT":
        start = clock_dt().date()
        end = start + timedelta(days=90)
        plan = {
            "id": new_id(),
            "resident_id": resident["id"],
            "ccc_review_id": c["id"],
            "trigger_source": "CCC_OUTCOME",
            "goals": "Clinical Competency Committee remediation (outcome NEEDS_IMPROVEMENT)",
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "outcome": None,
            "status": "ACTIVE",
            "cancel_reason": None,
        }
        core.stamp(plan)
        DB["remediation_plans"][plan["id"]] = plan
        calc.recompute_standing(resident)
    elif c["outcome"] == "UNSATISFACTORY":
        case = {
            "id": new_id(),
            "resident_id": resident["id"],
            "remediation_plan_id": None,
            "reason": "CCC outcome UNSATISFACTORY",
            "status": "ACTIVE",
            "recommended_by": None,
        }
        core.stamp(case)
        DB["probation_cases"][case["id"]] = case
        calc.recompute_standing(resident)
    return core.pub_ccc_review(c)


# ---------------------------------------------------------------------------
# ProcedureCaseLog
# ---------------------------------------------------------------------------

def create_case_log(data, user_id, role):
    _ownership_check(role, user_id, data["resident_id"])
    resident = get_resident(data["resident_id"])
    rotation = get_rotation(data["rotation_id"])
    # State: the resident must be ACTIVE.
    if resident["lifecycle_status"] != "ACTIVE":
        raise conflict("ERR_RESIDENT_NOT_ACTIVE",
                       "Case logging requires an ACTIVE resident")
    # Temporal: performed_date must fall inside an ACTIVE year of the program.
    performed = parse_dt(data["performed_date"])
    if not _inside_active_year(resident, performed):
        raise ApiError("ERR_DATE_OUT_OF_ACTIVE_YEAR", 422,
                       "performed_date is not inside an ACTIVE academic year of the program")
    rec = {
        "id": new_id(),
        "resident_id": resident["id"],
        "rotation_id": rotation["id"],
        "procedure_category": data["procedure_category"],
        "performed_date": data["performed_date"],
        "role": data["role"],
        "status": "LOGGED",
        "decision_reason": None,
    }
    core.stamp(rec)
    DB["procedure_case_logs"][rec["id"]] = rec
    return core.pub_case_log(rec)


def list_case_logs(args):
    items = list(DB["procedure_case_logs"].values())
    if args.get("resident_id") is not None:
        items = [l for l in items if l["resident_id"] == args.get("resident_id")]
    if args.get("rotation_id") is not None:
        items = [l for l in items if l["rotation_id"] == args.get("rotation_id")]
    if args.get("procedure_category") is not None:
        items = [l for l in items if l["procedure_category"] == args.get("procedure_category")]
    if args.get("status") is not None:
        items = [l for l in items if l["status"] == args.get("status")]
    items.sort(key=lambda l: l["_seq"])
    return [core.pub_case_log(l) for l in items]


def get_case_log_view(lid):
    return core.pub_case_log(get_case_log(lid))


def verify_case_log(lid):
    log = get_case_log(lid)
    if log["status"] != "LOGGED":
        raise conflict("ERR_CASE_LOG_NOT_LOGGED", "Verify requires status LOGGED")
    log["status"] = "VERIFIED"
    core.touch(log)
    return core.pub_case_log(log)


def reject_case_log(lid, data):
    log = get_case_log(lid)
    if log["status"] != "LOGGED":
        raise conflict("ERR_CASE_LOG_NOT_LOGGED", "Reject requires status LOGGED")
    log["status"] = "REJECTED"
    log["decision_reason"] = data["rejection_reason"]
    core.touch(log)
    return core.pub_case_log(log)


def resubmit_case_log(lid, user_id, role):
    log = get_case_log(lid)
    _ownership_check(role, user_id, log["resident_id"])
    if log["status"] != "REJECTED":
        raise conflict("ERR_CASE_LOG_NOT_LOGGED", "Resubmit requires status REJECTED")
    log["status"] = "LOGGED"
    core.touch(log)
    return core.pub_case_log(log)


def void_case_log(lid, data):
    log = get_case_log(lid)
    if log["status"] != "VERIFIED":
        raise conflict("ERR_CASE_LOG_NOT_VERIFIED", "Void requires status VERIFIED")
    log["status"] = "VOIDED"
    log["decision_reason"] = data["void_reason"]
    core.touch(log)
    return core.pub_case_log(log)


# ---------------------------------------------------------------------------
# CaseRequirement
# ---------------------------------------------------------------------------

def create_requirement(data):
    program = get_program(data["program_id"])
    for q in DB["case_requirements"].values():
        if q["program_id"] == program["id"] and q["procedure_category"] == data["procedure_category"]:
            raise conflict("ERR_REQUIREMENT_EXISTS",
                           "A case requirement already exists for (program, procedure_category)")
    rec = {
        "id": new_id(),
        "program_id": program["id"],
        "procedure_category": data["procedure_category"],
        "required_count": data["required_count"],
        "required_primary_count": data["required_primary_count"],
    }
    core.stamp(rec)
    DB["case_requirements"][rec["id"]] = rec
    return core.pub_requirement(rec)


def list_requirements(args):
    items = list(DB["case_requirements"].values())
    if args.get("program_id") is not None:
        items = [q for q in items if q["program_id"] == args.get("program_id")]
    if args.get("procedure_category") is not None:
        items = [q for q in items if q["procedure_category"] == args.get("procedure_category")]
    items.sort(key=lambda q: q["_seq"])
    return [core.pub_requirement(q) for q in items]


def get_requirement_view(qid):
    return core.pub_requirement(get_requirement(qid))


# ---------------------------------------------------------------------------
# RemediationPlan
# ---------------------------------------------------------------------------

def create_plan(data):
    resident = get_resident(data["resident_id"])
    rec = {
        "id": new_id(),
        "resident_id": resident["id"],
        "ccc_review_id": None,
        "trigger_source": "MANUAL",
        "goals": data["goals"],
        "start_date": data["start_date"],
        "end_date": data["end_date"],
        "outcome": None,
        "status": "ACTIVE",
        "cancel_reason": None,
    }
    core.stamp(rec)
    DB["remediation_plans"][rec["id"]] = rec
    calc.recompute_standing(resident)
    return core.pub_plan(rec)


def list_plans(args):
    items = list(DB["remediation_plans"].values())
    if args.get("resident_id") is not None:
        items = [p for p in items if p["resident_id"] == args.get("resident_id")]
    if args.get("ccc_review_id") is not None:
        items = [p for p in items if p.get("ccc_review_id") == args.get("ccc_review_id")]
    if args.get("status") is not None:
        items = [p for p in items if p["status"] == args.get("status")]
    items.sort(key=lambda p: p["_seq"])
    return [core.pub_plan(p) for p in items]


def get_plan_view(pid):
    return core.pub_plan(get_plan(pid))


def complete_plan(pid, data):
    plan = get_plan(pid)
    if plan["status"] != "ACTIVE":
        raise conflict("ERR_REMEDIATION_NOT_ACTIVE", "Complete requires status ACTIVE")
    if data["outcome"] not in PLAN_OUTCOMES:
        raise ApiError("ERR_INVALID_OUTCOME", 422, "outcome must be SUCCESS or FAILURE")
    resident = get_resident(plan["resident_id"])
    if data["outcome"] == "SUCCESS":
        plan["status"] = "COMPLETED_SUCCESS"
        plan["outcome"] = "SUCCESS"
        core.touch(plan)
        calc.recompute_standing(resident)
    else:
        plan["status"] = "COMPLETED_FAILURE"
        plan["outcome"] = "FAILURE"
        core.touch(plan)
        # Escalation: create a probation case unless one is already open.
        open_case = any(
            c["resident_id"] == resident["id"] and c["status"] in ("ACTIVE", "DISMISSAL_RECOMMENDED")
            for c in DB["probation_cases"].values()
        )
        if not open_case:
            case = {
                "id": new_id(),
                "resident_id": resident["id"],
                "remediation_plan_id": plan["id"],
                "reason": "Remediation plan failure",
                "status": "ACTIVE",
                "recommended_by": None,
            }
            core.stamp(case)
            DB["probation_cases"][case["id"]] = case
        calc.recompute_standing(resident)
    return core.pub_plan(plan)


def cancel_plan(pid, data):
    plan = get_plan(pid)
    if plan["status"] != "ACTIVE":
        raise conflict("ERR_REMEDIATION_NOT_ACTIVE", "Cancel requires status ACTIVE")
    plan["status"] = "CANCELLED"
    plan["cancel_reason"] = data["cancel_reason"]
    core.touch(plan)
    resident = get_resident(plan["resident_id"])
    calc.recompute_standing(resident)
    return core.pub_plan(plan)


# ---------------------------------------------------------------------------
# ProbationCase
# ---------------------------------------------------------------------------

def create_probation(data):
    resident = get_resident(data["resident_id"])
    for c in DB["probation_cases"].values():
        if c["resident_id"] == resident["id"] and c["status"] in ("ACTIVE", "DISMISSAL_RECOMMENDED"):
            raise conflict("ERR_OPEN_PROBATION_EXISTS",
                           "An ACTIVE or DISMISSAL_RECOMMENDED case already exists for the resident")
    rec = {
        "id": new_id(),
        "resident_id": resident["id"],
        "remediation_plan_id": None,
        "reason": data["reason"],
        "status": "ACTIVE",
        "recommended_by": None,
    }
    core.stamp(rec)
    DB["probation_cases"][rec["id"]] = rec
    calc.recompute_standing(resident)
    return core.pub_probation(rec)


def list_probation(args):
    items = list(DB["probation_cases"].values())
    if args.get("resident_id") is not None:
        items = [c for c in items if c["resident_id"] == args.get("resident_id")]
    if args.get("remediation_plan_id") is not None:
        items = [c for c in items if c.get("remediation_plan_id") == args.get("remediation_plan_id")]
    if args.get("status") is not None:
        items = [c for c in items if c["status"] == args.get("status")]
    items.sort(key=lambda c: c["_seq"])
    return [core.pub_probation(c) for c in items]


def get_probation_view(pid):
    return core.pub_probation(get_probation(pid))


def lift_probation(pid):
    case = get_probation(pid)
    if case["status"] != "ACTIVE":
        raise conflict("ERR_PROBATION_NOT_ACTIVE", "Lift requires status ACTIVE")
    case["status"] = "LIFTED"
    core.touch(case)
    resident = get_resident(case["resident_id"])
    calc.recompute_standing(resident)
    return core.pub_probation(case)


def recommend_dismissal(pid, user_id):
    case = get_probation(pid)
    if case["status"] != "ACTIVE":
        raise conflict("ERR_PROBATION_NOT_ACTIVE", "Recommend-dismissal requires status ACTIVE")
    case["status"] = "DISMISSAL_RECOMMENDED"
    case["recommended_by"] = user_id
    core.touch(case)
    resident = get_resident(case["resident_id"])
    calc.recompute_standing(resident)
    return core.pub_probation(case)


def confirm_dismissal(pid, user_id):
    case = get_probation(pid)
    # Segregation of duties (stage 4) precedes the state precondition.
    if case.get("recommended_by") is not None and user_id == case["recommended_by"]:
        raise ApiError("ERR_DISMISSAL_CONFIRMATION_CONFLICT", 403,
                       "The confirmer must differ from the recommender")
    if case["status"] != "DISMISSAL_RECOMMENDED":
        raise conflict("ERR_PROBATION_NOT_RECOMMENDED",
                       "Confirm-dismissal requires status DISMISSAL_RECOMMENDED")
    case["status"] = "DISMISSED"
    core.touch(case)
    resident = get_resident(case["resident_id"])
    # Cascade: resident moves ACTIVE/ON_LEAVE -> DISMISSED; complement fill recomputes.
    if resident["lifecycle_status"] in ("ACTIVE", "ON_LEAVE"):
        resident["lifecycle_status"] = "DISMISSED"
        core.touch(resident)
        calc.touch_complement_for_resident(resident)
    calc.recompute_standing(resident)
    return core.pub_probation(case)


# ---------------------------------------------------------------------------
# AccreditationCitation
# ---------------------------------------------------------------------------

def _create_citation(program_id, citation_code, severity, area_code, due_date,
                     annual_survey_id=None):
    rec = {
        "id": new_id(),
        "program_id": program_id,
        "annual_survey_id": annual_survey_id,
        "citation_code": citation_code,
        "area_code": area_code,
        "severity": severity,
        "received_date": clock_date_str(),
        "due_date": due_date,
        "status": "OPEN",
        "response_text": None,
        "resolution_note": None,
        "escalation_reason": None,
    }
    core.stamp(rec)
    DB["accreditation_citations"][rec["id"]] = rec
    return rec


def create_citation(data):
    program = get_program(data["program_id"])
    rec = _create_citation(
        program["id"], data["citation_code"], data["severity"], data["area_code"],
        data["due_date"],
    )
    calc.recompute_program_status(program)
    return core.pub_citation(rec)


def list_citations(args):
    items = list(DB["accreditation_citations"].values())
    if args.get("program_id") is not None:
        items = [c for c in items if c["program_id"] == args.get("program_id")]
    if args.get("annual_survey_id") is not None:
        items = [c for c in items if c.get("annual_survey_id") == args.get("annual_survey_id")]
    if args.get("status") is not None:
        items = [c for c in items if c["status"] == args.get("status")]
    if args.get("severity") is not None:
        items = [c for c in items if c["severity"] == args.get("severity")]
    items.sort(key=lambda c: c["_seq"])
    return [core.pub_citation(c) for c in items]


def get_citation_view(cid):
    return core.pub_citation(get_citation(cid))


def draft_citation_response(cid, data):
    c = get_citation(cid)
    if c["status"] not in ("OPEN", "ESCALATED"):
        raise conflict("ERR_CITATION_NOT_DRAFTABLE",
                       "Draft-response requires status OPEN or ESCALATED")
    c["status"] = "RESPONSE_DRAFTED"
    c["response_text"] = data["response_text"]
    core.touch(c)
    calc.recompute_program_status(get_program(c["program_id"]))
    return core.pub_citation(c)


def submit_citation_response(cid):
    c = get_citation(cid)
    if c["status"] != "RESPONSE_DRAFTED":
        raise conflict("ERR_CITATION_RESPONSE_NOT_DRAFTED",
                       "Submit-response requires status RESPONSE_DRAFTED")
    c["status"] = "RESPONSE_SUBMITTED"
    core.touch(c)
    return core.pub_citation(c)


def resolve_citation(cid, data):
    c = get_citation(cid)
    if c["status"] != "RESPONSE_SUBMITTED":
        raise conflict("ERR_CITATION_NOT_RESOLVABLE",
                       "Resolve requires status RESPONSE_SUBMITTED")
    c["status"] = "RESOLVED"
    c["resolution_note"] = data["resolution_note"]
    core.touch(c)
    calc.recompute_program_status(get_program(c["program_id"]))
    return core.pub_citation(c)


def escalate_citation(cid, data):
    c = get_citation(cid)
    if c["status"] != "RESPONSE_SUBMITTED":
        raise conflict("ERR_CITATION_NOT_ESCALATABLE",
                       "Escalate requires status RESPONSE_SUBMITTED")
    c["status"] = "ESCALATED"
    c["escalation_reason"] = data["escalation_reason"]
    core.touch(c)
    calc.recompute_program_status(get_program(c["program_id"]))
    return core.pub_citation(c)


# ---------------------------------------------------------------------------
# AnnualSurvey
# ---------------------------------------------------------------------------

def create_survey(data):
    program = get_program(data["program_id"])
    year = get_year(data["academic_year_id"])
    for s in DB["annual_surveys"].values():
        if s["program_id"] == program["id"] and s["academic_year_id"] == year["id"]:
            raise conflict("ERR_SURVEY_EXISTS",
                           "An annual survey already exists for (program, academic year)")
    if year["program_id"] != program["id"]:
        raise ApiError("ERR_CROSS_PROGRAM_REFERENCE", 400,
                       "The survey's academic year must belong to its program")
    rec = {
        "id": new_id(),
        "program_id": program["id"],
        "academic_year_id": year["id"],
        "status": "OPEN",
        "_rrate": None,
        "_frate": None,
        "area_results": None,
        "flagged_area_count": None,
    }
    core.stamp(rec)
    DB["annual_surveys"][rec["id"]] = rec
    return core.pub_survey(rec)


def list_surveys(args):
    items = list(DB["annual_surveys"].values())
    if args.get("program_id") is not None:
        items = [s for s in items if s["program_id"] == args.get("program_id")]
    if args.get("academic_year_id") is not None:
        items = [s for s in items if s["academic_year_id"] == args.get("academic_year_id")]
    if args.get("status") is not None:
        items = [s for s in items if s["status"] == args.get("status")]
    items.sort(key=lambda s: s["_seq"])
    return [core.pub_survey(s) for s in items]


def get_survey_view(sid):
    return core.pub_survey(get_survey(sid))


def _rate_in_range(value):
    return Decimal("0.00") <= value <= Decimal("100.00")


def close_survey(sid, data):
    survey = get_survey(sid)
    if survey["status"] != "OPEN":
        raise conflict("ERR_SURVEY_NOT_OPEN", "Close requires status OPEN")
    rrate = dec(data["resident_response_rate"])
    frate = dec(data["faculty_response_rate"])
    areas = data["area_results"]
    if not _rate_in_range(rrate) or not _rate_in_range(frate):
        raise ApiError("ERR_INVALID_SURVEY_RATE", 422,
                       "Response rates must lie within 0.00..100.00")
    for entry in areas:
        if not _rate_in_range(dec(entry["compliance_pct"])):
            raise ApiError("ERR_INVALID_SURVEY_RATE", 422,
                           "Area compliance_pct must lie within 0.00..100.00")
    threshold = Decimal("70.00")
    flagged = [e for e in areas if dec(e["compliance_pct"]) < threshold]
    survey["status"] = "CLOSED"
    survey["_rrate"] = round2(rrate)
    survey["_frate"] = round2(frate)
    survey["area_results"] = areas
    survey["flagged_area_count"] = len(flagged)
    core.touch(survey)
    # Citation cascade (PRD section 3.9).
    program = get_program(survey["program_id"])
    year = get_year(survey["academic_year_id"])
    year_label = year["year_label"]
    if rrate < threshold:
        _create_citation(program["id"], f"SURVEY-RESPONSE_RATE-{year_label}",
                         "WARNING", "RESPONSE_RATE", None, annual_survey_id=survey["id"])
    if frate < threshold:
        _create_citation(program["id"], f"SURVEY-FACULTY-{year_label}",
                         "WARNING", "RESPONSE_RATE", None, annual_survey_id=survey["id"])
    area_severity = "SERIOUS" if len(flagged) >= 3 else "WARNING"
    for entry in flagged:
        _create_citation(program["id"], f"SURVEY-{entry['area_code']}-{year_label}",
                         area_severity, entry["area_code"], None,
                         annual_survey_id=survey["id"])
    calc.recompute_program_status(program)
    return core.pub_survey(survey)
