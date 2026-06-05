"""Project endpoints (PRD §3.1, §3.7)."""
from flask import Blueprint

import db
import helpers as h
import services
from errors import err, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import authenticate, require_role
from response import success

bp = Blueprint("projects", __name__)


def get_project_or_404(project_id):
    p = db.projects.get(project_id)
    if p is None:
        raise err(ERR_NOT_FOUND, "Project not found.")
    return p


@bp.post("/projects")
def create_project():
    _uid, role = authenticate()
    require_role(role, {"Owner"})
    body = h.get_json()
    h.require_fields(body, ["name", "owner_user_id", "original_contract_sum_cents"])

    name = h.as_nonempty_string(body["name"], "name")
    owner_user_id = h.as_string(body["owner_user_id"], "owner_user_id")
    original = h.as_int(body["original_contract_sum_cents"], "original_contract_sum_cents",
                        minimum=0)
    default_retainage_pct = 0.10
    if body.get("default_retainage_pct") is not None:
        default_retainage_pct = h.as_number(body["default_retainage_pct"],
                                             "default_retainage_pct", minimum=0, maximum=0.20)

    record = {
        "name": name,
        "owner_user_id": owner_user_id,
        "original_contract_sum_cents": original,
        "default_retainage_pct": default_retainage_pct,
        "revised_contract_sum_cents": original,
        "total_completed_and_stored_cents": 0,
        "retainage_held_cents": 0,
        "status": "ACTIVE",
    }
    db.stamp_create(record)
    db.projects[record["id"]] = record
    return success(h.project_out(record), status=201)


@bp.get("/projects/<project_id>")
def get_project(project_id):
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    p = get_project_or_404(project_id)
    return success(h.project_out(p))


@bp.get("/projects")
def list_projects():
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    limit, offset = h.parse_pagination()
    from flask import request
    status = request.args.get("status")
    records = list(db.projects.values())
    if status:
        records = [r for r in records if r["status"] == status]
    page, meta = h.paginate(records, limit, offset)
    return success([h.project_out(r) for r in page], pagination=meta)


@bp.post("/projects/<project_id>/substantial-completion")
def substantial_completion(project_id):
    _uid, role = authenticate()
    require_role(role, {"Architect"})
    p = get_project_or_404(project_id)
    # State legality: ACTIVE -> SUBSTANTIALLY_COMPLETE.
    if p["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Project is not ACTIVE.")
    # Every punch item VERIFIED (vacuous if none).
    for item in db.punch_items.values():
        if item["project_id"] == project_id and item["status"] != "VERIFIED":
            raise err(ERR_INVALID_STATE, "Punch list not fully verified.")
    # At least one CERTIFIED pay application.
    has_certified = any(pa["project_id"] == project_id and pa["status"] == "CERTIFIED"
                        for pa in db.pay_applications.values())
    if not has_certified:
        raise err(ERR_INVALID_STATE, "No certified pay application exists.")
    p["status"] = "SUBSTANTIALLY_COMPLETE"
    db.touch(p)
    return success(h.project_out(p))


@bp.post("/projects/<project_id>/close")
def close_project(project_id):
    _uid, role = authenticate()
    require_role(role, {"Owner"})
    p = get_project_or_404(project_id)
    if p["status"] != "SUBSTANTIALLY_COMPLETE":
        raise err(ERR_INVALID_STATE, "Project is not SUBSTANTIALLY_COMPLETE.")
    if p["retainage_held_cents"] != 0:
        raise err(ERR_INVALID_STATE, "Retainage not fully released.")
    for c in db.subcontractor_commitments.values():
        if c["project_id"] == project_id and c["status"] != "CLOSED":
            raise err(ERR_INVALID_STATE, "Subcontractor commitments are not all closed.")
    p["status"] = "CLOSED"
    db.touch(p)
    return success(h.project_out(p))
