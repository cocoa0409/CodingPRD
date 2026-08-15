"""ReinsuranceTreaty endpoints (PRD §3.9)."""

from flask import Blueprint, request

import db
from errors import (
    err, ERR_INVALID_REQUEST, ERR_TREATY_NOT_PROPOSED, ERR_STALE_VERSION,
    ERR_PROGRAM_NOT_ACTIVE, ERR_TREATY_CAPACITY_INVALID, ERR_TREATY_NOT_FOUND,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from routes.common import (
    body, require_fields, pagination_params, paginate, sorted_by_created,
    get_program, get_treaty_in_program,
)
from services import domain, calc

bp = Blueprint("treaties", __name__)


@bp.post("/programs/<programId>/treaties")
def create_treaty(programId):
    require_roles("ProgramManager")
    prog = get_program(programId)
    data = body()
    require_fields(data, ["treaty_name", "ceded_percentage",
                          "attachment_point_cents", "treaty_limit_cents"])
    cp = data["ceded_percentage"]
    if not isinstance(cp, (int, float)) or cp <= 0 or cp > 100:
        raise err(ERR_TREATY_CAPACITY_INVALID, 422,
                  "ceded_percentage outside (0,100] or limits invalid")
    if not isinstance(data["attachment_point_cents"], int) or data["attachment_point_cents"] < 0:
        raise err(ERR_INVALID_REQUEST, 400, "attachment_point_cents must be a non-negative integer")
    if not isinstance(data["treaty_limit_cents"], int) or data["treaty_limit_cents"] < 0:
        raise err(ERR_INVALID_REQUEST, 400, "treaty_limit_cents must be a non-negative integer")
    t = domain.stamp_new({
        "program_id": prog["id"],
        "treaty_name": data["treaty_name"],
        "ceded_percentage": cp,
        "attachment_point_cents": data["attachment_point_cents"],
        "treaty_limit_cents": data["treaty_limit_cents"],
        "recovered_to_date_cents": 0,
        "status": "PROPOSED",
    })
    db.treaties[t["id"]] = t
    return success_object(domain.serialize(t), 201)


@bp.get("/programs/<programId>/treaties")
def list_treaties(programId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    limit, offset = pagination_params()
    items = sorted_by_created(
        t for t in db.treaties.values() if t["program_id"] == prog["id"]
    )
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/<programId>/treaties/<treatyId>")
def get_treaty(programId, treatyId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    t = get_treaty_in_program(prog, treatyId)
    return success_object(domain.serialize(t))


@bp.post("/programs/<programId>/treaties/<treatyId>/bind-treaty")
def bind_treaty(programId, treatyId):
    require_roles("ProgramManager")
    prog = get_program(programId)
    t = get_treaty_in_program(prog, treatyId)
    data = body()
    require_fields(data, ["expected_program_version"])
    # Scaffold precondition order: treaty PROPOSED -> OCC -> program ACTIVE
    if t["status"] != "PROPOSED":
        raise err(ERR_TREATY_NOT_PROPOSED, 409, "Bind-treaty requires treaty PROPOSED")
    if int(data["expected_program_version"]) != int(prog["version"]):
        raise err(ERR_STALE_VERSION, 412,
                  "OCC: expected_program_version does not match current program.version")
    if prog["status"] != "ACTIVE":
        raise err(ERR_PROGRAM_NOT_ACTIVE, 409, "Operation requires program status ACTIVE")
    t["status"] = "ACTIVE"
    domain.touch(t)
    calc.recompute_net_retained_exposure(prog)
    domain.touch(prog)  # increments program.version by 1 (OCC write)
    return success_object(domain.serialize(t))


# --- Flat reads ---

@bp.get("/programs/treaties")
def list_treaties_flat():
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    limit, offset = pagination_params()
    items = list(db.treaties.values())
    pid = request.args.get("program_id")
    st = request.args.get("status")
    if pid is not None:
        items = [t for t in items if t["program_id"] == pid]
    if st is not None:
        items = [t for t in items if t["status"] == st]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/treaties/<treatyId>")
def get_treaty_flat(treatyId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    t = db.treaties.get(treatyId)
    if not t:
        raise err(ERR_TREATY_NOT_FOUND, 404, "Treaty id does not exist")
    return success_object(domain.serialize(t))
