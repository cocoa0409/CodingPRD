"""Moodboard endpoints (PRD §3.3)."""
from flask import Blueprint

from db import db
from middleware import authenticate
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_PROJECT_WRONG_STAGE,
)
from helpers import (
    require_role, get_json_body, require_fields, as_string,
    parse_pagination, paginate, require_client_owns_project,
)
from response import success, success_list
from serialize import view
from routes.projects import resolve_project

bp = Blueprint("moodboards", __name__)


def _resolve_moodboard(studio_id, project_id, moodboard_id):
    proj = resolve_project(studio_id, project_id)
    mb = db.moodboards.get(moodboard_id)
    if mb is None or mb["project_id"] != project_id:
        raise err(ERR_NOT_FOUND, "Moodboard not found")
    return proj, mb


@bp.route("/studios/<studio_id>/projects/<project_id>/moodboards", methods=["POST"])
def create_moodboard(studio_id, project_id):
    caller = authenticate()
    require_role(caller, "Designer")
    resolve_project(studio_id, project_id)
    body = get_json_body()
    require_fields(body, "title")
    title = as_string(body["title"], "title")
    rec = db.create(db.moodboards, {
        "project_id": project_id,
        "title": title,
        "status": "DRAFT",
    })
    return success(view(rec), status=201)


@bp.route("/studios/<studio_id>/projects/<project_id>/moodboards", methods=["GET"])
def list_moodboards(studio_id, project_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "Designer", "Client")
    proj = resolve_project(studio_id, project_id)
    require_client_owns_project(caller, proj)
    limit, offset = parse_pagination()
    records = [m for m in db.moodboards.values() if m["project_id"] == project_id]
    window, total = paginate(records, limit, offset)
    return success_list([view(r) for r in window], limit, offset, total)


@bp.route("/studios/<studio_id>/projects/<project_id>/moodboards/<moodboard_id>",
          methods=["GET"])
def get_moodboard(studio_id, project_id, moodboard_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "Designer", "Client")
    proj, mb = _resolve_moodboard(studio_id, project_id, moodboard_id)
    require_client_owns_project(caller, proj)
    return success(view(mb), status=200)


@bp.route("/studios/<studio_id>/projects/<project_id>/moodboards/<moodboard_id>/submit",
          methods=["POST"])
def submit_moodboard(studio_id, project_id, moodboard_id):
    caller = authenticate()
    require_role(caller, "Designer")
    proj, mb = _resolve_moodboard(studio_id, project_id, moodboard_id)
    # DRAFT/REJECTED -> SUBMITTED.
    if mb["status"] not in ("DRAFT", "REJECTED"):
        raise err(ERR_INVALID_STATE, "Moodboard cannot be submitted from current state")
    if proj["status"] != "DISCOVERY":
        raise err(ERR_PROJECT_WRONG_STAGE, "Project is not in DISCOVERY")
    mb["status"] = "SUBMITTED"
    db.touch(mb)
    return success(view(mb), status=200)


@bp.route("/studios/<studio_id>/projects/<project_id>/moodboards/<moodboard_id>/approve",
          methods=["POST"])
def approve_moodboard(studio_id, project_id, moodboard_id):
    caller = authenticate()
    require_role(caller, "Client")
    proj, mb = _resolve_moodboard(studio_id, project_id, moodboard_id)
    require_client_owns_project(caller, proj)
    # SUBMITTED -> APPROVED.
    if mb["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Moodboard is not SUBMITTED")
    if proj["status"] != "DISCOVERY":
        raise err(ERR_PROJECT_WRONG_STAGE, "Project is not in DISCOVERY")
    mb["status"] = "APPROVED"
    db.touch(mb)
    return success(view(mb), status=200)


@bp.route("/studios/<studio_id>/projects/<project_id>/moodboards/<moodboard_id>/reject",
          methods=["POST"])
def reject_moodboard(studio_id, project_id, moodboard_id):
    caller = authenticate()
    require_role(caller, "Client")
    proj, mb = _resolve_moodboard(studio_id, project_id, moodboard_id)
    require_client_owns_project(caller, proj)
    # SUBMITTED -> REJECTED; no project-stage precondition.
    if mb["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Moodboard is not SUBMITTED")
    mb["status"] = "REJECTED"
    db.touch(mb)
    return success(view(mb), status=200)
