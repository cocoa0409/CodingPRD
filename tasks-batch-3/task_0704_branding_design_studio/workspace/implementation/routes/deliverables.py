"""Deliverable endpoints (PRD §3.5)."""
from flask import Blueprint

from db import db
from middleware import authenticate
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_PROJECT_WRONG_STAGE,
)
from helpers import (
    require_role, get_json_body, require_fields, require_enum, as_bool,
    parse_pagination, paginate, require_client_owns_project,
)
from response import success, success_list
from serialize import view
from routes.projects import resolve_project

bp = Blueprint("deliverables", __name__)

ASSET_TYPES = {
    "LOGO_PRIMARY", "LOGO_MARK", "COLOR_TOKENS", "TYPOGRAPHY",
    "BRAND_GUIDE", "WEB_KIT",
}


def _resolve_deliverable(studio_id, project_id, deliverable_id):
    proj = resolve_project(studio_id, project_id)
    d = db.deliverables.get(deliverable_id)
    if d is None or d["project_id"] != project_id:
        raise err(ERR_NOT_FOUND, "Deliverable not found")
    return proj, d


@bp.route("/studios/<studio_id>/projects/<project_id>/deliverables", methods=["POST"])
def create_deliverable(studio_id, project_id):
    caller = authenticate()
    require_role(caller, "Designer", "StudioOps")
    resolve_project(studio_id, project_id)
    body = get_json_body()
    require_fields(body, "asset_type")
    asset_type = require_enum(body["asset_type"], "asset_type", ASSET_TYPES)
    is_required = True
    if "is_required_for_handoff" in body and body["is_required_for_handoff"] is not None:
        is_required = as_bool(body["is_required_for_handoff"], "is_required_for_handoff")
    rec = db.create(db.deliverables, {
        "project_id": project_id,
        "asset_type": asset_type,
        "is_required_for_handoff": is_required,
        "status": "PENDING",
    })
    return success(view(rec), status=201)


@bp.route("/studios/<studio_id>/projects/<project_id>/deliverables", methods=["GET"])
def list_deliverables(studio_id, project_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "Designer", "Client")
    proj = resolve_project(studio_id, project_id)
    require_client_owns_project(caller, proj)
    limit, offset = parse_pagination()
    records = [d for d in db.deliverables.values() if d["project_id"] == project_id]
    window, total = paginate(records, limit, offset)
    return success_list([view(r) for r in window], limit, offset, total)


@bp.route("/studios/<studio_id>/projects/<project_id>/deliverables/<deliverable_id>",
          methods=["GET"])
def get_deliverable(studio_id, project_id, deliverable_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "Designer", "Client")
    proj, d = _resolve_deliverable(studio_id, project_id, deliverable_id)
    require_client_owns_project(caller, proj)
    return success(view(d), status=200)


@bp.route("/studios/<studio_id>/projects/<project_id>/deliverables/<deliverable_id>/deliver",
          methods=["POST"])
def deliver_asset(studio_id, project_id, deliverable_id):
    caller = authenticate()
    require_role(caller, "Designer")
    proj, d = _resolve_deliverable(studio_id, project_id, deliverable_id)
    # PENDING/REVISION_REQUESTED -> DELIVERED.
    if d["status"] not in ("PENDING", "REVISION_REQUESTED"):
        raise err(ERR_INVALID_STATE, "Deliverable cannot be delivered from current state")
    if proj["status"] not in ("DELIVERY", "HANDOFF"):
        raise err(ERR_PROJECT_WRONG_STAGE, "Project is not in DELIVERY or HANDOFF")
    d["status"] = "DELIVERED"
    db.touch(d)
    return success(view(d), status=200)


@bp.route("/studios/<studio_id>/projects/<project_id>/deliverables/<deliverable_id>/accept",
          methods=["POST"])
def accept_asset(studio_id, project_id, deliverable_id):
    caller = authenticate()
    require_role(caller, "Client")
    proj, d = _resolve_deliverable(studio_id, project_id, deliverable_id)
    require_client_owns_project(caller, proj)
    # DELIVERED -> ACCEPTED; no project-stage precondition.
    if d["status"] != "DELIVERED":
        raise err(ERR_INVALID_STATE, "Deliverable is not DELIVERED")
    d["status"] = "ACCEPTED"
    db.touch(d)
    return success(view(d), status=200)


@bp.route("/studios/<studio_id>/projects/<project_id>/deliverables/<deliverable_id>/request-revision",
          methods=["POST"])
def request_asset_revision(studio_id, project_id, deliverable_id):
    caller = authenticate()
    require_role(caller, "Client")
    proj, d = _resolve_deliverable(studio_id, project_id, deliverable_id)
    require_client_owns_project(caller, proj)
    # DELIVERED -> REVISION_REQUESTED; no project-stage precondition.
    if d["status"] != "DELIVERED":
        raise err(ERR_INVALID_STATE, "Deliverable is not DELIVERED")
    d["status"] = "REVISION_REQUESTED"
    db.touch(d)
    return success(view(d), status=200)
