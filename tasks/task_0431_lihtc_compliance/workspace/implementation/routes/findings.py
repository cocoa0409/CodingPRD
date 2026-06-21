"""Finding endpoints and the 8823 lifecycle (PRD §3.9)."""

from flask import Blueprint, g, request

import errors
import middleware
import response
import serializers
import validate
from clock import clock
from db import db, touch
from services import domain

bp = Blueprint("findings", __name__)


@bp.route("/findings", methods=["GET"])
def list_findings():
    middleware.require_role("OwnerAgent", "StateHFA")
    limit, offset = validate.parse_pagination()
    project_id = request.args.get("project_id")
    building_id = request.args.get("building_id")
    inspection_id = request.args.get("inspection_id")
    items = list(db.findings.values())
    if project_id is not None:
        items = [f for f in items if f["project_id"] == project_id]
    if building_id is not None:
        items = [f for f in items if f["building_id"] == building_id]
    if inspection_id is not None:
        items = [f for f in items if f["inspection_id"] == inspection_id]
    items = serializers.sort_by_created(items)
    page, meta = validate.paginate(items, limit, offset)
    return response.success(serializers.public_list(page), status=200, pagination=meta)


@bp.route("/findings/<fid>", methods=["GET"])
def get_finding(fid):
    middleware.require_role("OwnerAgent", "StateHFA")
    finding = db.findings.get(fid)
    if finding is None:
        raise errors.not_found("Finding not found")
    return response.success(serializers.public(finding), status=200)


@bp.route("/findings/<fid>/report", methods=["POST"])
def report_finding(fid):
    middleware.require_role("StateHFA")
    finding = db.findings.get(fid)
    if finding is None:
        raise errors.not_found("Finding not found")
    # Priority 4 (state) beats priority 6 (segregation of duties).
    if finding["status"] != "OPEN":
        raise errors.invalid_state("Finding must be OPEN to report")
    # Priority 6: segregation of duties.
    if g.user_id == finding["origin_agent_id"]:
        raise errors.ApiError(
            errors.ERR_SEGREGATION_OF_DUTIES, 403,
            "Reporting actor must differ from the finding's origin agent",
        )

    finding["status"] = "REPORTED_8823"
    finding["reported_8823_on"] = clock.now_iso()
    touch(finding)

    project = db.projects.get(finding["project_id"])
    if project is not None:
        domain.recompute_project_posture(project)
    return response.success(serializers.public(finding), status=200)


@bp.route("/findings/<fid>/correct", methods=["POST"])
def correct_finding(fid):
    middleware.require_role("OwnerAgent")
    finding = db.findings.get(fid)
    if finding is None:
        raise errors.not_found("Finding not found")
    if finding["status"] not in ("OPEN", "REPORTED_8823"):
        raise errors.invalid_state("Finding must be OPEN or REPORTED_8823 to correct")

    finding["status"] = "CORRECTED"
    touch(finding)

    project = db.projects.get(finding["project_id"])
    if project is not None:
        domain.recompute_project_posture(project)
    return response.success(serializers.public(finding), status=200)
