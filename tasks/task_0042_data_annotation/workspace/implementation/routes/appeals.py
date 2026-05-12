"""Appeal endpoints."""

from flask import Blueprint, request, g

import db
from middleware import require_role
from response import success
from errors import (
    raise_error,
    ERR_PACKAGE_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_APPEAL_NOT_FOUND,
    ERR_ANNOTATOR_NOT_FOUND,
    ERR_INVALID_PARAMETER,
)
from services.serializers import appeal_view
from services import appeal as appeal_svc


bp = Blueprint("appeals", __name__)


def _get_pkg(pkg_id: str) -> dict:
    p = db.find_by_id("task_packages", pkg_id)
    if not p:
        raise_error(ERR_PACKAGE_NOT_FOUND, "Package not found.")
    return p


def _get_appeal(appeal_id: str) -> dict:
    ap = db.find_by_id("appeals", appeal_id)
    if not ap:
        raise_error(ERR_APPEAL_NOT_FOUND, "Appeal not found.")
    return ap


@bp.route("/task-packages/<pkg_id>/appeals", methods=["POST"])
def create_appeal(pkg_id):
    require_role("Annotator")
    p = _get_pkg(pkg_id)
    project = db.find_by_id("projects", p["project_id"])
    body = request.get_json(silent=True) or {}
    inspection_id = body.get("inspection_id")
    reason = body.get("reason")
    if not inspection_id:
        raise_error(ERR_INVALID_PARAMETER, "inspection_id is required.")
    if not reason or not isinstance(reason, str):
        raise_error(ERR_INVALID_PARAMETER, "reason is required.")
    inspection = db.find_by_id("inspections", inspection_id)
    if not inspection:
        raise_error(ERR_INSPECTION_NOT_FOUND, "Inspection not found.")
    if inspection.get("package_id") != p["id"]:
        raise_error(ERR_INSPECTION_NOT_FOUND, "Inspection does not belong to package.")

    annotator = db.find_by_id("annotators", g.user_id)
    if not annotator:
        raise_error(ERR_ANNOTATOR_NOT_FOUND, "Annotator not found.")
    ap = appeal_svc.submit_appeal(p, project, inspection, annotator, reason)
    return success(appeal_view(ap), status_code=201)


@bp.route("/appeals/<appeal_id>", methods=["GET"])
def read_appeal(appeal_id):
    require_role("ProjectManager", "QAReviewer", "Annotator")
    ap = _get_appeal(appeal_id)
    return success(appeal_view(ap))


@bp.route("/appeals/<appeal_id>/assign-arbiter", methods=["POST"])
def assign_arbiter(appeal_id):
    require_role("ProjectManager")
    ap = _get_appeal(appeal_id)
    out = appeal_svc.assign_arbiter(ap)
    return success(appeal_view(out))


@bp.route("/appeals/<appeal_id>/decide", methods=["POST"])
def decide_appeal(appeal_id):
    require_role("Annotator")
    ap = _get_appeal(appeal_id)
    arbiter = db.find_by_id("annotators", g.user_id)
    if not arbiter:
        raise_error(ERR_ANNOTATOR_NOT_FOUND, "Annotator not found.")
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    out = appeal_svc.decide(ap, arbiter, decision)
    return success(appeal_view(out))
