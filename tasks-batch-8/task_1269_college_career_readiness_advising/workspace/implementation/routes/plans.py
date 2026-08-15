"""Student plans and course enrollments (PRD §3.2, §3.3)."""

from flask import Blueprint, g, request

from store import stores, mint, bump
from util import (
    ok_object, paginate, fail, get_body, validate_schema, require_role,
    ERR_VALIDATION, ERR_NOT_FOUND, ERR_STALE_VERSION, ERR_INVALID_STATE,
    ERR_PATHWAY_NOT_ACTIVE, ERR_PLAN_NOT_ACTIVE, ERR_STUDENT_NOT_ENROLLED,
)
from computed import ser_plan, ser_enrollment
from cascades import autoflag_certified_audits
from routes.students import get_student_or_404, student_ownership

bp = Blueprint("plans", __name__)

PLAN_STATUSES = ("DRAFT", "ACTIVE", "REVISING", "SUPERSEDED")
ENROLLMENT_STATUSES = ("PLANNED", "ENROLLED", "COMPLETED", "FAILED", "DROPPED")
PASSING_GRADES = ("A", "B", "C", "PASS")


def get_plan_or_404(pid):
    p = stores["plans"].get(pid)
    if p is None:
        fail(ERR_NOT_FOUND, 404, "Plan not found")
    return p


def plan_ownership(plan):
    student_ownership(plan["student_id"])


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

@bp.post("/ccr/students/<sid>/plans")
def plan_create(sid):
    body = get_body()
    validate_schema(body, {
        "pathway_id": {"kind": "str", "required": True},
        "interest_inventory": {"required": False, "inventory": True},
        "expected_student_version": {"kind": "int", "required": True},
    })
    require_role(g.user_role, "Advisor")
    student = get_student_or_404(sid)
    pathway = stores["pathways"].get(body["pathway_id"])
    if pathway is None:
        fail(ERR_NOT_FOUND, 404, "Pathway not found")
    # OCC (stage 6) precedes cross-entity state gates (stage 12).
    if body["expected_student_version"] != student["version"]:
        fail(ERR_STALE_VERSION, 412, "expected_student_version is stale")
    if student["status"] != "ENROLLED":
        fail(ERR_STUDENT_NOT_ENROLLED, 409, "Student is not ENROLLED")
    if pathway["status"] != "ACTIVE":
        fail(ERR_PATHWAY_NOT_ACTIVE, 409, "Pathway is not ACTIVE")
    rec = mint("plans")
    rec.update({
        "student_id": sid,
        "pathway_id": pathway["id"],
        "interest_inventory": body.get("interest_inventory") or [],
        "status": "DRAFT",
    })
    stores["plans"][rec["id"]] = rec
    # Plan creation is one of the four events that move Student.version.
    bump(student)
    return ok_object(ser_plan(rec), 201)


@bp.get("/ccr/students/<sid>/plans")
def plan_list(sid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student")
    get_student_or_404(sid)
    student_ownership(sid)
    items = [p for p in stores["plans"].values() if p["student_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items, ser_plan)


@bp.get("/ccr/plans/<pid>")
def plan_get(pid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student")
    plan = get_plan_or_404(pid)
    plan_ownership(plan)
    # milestone_pct_lenient is exposed only on this single-plan read (PRD §3.4).
    return ok_object(ser_plan(plan, include_lenient=True), 200)


@bp.patch("/ccr/plans/<pid>")
def plan_patch(pid):
    body = get_body()
    validate_schema(body, {
        "pathway_id": {"kind": "str", "required": False},
        "interest_inventory": {"required": False, "inventory": True},
    })
    require_role(g.user_role, "Advisor")
    plan = get_plan_or_404(pid)
    new_pathway = None
    if body.get("pathway_id") is not None:
        new_pathway = stores["pathways"].get(body["pathway_id"])
        if new_pathway is None:
            fail(ERR_NOT_FOUND, 404, "Pathway not found")
    if plan["status"] not in ("DRAFT", "REVISING"):
        fail(ERR_INVALID_STATE, 409, "Plan may only be edited while DRAFT or REVISING")
    if new_pathway is not None:
        if new_pathway["status"] != "ACTIVE":
            fail(ERR_PATHWAY_NOT_ACTIVE, 409, "Pathway is not ACTIVE")
        plan["pathway_id"] = new_pathway["id"]
    if "interest_inventory" in body and body["interest_inventory"] is not None:
        plan["interest_inventory"] = body["interest_inventory"]
    bump(plan)
    return ok_object(ser_plan(plan), 200)


@bp.post("/ccr/plans/<pid>/activate")
def plan_activate(pid):
    body = get_body()
    validate_schema(body, {})
    require_role(g.user_role, "Advisor")
    plan = get_plan_or_404(pid)
    if plan["status"] not in ("DRAFT", "REVISING"):
        fail(ERR_INVALID_STATE, 409, "Plan is not DRAFT or REVISING")
    pathway = stores["pathways"][plan["pathway_id"]]
    if pathway["status"] != "ACTIVE":
        fail(ERR_PATHWAY_NOT_ACTIVE, 409, "Pathway is not ACTIVE")
    student = stores["students"][plan["student_id"]]
    if student["status"] != "ENROLLED":
        fail(ERR_STUDENT_NOT_ENROLLED, 409, "Student is not ENROLLED")
    # Activation supersedes any other ACTIVE plan of the same student.
    for other in stores["plans"].values():
        if other["student_id"] == plan["student_id"] and other["id"] != plan["id"] \
                and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            bump(other)
    plan["status"] = "ACTIVE"
    bump(plan)
    return ok_object(ser_plan(plan), 200)


@bp.post("/ccr/plans/<pid>/revise")
def plan_revise(pid):
    body = get_body()
    validate_schema(body, {})
    require_role(g.user_role, "Advisor")
    plan = get_plan_or_404(pid)
    if plan["status"] != "ACTIVE":
        fail(ERR_INVALID_STATE, 409, "Plan is not ACTIVE")
    plan["status"] = "REVISING"
    bump(plan)
    return ok_object(ser_plan(plan), 200)


@bp.get("/ccr/plans/<pid>/enrollments")
def plan_enrollments(pid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student")
    plan = get_plan_or_404(pid)
    plan_ownership(plan)
    items = [e for e in stores["enrollments"].values() if e["plan_id"] == pid]
    return paginate(items, ser_enrollment)


# ---------------------------------------------------------------------------
# Course enrollments
# ---------------------------------------------------------------------------

@bp.post("/ccr/students/<sid>/enrollments")
def enrollment_create(sid):
    body = get_body()
    validate_schema(body, {
        "plan_id": {"kind": "str", "required": True},
        "course_code": {"kind": "str", "required": True},
        "term": {"kind": "str", "required": True},
        "credits": {"kind": "num", "required": True, "gt": 0, "quarter": True},
    })
    require_role(g.user_role, "Advisor")
    get_student_or_404(sid)
    plan = stores["plans"].get(body["plan_id"])
    if plan is None:
        fail(ERR_NOT_FOUND, 404, "Plan not found")
    # The named plan must belong to the student and be ACTIVE at creation.
    if plan["student_id"] != sid or plan["status"] != "ACTIVE":
        fail(ERR_PLAN_NOT_ACTIVE, 409, "Plan is not the student's ACTIVE plan")
    rec = mint("enrollments")
    rec.update({
        "student_id": sid,
        "plan_id": plan["id"],
        "course_code": body["course_code"],
        "term": body["term"],
        "credits": body["credits"],
        "grade": None,
        "status": "PLANNED",
    })
    stores["enrollments"][rec["id"]] = rec
    return ok_object(ser_enrollment(rec), 201)


@bp.get("/ccr/students/<sid>/enrollments")
def enrollment_list(sid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student")
    get_student_or_404(sid)
    student_ownership(sid)
    items = [e for e in stores["enrollments"].values() if e["student_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paginate(items, ser_enrollment)


@bp.get("/ccr/enrollments/<eid>")
def enrollment_get(eid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student")
    e = stores["enrollments"].get(eid)
    if e is None:
        fail(ERR_NOT_FOUND, 404, "Enrollment not found")
    student_ownership(e["student_id"])
    return ok_object(ser_enrollment(e), 200)


# Allowed from-states per target. COMPLETED is terminal (no exits).
_ENROLLMENT_TRANSITIONS = {
    "ENROLLED": ("PLANNED",),
    "COMPLETED": ("ENROLLED",),
    "FAILED": ("ENROLLED",),
    "DROPPED": ("PLANNED", "ENROLLED"),
    "PLANNED": ("DROPPED", "FAILED"),
}


@bp.post("/ccr/enrollments/<eid>/transition")
def enrollment_transition(eid):
    body = get_body()
    validate_schema(body, {
        "to_status": {"kind": "str", "required": True, "choices": ENROLLMENT_STATUSES},
        "grade": {"kind": "str", "required": False},
    })
    # Stage 2 schema: COMPLETED requires a payload grade in {A,B,C,PASS},
    # reported before any state evaluation (PRD §3.3 / §2.6).
    if body["to_status"] == "COMPLETED":
        grade = body.get("grade")
        if grade not in PASSING_GRADES:
            fail(ERR_VALIDATION, 400, "grade must be one of A, B, C, PASS")
    require_role(g.user_role, "Advisor")
    e = stores["enrollments"].get(eid)
    if e is None:
        fail(ERR_NOT_FOUND, 404, "Enrollment not found")
    target = body["to_status"]
    allowed_from = _ENROLLMENT_TRANSITIONS.get(target, ())
    if e["status"] not in allowed_from:
        fail(ERR_INVALID_STATE, 409, f"Cannot move enrollment from {e['status']} to {target}")
    # Replan/enroll gates on the owning plan still being ACTIVE.
    if target in ("ENROLLED", "PLANNED"):
        plan = stores["plans"][e["plan_id"]]
        if plan["status"] != "ACTIVE":
            fail(ERR_PLAN_NOT_ACTIVE, 409, "Owning plan is not ACTIVE")
    prior = e["status"]
    e["status"] = target
    if target == "COMPLETED":
        e["grade"] = body["grade"]
    elif target == "FAILED":
        e["grade"] = "F"
    elif target in ("PLANNED", "ENROLLED"):
        e["grade"] = None  # grade is null outside COMPLETED/FAILED
    bump(e)
    # Certified-audit drift: completion, failure, and dropping from ENROLLED
    # auto-flag a CERTIFIED audit (PRD §3.3); other moves never touch audits.
    if target == "COMPLETED" or (target in ("FAILED", "DROPPED") and prior == "ENROLLED"):
        autoflag_certified_audits(e["student_id"])
    return ok_object(ser_enrollment(e), 200)
