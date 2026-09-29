"""Deck findings, upgrade scoping and the re-permitting cascade (PRD 3.6)."""

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
    FINDING_STATUSES,
    FINDING_TYPES,
    SEVERITIES,
    acting_party_must_be,
    get_finding,
    get_project,
    invalid_state,
    paged,
)
from validation import (
    enum_field,
    enum_query,
    get_body,
    int_field,
    num_field,
    str_field,
    str_query,
)

bp = Blueprint("deck", __name__)

READ_ROLES = (
    "ProjectCoordinator",
    "RoofingContractor",
    "SolarOwner",
    "SystemOwner",
    "AHJInspector",
)


@bp.route("/reroof/projects/<project_id>/deck-findings", methods=["POST"])
@endpoint("RoofingContractor")
def create_finding(project_id):
    project = get_project(project_id)
    body = get_body()
    finding_type = enum_field(body, "finding_type", FINDING_TYPES, required=True)
    severity = enum_field(body, "severity", SEVERITIES, required=True)
    affected_area_sqft = num_field(
        body, "affected_area_sqft", required=True, exclusive_min=0
    )
    attachment_count_affected = int_field(
        body, "attachment_count_affected", required=True, minimum=0
    )

    snapshot = services.project_snapshot(project)
    finding = new_row(
        {
            "project_id": project["id"],
            "finding_type": finding_type,
            "severity": severity,
            "affected_area_sqft": affected_area_sqft,
            "attachment_count_affected": attachment_count_affected,
            "status": "OPEN",
            "upgrade_cost_cents": 0,
            "requires_repermit": calc.requires_repermit(finding_type, severity),
            "scoped_by_party_id": None,
            "completed_by_party_id": None,
            "waiver_reason": None,
            "scoped_at": None,
            "completed_at": None,
        }
    )
    db.findings[finding["id"]] = finding
    services.rollup_project(project)
    services.commit_project(project, snapshot)
    return ok_row(finding, 201)


@bp.route("/reroof/deck-findings/<finding_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_finding(finding_id):
    return ok_row(get_finding(finding_id))


@bp.route("/reroof/deck-findings", methods=["GET"])
@endpoint(*READ_ROLES)
def list_findings():
    project_id = str_query("project_id")
    severity = enum_query("severity", SEVERITIES)
    status = enum_query("status", FINDING_STATUSES)
    scoped_by = str_query("scoped_by_party_id")
    completed_by = str_query("completed_by_party_id")

    rows = []
    for finding in db.findings.values():
        if project_id is not None and finding["project_id"] != project_id:
            continue
        if severity is not None and finding["severity"] != severity:
            continue
        if status is not None and finding["status"] != status:
            continue
        if scoped_by is not None and finding["scoped_by_party_id"] != scoped_by:
            continue
        if completed_by is not None and finding["completed_by_party_id"] != completed_by:
            continue
        rows.append(finding)
    return paged(rows)


def _reopen_permits(project, finding):
    """The depth-4 re-permitting cascade of PRD 3.6."""
    now = db.now()
    for permit in services.project_permits(project["id"]):
        if permit["status"] != "APPROVED":
            continue
        jurisdiction = db.jurisdictions.get(permit["jurisdiction_id"])
        if jurisdiction is None or not jurisdiction["repermit_required_for_reinstall"]:
            continue
        permit["status"] = "SUBMITTED"
        permit["revision_count"] += 1
        permit["reopened_by_finding_id"] = finding["id"]
        permit["submitted_at"] = now
        permit["fee_cents"] = calc.permit_fee(
            permit, jurisdiction, project, permit["revision_count"]
        )
        permit["review_deadline_utc"] = now + timedelta(
            days=int(jurisdiction["permit_review_days"])
        )
        touch(permit)
        for inspection in services.permit_inspections(permit["id"]):
            if inspection["status"] != "PASSED":
                continue
            if inspection["inspection_type"] not in ("ROOF_DECK", "MOUNTING"):
                continue
            inspection["status"] = "CORRECTION_REQUIRED"
            inspection["attempt_number"] += 1
            touch(inspection)


@bp.route("/reroof/deck-findings/<finding_id>/upgrade", methods=["POST"])
@endpoint("RoofingContractor")
def upgrade_finding(finding_id):
    finding = get_finding(finding_id)
    project = db.projects.get(finding["project_id"])
    body = get_body()
    action = enum_field(
        body, "action", ("SCOPE", "COMPLETE", "WAIVE", "RESCOPE"), required=True
    )
    waiver_reason = str_field(body, "waiver_reason", required=False, default=None)
    if action == "WAIVE" and waiver_reason is None:
        raise E.invalid_request("field 'waiver_reason' is required for a WAIVE action")

    # Priority 8: state legality of the requested transition.
    legal_from = {
        "SCOPE": ("OPEN",),
        "WAIVE": ("OPEN",),
        "COMPLETE": ("UPGRADE_SCOPED",),
        "RESCOPE": ("UPGRADE_SCOPED",),
    }[action]
    if finding["status"] not in legal_from:
        raise invalid_state(
            "cannot %s a deck finding in %s" % (action, finding["status"])
        )

    actor = g.get("actor_id")

    # Priority 16: segregation of duties on completion.
    if action == "COMPLETE" and actor == finding["scoped_by_party_id"]:
        raise ApiError(
            E.ERR_SEGREGATION_OF_DUTIES,
            "the party that scoped a finding may not sign it off",
            403,
        )

    # Priority 17: the acting party must be a roofer.
    acting_party_must_be(("ROOFER",))

    snapshot = services.project_snapshot(project)
    now = db.now()

    if action == "SCOPE":
        cost = calc.deck_upgrade_cost(finding, project["posture"])
        # Priority 30
        if project["scoped_upgrade_cost_cents"] + cost > project["upgrade_budget_cents"]:
            raise ApiError(
                E.ERR_UPGRADE_BUDGET_EXCEEDED,
                "scoping this finding would exceed the project's upgrade budget",
                402,
            )
        finding["upgrade_cost_cents"] = cost
        finding["status"] = "UPGRADE_SCOPED"
        finding["scoped_at"] = now
        finding["scoped_by_party_id"] = actor
        touch(finding)
        if finding["requires_repermit"]:
            _reopen_permits(project, finding)
    elif action == "WAIVE":
        finding["status"] = "WAIVED"
        finding["waiver_reason"] = waiver_reason
        finding["completed_at"] = now
        touch(finding)
        if finding["severity"] == "CRITICAL":
            project["warranty_notice_status"] = "LAPSED"
    elif action == "COMPLETE":
        finding["status"] = "UPGRADE_COMPLETED"
        finding["completed_at"] = now
        finding["completed_by_party_id"] = actor
        touch(finding)
    else:
        finding["status"] = "OPEN"
        finding["upgrade_cost_cents"] = 0
        finding["scoped_by_party_id"] = None
        finding["scoped_at"] = None
        touch(finding)

    services.rollup_project(project)
    services.evaluate_reinstall(project)
    services.commit_project(project, snapshot)
    return ok_row(finding)
