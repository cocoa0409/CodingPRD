"""Project endpoints (PRD §3.1)."""

from flask import Blueprint, request

import db
from errors import err
from middleware import get_context, require_role, json_body, req_string, require_existence
from response import success, list_response, parse_pagination

bp = Blueprint("projects", __name__)

READ_ROLES = ("Any", "PlantManager", "Estimator", "Architect", "ProductionLead",
              "LabelAuthority", "QAInspector", "ShippingCoordinator")


def serialize(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "site_address": p["site_address"],
        "contract_code": p["contract_code"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/projects")
def create_project():
    _, role = get_context()
    require_role(role, "PlantManager")
    body = json_body(required=("name", "site_address", "contract_code"))
    name = req_string(body, "name")
    site_address = req_string(body, "site_address")
    contract_code = req_string(body, "contract_code")
    rec = db.new_record()
    rec.update({
        "name": name,
        "site_address": site_address,
        "contract_code": contract_code,
        "status": "OPEN",
    })
    db.projects[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/projects")
def list_projects():
    get_context()
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [p for p in db.projects.values() if status is None or p["status"] == status]
    return list_response(items, limit, offset, serialize)


@bp.get("/projects/<pid>")
def get_project(pid):
    get_context()
    project = require_existence(db.projects, pid, "ERR_PROJECT_NOT_FOUND", "Project")
    return success(serialize(project))


@bp.put("/projects/<pid>/status")
def transition_project(pid):
    _, role = get_context()
    require_role(role, "PlantManager")
    project = require_existence(db.projects, pid, "ERR_PROJECT_NOT_FOUND", "Project")
    body = json_body(required=("target_status",))
    target = req_string(body, "target_status")
    if target not in ("OPEN", "COMPLETED", "ARCHIVED"):
        raise err("ERR_INVALID_PROJECT_STATUS_TRANSITION",
                  "Unknown project status: %s" % target)
    current = project["status"]
    declared = (current, target) in (("OPEN", "COMPLETED"), ("COMPLETED", "ARCHIVED"), ("OPEN", "ARCHIVED"))
    if not declared:
        raise err("ERR_INVALID_PROJECT_STATUS_TRANSITION",
                  "Project cannot transition from %s to %s" % (current, target))
    if target == "COMPLETED":
        for order in db.orders.values():
            if order["project_id"] == pid and order["status"] not in ("CLOSED", "CANCELLED"):
                raise err("ERR_ORDERS_NOT_TERMINAL",
                          "Every order of the project must be CLOSED or CANCELLED")
    project["status"] = target
    db.touch(project)
    return success(serialize(project))
