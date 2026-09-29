"""Permit applications, fees and AHJ inspections (PRD 3.7)."""

from datetime import timedelta

import calc
import errors as E
import services
from errors import ApiError
from flask import Blueprint, g
from db import db, new_row, touch
from middleware import endpoint
from response import ok_row
from routes.helpers import (
    INSPECTION_STATUSES,
    INSPECTION_TYPES,
    PERMIT_SCOPES,
    PERMIT_STATUSES,
    get_inspection,
    get_jurisdiction,
    get_permit,
    get_project,
    invalid_state,
    paged,
    resolve_fk,
)
from validation import (
    bool_field,
    date_field,
    datetime_field,
    enum_field,
    enum_query,
    get_body,
    str_field,
    str_query,
)

bp = Blueprint("permits", __name__)

PERMIT_READ_ROLES = (
    "ProjectCoordinator",
    "RoofingContractor",
    "SolarOwner",
    "SystemOwner",
    "AHJInspector",
)
INSPECTION_READ_ROLES = (
    "ProjectCoordinator",
    "SolarContractor",
    "RoofingContractor",
    "SolarOwner",
    "SystemOwner",
    "AHJInspector",
)


def _jurisdiction_of(permit):
    return db.jurisdictions.get(permit["jurisdiction_id"])


def _require_own_jurisdiction(permit):
    """Priority 6: an AHJInspector acts only for its own jurisdiction."""
    if g.get("actor_id") != permit["jurisdiction_id"]:
        raise ApiError(
            E.ERR_PARTY_NOT_ON_PROJECT,
            "the acting jurisdiction does not govern this permit application",
            403,
        )


# --------------------------------------------------------------------------
# PermitApplication
# --------------------------------------------------------------------------
@bp.route("/reroof/permit-applications", methods=["POST"])
@endpoint("ProjectCoordinator")
def create_permit():
    body = get_body()
    project = resolve_fk(body, "project_id", get_project)
    jurisdiction = resolve_fk(body, "jurisdiction_id", get_jurisdiction)
    project_id = str_field(body, "project_id", required=True)
    jurisdiction_id = str_field(body, "jurisdiction_id", required=True)
    scope = enum_field(body, "scope", PERMIT_SCOPES, required=True)
    expedited = bool_field(body, "expedited", required=False, default=False)

    snapshot = services.project_snapshot(project)
    permit = new_row(
        {
            "project_id": project_id,
            "jurisdiction_id": jurisdiction_id,
            "scope": scope,
            "expedited": expedited,
            "status": "DRAFT",
            "revision_count": 0,
            "fee_cents": 0,
            "submitted_at": None,
            "decided_at": None,
            "review_deadline_utc": None,
            "rejection_reason": None,
            "reopened_by_finding_id": None,
        }
    )
    db.permits[permit["id"]] = permit
    services.rollup_project(project)
    services.commit_project(project, snapshot)
    return ok_row(permit, 201)


@bp.route("/reroof/permit-applications/<permit_id>", methods=["GET"])
@endpoint(*PERMIT_READ_ROLES)
def read_permit(permit_id):
    return ok_row(get_permit(permit_id))


@bp.route("/reroof/permit-applications", methods=["GET"])
@endpoint(*PERMIT_READ_ROLES)
def list_permits():
    project_id = str_query("project_id")
    jurisdiction_id = str_query("jurisdiction_id")
    status = enum_query("status", PERMIT_STATUSES)
    reopened_by = str_query("reopened_by_finding_id")

    rows = []
    for permit in db.permits.values():
        if project_id is not None and permit["project_id"] != project_id:
            continue
        if jurisdiction_id is not None and permit["jurisdiction_id"] != jurisdiction_id:
            continue
        if status is not None and permit["status"] != status:
            continue
        if reopened_by is not None and permit["reopened_by_finding_id"] != reopened_by:
            continue
        rows.append(permit)
    return paged(rows)


@bp.route("/reroof/permit-applications/<permit_id>/submission", methods=["POST"])
@endpoint("ProjectCoordinator")
def submit_permit(permit_id):
    permit = get_permit(permit_id)
    project = db.projects.get(permit["project_id"])
    jurisdiction = _jurisdiction_of(permit)
    get_body()

    # Priority 8
    if permit["status"] not in ("DRAFT", "REJECTED"):
        raise invalid_state(
            "cannot submit a permit application in %s" % permit["status"]
        )

    snapshot = services.project_snapshot(project)
    now = db.now()
    resubmission = permit["status"] == "REJECTED"
    permit["status"] = "SUBMITTED"
    permit["submitted_at"] = now
    permit["review_deadline_utc"] = now + timedelta(
        days=int(jurisdiction["permit_review_days"])
    )
    if resubmission:
        permit["revision_count"] += 1
        permit["rejection_reason"] = None
    permit["fee_cents"] = calc.permit_fee(
        permit, jurisdiction, project, permit["revision_count"]
    )
    touch(permit)

    services.rollup_project(project)
    services.commit_project(project, snapshot)
    return ok_row(permit)


@bp.route("/reroof/permit-applications/<permit_id>/decision", methods=["POST"])
@endpoint("AHJInspector")
def decide_permit(permit_id):
    permit = get_permit(permit_id)
    project = db.projects.get(permit["project_id"])
    body = get_body()
    decision = enum_field(body, "decision", ("APPROVE", "REJECT"), required=True)
    rejection_reason = str_field(body, "rejection_reason", required=False, default=None)
    if decision == "REJECT" and rejection_reason is None:
        raise E.invalid_request("field 'rejection_reason' is required for a REJECT")

    # Priority 6
    _require_own_jurisdiction(permit)
    # Priority 8
    if permit["status"] != "SUBMITTED":
        raise invalid_state(
            "cannot decide a permit application in %s" % permit["status"]
        )

    snapshot = services.project_snapshot(project)
    now = db.now()
    if decision == "APPROVE":
        permit["status"] = "APPROVED"
        permit["decided_at"] = now
        touch(permit)
        services.rollup_project(project)
        services.evaluate_reinstall(project)
    else:
        permit["status"] = "REJECTED"
        permit["decided_at"] = now
        permit["rejection_reason"] = rejection_reason
        touch(permit)
        services.revoke_scheduled_windows(project, only_from_now=True)
        services.rollup_project(project)
        services.evaluate_reinstall(project)

    services.commit_project(project, snapshot)
    return ok_row(permit)


# --------------------------------------------------------------------------
# Inspection
# --------------------------------------------------------------------------
@bp.route("/reroof/permit-applications/<permit_id>/inspections", methods=["POST"])
@endpoint("ProjectCoordinator")
def book_inspection(permit_id):
    permit = get_permit(permit_id)
    project = db.projects.get(permit["project_id"])
    jurisdiction = _jurisdiction_of(permit)
    body = get_body()
    inspection_type = enum_field(
        body, "inspection_type", INSPECTION_TYPES, required=True
    )
    slot_date = date_field(body, "slot_date", required=True)
    window_start_utc = datetime_field(body, "window_start_utc", required=True)
    window_end_utc = datetime_field(body, "window_end_utc", required=True)

    # Priority 8
    if permit["status"] not in ("SUBMITTED", "APPROVED"):
        raise ApiError(
            E.ERR_PERMIT_NOT_SUBMITTED,
            "the permit application must be SUBMITTED or APPROVED to book an inspection",
            409,
        )
    # Priority 20
    if window_end_utc <= window_start_utc:
        raise ApiError(
            E.ERR_INVALID_WINDOW_BOUNDS,
            "window_end_utc must be strictly after window_start_utc",
            422,
        )
    if window_start_utc.date() != window_end_utc.date():
        raise ApiError(
            E.ERR_INVALID_WINDOW_BOUNDS,
            "the inspection window must fall on a single UTC calendar date",
            422,
        )
    if slot_date != window_start_utc.date().isoformat():
        raise ApiError(
            E.ERR_INVALID_WINDOW_BOUNDS,
            "slot_date must equal the UTC date of window_start_utc",
            422,
        )
    # Priority 21
    floor = db.now() + timedelta(days=int(jurisdiction["backlog_days"]))
    if window_start_utc < floor:
        raise ApiError(
            E.ERR_INSPECTION_BACKLOG_VIOLATION,
            "window_start_utc is earlier than the jurisdiction's backlog floor",
            422,
        )
    # Priority 23
    booked = 0
    for other in db.inspections.values():
        parent = db.permits.get(other["permit_application_id"])
        if parent is None or parent["jurisdiction_id"] != permit["jurisdiction_id"]:
            continue
        if other["slot_date"] != slot_date:
            continue
        if other["status"] in ("SCHEDULED", "CORRECTION_REQUIRED"):
            booked += 1
    if booked >= int(jurisdiction["inspection_slots_per_day"]):
        raise ApiError(
            E.ERR_INSPECTION_SLOT_FULL,
            "the jurisdiction has no remaining inspection slots on %s" % slot_date,
            409,
        )

    snapshot = services.project_snapshot(project)
    inspection = new_row(
        {
            "permit_application_id": permit["id"],
            "inspection_type": inspection_type,
            "slot_date": slot_date,
            "window_start_utc": window_start_utc,
            "window_end_utc": window_end_utc,
            "status": "SCHEDULED",
            "attempt_number": 1,
            "result_note": None,
            "inspected_at": None,
        }
    )
    db.inspections[inspection["id"]] = inspection
    services.rollup_project(project)
    services.commit_project(project, snapshot)
    return ok_row(inspection, 201)


@bp.route("/reroof/permit-applications/<permit_id>/inspections", methods=["GET"])
@endpoint(*PERMIT_READ_ROLES)
def list_permit_inspections(permit_id):
    permit = get_permit(permit_id)
    return paged(services.permit_inspections(permit["id"]))


@bp.route("/reroof/inspections/<inspection_id>", methods=["GET"])
@endpoint(*INSPECTION_READ_ROLES)
def read_inspection(inspection_id):
    return ok_row(get_inspection(inspection_id))


@bp.route("/reroof/inspections/<inspection_id>/result", methods=["POST"])
@endpoint("AHJInspector")
def record_result(inspection_id):
    inspection = get_inspection(inspection_id)
    permit = db.permits.get(inspection["permit_application_id"])
    project = db.projects.get(permit["project_id"])
    body = get_body()
    result = enum_field(body, "result", ("PASS", "FAIL", "CORRECTION"), required=True)
    result_note = str_field(body, "result_note", required=False, default=None)

    # Priority 6
    _require_own_jurisdiction(permit)
    # Priority 8
    if inspection["status"] != "SCHEDULED":
        raise invalid_state(
            "cannot record a result on an inspection in %s" % inspection["status"]
        )
    if result == "PASS" and permit["status"] not in ("SUBMITTED", "APPROVED"):
        raise ApiError(
            E.ERR_PERMIT_NOT_SUBMITTED,
            "the parent permit application must still be SUBMITTED or APPROVED to pass",
            409,
        )

    snapshot = services.project_snapshot(project)
    inspection["inspected_at"] = db.now()
    if result_note is not None:
        inspection["result_note"] = result_note
    if result == "PASS":
        inspection["status"] = "PASSED"
    elif result == "FAIL":
        inspection["status"] = "FAILED"
    else:
        inspection["status"] = "CORRECTION_REQUIRED"
    touch(inspection)

    services.rollup_project(project)
    if result == "PASS" and inspection["inspection_type"] == "ELECTRICAL_FINAL":
        services.evaluate_commissioned(project)
    services.commit_project(project, snapshot)
    return ok_row(inspection)
