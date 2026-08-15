"""PermitFiling endpoints (PRD 3.5): create, submit, record-decision,
resubmit (cyclic review loop capped at MAX_REVIEW_CYCLES)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_FILING_NOT_DRAFT,
    ERR_FILING_NOT_REJECTED,
    ERR_FILING_NOT_SUBMITTED,
    ERR_LAYOUT_NOT_APPROVED,
    ERR_LAYOUT_NOT_FOUND,
    ERR_REVIEW_CYCLE_LIMIT_REACHED,
    HTTP_STATUS,
)
from middleware import require_roles
from response import success_object
from routes.common import paginate, resolve_filing, resolve_project, serialize
from services.validate import json_body, req_enum, req_str
from services.workflow import MAX_REVIEW_CYCLES

bp = Blueprint("filings", __name__)

AUTHORITIES = ("HEALTH_DEPT", "BUILDING_DEPT", "FIRE_MARSHAL")
FILING_READ_ROLES = ("PlatformAdmin", "ProjectManager", "PermitCoordinator")


@bp.route("/design-build-projects/<id>/permit-filings", methods=["POST"])
@require_roles("PermitCoordinator")
def create_filing(id, _user_id=None, _role=None):
    project = resolve_project(id)
    body = json_body(required=True)
    layout_id = req_str(body, "layout_id")
    authority = req_enum(body, "authority", AUTHORITIES)
    layout = db.layouts.get(layout_id)
    if layout is None or layout["project_id"] != project["id"]:
        raise ApiError(
            ERR_LAYOUT_NOT_FOUND, HTTP_STATUS[ERR_LAYOUT_NOT_FOUND],
            "KitchenLayout not found",
        )
    filing = db.stamp_new({
        "project_id": project["id"],
        "layout_id": layout["id"],
        "authority": authority,
        "submitted_at": None,
        "review_cycle_no": 0,
        "status": "DRAFT",
    })
    db.filings[filing["id"]] = filing
    return success_object(serialize(filing), 201)


@bp.route("/design-build-projects/<id>/permit-filings", methods=["GET"])
@require_roles(*FILING_READ_ROLES)
def list_filings(id, _user_id=None, _role=None):
    project = resolve_project(id)
    status = request.args.get("status")
    authority = request.args.get("authority")
    records = [f for f in db.filings.values() if f["project_id"] == project["id"]]
    if status is not None:
        records = [f for f in records if f["status"] == status]
    if authority is not None:
        records = [f for f in records if f["authority"] == authority]
    return paginate(records)


@bp.route("/design-build-projects/<id>/permit-filings/<filingId>", methods=["GET"])
@require_roles(*FILING_READ_ROLES)
def get_filing(id, filingId, _user_id=None, _role=None):
    project = resolve_project(id)
    filing = resolve_filing(project, filingId)
    return success_object(serialize(filing), 200)


def _submit_filing(filing: dict) -> None:
    filing["status"] = "SUBMITTED"
    filing["review_cycle_no"] = int(filing["review_cycle_no"]) + 1
    filing["submitted_at"] = db.now_iso()
    db.touch(filing)


@bp.route("/design-build-projects/<id>/permit-filings/<filingId>/submit", methods=["POST"])
@require_roles("PermitCoordinator")
def submit_filing(id, filingId, _user_id=None, _role=None):
    project = resolve_project(id)
    filing = resolve_filing(project, filingId)
    if filing["status"] != "DRAFT":
        raise ApiError(
            ERR_FILING_NOT_DRAFT, HTTP_STATUS[ERR_FILING_NOT_DRAFT],
            "Submit requires Filing in DRAFT",
        )
    layout = db.layouts.get(filing["layout_id"])
    if layout is None or layout["status"] != "APPROVED":
        raise ApiError(
            ERR_LAYOUT_NOT_APPROVED, HTTP_STATUS[ERR_LAYOUT_NOT_APPROVED],
            "Filing submit requires an APPROVED layout",
        )
    _submit_filing(filing)
    return success_object(serialize(filing), 200)


@bp.route("/design-build-projects/<id>/permit-filings/<filingId>/record-decision", methods=["POST"])
@require_roles("PermitCoordinator")
def record_decision(id, filingId, _user_id=None, _role=None):
    project = resolve_project(id)
    filing = resolve_filing(project, filingId)
    body = json_body(required=True)
    decision = req_enum(body, "decision", ("APPROVED", "REJECTED"))
    if filing["status"] != "SUBMITTED":
        raise ApiError(
            ERR_FILING_NOT_SUBMITTED, HTTP_STATUS[ERR_FILING_NOT_SUBMITTED],
            "Record-decision requires Filing in SUBMITTED",
        )
    filing["status"] = decision
    db.touch(filing)
    return success_object(serialize(filing), 200)


@bp.route("/design-build-projects/<id>/permit-filings/<filingId>/resubmit", methods=["POST"])
@require_roles("PermitCoordinator")
def resubmit_filing(id, filingId, _user_id=None, _role=None):
    project = resolve_project(id)
    filing = resolve_filing(project, filingId)
    # State legality before the structural cycle-limit check.
    if filing["status"] != "REJECTED":
        raise ApiError(
            ERR_FILING_NOT_REJECTED, HTTP_STATUS[ERR_FILING_NOT_REJECTED],
            "Resubmit requires Filing in REJECTED",
        )
    if int(filing["review_cycle_no"]) >= MAX_REVIEW_CYCLES:
        raise ApiError(
            ERR_REVIEW_CYCLE_LIMIT_REACHED, HTTP_STATUS[ERR_REVIEW_CYCLE_LIMIT_REACHED],
            "review_cycle_no has reached MAX_REVIEW_CYCLES (3)",
        )
    _submit_filing(filing)
    return success_object(serialize(filing), 200)
