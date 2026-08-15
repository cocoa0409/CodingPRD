"""Students: enroll, list, get, graduate, withdraw (PRD §3.1, §3.7)."""

from flask import Blueprint, g, request

from store import stores, mint, bump
from util import (
    ok_object, paginate, fail, get_body, validate_schema, require_role,
    ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_DUPLICATE_CODE,
    ERR_CASELOAD_FULL, ERR_NO_ADVISOR_AVAILABLE, ERR_NO_CERTIFIED_AUDIT,
)
from computed import ser_student, active_caseload_count
from cascades import student_terminal_cascade

bp = Blueprint("students", __name__)

STUDENT_STATUSES = ("ENROLLED", "GRADUATED", "TRANSFERRED_OUT", "WITHDRAWN")
DEMOGRAPHIC_GROUPS = ("GROUP_A", "GROUP_B", "GROUP_C", "GROUP_D")


def get_student_or_404(sid):
    s = stores["students"].get(sid)
    if s is None:
        fail(ERR_NOT_FOUND, 404, "Student not found")
    return s


def student_ownership(student_id):
    """Pipeline stage 7: a Student role touches only their own resources."""
    if g.user_role == "Student" and g.user_id != student_id:
        fail(ERR_FORBIDDEN, 403, "Student may only access their own resources")


@bp.post("/ccr/students")
def student_create():
    body = get_body()
    validate_schema(body, {
        "student_ref": {"kind": "str", "required": True},
        "full_name": {"kind": "str", "required": True},
        "grade_level": {"kind": "int", "required": True, "min": 9, "max": 12},
        "demographic_group": {"kind": "str", "required": True, "choices": DEMOGRAPHIC_GROUPS},
        "first_generation": {"kind": "bool", "required": False},
        "advisor_id": {"kind": "str", "required": False},
    })
    require_role(g.user_role, "DistrictAdmin")
    # Body FK existence (stage 5) precedes uniqueness (stage 10) and capacity (13).
    advisor = None
    if body.get("advisor_id") is not None:
        advisor = stores["advisors"].get(body["advisor_id"])
        if advisor is None:
            fail(ERR_NOT_FOUND, 404, "Advisor not found")
    if any(s["student_ref"] == body["student_ref"] for s in stores["students"].values()):
        fail(ERR_DUPLICATE_CODE, 409, "student_ref already in use")
    if advisor is not None:
        # Explicit assignment: capacity ceiling, equality rejects (PRD §3.1).
        if active_caseload_count(advisor["id"]) >= advisor["max_caseload"]:
            fail(ERR_CASELOAD_FULL, 409, "Advisor caseload is full")
    else:
        # Deterministic selector (PRD §2.9): ACTIVE, count < max, count ASC,
        # created_at ASC. Empty pool rejects the enrollment.
        from routes.admin import _selector_pool
        pool = _selector_pool()
        if not pool:
            fail(ERR_NO_ADVISOR_AVAILABLE, 409, "No advisor with spare capacity")
        advisor = pool[0][0]
    rec = mint("students")
    rec.update({
        "student_ref": body["student_ref"],
        "full_name": body["full_name"],
        "grade_level": body["grade_level"],
        "demographic_group": body["demographic_group"],
        "first_generation": body.get("first_generation", False),
        "status": "ENROLLED",
        "assigned_advisor_id": advisor["id"],
        "graduated_at": None,
    })
    stores["students"][rec["id"]] = rec
    return ok_object(ser_student(rec), 201)


@bp.get("/ccr/students")
def student_list():
    require_role(g.user_role, "DistrictAdmin", "Advisor")
    items = list(stores["students"].values())
    advisor_id = request.args.get("advisor_id")
    status = request.args.get("status")
    group = request.args.get("demographic_group")
    if advisor_id is not None:
        items = [s for s in items if s["assigned_advisor_id"] == advisor_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if group is not None:
        items = [s for s in items if s["demographic_group"] == group]
    return paginate(items, ser_student)


@bp.get("/ccr/students/<sid>")
def student_get(sid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student")
    student = get_student_or_404(sid)
    student_ownership(sid)
    return ok_object(ser_student(student), 200)


@bp.post("/ccr/students/<sid>/graduate")
def student_graduate(sid):
    body = get_body()
    validate_schema(body, {})
    require_role(g.user_role, "DistrictAdmin")
    student = get_student_or_404(sid)
    if student["status"] != "ENROLLED":
        fail(ERR_INVALID_STATE, 409, "Student is not ENROLLED")
    certified = any(a["student_id"] == sid and a["status"] == "CERTIFIED"
                    for a in stores["audits"].values())
    if not certified:
        fail(ERR_NO_CERTIFIED_AUDIT, 409, "No CERTIFIED senior audit for this student")
    from store import now
    student["status"] = "GRADUATED"
    student["graduated_at"] = now()
    bump(student)
    student_terminal_cascade(student, "GRADUATED")
    return ok_object(ser_student(student), 200)


@bp.post("/ccr/students/<sid>/withdraw")
def student_withdraw(sid):
    body = get_body()
    validate_schema(body, {
        "reason": {"kind": "str", "required": True, "choices": ("WITHDRAWN", "TRANSFERRED_OUT")},
    })
    require_role(g.user_role, "DistrictAdmin")
    student = get_student_or_404(sid)
    if student["status"] != "ENROLLED":
        fail(ERR_INVALID_STATE, 409, "Student is not ENROLLED")
    target = body["reason"]
    student["status"] = target
    bump(student)
    student_terminal_cascade(student, target)
    return ok_object(ser_student(student), 200)
