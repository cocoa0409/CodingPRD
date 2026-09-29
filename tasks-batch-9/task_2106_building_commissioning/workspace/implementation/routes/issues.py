"""Issue log endpoints."""
from flask import Blueprint

import calc
import services
from core import (
    ALL_ROLES, ROLE_CONTRACTOR, ROLE_CX_AUTHORITY, ROLE_OWNER_REP, actor, authenticate,
    body_json, bump_project, db, fail, ok, ok_list, paginate, public, q, sorted_rows,
    touch, v_enum, v_string,
)
from finders import get_equipment, get_issue, get_project, get_test

bp = Blueprint("issues", __name__)


@bp.post("/issues")
def create_issue_route():
    authenticate([ROLE_CX_AUTHORITY, ROLE_CONTRACTOR])
    body = body_json()
    project_id = v_string(body, "project_id")
    origin = v_enum(body, "origin", calc.ISSUE_ORIGINS)
    severity = v_enum(body, "severity", calc.ISSUE_SEVERITIES)
    description = v_string(body, "description")
    equipment_id = v_string(body, "equipment_id", required=False, default=None)
    source_ref_id = v_string(body, "source_ref_id", required=False, default=None)

    project = get_project(project_id)
    equipment_row = get_equipment(equipment_id) if equipment_id is not None else None

    if equipment_row is not None and equipment_row["project_id"] != project_id:
        fail("ERR_PROJECT_SCOPE_MISMATCH",
             "The equipment unit belongs to a different engagement.")

    hold = calc.compute_retainage_hold_cents(project, equipment_row, severity)
    cap = calc.retainage_cap_cents(project)
    if project["retainage_withheld_cents"] + hold > cap:
        fail("ERR_RETAINAGE_CAP_EXCEEDED",
             "The retainage hold would exceed the cap of %d cents." % cap)

    issue = services.create_issue(
        project,
        origin=origin,
        severity=severity,
        description=description,
        equipment_id=equipment_id,
        source_ref_id=source_ref_id,
        opened_by_user_id=actor(),
    )
    bump_project(project)
    services.reconcile()
    return ok(public(issue), 201)


@bp.get("/issues")
def list_issues():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(db.issues.values()))
    filters = [
        ("project_id", "project_id"),
        ("equipment_id", "equipment_id"),
        ("closure_retest_id", "closure_retest_id"),
        ("status", "status"),
        ("severity", "severity"),
        ("origin", "origin"),
    ]
    for param, field in filters:
        value = q(param)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, limit, offset, total = paginate(rows)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.get("/issues/<issue_id>")
def read_issue(issue_id):
    authenticate(ALL_ROLES)
    return ok(public(get_issue(issue_id)))


@bp.post("/issues/<issue_id>/propose-resolution")
def propose_resolution(issue_id):
    authenticate([ROLE_CONTRACTOR])
    issue = get_issue(issue_id)
    body = body_json()
    proposed_resolution = v_string(body, "proposed_resolution")

    if issue["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Only an OPEN issue may receive a proposed resolution.")

    services.apply_issue_status_change(issue, "IN_REVIEW")
    issue["proposed_by_user_id"] = actor()
    issue["proposed_resolution"] = proposed_resolution
    touch(issue)
    services.reconcile()
    return ok(public(issue))


@bp.post("/issues/<issue_id>/verify-closure")
def verify_closure(issue_id):
    authenticate([ROLE_CX_AUTHORITY])
    issue = get_issue(issue_id)
    body = body_json()
    v_string(body, "closure_note")
    closure_retest_id = v_string(body, "closure_retest_id", required=False, default=None)

    retest = get_test(closure_retest_id) if closure_retest_id is not None else None

    if issue["status"] != "IN_REVIEW":
        fail("ERR_INVALID_STATE", "Only an IN_REVIEW issue may be closed.")

    if issue["origin"] == "FUNCTIONAL" and issue["severity"] in ("S1", "S2"):
        if retest is None or retest["status"] != "PASSED":
            fail("ERR_RETEST_EVIDENCE_REQUIRED",
                 "Closing this deficiency requires a PASSED re-test.")

    if retest is not None and retest["equipment_id"] != issue["equipment_id"]:
        fail("ERR_RETEST_SCOPE_MISMATCH",
             "The re-test belongs to a different equipment unit.")

    project = db.projects.get(issue["project_id"])
    services.apply_issue_status_change(issue, "VERIFIED_CLOSED")
    issue["closure_retest_id"] = closure_retest_id
    touch(issue)
    bump_project(project)
    services.reconcile()
    return ok(public(issue))


@bp.post("/issues/<issue_id>/reopen")
def reopen_issue(issue_id):
    authenticate([ROLE_CX_AUTHORITY])
    issue = get_issue(issue_id)
    body = body_json()
    v_string(body, "reason")

    if issue["status"] not in ("IN_REVIEW", "VERIFIED_CLOSED", "DEFERRED"):
        fail("ERR_INVALID_STATE",
             "Only an IN_REVIEW, VERIFIED_CLOSED or DEFERRED issue may be re-opened.")

    project = db.projects.get(issue["project_id"])
    previous = issue["status"]
    services.apply_issue_status_change(issue, "OPEN")
    issue["reopen_count"] = issue["reopen_count"] + 1
    if previous in ("IN_REVIEW", "VERIFIED_CLOSED"):
        issue["proposed_by_user_id"] = None
        issue["proposed_resolution"] = None
        issue["closure_retest_id"] = None
    touch(issue)
    bump_project(project)
    services.reconcile()
    return ok(public(issue))


@bp.post("/issues/<issue_id>/defer")
def defer_issue(issue_id):
    authenticate([ROLE_OWNER_REP])
    issue = get_issue(issue_id)
    body = body_json()
    v_string(body, "deferral_reason")

    if issue["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Only an OPEN issue may be deferred.")
    linked = [d for d in db.deferred_tests.values()
              if d.get("issue_id") == issue["id"] and d["status"] in calc.DEFERRED_LIVE]
    if not linked:
        fail("ERR_INVALID_STATE",
             "A PLANNED or BLOCKED seasonal test must reference this issue.")

    project = db.projects.get(issue["project_id"])
    services.apply_issue_status_change(issue, "DEFERRED")
    touch(issue)
    bump_project(project)
    services.reconcile()
    return ok(public(issue))


@bp.post("/issues/<issue_id>/void")
def void_issue(issue_id):
    authenticate([ROLE_CX_AUTHORITY])
    issue = get_issue(issue_id)
    body = body_json()
    v_string(body, "reason")

    if issue["status"] not in ("OPEN", "IN_REVIEW", "DEFERRED"):
        fail("ERR_INVALID_STATE",
             "Only an OPEN, IN_REVIEW or DEFERRED issue may be voided.")

    project = db.projects.get(issue["project_id"])
    services.apply_issue_status_change(issue, "VOID")
    touch(issue)
    bump_project(project)
    services.reconcile()
    return ok(public(issue))
