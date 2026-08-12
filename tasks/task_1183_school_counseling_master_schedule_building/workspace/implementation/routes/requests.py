"""CourseRequest routes (draft/submit/unsubmit/withdraw + lists)."""

from decimal import Decimal

from flask import Blueprint, request

import db
import domain
import serializers as ser
from auth import require_role, body
from envelope import success_object, success_list, paginate
from errors import (ApiError, invalid_request, invalid_posture, invalid_state,
                    forbidden_ownership, ERR_COURSE_INELIGIBLE,
                    ERR_REQUEST_CAP_EXCEEDED)
from util import to_d, q2
from validate import (new_record, touch, req_field, as_int, opt_bool,
                      fk_or_404, get_or_404)

bp = Blueprint("course_requests", __name__)

ACTIVE_STATES = ("DRAFT", "SUBMITTED", "LOCKED", "PLACED", "UNPLACED")


def _eligibility(student, course, req_id):
    """Course eligibility battery -> ERR_COURSE_INELIGIBLE (422)."""
    if not course["grade_band_min"] <= student["grade_level"] <= course["grade_band_max"]:
        raise ApiError(ERR_COURSE_INELIGIBLE, 422,
                       "Student grade_level is outside the course grade band")
    prereq = course["prerequisite_course_id"]
    if prereq:
        satisfied = False
        for e in db.schedule_entries.values():
            if e["student_id"] != student["id"] or e["state"] != "ENROLLED":
                continue
            sec = db.sections.get(e["section_id"])
            if sec and sec["course_id"] == prereq:
                satisfied = True
                break
        if not satisfied:
            raise ApiError(ERR_COURSE_INELIGIBLE, 422,
                           "Prerequisite course is not satisfied")
    if (course["special_program_exclusive"] != "NONE"
            and student["special_program"] != course["special_program_exclusive"]):
        raise ApiError(ERR_COURSE_INELIGIBLE, 422,
                       "Course is restricted to a special program")
    for r in db.course_requests.values():
        if (r["id"] != req_id and r["student_id"] == student["id"]
                and r["course_id"] == course["id"]
                and r["state"] in ACTIVE_STATES and not r["is_alternate"]):
            raise ApiError(ERR_COURSE_INELIGIBLE, 422,
                           "Student already holds a non-alternate request for "
                           "this course this term")


def _rank_contiguity(student_id, term_id, new_rank, new_is_alternate, self_id=None):
    """Non-alternate ranks per (student, term) must form a contiguous 1..N."""
    if new_is_alternate:
        return
    ranks = [r["priority_rank"] for r in db.course_requests.values()
             if r["student_id"] == student_id and r["term_id"] == term_id
             and not r["is_alternate"] and r["state"] in ("DRAFT", "SUBMITTED")
             and r["id"] != self_id]
    ranks.append(new_rank)
    n = len(ranks)
    if sorted(ranks) != list(range(1, n + 1)):
        raise invalid_request("priority_rank values of non-alternate requests "
                              "must form a contiguous 1..N sequence")


@bp.post("/scheduling/course-requests")
def create_request():
    user_id, _ = require_role("Student")
    data = body()
    student_id = req_field(data, "student_id")
    course_id = req_field(data, "course_id")
    term_id = req_field(data, "term_id")
    for v, name in ((student_id, "student_id"), (course_id, "course_id"),
                    (term_id, "term_id")):
        if not isinstance(v, str):
            raise invalid_request("%s must be a string" % name)
    student = fk_or_404(db.students, student_id, "student_id")
    course = fk_or_404(db.courses, course_id, "course_id")
    term = fk_or_404(db.terms, term_id, "term_id")
    if term["posture"] != "COLLECTING":
        raise invalid_posture("Course requests may only be created while the "
                              "term is COLLECTING")
    if user_id != student["id"]:
        raise forbidden_ownership()
    rank = as_int(req_field(data, "priority_rank"), "priority_rank")
    if rank < 1:
        raise invalid_request("priority_rank must be >= 1")
    is_alternate = opt_bool(data, "is_alternate", False)
    _rank_contiguity(student_id, term_id, rank, is_alternate)
    _eligibility(student, course, None)
    r = new_record()
    r.update({"student_id": student_id, "course_id": course_id,
              "term_id": term_id, "priority_rank": rank,
              "is_alternate": is_alternate, "state": "DRAFT"})
    db.course_requests[r["id"]] = r
    return success_object(ser.course_request(r), 201)


@bp.get("/scheduling/course-requests")
def list_requests():
    require_role("Administrator", "Counselor", "Student")
    rows = list(db.course_requests.values())
    for param, field in (("student_id", "student_id"), ("term_id", "term_id"),
                         ("state", "state"), ("course_id", "course_id")):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if r[field] == v]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.course_request(r) for r in page],
                        limit, offset, total)


@bp.get("/scheduling/course-requests/<rid>")
def get_request(rid):
    require_role("Administrator", "Counselor", "Student")
    return success_object(ser.course_request(get_or_404(db.course_requests, rid)))


@bp.post("/scheduling/course-requests/<rid>/submit")
def submit_request(rid):
    user_id, _ = require_role("Student")
    r = get_or_404(db.course_requests, rid)
    term = get_or_404(db.terms, r["term_id"])
    if term["posture"] != "COLLECTING":
        raise invalid_posture("Submission requires the term to be COLLECTING")
    if r["state"] != "DRAFT":
        raise invalid_state("Only DRAFT requests can be submitted")
    if user_id != r["student_id"]:
        raise forbidden_ownership()
    student = db.students.get(r["student_id"])
    course = db.courses.get(r["course_id"])
    if student is None or course is None:
        raise invalid_request("Request references a missing resource")
    _rank_contiguity(r["student_id"], r["term_id"], r["priority_rank"],
                     r["is_alternate"], self_id=r["id"])
    _eligibility(student, course, r["id"])
    # Caps: fewer than 8 other non-alternate DRAFT/SUBMITTED requests;
    # primary credit load (including this request) <= 8.0.
    others = [x for x in db.course_requests.values()
              if x["student_id"] == r["student_id"] and x["term_id"] == r["term_id"]
              and not x["is_alternate"] and x["state"] in ("DRAFT", "SUBMITTED")
              and x["id"] != r["id"]]
    load = Decimal("0")
    pool = others + ([] if r["is_alternate"] else [r])
    for x in pool:
        c = db.courses.get(x["course_id"])
        if c:
            load += to_d(c["credits"])
    if len(others) >= 8 or load > Decimal("8.0"):
        raise ApiError(ERR_REQUEST_CAP_EXCEEDED, 422,
                       "More than 8 non-alternate requests or primary credit "
                       "load above 8.0")
    r["state"] = "SUBMITTED"
    r["version"] += 1
    touch(r)
    return success_object(ser.course_request(r))


@bp.post("/scheduling/course-requests/<rid>/unsubmit")
def unsubmit_request(rid):
    user_id, _ = require_role("Student")
    r = get_or_404(db.course_requests, rid)
    term = get_or_404(db.terms, r["term_id"])
    if term["posture"] != "COLLECTING":
        raise invalid_posture("Unsubmit requires the term to be COLLECTING")
    if r["state"] != "SUBMITTED":
        raise invalid_state("Only SUBMITTED requests can be unsubmitted")
    if user_id != r["student_id"]:
        raise forbidden_ownership()
    r["state"] = "DRAFT"
    r["version"] += 1
    touch(r)
    return success_object(ser.course_request(r))


@bp.delete("/scheduling/course-requests/<rid>")
def delete_request(rid):
    user_id, _ = require_role("Student")
    r = get_or_404(db.course_requests, rid)
    if r["state"] != "DRAFT":
        raise invalid_state("Only DRAFT requests can be withdrawn; SUBMITTED "
                            "rows must be unsubmitted first")
    if user_id != r["student_id"]:
        raise forbidden_ownership()
    del db.course_requests[rid]
    return "", 204
