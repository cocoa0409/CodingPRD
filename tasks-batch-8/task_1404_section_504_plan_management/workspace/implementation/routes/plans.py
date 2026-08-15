"""Section 504 plans: draft (OCC), consent, teacher acks fan-out, suspend/reinstate,
compliance summary, and the auto-activation cascade."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import db, create_record, now, touch
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NO_SUSPENSION_JUSTIFICATION,
                    ERR_PLAN_HAS_NO_ACCOMMODATIONS, ERR_PLAN_NOT_ACTIVE,
                    ERR_PLAN_NOT_AWAITING_CONSENT, ERR_PLAN_NOT_DRAFT,
                    ERR_PLAN_NOT_SUSPENDED,
                    ERR_PLAN_REQUIRES_ELIGIBLE_DETERMINATION,
                    ERR_SCHOOL_UNDER_AUDIT_HOLD, ERR_STALE_PLAN_VERSION,
                    ERR_STALE_STUDENT_VERSION, ERR_STUDENT_PLAN_ALREADY_OPEN,
                    raise_err)
from middleware import body, req_bool, req_int, req_str, require_roles
from response import success
from routes import list_response
from services import (ANNUAL_WINDOW_DAYS, PLAN_BLOCKING_STATES_AT_SUBMIT,
                      PLAN_OPEN_STATES_AT_CREATE, RE_EVAL_WINDOW_DAYS,
                      ack_gate_satisfied, compliance_cumulative,
                      compliance_trailing_30, emit, get_evaluation, get_plan,
                      get_student, plan_out, posture_gate, school_of_plan,
                      school_of_student)
from util import iso

bp = Blueprint("plans", __name__)

PLAN_READERS = ("District504Director", "Section504Coordinator", "SchoolPrincipal", "Teacher", "Parent")


def activate_plan(plan, actor_staff_id):
    """PENDING_TEACHER_ACK -> ACTIVE cascade (auto, triggered by the last ack)."""
    ts = now()
    plan["plan_status"] = "ACTIVE"
    plan["plan_effective_date"] = ts
    plan["next_annual_review_due"] = ts + timedelta(days=ANNUAL_WINDOW_DAYS)
    ev = db.evaluations.get(plan["evaluation_id"])
    if ev is not None:
        plan["next_re_evaluation_due"] = ev["created_at"] + timedelta(days=RE_EVAL_WINDOW_DAYS)
    for a in db.accommodations.values():
        if a["plan_id"] == plan["id"] and a["accommodation_status"] == "DRAFT":
            a["accommodation_status"] = "ACTIVE"
            touch(a)
    stu = db.students.get(plan["student_id"])
    school = school_of_plan(plan)
    if stu is not None and stu["section_504_status"] != "PLAN_ACTIVE":
        stu["section_504_status"] = "PLAN_ACTIVE"
        touch(stu)
    emit("PLAN_ACTIVATED", school["id"] if school else None, plan["id"], actor_staff_id,
         {"student_id": plan["student_id"]})


@bp.post("/plans")
@require_roles("Section504Coordinator")
def create_plan():
    d = body()
    stu = get_student(req_str(d, "student_id"))
    ev = get_evaluation(req_str(d, "evaluation_id"))
    school = school_of_student(stu)
    posture_gate(school)
    expected = req_int(d, "expected_student_version")
    if expected != stu["version"]:
        emit("OCC_CONFLICT", school["id"], stu["id"], g.user_id,
             {"occ_field": "expected_student_version", "expected": expected,
              "actual": stu["version"], "endpoint": "POST /plans"})
        raise_err(ERR_STALE_STUDENT_VERSION,
                  "expected_student_version does not match the student's current version")
    for p in db.plans.values():
        if p["student_id"] == stu["id"] and p["plan_status"] in PLAN_OPEN_STATES_AT_CREATE:
            raise_err(ERR_STUDENT_PLAN_ALREADY_OPEN,
                      "Student already has an open plan (not TERMINATED/EXITED_TO_IEP)")
    rec = create_record(db.plans, {
        "student_id": stu["id"],
        "evaluation_id": ev["id"],
        "plan_status": "DRAFT",
        "drafted_by_staff_id": g.user_id,
        "plan_effective_date": None,
        "next_annual_review_due": None,
        "next_re_evaluation_due": None,
        "implementation_compliance_pct": 100.0,
        "all_teachers_acknowledged": False,
    })
    # The student is the OCC parent of this write: its version advances.
    touch(stu)
    return success(plan_out(rec), 201)


@bp.get("/plans")
@require_roles(*PLAN_READERS)
def list_plans():
    items = list(db.plans.values())
    student_id = request.args.get("student_id")
    evaluation_id = request.args.get("evaluation_id")
    status = request.args.get("plan_status")
    if student_id is not None:
        items = [p for p in items if p["student_id"] == student_id]
    if evaluation_id is not None:
        items = [p for p in items if p["evaluation_id"] == evaluation_id]
    if status is not None:
        items = [p for p in items if p["plan_status"] == status]
    return list_response(items, plan_out)


@bp.get("/plans/<planId>")
@require_roles(*PLAN_READERS)
def get_plan_detail(planId):
    return success(plan_out(get_plan(planId)), 200)


@bp.get("/plans/<planId>/compliance-summary")
@require_roles("District504Director", "Section504Coordinator", "SchoolPrincipal", "Teacher")
def plan_compliance_summary(planId):
    plan = get_plan(planId)
    data = {
        "implementation_compliance_pct_trailing_30": compliance_trailing_30(plan["id"]),
        "implementation_compliance_pct_cumulative": compliance_cumulative(plan),
        "next_annual_review_due": iso(plan.get("next_annual_review_due")),
        "next_re_evaluation_due": iso(plan.get("next_re_evaluation_due")),
    }
    return success(data, 200)


@bp.post("/plans/<planId>/submit-for-consent")
@require_roles("Section504Coordinator")
def submit_for_consent(planId):
    plan = get_plan(planId)
    school = school_of_plan(plan)
    posture_gate(school)
    d = body()
    expected = req_int(d, "expected_plan_version")
    if expected != plan["version"]:
        emit("OCC_CONFLICT", school["id"], plan["id"], g.user_id,
             {"occ_field": "expected_plan_version", "expected": expected,
              "actual": plan["version"], "endpoint": "POST /plans/{planId}/submit-for-consent"})
        raise_err(ERR_STALE_PLAN_VERSION,
                  "expected_plan_version does not match the plan's current version")
    if plan["plan_status"] != "DRAFT":
        raise_err(ERR_PLAN_NOT_DRAFT, "Plan must be DRAFT to submit for consent")
    ev = db.evaluations.get(plan["evaluation_id"])
    if ev is None or ev.get("determination_outcome") != "ELIGIBLE":
        raise_err(ERR_PLAN_REQUIRES_ELIGIBLE_DETERMINATION,
                  "Linked evaluation must have an ELIGIBLE determination")
    for p in db.plans.values():
        if (p["student_id"] == plan["student_id"] and p["id"] != plan["id"]
                and p["plan_status"] in PLAN_BLOCKING_STATES_AT_SUBMIT):
            raise_err(ERR_STUDENT_PLAN_ALREADY_OPEN,
                      "Student already has another open plan")
    has_accommodation = any(a["plan_id"] == plan["id"] for a in db.accommodations.values())
    if not has_accommodation:
        raise_err(ERR_PLAN_HAS_NO_ACCOMMODATIONS,
                  "Plan must have at least 1 accommodation before consent submission")
    plan["plan_status"] = "PENDING_PARENT_CONSENT"
    touch(plan)
    create_record(db.consents, {
        "student_id": plan["student_id"],
        "evaluation_id": None,
        "plan_id": plan["id"],
        "consent_scope": "INITIAL_PLAN",
        "consent_status": "REQUESTED",
        "requested_at": now(),
        "responded_at": None,
        "responded_by_parent_ref": None,
    })
    return success(plan_out(plan), 200)


def _linked_plan_consent(plan_id):
    cands = [c for c in db.consents.values()
             if c.get("plan_id") == plan_id and c["consent_scope"] == "INITIAL_PLAN"
             and c["consent_status"] == "REQUESTED"]
    if not cands:
        return None
    return max(cands, key=lambda c: c["_seq"])


@bp.post("/plans/<planId>/record-parent-consent")
@require_roles("Section504Coordinator")
def record_parent_consent(planId):
    plan = get_plan(planId)
    school = school_of_plan(plan)
    posture_gate(school)
    d = body()
    granted = req_bool(d, "granted")
    parent_ref = req_str(d, "responded_by_parent_ref")
    if plan["plan_status"] != "PENDING_PARENT_CONSENT":
        raise_err(ERR_PLAN_NOT_AWAITING_CONSENT,
                  "Plan must be PENDING_PARENT_CONSENT to record consent")
    rec = _linked_plan_consent(plan["id"])
    if rec is not None:
        rec["consent_status"] = "GRANTED" if granted else "DENIED"
        rec["responded_at"] = now()
        rec["responded_by_parent_ref"] = parent_ref
        touch(rec)
    if granted:
        plan["plan_status"] = "PENDING_TEACHER_ACK"
        touch(plan)
        stu = db.students.get(plan["student_id"])
        school_id = stu["school_id"] if stu else None
        teachers = sorted(
            [s for s in db.staff.values()
             if s["school_id"] == school_id and s["staff_role"] == "TEACHER"
             and s.get("is_active", True)],
            key=lambda s: (s["created_at"], s["_seq"]),
        )
        for t in teachers:
            create_record(db.acks, {
                "plan_id": plan["id"],
                "staff_id": t["id"],
                "ack_status": "PENDING",
                "ack_requested_at": now(),
                "ack_responded_at": None,
            })
        plan["all_teachers_acknowledged"] = ack_gate_satisfied(plan["id"])
    else:
        plan["plan_status"] = "DRAFT"
        touch(plan)
        plan["all_teachers_acknowledged"] = False
        emit("CONSENT_DENIED", school["id"], plan["id"], g.user_id,
             {"student_id": plan["student_id"], "consent_id": rec["id"] if rec else None})
    return success(plan_out(plan), 200)


@bp.post("/plans/<planId>/suspend")
@require_roles("Section504Coordinator")
def suspend_plan(planId):
    plan = get_plan(planId)
    school = school_of_plan(plan)
    # NOTE: suspend is exempt from the blanket AUDIT_HOLD gate — AUDIT_HOLD is
    # itself one of the two suspension justifications.
    d = body()
    req_str(d, "justification")
    if plan["plan_status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to suspend")
    compliance = compliance_trailing_30(plan["id"])
    justified = compliance < 60 or (school is not None and school.get("school_posture") == "AUDIT_HOLD")
    if not justified:
        raise_err(ERR_NO_SUSPENSION_JUSTIFICATION,
                  "Suspension requires implementation_compliance_pct < 60 or school AUDIT_HOLD")
    plan["plan_status"] = "SUSPENDED"
    touch(plan)
    stu = db.students.get(plan["student_id"])
    if stu is not None:
        stu["section_504_status"] = "PLAN_SUSPENDED"
        touch(stu)
    emit("PLAN_SUSPENDED", school["id"] if school else None, plan["id"], g.user_id,
         {"student_id": plan["student_id"],
          "implementation_compliance_pct": compliance})
    return success(plan_out(plan), 200)


@bp.post("/plans/<planId>/reinstate")
@require_roles("Section504Coordinator")
def reinstate_plan(planId):
    plan = get_plan(planId)
    school = school_of_plan(plan)
    posture_gate(school)
    if plan["plan_status"] != "SUSPENDED":
        raise_err(ERR_PLAN_NOT_SUSPENDED, "Plan must be SUSPENDED to reinstate")
    if school is None or school.get("school_posture") != "OPERATIONAL":
        raise_err(ERR_SCHOOL_UNDER_AUDIT_HOLD,
                  "School posture must be OPERATIONAL to reinstate a plan")
    plan["plan_status"] = "ACTIVE"
    touch(plan)
    stu = db.students.get(plan["student_id"])
    if stu is not None:
        stu["section_504_status"] = "PLAN_ACTIVE"
        touch(stu)
    return success(plan_out(plan), 200)
