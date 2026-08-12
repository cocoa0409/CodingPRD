"""ScheduleChangeRequest routes (window workflow: claim/decide/execute...)."""

from decimal import Decimal

from flask import Blueprint, request

import db
import domain
import engine
import serializers as ser
from auth import require_role, body
from envelope import success_object, success_list, paginate
from errors import (ApiError, invalid_request, invalid_posture, invalid_state,
                    forbidden_ownership, ERR_COURSE_INELIGIBLE,
                    ERR_STUDENT_PERIOD_CONFLICT, ERR_SECTION_FULL,
                    ERR_CREDIT_CEILING_EXCEEDED, ERR_SINGLETON_CAP_EXCEEDED,
                    ERR_CHANGE_QUOTA_EXCEEDED, ERR_COHORT_CAP_EXCEEDED,
                    ERR_NO_ELIGIBLE_SECTION, ERR_SEGREGATION_OF_DUTIES)
from util import to_d
from validate import (new_record, touch, req_field, as_str, occ_early,
                      occ_required, fk_or_404, get_or_404)

bp = Blueprint("change_requests", __name__)

KINDS = ("DROP", "ADD", "SWAP")


def _add_checks(student, term, add_section, add_course, drop_entry,
                check_program, check_cohort):
    """Business guards on the section being joined, in pipeline priority
    order. drop_entry is excluded from period/singleton math for SWAP."""
    drop_id = drop_entry["id"] if drop_entry else None
    if check_program and add_course["special_program_exclusive"] != "NONE" \
            and student["special_program"] != add_course["special_program_exclusive"]:
        raise ApiError(ERR_COURSE_INELIGIBLE, 422,
                       "Course is restricted to a special program")
    taken = domain.student_enrolled_periods(student["id"], term["id"],
                                            exclude_entry_id=drop_id)
    if add_section.get("period") in taken:
        raise ApiError(ERR_STUDENT_PERIOD_CONFLICT, 409,
                       "Target section's period collides with another "
                       "ENROLLED entry")
    if domain.section_enrolled_count(add_section["id"]) >= add_section["capacity"]:
        raise ApiError(ERR_SECTION_FULL, 422,
                       "Target section is at capacity")
    load = domain.student_planned_credit_load(student["id"], term["id"])
    if load + to_d(add_course["credits"]) > domain.CREDIT_LOAD_CEILING:
        raise ApiError(ERR_CREDIT_CEILING_EXCEEDED, 422,
                       "Change would push planned_credit_load above 8.0")
    cap = term["singleton_section_cap"]
    if cap > 0:
        count = domain.student_singleton_count(student["id"], term["id"],
                                               exclude_entry_id=drop_id)
        if add_course["singleton"]:
            count += 1
        if count > cap:
            raise ApiError(ERR_SINGLETON_CAP_EXCEEDED, 422,
                           "Change would exceed the singleton section cap")
    if check_cohort and student["special_program"] != "NONE":
        counts = domain.section_cohort_counts(add_section["id"])
        prog = student["special_program"]
        if (counts.get(prog, 0) + 1
                > domain.cohort_half_cap(add_section["capacity"])):
            raise ApiError(ERR_COHORT_CAP_EXCEEDED, 422,
                           "Change would push the section's cohort above half "
                           "its capacity")
    if add_section["state"] != "PUBLISHED":
        raise ApiError(ERR_NO_ELIGIBLE_SECTION, 422,
                       "No PUBLISHED section passes the placement selector")


def _quota_check(student_id, term):
    approved = sum(1 for r in db.change_requests.values()
                   if r["student_id"] == student_id and r["term_id"] == term["id"]
                   and r["state"] == "APPROVED")
    if approved >= term["change_request_max_per_student"]:
        raise ApiError(ERR_CHANGE_QUOTA_EXCEEDED, 422,
                       "Student already holds the maximum number of approved "
                       "change requests")


@bp.post("/scheduling/change-requests")
def create_change_request():
    user_id, _ = require_role("Student")
    data = body()
    student_id = req_field(data, "student_id")
    term_id = req_field(data, "term_id")
    if not isinstance(student_id, str) or not isinstance(term_id, str):
        raise invalid_request("student_id and term_id must be strings")
    student = fk_or_404(db.students, student_id, "student_id")
    term = fk_or_404(db.terms, term_id, "term_id")
    drop_entry = fk_or_404(db.schedule_entries, data.get("drop_entry_id"),
                           "drop_entry_id")
    add_section = fk_or_404(db.sections, data.get("add_section_id"),
                            "add_section_id")
    if term["posture"] != "CHANGE_WINDOW":
        raise invalid_posture("Change requests require the change window to "
                              "be open")
    if user_id != student["id"]:
        raise forbidden_ownership()
    kind = req_field(data, "kind")
    if kind not in KINDS:
        raise invalid_request("kind must be one of DROP|ADD|SWAP")
    reason = as_str(req_field(data, "reason"), "reason")
    if not 10 <= len(reason) <= 500:
        raise invalid_request("reason must be 10-500 characters")
    if kind in ("DROP", "SWAP") and drop_entry is None:
        raise invalid_request("drop_entry_id is required for DROP and SWAP")
    if kind == "ADD" and data.get("drop_entry_id") is not None:
        raise invalid_request("drop_entry_id is forbidden for ADD")
    if kind in ("ADD", "SWAP") and add_section is None:
        raise invalid_request("add_section_id is required for ADD and SWAP")
    if kind == "DROP" and data.get("add_section_id") is not None:
        raise invalid_request("add_section_id is forbidden for DROP")
    r = new_record()
    r.update({"student_id": student_id, "term_id": term_id, "kind": kind,
              "drop_entry_id": drop_entry["id"] if drop_entry else None,
              "add_section_id": add_section["id"] if add_section else None,
              "reason": reason, "state": "SUBMITTED",
              "reviewed_by_counselor_id": None, "decided_by_admin": False})
    db.change_requests[r["id"]] = r
    return success_object(ser.change_request(r), 201)


@bp.get("/scheduling/change-requests")
def list_change_requests():
    require_role("Administrator", "Counselor", "Student")
    rows = list(db.change_requests.values())
    for param in ("student_id", "term_id", "state", "kind", "drop_entry_id",
                  "add_section_id", "reviewed_by_counselor_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if r.get(param) == v]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.change_request(r) for r in page],
                        limit, offset, total)


@bp.get("/scheduling/change-requests/<rid>")
def get_change_request(rid):
    require_role("Administrator", "Counselor", "Student")
    return success_object(ser.change_request(get_or_404(db.change_requests, rid)))


@bp.post("/scheduling/change-requests/<rid>/claim")
def claim(rid):
    user_id, _ = require_role("Counselor")
    r = get_or_404(db.change_requests, rid)
    term = get_or_404(db.terms, r["term_id"])
    if term["posture"] != "CHANGE_WINDOW":
        raise invalid_posture("Claiming requires the change window to be open")
    if r["state"] != "SUBMITTED":
        raise invalid_state("Only SUBMITTED requests can be claimed")
    student = db.students.get(r["student_id"])
    if student is None or student["counselor_id"] != user_id:
        raise forbidden_ownership("Only the student's counselor may claim")
    r["state"] = "COUNSELOR_REVIEW"
    r["reviewed_by_counselor_id"] = user_id
    r["version"] += 1
    touch(r)
    return success_object(ser.change_request(r))


@bp.post("/scheduling/change-requests/<rid>/return-for-revision")
def return_for_revision(rid):
    user_id, _ = require_role("Counselor")
    r = get_or_404(db.change_requests, rid)
    if r["state"] != "COUNSELOR_REVIEW":
        raise invalid_state("Only requests in COUNSELOR_REVIEW can be "
                            "returned for revision")
    if r["reviewed_by_counselor_id"] != user_id:
        raise forbidden_ownership("Only the reviewing counselor may return "
                                  "the request")
    data = body()
    note = as_str(req_field(data, "revision_note"), "revision_note")
    r["state"] = "REVISED"
    r["version"] += 1
    touch(r)
    return success_object(ser.change_request(r))


@bp.post("/scheduling/change-requests/<rid>/resubmit")
def resubmit(rid):
    user_id, _ = require_role("Student")
    r = get_or_404(db.change_requests, rid)
    term = get_or_404(db.terms, r["term_id"])
    if term["posture"] != "CHANGE_WINDOW":
        raise invalid_posture("Resubmit requires the change window to be open")
    if r["state"] != "REVISED":
        raise invalid_state("Only REVISED requests can be resubmitted")
    if user_id != r["student_id"]:
        raise forbidden_ownership()
    r["state"] = "SUBMITTED"
    r["reviewed_by_counselor_id"] = None
    r["version"] += 1
    touch(r)
    return success_object(ser.change_request(r))


@bp.post("/scheduling/change-requests/<rid>/decide")
def decide(rid):
    user_id, _ = require_role("Administrator")
    r = get_or_404(db.change_requests, rid)
    term = get_or_404(db.terms, r["term_id"])
    data = body()
    occ_early(data, term)
    if r["state"] != "COUNSELOR_REVIEW":
        raise invalid_state("Only requests in COUNSELOR_REVIEW can be "
                            "decided")
    if user_id == r["reviewed_by_counselor_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "The reviewing counselor may not also decide")
    decision = req_field(data, "decision")
    if decision not in ("APPROVE", "REJECT"):
        raise invalid_request("decision must be APPROVE or REJECT")
    occ_required(data)
    if decision == "APPROVE":
        student = db.students.get(r["student_id"])
        if r["kind"] in ("ADD", "SWAP"):
            add_section = db.sections.get(r["add_section_id"])
            add_course = (db.courses.get(add_section["course_id"])
                          if add_section else None)
            drop_entry = (db.schedule_entries.get(r["drop_entry_id"])
                          if r["drop_entry_id"] else None)
            if add_section is None or add_course is None:
                raise invalid_request("Request references a missing section")
            _add_checks(student, term, add_section, add_course, drop_entry,
                        check_program=True, check_cohort=False)
        _quota_check(r["student_id"], term)
        r["state"] = "APPROVED"
    else:
        r["state"] = "REJECTED"
    r["decided_by_admin"] = True
    r["version"] += 1
    touch(r)
    return success_object(ser.change_request(r))


@bp.post("/scheduling/change-requests/<rid>/execute")
def execute(rid):
    require_role("Administrator")
    r = get_or_404(db.change_requests, rid)
    term = get_or_404(db.terms, r["term_id"])
    if term["posture"] != "CHANGE_WINDOW":
        raise invalid_posture("Execution requires the change window to be "
                              "open")
    if r["state"] != "APPROVED":
        raise invalid_state("Only APPROVED requests can be executed")
    student = db.students.get(r["student_id"])
    drop_entry = None
    if r["kind"] in ("DROP", "SWAP"):
        drop_entry = db.schedule_entries.get(r["drop_entry_id"])
        if drop_entry is None:
            raise invalid_request("Request references a missing entry")
        if drop_entry["state"] != "ENROLLED":
            raise invalid_state("The entry to drop is no longer ENROLLED")
    add_section = None
    add_course = None
    if r["kind"] in ("ADD", "SWAP"):
        add_section = db.sections.get(r["add_section_id"])
        if add_section is None:
            raise invalid_request("Request references a missing section")
        add_course = db.courses.get(add_section["course_id"])
        _add_checks(student, term, add_section, add_course, drop_entry,
                    check_program=False, check_cohort=True)
    if r["kind"] == "DROP":
        drop_entry["state"] = "DROPPED"
        touch(drop_entry)
    elif r["kind"] == "ADD":
        engine.create_entry(student["id"], add_section, term["id"],
                            "CHANGE_REQUEST", term["rebalance_epoch"])
    else:  # SWAP
        drop_entry["state"] = "MOVED"
        drop_entry["moved_to_section_id"] = add_section["id"]
        touch(drop_entry)
        engine.create_entry(student["id"], add_section, term["id"],
                            "CHANGE_REQUEST", term["rebalance_epoch"])
    r["state"] = "EXECUTED"
    r["version"] += 1
    touch(r)
    return success_object(ser.change_request(r))


@bp.post("/scheduling/change-requests/<rid>/cancel")
def cancel(rid):
    user_id, _ = require_role("Student")
    r = get_or_404(db.change_requests, rid)
    if r["state"] not in ("SUBMITTED", "REVISED"):
        raise invalid_state("Only SUBMITTED or REVISED requests can be "
                            "cancelled")
    if user_id != r["student_id"]:
        raise forbidden_ownership()
    r["state"] = "CANCELLED"
    r["version"] += 1
    touch(r)
    return success_object(ser.change_request(r))
