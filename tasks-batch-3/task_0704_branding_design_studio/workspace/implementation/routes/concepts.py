"""Concept endpoints (PRD §3.4)."""
from flask import Blueprint

from db import db
from middleware import authenticate
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_PROJECT_WRONG_STAGE,
    ERR_REVISION_LIMIT_REACHED,
)
from helpers import (
    require_role, get_json_body, require_fields, as_string, require_nonneg_int,
    parse_pagination, paginate, require_client_owns_project,
)
from response import success, success_list
from serialize import view
from routes.projects import resolve_project

bp = Blueprint("concepts", __name__)


def _resolve_concept(studio_id, project_id, concept_id):
    proj = resolve_project(studio_id, project_id)
    cp = db.concepts.get(concept_id)
    if cp is None or cp["project_id"] != project_id:
        raise err(ERR_NOT_FOUND, "Concept not found")
    return proj, cp


def effective_revision_limit(concept):
    """revision_limit + sum(extra_revisions for APPROVED EXTRA_REVISION change
    orders whose concept_id names this concept) (PRD §3.4)."""
    granted = sum(
        co["extra_revisions"]
        for co in db.change_orders.values()
        if co["status"] == "APPROVED"
        and co["reason"] == "EXTRA_REVISION"
        and co["concept_id"] == concept["id"]
    )
    return concept["revision_limit"] + granted


@bp.route("/studios/<studio_id>/projects/<project_id>/concepts", methods=["POST"])
def create_concept(studio_id, project_id):
    caller = authenticate()
    require_role(caller, "Designer")
    resolve_project(studio_id, project_id)
    body = get_json_body()
    require_fields(body, "label")
    label = as_string(body["label"], "label")
    revision_limit = 3
    if "revision_limit" in body and body["revision_limit"] is not None:
        revision_limit = require_nonneg_int(body["revision_limit"], "revision_limit")
    rec = db.create(db.concepts, {
        "project_id": project_id,
        "label": label,
        "revision_limit": revision_limit,
        "rounds_used": 0,
        "status": "DRAFT",
    })
    return success(view(rec), status=201)


@bp.route("/studios/<studio_id>/projects/<project_id>/concepts", methods=["GET"])
def list_concepts(studio_id, project_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "Designer", "Client")
    proj = resolve_project(studio_id, project_id)
    require_client_owns_project(caller, proj)
    limit, offset = parse_pagination()
    records = [c for c in db.concepts.values() if c["project_id"] == project_id]
    window, total = paginate(records, limit, offset)
    return success_list([view(r) for r in window], limit, offset, total)


@bp.route("/studios/<studio_id>/projects/<project_id>/concepts/<concept_id>",
          methods=["GET"])
def get_concept(studio_id, project_id, concept_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "Designer", "Client")
    proj, cp = _resolve_concept(studio_id, project_id, concept_id)
    require_client_owns_project(caller, proj)
    return success(view(cp), status=200)


@bp.route("/studios/<studio_id>/projects/<project_id>/concepts/<concept_id>/present",
          methods=["POST"])
def present_concept(studio_id, project_id, concept_id):
    caller = authenticate()
    require_role(caller, "Designer")
    proj, cp = _resolve_concept(studio_id, project_id, concept_id)
    # DRAFT/IN_REVISION -> PRESENTED.
    if cp["status"] not in ("DRAFT", "IN_REVISION"):
        raise err(ERR_INVALID_STATE, "Concept cannot be presented from current state")
    if proj["status"] != "CONCEPT":
        raise err(ERR_PROJECT_WRONG_STAGE, "Project is not in CONCEPT")
    cp["status"] = "PRESENTED"
    db.touch(cp)
    return success(view(cp), status=200)


@bp.route("/studios/<studio_id>/projects/<project_id>/concepts/<concept_id>/request-revision",
          methods=["POST"])
def request_revision(studio_id, project_id, concept_id):
    caller = authenticate()
    require_role(caller, "Client")
    proj, cp = _resolve_concept(studio_id, project_id, concept_id)
    require_client_owns_project(caller, proj)
    # PRESENTED -> IN_REVISION.
    if cp["status"] != "PRESENTED":
        raise err(ERR_INVALID_STATE, "Concept is not PRESENTED")
    # Revision-limit gate uses pre-increment rounds_used.
    if cp["rounds_used"] >= effective_revision_limit(cp):
        raise err(ERR_REVISION_LIMIT_REACHED, "Concept revision limit reached")
    cp["status"] = "IN_REVISION"
    cp["rounds_used"] += 1
    db.touch(cp)
    return success(view(cp), status=200)


@bp.route("/studios/<studio_id>/projects/<project_id>/concepts/<concept_id>/approve",
          methods=["POST"])
def approve_concept(studio_id, project_id, concept_id):
    caller = authenticate()
    require_role(caller, "Client")
    proj, cp = _resolve_concept(studio_id, project_id, concept_id)
    require_client_owns_project(caller, proj)
    # PRESENTED -> APPROVED; no project-stage precondition.
    if cp["status"] != "PRESENTED":
        raise err(ERR_INVALID_STATE, "Concept is not PRESENTED")
    cp["status"] = "APPROVED"
    db.touch(cp)
    return success(view(cp), status=200)


@bp.route("/studios/<studio_id>/projects/<project_id>/concepts/<concept_id>/reject",
          methods=["POST"])
def reject_concept(studio_id, project_id, concept_id):
    caller = authenticate()
    require_role(caller, "Client")
    proj, cp = _resolve_concept(studio_id, project_id, concept_id)
    require_client_owns_project(caller, proj)
    # PRESENTED -> REJECTED; no project-stage precondition.
    if cp["status"] != "PRESENTED":
        raise err(ERR_INVALID_STATE, "Concept is not PRESENTED")
    cp["status"] = "REJECTED"
    db.touch(cp)
    return success(view(cp), status=200)
