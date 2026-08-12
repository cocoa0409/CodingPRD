"""People routes: counselors, teachers, qualifications, students."""

from flask import Blueprint, request

import db
import domain
import engine
import serializers as ser
from auth import require_role, body
from envelope import success_object, success_list, paginate
from errors import (ApiError, invalid_request, invalid_posture, not_found,
                    forbidden_ownership, ERR_CASELOAD_FULL)
from util import parse_iso, q2
from validate import (new_record, req_field, as_str, as_int, as_decimal,
                      opt_enum, fk_or_404, get_or_404)

bp = Blueprint("people", __name__)

PROGRAMS = ("NONE", "IEP", "ELL", "GIFTED", "ATHLETE")


# --- Counselors --------------------------------------------------------------

@bp.post("/scheduling/counselors")
def create_counselor():
    require_role("Administrator")
    data = body()
    name = as_str(req_field(data, "full_name"), "full_name")
    max_caseload = as_int(req_field(data, "max_caseload"), "max_caseload")
    if max_caseload < 1:
        raise invalid_request("max_caseload must be >= 1")
    c = new_record()
    c.update({"full_name": name, "max_caseload": max_caseload})
    db.counselors[c["id"]] = c
    return success_object(ser.counselor(c), 201)


@bp.get("/scheduling/counselors/<cid>")
def get_counselor(cid):
    require_role("Administrator", "Counselor")
    return success_object(ser.counselor(get_or_404(db.counselors, cid)))


@bp.get("/scheduling/counselors/<cid>/students")
def counselor_students(cid):
    require_role("Administrator", "Counselor")
    c = get_or_404(db.counselors, cid)
    rows = [s for s in db.students.values() if s["counselor_id"] == c["id"]]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.student(s) for s in page], limit, offset, total)


@bp.get("/scheduling/counselors/<cid>/utilization")
def counselor_utilization(cid):
    require_role("Administrator", "Counselor")
    c = get_or_404(db.counselors, cid)
    ws = request.args.get("window_start")
    we = request.args.get("window_end")
    try:
        window_start = parse_iso(ws) if ws else db.clock.now().replace(
            hour=0, minute=0, second=0, microsecond=0)
        window_end = parse_iso(we) if we else db.clock.now()
    except ValueError:
        raise invalid_request("window_start/window_end must be ISO8601")
    return success_object(domain.counselor_utilization(c["id"], window_start,
                                                       window_end))


# --- Teachers & qualifications ------------------------------------------------

@bp.post("/scheduling/teachers")
def create_teacher():
    require_role("Administrator")
    data = body()
    name = as_str(req_field(data, "full_name"), "full_name")
    max_sections = as_int(req_field(data, "max_sections"), "max_sections")
    if max_sections < 1:
        raise invalid_request("max_sections must be >= 1")
    t = new_record()
    t.update({"full_name": name, "max_sections": max_sections})
    db.teachers[t["id"]] = t
    return success_object(ser.teacher(t), 201)


@bp.get("/scheduling/teachers/<tid>")
def get_teacher(tid):
    require_role("Administrator", "Counselor")
    return success_object(ser.teacher(get_or_404(db.teachers, tid)))


@bp.post("/scheduling/teachers/<tid>/qualifications")
def create_qualification(tid):
    require_role("Administrator")
    teacher = get_or_404(db.teachers, tid)
    data = body()
    course_id = req_field(data, "course_id")
    if not isinstance(course_id, str):
        raise invalid_request("course_id must be a string")
    fk_or_404(db.courses, course_id, "course_id")
    qualified_at = as_str(req_field(data, "qualified_at"), "qualified_at")
    try:
        parse_iso(qualified_at)
    except ValueError:
        raise invalid_request("qualified_at must be an ISO8601 timestamp")
    q = new_record(slim=True)
    q.update({"teacher_id": teacher["id"], "course_id": course_id,
              "qualified_at": qualified_at})
    db.qualifications[q["id"]] = q
    return success_object(ser.qualification(q), 201)


@bp.get("/scheduling/teachers/<tid>/qualifications")
def list_teacher_qualifications(tid):
    require_role("Administrator", "Counselor")
    teacher = get_or_404(db.teachers, tid)
    rows = [q for q in db.qualifications.values()
            if q["teacher_id"] == teacher["id"]]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.qualification(q) for q in page],
                        limit, offset, total)


# --- Students -----------------------------------------------------------------

@bp.post("/scheduling/students")
def create_student():
    require_role("Administrator")
    data = body()
    ext = as_str(req_field(data, "external_ref"), "external_ref")
    if not 4 <= len(ext) <= 32:
        raise invalid_request("external_ref must be 4-32 characters")
    if any(s["external_ref"] == ext for s in db.students.values()):
        raise invalid_request("external_ref must be unique")
    name = as_str(req_field(data, "full_name"), "full_name")
    grade = as_int(req_field(data, "grade_level"), "grade_level")
    if grade not in (9, 10, 11, 12):
        raise invalid_request("grade_level must be one of 9, 10, 11, 12")
    program = opt_enum(data, "special_program", PROGRAMS, "NONE")
    counselor_id = req_field(data, "counselor_id")
    if not isinstance(counselor_id, str):
        raise invalid_request("counselor_id must be a string")
    counselor = fk_or_404(db.counselors, counselor_id, "counselor_id")
    earned = as_decimal(data.get("earned_credits", 0), "earned_credits")
    if earned < 0:
        raise invalid_request("earned_credits must be >= 0")
    if domain.counselor_caseload_count(counselor["id"]) >= counselor["max_caseload"]:
        raise ApiError(ERR_CASELOAD_FULL, 422, "Counselor caseload is full")
    s = new_record()
    s.update({"external_ref": ext, "full_name": name, "grade_level": grade,
              "special_program": program, "counselor_id": counselor["id"],
              "earned_credits": q2(earned)})
    db.students[s["id"]] = s
    return success_object(ser.student(s), 201)


@bp.get("/scheduling/students")
def list_students():
    require_role("Administrator", "Counselor")
    rows = list(db.students.values())
    cid = request.args.get("counselor_id")
    if cid is not None:
        rows = [s for s in rows if s["counselor_id"] == cid]
    grade = request.args.get("grade_level")
    if grade is not None:
        try:
            g = int(grade)
            rows = [s for s in rows if s["grade_level"] == g]
        except ValueError:
            rows = []
    deficient = request.args.get("credit_deficient")
    if deficient is not None:
        want = deficient.lower() == "true"
        rows = [s for s in rows
                if domain.student_credit_deficient(s["id"]) == want]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.student(s) for s in page], limit, offset, total)


def _student_scoped_read(sid):
    """Student-role callers may only read their own student-scoped data."""
    user_id, role = require_role("Administrator", "Counselor", "Student")
    s = get_or_404(db.students, sid)
    if role == "Student" and user_id != s["id"]:
        raise forbidden_ownership()
    return s


def _resolve_term_id():
    term_id = request.args.get("term_id")
    if term_id:
        return get_or_404(db.terms, term_id)
    if db.terms:
        return max(db.terms.values(),
                   key=lambda t: (t["created_at"], t["_seq"]))
    raise not_found("No term exists")


@bp.get("/scheduling/students/<sid>")
def get_student(sid):
    return success_object(ser.student(_student_scoped_read(sid)))


@bp.get("/scheduling/students/<sid>/schedule")
def student_schedule(sid):
    s = _student_scoped_read(sid)
    rows = [e for e in db.schedule_entries.values() if e["student_id"] == s["id"]]
    term_id = request.args.get("term_id")
    if term_id is not None:
        rows = [e for e in rows if e["term_id"] == term_id]
    state = request.args.get("state")
    if state is not None:
        rows = [e for e in rows if e["state"] == state]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.schedule_entry(e) for e in page],
                        limit, offset, total)


@bp.get("/scheduling/students/<sid>/credit-audit")
def student_credit_audit(sid):
    s = _student_scoped_read(sid)
    term = _resolve_term_id()
    audit = engine.write_credit_audit(s, term)
    return success_object(ser.credit_audit(audit))


@bp.get("/scheduling/students/<sid>/credit-projection")
def student_credit_projection(sid):
    s = _student_scoped_read(sid)
    term = _resolve_term_id()
    if term["posture"] != "COLLECTING":
        raise invalid_posture()
    vals = domain.credit_audit_values(s, term["id"], provisional=True)
    return success_object({
        "student_id": s["id"],
        "projected_credits": float(vals["projected_credits"]),
        "required_credits": float(vals["required_credits"]),
        "deficiency_credits": float(vals["deficiency_credits"]),
        "deficient_subjects": list(vals["deficient_subjects"]),
    })
