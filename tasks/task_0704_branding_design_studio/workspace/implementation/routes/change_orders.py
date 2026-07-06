"""ChangeOrder endpoints (PRD §3.8, §2.7 OCC)."""
from flask import Blueprint, request

from db import db
from middleware import authenticate
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_STALE_PROJECT_VERSION,
    ERR_INVALID_STATE, ERR_PROJECT_WRONG_STAGE, ERR_PROJECT_NOT_ACTIVATED,
)
from helpers import (
    require_role, get_json_body, require_fields, require_enum, as_string,
    as_int, require_nonneg_int, parse_pagination, paginate, get_studio,
    require_client_owns_project,
)
from response import success, success_list
from serialize import view
from services.ledger import recompute_contract_and_final_deposit

bp = Blueprint("change_orders", __name__)

REASONS = {"SCOPE_ADD", "EXTRA_REVISION", "RUSH"}


def _resolve_change_order(studio_id, change_order_id):
    get_studio(studio_id)
    co = db.change_orders.get(change_order_id)
    if co is None:
        raise err(ERR_NOT_FOUND, "ChangeOrder not found")
    proj = db.projects.get(co["project_id"])
    if proj is None or proj["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "ChangeOrder not found in this studio")
    return proj, co


@bp.route("/studios/<studio_id>/change-orders", methods=["POST"])
def propose_change_order(studio_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    get_studio(studio_id)
    body = get_json_body()
    require_fields(body, "project_id", "reason", "delta_cents", "expected_project_version")
    project_id = as_string(body["project_id"], "project_id")
    reason = require_enum(body["reason"], "reason", REASONS)
    delta_cents = as_int(body["delta_cents"], "delta_cents")
    expected_version = as_int(body["expected_project_version"], "expected_project_version")

    # Body-referenced project existence (§2.9, priority 3).
    proj = db.projects.get(project_id)
    if proj is None or proj["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "Project not found in this studio")

    # EXTRA_REVISION names a concept and extra_revisions; otherwise defaults.
    concept_id = None
    extra_revisions = 0
    if reason == "EXTRA_REVISION":
        require_fields(body, "concept_id", "extra_revisions")
        concept_id = as_string(body["concept_id"], "concept_id")
        extra_revisions = require_nonneg_int(body["extra_revisions"], "extra_revisions")
        concept = db.concepts.get(concept_id)
        if concept is None or concept["project_id"] != project_id:
            raise err(ERR_NOT_FOUND, "Concept not found in this project")
    else:
        if "concept_id" in body and body["concept_id"] is not None:
            concept_id = as_string(body["concept_id"], "concept_id")
        if "extra_revisions" in body and body["extra_revisions"] is not None:
            extra_revisions = require_nonneg_int(body["extra_revisions"], "extra_revisions")

    # OCC check (priority 5): expected_project_version == current Project.version.
    if expected_version != proj["version"]:
        raise err(ERR_STALE_PROJECT_VERSION, "Project version is stale")

    rec = db.create(db.change_orders, {
        "project_id": project_id,
        "reason": reason,
        "concept_id": concept_id,
        "extra_revisions": extra_revisions,
        "delta_cents": delta_cents,
        "status": "PROPOSED",
    })
    return success(view(rec), status=201)


@bp.route("/studios/<studio_id>/change-orders/<change_order_id>", methods=["GET"])
def get_change_order(studio_id, change_order_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps", "Client")
    proj, co = _resolve_change_order(studio_id, change_order_id)
    require_client_owns_project(caller, proj)
    return success(view(co), status=200)


@bp.route("/studios/<studio_id>/change-orders", methods=["GET"])
def list_change_orders(studio_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps", "Client")
    get_studio(studio_id)
    limit, offset = parse_pagination()

    studio_project_ids = {
        p["id"] for p in db.projects.values() if p["studio_id"] == studio_id
    }
    records = [co for co in db.change_orders.values()
               if co["project_id"] in studio_project_ids]
    filter_project = request.args.get("project_id")
    filter_concept = request.args.get("concept_id")
    if filter_project is not None:
        records = [co for co in records if co["project_id"] == filter_project]
    if filter_concept is not None:
        records = [co for co in records if co["concept_id"] == filter_concept]
    if caller.role == "Client":
        owned = {p["id"] for p in db.projects.values()
                 if p["studio_id"] == studio_id and p["client_id"] == caller.user_id}
        records = [co for co in records if co["project_id"] in owned]

    window, total = paginate(records, limit, offset)
    return success_list([view(r) for r in window], limit, offset, total)


@bp.route("/studios/<studio_id>/change-orders/<change_order_id>/approve", methods=["POST"])
def approve_change_order(studio_id, change_order_id):
    caller = authenticate()
    require_role(caller, "Client")
    proj, co = _resolve_change_order(studio_id, change_order_id)
    require_client_owns_project(caller, proj)
    # PROPOSED -> APPROVED.
    if co["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "ChangeOrder is not PROPOSED")
    # Parent project not terminal and not already handed off.
    if proj["status"] in ("COMPLETED", "CANCELLED", "HANDOFF"):
        raise err(ERR_PROJECT_WRONG_STAGE, "Project is terminal or handed off")
    # Project must have been activated (not DRAFT).
    if proj["status"] == "DRAFT":
        raise err(ERR_PROJECT_NOT_ACTIVATED, "Project has not been activated")

    co["status"] = "APPROVED"
    db.touch(co)
    # Ledger sync: recompute contract_value and final_deposit; bump project version.
    recompute_contract_and_final_deposit(proj)
    db.touch(proj)
    return success(view(co), status=200)


@bp.route("/studios/<studio_id>/change-orders/<change_order_id>/reject", methods=["POST"])
def reject_change_order(studio_id, change_order_id):
    caller = authenticate()
    require_role(caller, "Client")
    proj, co = _resolve_change_order(studio_id, change_order_id)
    require_client_owns_project(caller, proj)
    # PROPOSED -> REJECTED; no precondition; does not touch ledger.
    if co["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "ChangeOrder is not PROPOSED")
    co["status"] = "REJECTED"
    db.touch(co)
    return success(view(co), status=200)
