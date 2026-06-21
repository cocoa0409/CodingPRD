"""Routes for ExternshipAssignment, LicensureExamAttempt, PlacementOutcome."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_role, ALL_ROLES
from helpers import (
    get_json_body, serialize, stamp_new, bump, paginate, sorted_collection,
    find_or_404, as_int, as_number, as_enum, as_str,
)
from response import success
import services

bp = Blueprint("externship", __name__)


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection. Touch (end==start) is NOT overlap."""
    return a_start < b_end and b_start < a_end


# ==========================================================================
# ExternshipAssignment
# ==========================================================================
@bp.post("/v1/externship-assignments")
def create_assignment():
    require_role(["AcademicAdvisor"])
    body = get_json_body()
    agreement_id = body.get("agreement_id")
    if agreement_id is None or not isinstance(agreement_id, str) or agreement_id == "":
        raise err("ERR_INVALID_REQUEST", "Missing required field: agreement_id")
    site_id = body.get("site_id")
    if site_id is None or not isinstance(site_id, str) or site_id == "":
        raise err("ERR_INVALID_REQUEST", "Missing required field: site_id")
    # Existence resolved left-to-right (agreement, then site).
    agreement = find_or_404(store.enrollment_agreements, agreement_id, "EnrollmentAgreement")
    site = find_or_404(store.externship_sites, site_id, "ExternshipSite")

    start_idx = as_int(body, "start_term_index", required=True, minimum=0)
    end_idx = as_int(body, "end_term_index", required=True)
    planned_hours = as_number(body, "planned_hours", required=True, exclusive_min=0)
    if end_idx <= start_idx:
        raise err("ERR_INVALID_REQUEST", "end_term_index must be > start_term_index.")

    # Priority 9.5: site must be ACTIVE.
    if site["status"] != "ACTIVE":
        raise err("ERR_SITE_SUSPENDED", "Externship site is SUSPENDED.")

    # Priority 10: window must not overlap a non-terminal assignment of the SAME
    # agreement. Non-terminal = PLACED or IN_PROGRESS.
    for asg in store.externship_assignments.values():
        if (asg["agreement_id"] == agreement_id
                and asg["status"] in ("PLACED", "IN_PROGRESS")
                and _windows_overlap(start_idx, end_idx,
                                     asg["start_term_index"], asg["end_term_index"])):
            raise err("ERR_EXTERNSHIP_WINDOW_CONFLICT",
                      "Window overlaps an existing assignment of the same agreement.")

    # Priority 11: site capacity — overlapping {PLACED,IN_PROGRESS} at the site.
    overlapping = 0
    for asg in store.externship_assignments.values():
        if (asg["site_id"] == site_id
                and asg["status"] in ("PLACED", "IN_PROGRESS")
                and _windows_overlap(start_idx, end_idx,
                                     asg["start_term_index"], asg["end_term_index"])):
            overlapping += 1
    if overlapping >= site["daily_slot_capacity"]:
        raise err("ERR_SITE_CAPACITY_EXCEEDED",
                  "Overlapping assignments would exceed site capacity.")

    assignment = {
        "agreement_id": agreement_id,
        "site_id": site_id,
        "start_term_index": start_idx,
        "end_term_index": end_idx,
        "planned_hours": planned_hours,
        "verified_hours": 0,
        "status": "PLACED",
    }
    stamp_new(assignment)
    store.externship_assignments[assignment["id"]] = assignment
    site["active_assignment_count"] += 1
    bump(site)
    return success(serialize(assignment), 201)


@bp.get("/v1/externship-assignments")
def list_assignments():
    require_role(ALL_ROLES)
    agreement_id = request.args.get("agreement_id")
    site_id = request.args.get("site_id")
    status = request.args.get("status")

    def pred(e):
        if agreement_id and e["agreement_id"] != agreement_id:
            return False
        if site_id and e["site_id"] != site_id:
            return False
        if status and e["status"] != status:
            return False
        return True

    items = sorted_collection(store.externship_assignments, predicate=pred)
    page, meta = paginate(items)
    return success([serialize(e) for e in page], 200, pagination=meta)


@bp.get("/v1/externship-assignments/<eid>")
def get_assignment(eid):
    require_role(ALL_ROLES)
    asg = find_or_404(store.externship_assignments, eid, "ExternshipAssignment")
    return success(serialize(asg), 200)


@bp.post("/v1/externship-assignments/<eid>/begin")
def begin_assignment(eid):
    require_role(["AcademicAdvisor"])
    asg = find_or_404(store.externship_assignments, eid, "ExternshipAssignment")
    if asg["status"] != "PLACED":
        raise err("ERR_INVALID_STATE", "Assignment must be PLACED to begin.")
    if store.clock()["current_term_index"] < asg["start_term_index"]:
        raise err("ERR_EXTERNSHIP_NOT_STARTED",
                  "Clock has not reached the assignment start_term_index.")
    agreement = store.enrollment_agreements[asg["agreement_id"]]
    if agreement["status"] != "ENROLLED":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ENROLLED.")
    asg["status"] = "IN_PROGRESS"
    bump(asg)
    return success(serialize(asg), 200)


@bp.post("/v1/externship-assignments/<eid>/complete")
def complete_assignment(eid):
    require_role(["AcademicAdvisor"])
    asg = find_or_404(store.externship_assignments, eid, "ExternshipAssignment")
    body = get_json_body()
    if asg["status"] != "IN_PROGRESS":
        # Body validity precedes state per §2.5.
        as_number(body, "actual_hours", required=True, exclusive_min=0)
        raise err("ERR_INVALID_STATE", "Assignment must be IN_PROGRESS to complete.")
    actual_hours = as_number(body, "actual_hours", required=True, exclusive_min=0)

    asg["verified_hours"] = actual_hours
    asg["status"] = "COMPLETED"
    bump(asg)

    agreement = store.enrollment_agreements[asg["agreement_id"]]
    # System-generated EXTERNSHIP attendance entry.
    entry = {
        "agreement_id": agreement["id"],
        "term_index": store.clock()["current_term_index"],
        "kind": "EXTERNSHIP",
        "scheduled_hours": actual_hours,
        "attended_hours": actual_hours,
        "status": "POSTED",
    }
    stamp_new(entry)
    store.attendance_entries[entry["id"]] = entry

    services.recompute_agreement(agreement)
    bump(agreement)

    site = store.externship_sites[asg["site_id"]]
    site["active_assignment_count"] -= 1
    bump(site)
    return success(serialize(asg), 200)


@bp.post("/v1/externship-assignments/<eid>/terminate")
def terminate_assignment(eid):
    require_role(["AcademicAdvisor"])
    asg = find_or_404(store.externship_assignments, eid, "ExternshipAssignment")
    if asg["status"] not in ("PLACED", "IN_PROGRESS"):
        raise err("ERR_INVALID_STATE", "Assignment must be PLACED or IN_PROGRESS to terminate.")
    asg["status"] = "TERMINATED"
    bump(asg)
    site = store.externship_sites[asg["site_id"]]
    site["active_assignment_count"] -= 1
    bump(site)
    return success(serialize(asg), 200)


# ==========================================================================
# LicensureExamAttempt
# ==========================================================================
@bp.post("/v1/licensure-exam-attempts")
def create_exam():
    require_role(["AcademicAdvisor"])
    body = get_json_body()
    agreement_id = body.get("agreement_id")
    if agreement_id is None or not isinstance(agreement_id, str) or agreement_id == "":
        raise err("ERR_INVALID_REQUEST", "Missing required field: agreement_id")
    agreement = find_or_404(store.enrollment_agreements, agreement_id, "EnrollmentAgreement")

    attempt_index = as_int(body, "attempt_index", required=True, minimum=1)
    scaled_score = as_int(body, "scaled_score", required=True, minimum=0, maximum=1000)
    passing_score = as_int(body, "passing_score", required=True, minimum=0, maximum=1000)

    # Uniqueness: attempt_index unique per agreement.
    for a in store.licensure_exam_attempts.values():
        if a["agreement_id"] == agreement_id and a["attempt_index"] == attempt_index:
            raise err("ERR_DUPLICATE_KEY", "attempt_index already exists for agreement.")

    if agreement["status"] not in ("ENROLLED", "GRADUATED"):
        raise err("ERR_AGREEMENT_NOT_ACTIVE",
                  "Agreement must be ENROLLED or GRADUATED to record an exam attempt.")

    result = "PASS" if scaled_score >= passing_score else "FAIL"
    attempt = {
        "agreement_id": agreement_id,
        "attempt_index": attempt_index,
        "scaled_score": scaled_score,
        "passing_score": passing_score,
        "result": result,
    }
    stamp_new(attempt)
    store.licensure_exam_attempts[attempt["id"]] = attempt

    # Recompute licensure eligibility on the agreement; that is a mutation.
    services.recompute_agreement(agreement)
    bump(agreement)
    return success(serialize(attempt), 201)


@bp.get("/v1/licensure-exam-attempts")
def list_exams():
    require_role(ALL_ROLES)
    agreement_id = request.args.get("agreement_id")
    result = request.args.get("result")

    def pred(e):
        if agreement_id and e["agreement_id"] != agreement_id:
            return False
        if result and e["result"] != result:
            return False
        return True

    items = sorted_collection(store.licensure_exam_attempts, predicate=pred)
    page, meta = paginate(items)
    return success([serialize(e) for e in page], 200, pagination=meta)


@bp.get("/v1/licensure-exam-attempts/<eid>")
def get_exam(eid):
    require_role(ALL_ROLES)
    attempt = find_or_404(store.licensure_exam_attempts, eid, "LicensureExamAttempt")
    return success(serialize(attempt), 200)


# ==========================================================================
# PlacementOutcome
# ==========================================================================
@bp.post("/v1/placement-outcomes")
def create_placement():
    require_role(["AcademicAdvisor"])
    body = get_json_body()
    agreement_id = body.get("agreement_id")
    if agreement_id is None or not isinstance(agreement_id, str) or agreement_id == "":
        raise err("ERR_INVALID_REQUEST", "Missing required field: agreement_id")
    agreement = find_or_404(store.enrollment_agreements, agreement_id, "EnrollmentAgreement")

    outcome_term = as_int(body, "outcome_term_index", required=True, minimum=0)
    outcome_type = as_enum(
        body, "outcome_type",
        {"EMPLOYED_IN_FIELD", "EMPLOYED_RELATED", "CONTINUING_EDUCATION", "NOT_PLACED"},
        required=True)
    # employer_name required unless NOT_PLACED or CONTINUING_EDUCATION.
    employer_name = None
    if outcome_type in ("EMPLOYED_IN_FIELD", "EMPLOYED_RELATED"):
        employer_name = as_str(body, "employer_name", required=True)
    else:
        if "employer_name" in body and body["employer_name"] is not None:
            employer_name = as_str(body, "employer_name", required=True)

    if agreement["status"] != "GRADUATED":
        raise err("ERR_AGREEMENT_NOT_ACTIVE",
                  "Agreement must be GRADUATED to record a placement outcome.")

    counts_as_placed = outcome_type in ("EMPLOYED_IN_FIELD", "EMPLOYED_RELATED")
    outcome = {
        "agreement_id": agreement_id,
        "outcome_term_index": outcome_term,
        "outcome_type": outcome_type,
        "employer_name": employer_name,
        "counts_as_placed": counts_as_placed,
    }
    stamp_new(outcome)
    store.placement_outcomes[outcome["id"]] = outcome
    return success(serialize(outcome), 201)


@bp.get("/v1/placement-outcomes")
def list_placements():
    require_role(ALL_ROLES)
    agreement_id = request.args.get("agreement_id")
    outcome_type = request.args.get("outcome_type")

    def pred(e):
        if agreement_id and e["agreement_id"] != agreement_id:
            return False
        if outcome_type and e["outcome_type"] != outcome_type:
            return False
        return True

    items = sorted_collection(store.placement_outcomes, predicate=pred)
    page, meta = paginate(items)
    return success([serialize(e) for e in page], 200, pagination=meta)


@bp.get("/v1/placement-outcomes/<pid>")
def get_placement(pid):
    require_role(ALL_ROLES)
    outcome = find_or_404(store.placement_outcomes, pid, "PlacementOutcome")
    return success(serialize(outcome), 200)
