"""FunctionalTest endpoints."""
from flask import Blueprint

import calc
import services
from core import (
    ALL_ROLES, ROLE_CX_AUTHORITY, actor, authenticate, body_json, bump_project, clock,
    db, fail, fmt_dt, new_row, num, ok, ok_list, paginate, public, q, sorted_rows,
    touch, v_datetime, v_number, v_string,
)
from finders import get_equipment, get_requirement, get_test

bp = Blueprint("functional_tests", __name__)


def _check_plan_approved(project_id):
    plan = calc.newest_plan(project_id)
    if plan is None or plan["status"] != "APPROVED":
        fail("ERR_PLAN_NOT_APPROVED",
             "The engagement's newest commissioning plan is not APPROVED.")
    return plan


@bp.post("/functional-tests")
def create_test():
    authenticate([ROLE_CX_AUTHORITY])
    body = body_json()
    equipment_id = v_string(body, "equipment_id")
    requirement_id = v_string(body, "requirement_id")
    script_code = v_string(body, "script_code")
    scheduled_start = v_datetime(body, "scheduled_start")
    scheduled_end = v_datetime(body, "scheduled_end")

    equipment_row = get_equipment(equipment_id)
    requirement = get_requirement(requirement_id)

    if equipment_row["project_id"] != requirement["project_id"]:
        fail("ERR_PROJECT_SCOPE_MISMATCH",
             "The equipment unit and the owner requirement belong to different engagements.")

    project = db.projects.get(equipment_row["project_id"])

    if (equipment_row["verification_status"] != "PREFUNCTIONAL_VERIFIED"
            or equipment_row["install_status"] != "STARTED_UP"):
        fail("ERR_EQUIPMENT_NOT_READY",
             "The equipment unit must be PREFUNCTIONAL_VERIFIED and STARTED_UP.")

    plan = _check_plan_approved(project["id"])

    if scheduled_end <= scheduled_start:
        fail("ERR_INVALID_WINDOW", "scheduled_end must be strictly after scheduled_start.")

    colliding = calc.witness_conflict_count(project["id"], scheduled_start, scheduled_end)
    if colliding >= project["witness_capacity"]:
        fail("ERR_WITNESS_WINDOW_CONFLICT",
             "The buffered witness window collides with %d occupied windows." % colliding)

    if requirement_id not in plan["pinned_requirement_ids"]:
        fail("ERR_REQUIREMENT_NOT_PINNED",
             "The requirement is not pinned by the newest approved commissioning plan.")

    row = new_row(db.tests, {
        "equipment_id": equipment_id,
        "requirement_id": requirement_id,
        "retest_of_test_id": None,
        "script_code": script_code,
        "scheduled_start": fmt_dt(scheduled_start),
        "scheduled_end": fmt_dt(scheduled_end),
        "status": "SCHEDULED",
        "measured_value": None,
        "outcome_deviation_pct": None,
        "witness_user_id": None,
        "started_at": None,
        "completed_at": None,
        "generated_issue_id": None,
    })
    services.reconcile()
    return ok(public(row), 201)


@bp.get("/functional-tests")
def list_tests():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(db.tests.values()))
    equipment_id = q("equipment_id")
    requirement_id = q("requirement_id")
    retest_of_test_id = q("retest_of_test_id")
    status = q("status")
    if equipment_id is not None:
        rows = [r for r in rows if r["equipment_id"] == equipment_id]
    if requirement_id is not None:
        rows = [r for r in rows if r["requirement_id"] == requirement_id]
    if retest_of_test_id is not None:
        rows = [r for r in rows if r["retest_of_test_id"] == retest_of_test_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.get("/functional-tests/<test_id>")
def read_test(test_id):
    authenticate(ALL_ROLES)
    return ok(public(get_test(test_id)))


@bp.post("/functional-tests/<test_id>/start")
def start_test(test_id):
    authenticate([ROLE_CX_AUTHORITY])
    test = get_test(test_id)
    equipment_row = db.equipment.get(test["equipment_id"])

    if test["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "Only a SCHEDULED test may be started.")
    if equipment_row["install_status"] != "STARTED_UP":
        fail("ERR_EQUIPMENT_NOT_READY", "The equipment unit must be STARTED_UP.")

    test["status"] = "IN_PROGRESS"
    test["started_at"] = clock.now_iso()
    touch(test)
    services.reconcile()
    return ok(public(test))


@bp.post("/functional-tests/<test_id>/record-result")
def record_result(test_id):
    authenticate([ROLE_CX_AUTHORITY])
    test = get_test(test_id)
    body = body_json()
    measured_value = v_number(body, "measured_value")
    v_string(body, "note", required=False, default=None)

    if test["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "Only an IN_PROGRESS test may record a result.")

    equipment_row = db.equipment.get(test["equipment_id"])
    project = db.projects.get(equipment_row["project_id"])
    requirement = db.requirements.get(test["requirement_id"])

    deviation = calc.compute_deviation_pct(measured_value, requirement)
    outcome = calc.outcome_for_deviation(deviation, requirement)

    test["status"] = outcome
    test["measured_value"] = measured_value
    test["outcome_deviation_pct"] = num(deviation)
    test["witness_user_id"] = actor()
    test["completed_at"] = clock.now_iso()
    touch(test)

    if outcome == "PASSED":
        if equipment_row["verification_status"] == "PREFUNCTIONAL_VERIFIED":
            equipment_row["verification_status"] = "FUNCTIONAL_ACCEPTED"
            touch(equipment_row)
    elif outcome == "PASSED_WITH_EXCEPTIONS":
        issue = services.create_issue(
            project,
            origin="FUNCTIONAL",
            severity="S3",
            description="Functional performance test passed with exceptions.",
            equipment_id=equipment_row["id"],
            source_ref_id=test["id"],
            opened_by_user_id="SYSTEM",
        )
        test["generated_issue_id"] = issue["id"]
        if equipment_row["verification_status"] == "PREFUNCTIONAL_VERIFIED":
            equipment_row["verification_status"] = "CONDITIONALLY_ACCEPTED"
            touch(equipment_row)
    else:
        severity = calc.AUTO_ISSUE_SEVERITY_BY_CRITICALITY[equipment_row["criticality"]]
        issue = services.create_issue(
            project,
            origin="FUNCTIONAL",
            severity=severity,
            description="Functional performance test failed.",
            equipment_id=equipment_row["id"],
            source_ref_id=test["id"],
            opened_by_user_id="SYSTEM",
        )
        test["generated_issue_id"] = issue["id"]

    bump_project(project)
    services.reconcile()
    return ok(public(test))


@bp.post("/functional-tests/<test_id>/schedule-retest")
def schedule_retest(test_id):
    authenticate([ROLE_CX_AUTHORITY])
    original = get_test(test_id)
    body = body_json()
    scheduled_start = v_datetime(body, "scheduled_start")
    scheduled_end = v_datetime(body, "scheduled_end")

    if original["status"] not in ("FAILED", "PASSED_WITH_EXCEPTIONS"):
        fail("ERR_INVALID_STATE",
             "Only a FAILED or PASSED_WITH_EXCEPTIONS test may be re-tested.")

    equipment_row = db.equipment.get(original["equipment_id"])
    project = db.projects.get(equipment_row["project_id"])

    if equipment_row["install_status"] != "STARTED_UP":
        fail("ERR_EQUIPMENT_NOT_READY", "The equipment unit must be STARTED_UP.")

    _check_plan_approved(project["id"])

    if scheduled_end <= scheduled_start:
        fail("ERR_INVALID_WINDOW", "scheduled_end must be strictly after scheduled_start.")

    colliding = calc.witness_conflict_count(project["id"], scheduled_start, scheduled_end)
    if colliding >= project["witness_capacity"]:
        fail("ERR_WITNESS_WINDOW_CONFLICT",
             "The buffered witness window collides with %d occupied windows." % colliding)

    row = new_row(db.tests, {
        "equipment_id": original["equipment_id"],
        "requirement_id": original["requirement_id"],
        "retest_of_test_id": original["id"],
        "script_code": original["script_code"],
        "scheduled_start": fmt_dt(scheduled_start),
        "scheduled_end": fmt_dt(scheduled_end),
        "status": "SCHEDULED",
        "measured_value": None,
        "outcome_deviation_pct": None,
        "witness_user_id": None,
        "started_at": None,
        "completed_at": None,
        "generated_issue_id": None,
    })
    services.reconcile()
    return ok(public(row), 201)
