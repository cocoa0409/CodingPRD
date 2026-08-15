"""Worker routes (PRD §3.1)."""
from flask import Blueprint

import db
from errors import ApiError, ERR_PI_ALREADY_ASSIGNED, ERR_NOT_FOUND
from middleware import get_actor, require_role
from response import success_object, success_list
from services.common import (get_body, serialize_worker, parse_pagination, paginate,
                             get_or_404, require_fields, require_string, require_enum,
                             WORKER_ROLES, touch, serialize_lab)

bp = Blueprint("workers", __name__)

READ_ROLES = ("EHSAdmin", "EHSInspector", "PrincipalInvestigator", "LabMember")


@bp.post("/ehs/workers")
def create_worker():
    _, role = get_actor()
    body = get_body()
    require_role(role, ("EHSAdmin", "PrincipalInvestigator"))
    require_fields(body, ["lab_id", "full_name", "role_in_lab"])
    role_in_lab = require_enum(body, "role_in_lab", WORKER_ROLES)
    full_name = require_string(body, "full_name")
    lab_id = body.get("lab_id")
    lab = db.labs.get(lab_id)
    if lab is None:
        raise ApiError(ERR_NOT_FOUND, f"Lab not found: {lab_id}", 404)
    # Priority 12: at most one PI-role worker per lab.
    if role_in_lab == "PI" and lab["pi_worker_id"] is not None:
        raise ApiError(ERR_PI_ALREADY_ASSIGNED, "Lab already has a PI-role worker", 409)
    worker = {
        "id": db.new_id(),
        "lab_id": lab["id"],
        "full_name": full_name,
        "role_in_lab": role_in_lab,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.workers[worker["id"]] = worker
    if role_in_lab == "PI":
        lab["pi_worker_id"] = worker["id"]
        touch(lab)
    return success_object(serialize_worker(worker), 201)


@bp.get("/ehs/labs/<lab_id>/workers")
def list_lab_workers(lab_id):
    _, role = get_actor()
    require_role(role, READ_ROLES)
    get_or_404(db.labs, lab_id, "Lab")
    limit, offset = parse_pagination()
    records = [w for w in db.workers.values() if w["lab_id"] == lab_id]
    page, total = paginate(records, limit, offset)
    return success_list([serialize_worker(w) for w in page], limit, offset, total)


@bp.get("/ehs/workers/<worker_id>")
def get_worker(worker_id):
    _, role = get_actor()
    require_role(role, READ_ROLES)
    worker = get_or_404(db.workers, worker_id, "Worker")
    return success_object(serialize_worker(worker))
