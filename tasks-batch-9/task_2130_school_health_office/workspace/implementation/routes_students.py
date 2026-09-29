"""Students and chronic-condition action plans."""
from flask import Blueprint, request

import calc
import cascades
import serializers as ser
from auth import (ALL_READ_ROLES, ALL_READ_ROLES_WITH_GUARDIAN, authorize,
                  guardian_owns, insert, must_exist, resolve, rows)
from envelope import created, listing, ok, parse_pagination
from errors import fail
from store import db, days, new_record, parse_dt, sorted_rows, touch
from validators import Field, get_body, supplied, validate, value_or

bp = Blueprint("students", __name__)

ALLERGY = {"NONE", "MILD", "MODERATE", "ANAPHYLAXIS"}
CONDITIONS = {"ASTHMA", "T1DM", "SEIZURE", "CARDIAC", "MENTAL_HEALTH"}
IMMUNIZATION = {"COMPLIANT", "PROVISIONAL", "EXEMPT", "NONCOMPLIANT"}
ENROLLMENT = {"ENROLLED", "TRANSFERRED", "WITHDRAWN"}
PLAN_CONDITIONS = {"ASTHMA", "ANAPHYLAXIS", "SEIZURE", "T1DM"}


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------

@bp.post("/health-office/students")
def create_student():
    authorize(["DistrictHealthAdmin", "SchoolNurse"])
    body = get_body(request)
    school = resolve("schools", body.get("school_id"), "School")
    values = validate(body, [
        Field("school_id", "string"),
        Field("full_name", "string"),
        Field("grade_level", "integer", minimum=0, maximum=12),
        Field("date_of_birth", "datetime"),
        Field("allergy_severity", "enum", enum=ALLERGY),
        Field("chronic_condition_codes", "array", members=CONDITIONS),
        Field("immunization_status", "enum", enum=IMMUNIZATION),
        Field("privacy_hold", "boolean", required=False),
    ])
    record = new_record({
        "school_id": school["id"],
        "full_name": values["full_name"],
        "grade_level": values["grade_level"],
        "date_of_birth": parse_dt(values["date_of_birth"]),
        "allergy_severity": values["allergy_severity"],
        "chronic_condition_codes": list(values["chronic_condition_codes"]),
        "immunization_status": values["immunization_status"],
        "privacy_hold": value_or(values, "privacy_hold", False),
        "enrollment_status": "ENROLLED",
        "intake_risk_score": 0,
        "observed_risk_score": 0,
    })
    record["intake_risk_score"] = calc.intake_risk_score(record)
    insert("students", record)
    return created(ser.student_json(record))


@bp.get("/health-office/students/<student_id>")
def get_student(student_id):
    user_id, role = authorize(ALL_READ_ROLES_WITH_GUARDIAN)
    student = db.students.get(student_id)
    if student is not None and role == "Guardian" and student["id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Guardian may only read their own child's record.")
    student = must_exist("students", student_id, "Student")
    return ok(ser.student_json(student))


@bp.get("/health-office/students")
def list_students():
    authorize(ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    result = rows("students")
    school_id = request.args.get("school_id")
    enrollment_status = request.args.get("enrollment_status")
    tier = request.args.get("risk_tier")
    alert_flag = request.args.get("alert_flag")
    if school_id:
        result = [r for r in result if r["school_id"] == school_id]
    if enrollment_status:
        result = [r for r in result if r["enrollment_status"] == enrollment_status]
    if tier:
        result = [r for r in result
                  if calc.risk_tier(calc.effective_risk_score(r)) == tier]
    if alert_flag:
        result = [r for r in result if alert_flag in calc.alert_flags(r)]
    return listing([ser.student_json(r) for r in sorted_rows(result)], limit, offset)


@bp.patch("/health-office/students/<student_id>")
def patch_student(student_id):
    authorize(["DistrictHealthAdmin", "SchoolNurse"])
    student = must_exist("students", student_id, "Student")
    body = get_body(request)
    values = validate(body, [
        Field("allergy_severity", "enum", required=False, enum=ALLERGY),
        Field("chronic_condition_codes", "array", required=False, members=CONDITIONS),
        Field("immunization_status", "enum", required=False, enum=IMMUNIZATION),
        Field("privacy_hold", "boolean", required=False),
        Field("enrollment_status", "enum", required=False, enum=ENROLLMENT),
    ])
    if supplied(values, "allergy_severity"):
        student["allergy_severity"] = values["allergy_severity"]
    if supplied(values, "chronic_condition_codes"):
        student["chronic_condition_codes"] = list(values["chronic_condition_codes"])
    if supplied(values, "immunization_status"):
        student["immunization_status"] = values["immunization_status"]
    if supplied(values, "privacy_hold"):
        student["privacy_hold"] = values["privacy_hold"]
    left_enrollment = False
    if supplied(values, "enrollment_status"):
        previous = student["enrollment_status"]
        student["enrollment_status"] = values["enrollment_status"]
        left_enrollment = (previous == "ENROLLED"
                           and values["enrollment_status"] != "ENROLLED")
    student["intake_risk_score"] = calc.intake_risk_score(student)
    touch(student)
    if left_enrollment:
        for screening in db.screenings.values():
            if screening["student_id"] != student["id"]:
                continue
            if screening["status"] in ("SCHEDULED", "RESCREEN_DUE"):
                screening["status"] = "DECLINED"
                touch(screening)
    return ok(ser.student_json(student))


# ---------------------------------------------------------------------------
# ActionPlan
# ---------------------------------------------------------------------------

@bp.post("/health-office/action-plans")
def create_plan():
    authorize(["SchoolNurse"])
    body = get_body(request)
    student = resolve("students", body.get("student_id"), "Student")
    supersedes = None
    if body.get("supersedes_action_plan_id") is not None:
        supersedes = resolve("action_plans", body.get("supersedes_action_plan_id"),
                                "ActionPlan")
    values = validate(body, [
        Field("student_id", "string"),
        Field("condition_code", "enum", enum=PLAN_CONDITIONS),
        Field("severity_score", "integer", minimum=1, maximum=5),
        Field("requires_stock_epinephrine", "boolean"),
        Field("self_carry_requested", "boolean"),
        Field("effective_from", "datetime"),
        Field("expected_student_version", "integer"),
        Field("supersedes_action_plan_id", "string", required=False),
    ])
    # Ladder position 14 - optimistic concurrency on the Student version
    if values["expected_student_version"] != student["version"]:
        fail("ERR_STALE_STUDENT_VERSION", "expected_student_version is stale.")
    # Ladder position 17
    if student["enrollment_status"] != "ENROLLED":
        fail("ERR_STUDENT_NOT_ENROLLED", "The student is not enrolled.")
    # Ladder position 41
    for plan in rows("action_plans"):
        if plan["student_id"] != student["id"]:
            continue
        if plan["condition_code"] != values["condition_code"]:
            continue
        if plan["status"] != "ACTIVE":
            continue
        if supersedes is not None and supersedes["id"] == plan["id"]:
            continue
        fail("ERR_ACTIVE_PLAN_CONFLICT",
             "Another active plan already covers this condition.")
    record = new_record({
        "student_id": student["id"],
        "supersedes_action_plan_id": supersedes["id"] if supersedes else None,
        "condition_code": values["condition_code"],
        "severity_score": values["severity_score"],
        "requires_stock_epinephrine": values["requires_stock_epinephrine"],
        "self_carry_requested": values["self_carry_requested"],
        "effective_from": parse_dt(values["effective_from"]),
        "review_due_at": None,
        "guardian_consent_at": None,
        "provider_signed_at": None,
        "revision_round": 0,
        "status": "DRAFT",
    })
    insert("action_plans", record)
    touch(student)
    return created(ser.plan_json(record))


@bp.get("/health-office/action-plans/<plan_id>")
def get_plan(plan_id):
    user_id, role = authorize(ALL_READ_ROLES_WITH_GUARDIAN)
    plan = db.action_plans.get(plan_id)
    guardian_owns(plan, user_id, role)
    plan = must_exist("action_plans", plan_id, "ActionPlan")
    return ok(ser.plan_json(plan))


@bp.get("/health-office/action-plans")
def list_plans():
    authorize(ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    result = rows("action_plans")
    for key in ("student_id", "status", "condition_code", "supersedes_action_plan_id"):
        value = request.args.get(key)
        if value:
            result = [r for r in result if r.get(key) == value]
    return listing([ser.plan_json(r) for r in sorted_rows(result)], limit, offset)


@bp.post("/health-office/action-plans/<plan_id>/submit")
def submit_plan(plan_id):
    authorize(["SchoolNurse"])
    plan = must_exist("action_plans", plan_id, "ActionPlan")
    if plan["status"] != "DRAFT":
        fail("ERR_PLAN_INVALID_STATE", "Only a DRAFT plan may be submitted.")
    student = db.students.get(plan["student_id"])
    if student is None or student["enrollment_status"] != "ENROLLED":
        fail("ERR_STUDENT_NOT_ENROLLED", "The student is not enrolled.")
    plan["status"] = "PENDING_GUARDIAN"
    touch(plan)
    return ok(ser.plan_json(plan))


@bp.post("/health-office/action-plans/<plan_id>/guardian-consent")
def plan_guardian_consent(plan_id):
    user_id, role = authorize(["Guardian"])
    plan = db.action_plans.get(plan_id)
    guardian_owns(plan, user_id, role)
    plan = must_exist("action_plans", plan_id, "ActionPlan")
    if plan["status"] != "PENDING_GUARDIAN":
        fail("ERR_PLAN_INVALID_STATE", "The plan is not awaiting guardian consent.")
    plan["guardian_consent_at"] = db.now()
    plan["status"] = "PENDING_PROVIDER"
    touch(plan)
    return ok(ser.plan_json(plan))


@bp.post("/health-office/action-plans/<plan_id>/decision")
def plan_decision(plan_id):
    authorize(["SchoolPhysician"])
    plan = must_exist("action_plans", plan_id, "ActionPlan")
    body = get_body(request)
    values = validate(body, [
        Field("decision", "enum", enum={"APPROVE", "REQUEST_REVISION"}),
        Field("note", "string", required=False),
    ])
    decision = values["decision"]
    if plan["status"] != "PENDING_PROVIDER":
        fail("ERR_PLAN_INVALID_STATE", "The plan is not awaiting a provider decision.")
    if decision == "APPROVE":
        student = db.students.get(plan["student_id"])
        if student is None or student["enrollment_status"] != "ENROLLED":
            fail("ERR_STUDENT_NOT_ENROLLED", "The student is not enrolled.")
        if plan.get("guardian_consent_at") is None:
            fail("ERR_GUARDIAN_CONSENT_MISSING", "Guardian consent has not been recorded.")
        plan["provider_signed_at"] = db.now()
        plan["review_due_at"] = plan["effective_from"] + days(calc.PLAN_REVIEW_DAYS)
        plan["status"] = "ACTIVE"
        if supplied(values, "note"):
            plan["note"] = values["note"]
        touch(plan)
        predecessor_id = plan.get("supersedes_action_plan_id")
        if predecessor_id:
            predecessor = db.action_plans.get(predecessor_id)
            if predecessor is not None and predecessor["status"] == "ACTIVE":
                cascades.supersede_cascade(predecessor)
    else:
        if plan["revision_round"] >= calc.MAX_REVISION_ROUNDS:
            fail("ERR_REVISION_LIMIT_REACHED",
                 "The plan has already been revised twice.")
        plan["revision_round"] += 1
        plan["guardian_consent_at"] = None
        plan["status"] = "DRAFT"
        if supplied(values, "note"):
            plan["note"] = values["note"]
        touch(plan)
    return ok(ser.plan_json(plan))


@bp.post("/health-office/action-plans/<plan_id>/revoke")
def revoke_plan(plan_id):
    authorize(["SchoolPhysician"])
    plan = must_exist("action_plans", plan_id, "ActionPlan")
    body = get_body(request)
    values = validate(body, [Field("reason_code", "string", required=False)])
    if plan["status"] not in ("DRAFT", "PENDING_GUARDIAN", "PENDING_PROVIDER", "ACTIVE"):
        fail("ERR_PLAN_INVALID_STATE", "The plan is already terminal.")
    plan["status"] = "REVOKED"
    if supplied(values, "reason_code"):
        plan["reason_code"] = values["reason_code"]
    touch(plan)
    cascades.suspend_orders_for_plan(plan, ("UNVERIFIED", "VERIFIED"))
    return ok(ser.plan_json(plan))
