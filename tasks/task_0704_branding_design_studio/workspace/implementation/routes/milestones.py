"""Milestone endpoints (PRD §3.2)."""
from flask import Blueprint

from db import db
from middleware import authenticate
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_PROJECT_WRONG_STAGE,
)
from helpers import (
    require_role, get_json_body, require_fields, as_string, as_int,
    require_nonneg_int, parse_pagination, paginate, require_client_owns_project,
)
from response import success, success_list
from serialize import view
from routes.projects import resolve_project
from services.ledger import project_milestones

bp = Blueprint("milestones", __name__)


@bp.route("/studios/<studio_id>/projects/<project_id>/milestones", methods=["POST"])
def create_milestone(studio_id, project_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    proj = resolve_project(studio_id, project_id)
    body = get_json_body()
    require_fields(body, "name", "amount_cents", "sequence_index")
    name = as_string(body["name"], "name")
    amount_cents = require_nonneg_int(body["amount_cents"], "amount_cents")
    sequence_index = as_int(body["sequence_index"], "sequence_index")

    # Created only while Project is in DRAFT (PRD §3.2).
    if proj["status"] != "DRAFT":
        raise err(ERR_PROJECT_WRONG_STAGE, "Milestones can only be created while DRAFT")

    # sequence_index must be unique among that project's milestones (PRD §3.2).
    for existing in project_milestones(project_id):
        if existing["sequence_index"] == sequence_index:
            raise err(ERR_INVALID_REQUEST, "sequence_index must be unique within the project")

    rec = db.create(db.milestones, {
        "project_id": project_id,
        "name": name,
        "amount_cents": amount_cents,
        "sequence_index": sequence_index,
        "status": "PENDING",
    })
    return success(view(rec), status=201)


@bp.route("/studios/<studio_id>/projects/<project_id>/milestones", methods=["GET"])
def list_milestones(studio_id, project_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps", "Client")
    proj = resolve_project(studio_id, project_id)
    require_client_owns_project(caller, proj)
    limit, offset = parse_pagination()
    records = project_milestones(project_id)
    window, total = paginate(records, limit, offset)
    return success_list([view(r) for r in window], limit, offset, total)


@bp.route("/studios/<studio_id>/projects/<project_id>/milestones/<milestone_id>",
          methods=["GET"])
def get_milestone(studio_id, project_id, milestone_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps", "Client")
    proj = resolve_project(studio_id, project_id)
    ms = db.milestones.get(milestone_id)
    if ms is None or ms["project_id"] != project_id:
        raise err(ERR_NOT_FOUND, "Milestone not found")
    require_client_owns_project(caller, proj)
    return success(view(ms), status=200)
