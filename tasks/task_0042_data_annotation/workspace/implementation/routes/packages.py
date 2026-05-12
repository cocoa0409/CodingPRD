"""TaskPackage and QualityInspection endpoints."""

from flask import Blueprint, request, g

import db
from middleware import require_role
from response import success
from errors import (
    raise_error,
    ERR_PROJECT_NOT_FOUND,
    ERR_PACKAGE_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_ANNOTATOR_NOT_FOUND,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_PROJECT_NOT_OPEN,
    ERR_PACKAGE_STATE_INVALID,
    ERR_INVALID_PARAMETER,
)
from services.serializers import (
    task_package_view, inspection_view, submission_view,
)
from services import package as pkg_svc


bp = Blueprint("packages", __name__)


def _get_pkg(pkg_id: str) -> dict:
    p = db.find_by_id("task_packages", pkg_id)
    if not p:
        raise_error(ERR_PACKAGE_NOT_FOUND, "Package not found.")
    return p


def _get_project(project_id: str) -> dict:
    p = db.find_by_id("projects", project_id)
    if not p:
        raise_error(ERR_PROJECT_NOT_FOUND, "Project not found.")
    return p


def _get_annotator_or_404(aid: str) -> dict:
    a = db.find_by_id("annotators", aid)
    if not a:
        raise_error(ERR_ANNOTATOR_NOT_FOUND, "Annotator not found.")
    return a


@bp.route("/task-packages/<pkg_id>", methods=["GET"])
def read_package(pkg_id):
    require_role("ProjectManager", "QAReviewer", "Annotator")
    p = _get_pkg(pkg_id)
    return success(task_package_view(p))


@bp.route("/task-packages/<pkg_id>/claim", methods=["POST"])
def claim(pkg_id):
    require_role("Annotator")
    p = _get_pkg(pkg_id)
    project = _get_project(p["project_id"])
    annotator = _get_annotator_or_404(g.user_id)
    out = pkg_svc.claim_package(p, project, annotator)
    return success(task_package_view(out))


@bp.route("/task-packages/<pkg_id>/dispatch", methods=["POST"])
def dispatch(pkg_id):
    require_role("ProjectManager")
    p = _get_pkg(pkg_id)
    project = _get_project(p["project_id"])
    body = request.get_json(silent=True) or {}
    aid = body.get("annotator_id")
    if not aid:
        raise_error(ERR_INVALID_PARAMETER, "annotator_id is required.")
    annotator = _get_annotator_or_404(aid)
    out = pkg_svc.dispatch_package(p, project, annotator)
    return success(task_package_view(out))


@bp.route("/task-packages/<pkg_id>/submit", methods=["POST"])
def submit(pkg_id):
    require_role("Annotator")
    p = _get_pkg(pkg_id)
    project = _get_project(p["project_id"])
    annotator = _get_annotator_or_404(g.user_id)
    body = request.get_json(silent=True) or {}
    labels = body.get("labels")
    if labels is None:
        raise_error(ERR_INVALID_PARAMETER, "labels is required.")
    pkg, _sub = pkg_svc.submit_labels(p, project, annotator, labels)
    return success(task_package_view(pkg))


@bp.route("/task-packages/<pkg_id>/start-inspection", methods=["POST"])
def start_inspection(pkg_id):
    require_role("QAReviewer")
    p = _get_pkg(pkg_id)
    project = _get_project(p["project_id"])
    inspection = pkg_svc.start_inspection(p, project, g.user_id)
    return success(inspection_view(inspection))


@bp.route("/task-packages/<pkg_id>/inspections/<inspection_id>/finalize",
          methods=["POST"])
def finalize_inspection(pkg_id, inspection_id):
    require_role("QAReviewer")
    p = _get_pkg(pkg_id)
    project = _get_project(p["project_id"])
    inspection = db.find_by_id("inspections", inspection_id)
    if not inspection:
        raise_error(ERR_INSPECTION_NOT_FOUND, "Inspection not found.")
    if inspection.get("package_id") != p["id"]:
        raise_error(ERR_INSPECTION_NOT_FOUND, "Inspection does not belong to package.")

    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    defects_found = body.get("defects_found")
    if not isinstance(defects_found, int):
        raise_error(ERR_INVALID_PARAMETER, "defects_found must be integer.")

    insp = pkg_svc.finalize_inspection(p, project, inspection, outcome, defects_found)
    return success(inspection_view(insp))


@bp.route("/task-packages/<pkg_id>/rework-claim", methods=["POST"])
def rework_claim(pkg_id):
    require_role("Annotator")
    p = _get_pkg(pkg_id)
    project = _get_project(p["project_id"])
    annotator = _get_annotator_or_404(g.user_id)
    out = pkg_svc.rework_claim(p, project, annotator)
    return success(task_package_view(out))


@bp.route("/task-packages/<pkg_id>/rework-dispatch", methods=["POST"])
def rework_dispatch(pkg_id):
    require_role("ProjectManager")
    p = _get_pkg(pkg_id)
    out = pkg_svc.rework_dispatch_back_to_pool(p)
    return success(task_package_view(out))


@bp.route("/task-packages/<pkg_id>/arbitrate", methods=["POST"])
def arbitrate(pkg_id):
    require_role("Annotator")
    p = _get_pkg(pkg_id)
    project = _get_project(p["project_id"])
    arbiter = _get_annotator_or_404(g.user_id)
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    out = pkg_svc.arbitrate(p, project, arbiter, decision)
    return success(task_package_view(out))
