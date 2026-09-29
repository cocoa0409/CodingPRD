"""Deterministic assessor selection and assignment creation (PRD 3.6, 3.9)."""
from datetime import timedelta

from db import assignments_of_claim, db, new_row, order_rows
from errors import ApiError
from services.sla import (at_risk_offset_hours, turnaround_hours)
from util import ASSIGNMENT_BUFFER_HOURS, dtv, put_dt, touch

LIVE_STATUSES = ("ASSIGNED", "ACCEPTED")


def rank_floor(course):
    return 3 if course["level"] == "UPPER" else 2


def ever_assigned(claim_id, assessor_id):
    return any(a["assessor_id"] == assessor_id for a in assignments_of_claim(claim_id))


def conflict_count(assessor_id, window_start, window_end):
    """Closed new window against 24h-padded closed windows of live assignments."""
    count = 0
    pad = timedelta(hours=ASSIGNMENT_BUFFER_HOURS)
    for assignment in db.assignments.values():
        if assignment["assessor_id"] != assessor_id:
            continue
        if assignment["status"] not in LIVE_STATUSES:
            continue
        start = dtv(assignment, "assigned_at")
        end = dtv(assignment, "due_at")
        if start is None or end is None:
            continue
        if window_start <= end + pad and start - pad <= window_end:
            count += 1
    return count


def has_capacity(assessor, window_start, window_end):
    limit = assessor["max_concurrent_assignments"]
    return conflict_count(assessor["id"], window_start, window_end) < limit


def assignment_window(claim, assigned_at):
    sla_hours = turnaround_hours(claim)
    return assigned_at, assigned_at + timedelta(hours=sla_hours), sla_hours


def failing_predicates(assessor, course, claim, window, for_reviewer=False, appeal=None):
    """Returns an ordered list of predicate failure tokens."""
    failures = []
    if for_reviewer and appeal is not None and assessor["id"] in (appeal.get("prior_scorer_assessor_ids") or []):
        failures.append("segregation")
    if not for_reviewer and ever_assigned(claim["id"], assessor["id"]):
        failures.append("already_assigned")
    if assessor["status"] != "ACTIVE":
        failures.append("inactive")
    if assessor["department_code"] != course["department_code"]:
        failures.append("not_eligible")
    if assessor["credential_rank"] < rank_floor(course):
        failures.append("not_eligible")
    if for_reviewer and not assessor["appeal_panel_member"]:
        failures.append("not_eligible")
    if not has_capacity(assessor, window[0], window[1]):
        failures.append("capacity")
    return failures


def rank_pool(pool):
    return order_rows(pool, [
        (lambda a: a["active_assignment_count"], False),
        (lambda a: a["credential_rank"], True),
        (lambda a: a["created_at"], False),
        (lambda a: a["employee_number"], False),
    ])


def eligible_pool(course, claim, window, for_reviewer=False, appeal=None):
    pool = []
    for assessor in db.assessors.values():
        if not failing_predicates(assessor, course, claim, window, for_reviewer, appeal):
            pool.append(assessor)
    return rank_pool(pool)


def resolve_named(assessor, course, claim, window, for_reviewer=False, appeal=None):
    """Distinguished failure modes for an explicitly named candidate."""
    failures = failing_predicates(assessor, course, claim, window, for_reviewer, appeal)
    if "segregation" in failures:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if "already_assigned" in failures:
        raise ApiError("ERR_ASSESSOR_ALREADY_ASSIGNED")
    if "inactive" in failures:
        raise ApiError("ERR_ASSESSOR_INACTIVE")
    if "not_eligible" in failures:
        raise ApiError("ERR_ASSESSOR_NOT_ELIGIBLE")
    if "capacity" in failures:
        raise ApiError("ERR_ASSESSOR_CAPACITY_CONFLICT")
    return assessor


def create_assignment(claim, assessor, selection_reason):
    assigned_at = db.clock
    sla_hours = turnaround_hours(claim)
    assignment = new_row("AssessorAssignment")
    assignment["claim_id"] = claim["id"]
    assignment["assessor_id"] = assessor["id"]
    assignment["status"] = "ASSIGNED"
    assignment["selection_reason"] = selection_reason
    put_dt(assignment, "assigned_at", assigned_at)
    put_dt(assignment, "accepted_at", None)
    assignment["sla_hours"] = sla_hours
    put_dt(assignment, "due_at", assigned_at + timedelta(hours=sla_hours))
    put_dt(assignment, "at_risk_at", assigned_at + timedelta(hours=at_risk_offset_hours(sla_hours)))
    assignment["elapsed_bp"] = 0
    assignment["sla_state"] = "ON_TRACK"
    put_dt(assignment, "rubric_submitted_at", None)
    assignment["recommendation"] = None
    assignment["verified_coverage_bp"] = None
    assignment["revoke_reason"] = None
    assignment["decline_reason"] = None
    db.assignments[assignment["id"]] = assignment

    assessor["active_assignment_count"] += 1
    touch(assessor)
    claim["assessment_status"] = "UNDER_ASSESSMENT"
    claim["hold_reason"] = None
    touch(claim)
    return assignment


def create_replacement(claim):
    """Selector rerun excluding every assessor ever assigned to this claim."""
    course = db.courses.get(claim["course_id"])
    if course is None:
        return None
    assigned_at = db.clock
    window = assignment_window(claim, assigned_at)
    pool = eligible_pool(course, claim, (window[0], window[1]))
    if not pool:
        claim["hold_reason"] = "NO_ELIGIBLE_ASSESSOR"
        touch(claim)
        return None
    return create_assignment(claim, pool[0], "AUTO_REPLACEMENT")
