"""RecoveryPlacement routes (create/place/waive + lists)."""

from flask import Blueprint, request

import db
import domain
import engine
import serializers as ser
from auth import require_role, body
from envelope import success_object, success_list, paginate
from errors import (ApiError, invalid_request, invalid_posture, invalid_state,
                    forbidden_ownership, ERR_CREDIT_CEILING_EXCEEDED,
                    ERR_SINGLETON_CAP_EXCEEDED, ERR_COHORT_CAP_EXCEEDED,
                    ERR_RECOVERY_NO_SECTION)
from util import to_d
from validate import (new_record, touch, req_field, as_str, fk_or_404,
                      get_or_404)

bp = Blueprint("recovery", __name__)


@bp.post("/scheduling/recovery-placements")
def create_placement():
    user_id, _ = require_role("Counselor")
    data = body()
    student_id = req_field(data, "student_id")
    term_id = req_field(data, "term_id")
    target_course_id = req_field(data, "target_course_id")
    for v, name in ((student_id, "student_id"), (term_id, "term_id"),
                    (target_course_id, "target_course_id")):
        if not isinstance(v, str):
            raise invalid_request("%s must be a string" % name)
    student = fk_or_404(db.students, student_id, "student_id")
    term = fk_or_404(db.terms, term_id, "term_id")
    fk_or_404(db.courses, target_course_id, "target_course_id")
    if student["counselor_id"] != user_id:
        raise forbidden_ownership("Only the student's counselor may open a "
                                  "recovery placement")
    p = new_record()
    p.update({"student_id": student_id, "term_id": term_id,
              "target_course_id": target_course_id, "section_id": None,
              "state": "PENDING",
              "priority_score": domain.recovery_priority_score(student,
                                                               term_id)})
    db.recovery_placements[p["id"]] = p
    return success_object(ser.recovery_placement(p), 201)


@bp.get("/scheduling/recovery-placements")
def list_placements():
    require_role("Administrator", "Counselor", "Student")
    rows = list(db.recovery_placements.values())
    for param in ("student_id", "term_id", "state", "target_course_id",
                  "section_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [p for p in rows if p.get(param) == v]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.recovery_placement(p) for p in page],
                        limit, offset, total)


@bp.get("/scheduling/recovery-placements/<pid>")
def get_placement(pid):
    require_role("Administrator", "Counselor", "Student")
    return success_object(ser.recovery_placement(
        get_or_404(db.recovery_placements, pid)))


@bp.post("/scheduling/recovery-placements/<pid>/place")
def place(pid):
    user_id, _ = require_role("Counselor")
    p = get_or_404(db.recovery_placements, pid)
    term = get_or_404(db.terms, p["term_id"])
    if term["posture"] not in ("PUBLISHED", "CHANGE_WINDOW", "LOCKED"):
        raise invalid_posture("Recovery placement requires the term to be "
                              "PUBLISHED, CHANGE_WINDOW, or LOCKED")
    if p["state"] != "PENDING":
        raise invalid_state("Only PENDING placements can be placed")
    student = db.students.get(p["student_id"])
    if student is None or student["counselor_id"] != user_id:
        raise forbidden_ownership("Only the student's counselor may place")
    course = db.courses.get(p["target_course_id"])
    if course is None:
        raise invalid_request("Placement references a missing course")
    # Credit ceiling (planned + target credits <= 8.0).
    load = domain.student_planned_credit_load(student["id"], term["id"])
    if load + to_d(course["credits"]) > domain.CREDIT_LOAD_CEILING:
        raise ApiError(ERR_CREDIT_CEILING_EXCEEDED, 422,
                       "Placement would push planned_credit_load above 8.0")
    # Singleton cap.
    cap = term["singleton_section_cap"]
    if cap > 0 and course["singleton"]:
        if domain.student_singleton_count(student["id"], term["id"]) + 1 > cap:
            raise ApiError(ERR_SINGLETON_CAP_EXCEEDED, 422,
                           "Placement would exceed the singleton section cap")
    # Recovery selector = placement selector run for the target course.
    section = domain.placement_select(student, course, term["id"])
    if section is None:
        raise ApiError(ERR_RECOVERY_NO_SECTION, 422,
                       "No eligible section for the target course")
    # Cohort concentration guard on the selected section.
    prog = student["special_program"]
    if prog != "NONE":
        counts = domain.section_cohort_counts(section["id"])
        if (counts.get(prog, 0) + 1
                > domain.cohort_half_cap(section["capacity"])):
            raise ApiError(ERR_COHORT_CAP_EXCEEDED, 422,
                           "Placement would push the section's cohort above "
                           "half its capacity")
    p["section_id"] = section["id"]
    p["state"] = "PLACED"
    p["version"] += 1
    touch(p)
    engine.create_entry(student["id"], section, term["id"],
                        "RECOVERY_PLACEMENT", term["rebalance_epoch"])
    engine.write_credit_audit(student, term)
    return success_object(ser.recovery_placement(p))


@bp.post("/scheduling/recovery-placements/<pid>/waive")
def waive(pid):
    require_role("Administrator")
    p = get_or_404(db.recovery_placements, pid)
    if p["state"] != "PENDING":
        raise invalid_state("Only PENDING placements can be waived")
    data = body()
    reason = as_str(req_field(data, "waiver_reason"), "waiver_reason")
    if not 10 <= len(reason) <= 500:
        raise invalid_request("waiver_reason must be 10-500 characters")
    p["state"] = "WAIVED"
    touch(p)
    return success_object(ser.recovery_placement(p))
