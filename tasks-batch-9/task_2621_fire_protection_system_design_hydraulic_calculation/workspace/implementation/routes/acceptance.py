"""Witnessed acceptance testing and as-built close-out (PRD 3.9)."""
from flask import Blueprint

import cascades
import clock
import db
import guards
import helpers
import ledger
import response
import validate
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from utils import _dec, fmt_dt, minutes, parse_dt

bp = Blueprint("acceptance", __name__)

TEST_TYPES = ["SYSTEM_FLOW_TEST", "PUMP_FLOW_TEST", "HYDROSTATIC_TEST", "STANDPIPE_FLOW_TEST"]
AS_BUILT_DISPOSITIONS = ["ACCEPTED", "REJECTED"]
OPENABLE_PROJECT_STATUSES = ("PERMITTED", "ACCEPTANCE")
TRAVEL_BUFFER = minutes(60)


def tests_of(project_id):
    return [t for t in db.acceptance_tests.values() if t["project_id"] == project_id]


@bp.post("/acceptance-tests")
def create_test():
    authenticate(["Contractor"])
    data = validate.body()
    project = guards.must_fk("project", validate.raw_fk(data, "project_id"))
    validate.req_str(data, "project_id")
    test_type = validate.req_str(data, "test_type", enum=TEST_TYPES)

    guards.require_not_frozen(project)
    guards.require_not_gated(project)
    guards.require_project_open(project)
    if project["status"] not in OPENABLE_PROJECT_STATUSES:
        guards.invalid_transition(
            "Acceptance tests open only against a PERMITTED or ACCEPTANCE project."
        )
    for drawing in db.shop_drawings.values():
        if drawing["project_id"] == project["id"] and drawing["state"] != "ISSUED":
            raise ApiError(
                "ERR_DRAWING_NOT_ISSUED",
                "Every shop drawing of the project must be ISSUED before acceptance testing.",
            )
    if ledger.governing_calculation(project) is None:
        raise ApiError(
            "ERR_NO_GOVERNING_CALCULATION",
            "The project has no governing hydraulic calculation, so thresholds are undefined.",
        )

    thresholds = ledger.acceptance_thresholds(project)
    row = {
        "project_id": project["id"],
        "witness_reviewer_id": None,
        "test_type": test_type,
        "required_flow_gpm": thresholds["required_flow_gpm"],
        "required_residual_psi": thresholds["required_residual_psi"],
        "measured_flow_gpm": None,
        "measured_residual_psi": None,
        "witness_window_start": None,
        "witness_window_end": None,
        "as_built_document_ref": None,
        "retest_count": 0,
        "witness_status": "NOT_SCHEDULED",
        "documentation_status": "PENDING",
    }
    db.stamp_create(row)
    db.acceptance_tests[row["id"]] = row

    before_project = db.snapshot(project)
    if project["status"] == "PERMITTED":
        project["status"] = "ACCEPTANCE"
    ledger.recompute_posture(project)
    db.touch_if_changed(project, before_project)
    return response.created(response.public(row))


@bp.get("/acceptance-tests/<test_id>")
def get_test(test_id):
    authenticate(ALL_ROLES)
    return response.ok(response.public(guards.must("acceptance_test", test_id)))


@bp.get("/acceptance-tests")
def list_tests():
    authenticate(ALL_ROLES)
    rows = helpers.apply_filters(
        list(db.acceptance_tests.values()),
        ["project_id", "witness_reviewer_id", "test_type", "witness_status", "documentation_status"],
    )
    return helpers.list_response(rows)


def _calendar_conflict(test, reviewer_id, start, end):
    """Closed interval with a symmetric 60-minute travel buffer (PRD 3.9)."""
    for other in db.acceptance_tests.values():
        if other["id"] == test["id"]:
            continue
        if other["witness_reviewer_id"] != reviewer_id:
            continue
        if other["witness_status"] != "SCHEDULED":
            continue
        other_start = parse_dt(other["witness_window_start"])
        other_end = parse_dt(other["witness_window_end"])
        if other_start is None or other_end is None:
            continue
        if start - TRAVEL_BUFFER <= other_end and end + TRAVEL_BUFFER >= other_start:
            return True
    return False


@bp.post("/acceptance-tests/<test_id>/schedule-witness")
def schedule_witness(test_id):
    actor = authenticate(["AhjReviewer"])
    test = guards.must("acceptance_test", test_id)
    project = guards.project_of(test)
    data = validate.body()
    guards.require_assigned_reviewer(actor, project, data.get("witness_reviewer_id"))
    start = validate.req_dt(data, "witness_window_start")
    end = validate.req_dt(data, "witness_window_end")

    guards.require_project_open(project)
    if test["witness_status"] == "WITNESSED_PASS":
        guards.terminal("This test has already passed its witnessed measurement.")
    if test["witness_status"] not in ("NOT_SCHEDULED", "WITNESSED_FAIL"):
        guards.invalid_transition(
            "A witness window is booked only from NOT_SCHEDULED or WITNESSED_FAIL."
        )
    if not start < end:
        raise ApiError(
            "ERR_WINDOW_START_NOT_BEFORE_END",
            "witness_window_start must be strictly before witness_window_end.",
        )
    if start < clock.now():
        raise ApiError(
            "ERR_WITNESS_WINDOW_IN_PAST",
            "A witness window must start at or after the current clock reading.",
        )
    if _calendar_conflict(test, actor.user_id, start, end):
        raise ApiError(
            "ERR_WITNESS_WINDOW_CONFLICT",
            "The buffered window collides with another scheduled witness visit.",
        )

    before_project = db.snapshot(project)
    was_failed = test["witness_status"] == "WITNESSED_FAIL"
    test["witness_reviewer_id"] = actor.user_id
    test["witness_window_start"] = fmt_dt(start)
    test["witness_window_end"] = fmt_dt(end)
    test["witness_status"] = "SCHEDULED"
    if was_failed:
        test["retest_count"] = (test["retest_count"] or 0) + 1
        if project["status"] == "CORRECTIVE_ACTION":
            project["status"] = "ACCEPTANCE"
        ledger.recompute_posture(project)
    db.touch(test)
    db.touch_if_changed(project, before_project)
    return response.ok(response.public(test))


@bp.post("/acceptance-tests/<test_id>/record-witness")
def record_witness(test_id):
    actor = authenticate(["AhjReviewer"])
    test = guards.must("acceptance_test", test_id)
    project = guards.project_of(test)
    guards.require_assigned_reviewer(actor, project)
    if test["witness_reviewer_id"] is not None and actor.user_id != test["witness_reviewer_id"]:
        raise ApiError(
            "ERR_NOT_ASSIGNED_REVIEWER",
            "Only the reviewer recorded as witness_reviewer_id may record the measurement.",
        )
    data = validate.body()
    flow = validate.req_num(data, "measured_flow_gpm", ge=0)
    residual = validate.req_num(data, "measured_residual_psi", ge=0)

    guards.require_project_open(project)
    if test["witness_status"] == "WITNESSED_PASS":
        guards.terminal("This test has already passed its witnessed measurement.")
    if test["witness_status"] != "SCHEDULED":
        guards.invalid_transition("A measurement is recorded only against a SCHEDULED test.")

    before_project = db.snapshot(project)
    test["measured_flow_gpm"] = float(flow)
    test["measured_residual_psi"] = float(residual)
    passed = _dec(flow) >= _dec(test["required_flow_gpm"]) and _dec(residual) >= _dec(
        test["required_residual_psi"]
    )
    if passed:
        test["witness_status"] = "WITNESSED_PASS"
        if test["test_type"] == "PUMP_FLOW_TEST":
            for pump in db.pumps.values():
                if pump["project_id"] == project["id"] and pump["state"] == "SIZED":
                    pump["state"] = "ACCEPTED"
                    db.touch(pump)
    else:
        test["witness_status"] = "WITNESSED_FAIL"
        cascades.cascade_witness_failure(project)
    db.touch(test)
    db.touch_if_changed(project, before_project)
    return response.ok(response.public(test))


@bp.post("/acceptance-tests/<test_id>/submit-as-built")
def submit_as_built(test_id):
    authenticate(["Contractor"])
    test = guards.must("acceptance_test", test_id)
    project = guards.project_of(test)
    data = validate.body()
    ref = validate.req_str(data, "as_built_document_ref")

    guards.require_project_open(project)
    if test["documentation_status"] == "AS_BUILT_ACCEPTED":
        guards.terminal("The as-built package for this test has already been accepted.")
    if test["documentation_status"] not in ("PENDING", "AS_BUILT_REJECTED"):
        guards.invalid_transition(
            "As-built documentation is lodged only from PENDING or AS_BUILT_REJECTED."
        )

    test["as_built_document_ref"] = ref
    test["documentation_status"] = "AS_BUILT_SUBMITTED"
    db.touch(test)
    return response.ok(response.public(test))


@bp.post("/acceptance-tests/<test_id>/accept-as-built")
def accept_as_built(test_id):
    actor = authenticate(["AhjReviewer"])
    test = guards.must("acceptance_test", test_id)
    project = guards.project_of(test)
    guards.require_assigned_reviewer(actor, project)
    data = validate.body()
    disposition = validate.req_str(data, "disposition", enum=AS_BUILT_DISPOSITIONS)

    guards.require_project_open(project)
    if test["documentation_status"] == "AS_BUILT_ACCEPTED":
        guards.terminal("The as-built package for this test has already been accepted.")
    if test["documentation_status"] != "AS_BUILT_SUBMITTED":
        guards.invalid_transition(
            "An as-built package is disposed of only from AS_BUILT_SUBMITTED."
        )
    if disposition == "ACCEPTED" and test["witness_status"] != "WITNESSED_PASS":
        guards.invalid_transition(
            "As-built acceptance requires the test's witness_status to be WITNESSED_PASS."
        )

    before_project = db.snapshot(project)
    if disposition == "REJECTED":
        test["documentation_status"] = "AS_BUILT_REJECTED"
    else:
        test["documentation_status"] = "AS_BUILT_ACCEPTED"
        rows = tests_of(project["id"])
        complete = all(
            t["witness_status"] == "WITNESSED_PASS"
            and t["documentation_status"] == "AS_BUILT_ACCEPTED"
            for t in rows
        )
        if complete and project["status"] == "ACCEPTANCE":
            cascades.cascade_close_out(project)
    db.touch(test)
    db.touch_if_changed(project, before_project)
    return response.ok(response.public(test))
