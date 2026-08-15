"""Rep routes: create, get, update, list."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_DUPLICATE_EMPLOYEE_REF,
    ERR_REP_HIERARCHY_CYCLE,
    ERR_MANAGER_PROGRAM_MISMATCH,
)
from middleware import authorized
from response import success_object, success_list
from util import new_entity, touch, serialize
from validate import (
    get_body, req_str, opt_str, opt_nullable_str,
    parse_pagination, require_path_resource,
)

bp = Blueprint("reps", __name__)

ADMIN_ONLY = ["CompAdmin"]
ALL_ROLES = ["CompAdmin", "CompAnalyst", "CompManager", "Rep"]


def _check_manager_valid(rep_id, manager_id, program_id):
    """Check manager is same-program and chain is acyclic."""
    if manager_id is None:
        return
    manager = db["reps"].get(manager_id)
    if manager is None:
        raise_error(ERR_NOT_FOUND, f"manager rep not found: {manager_id}")
    if manager["program_id"] != program_id:
        raise_error(ERR_MANAGER_PROGRAM_MISMATCH,
                    "manager must belong to the same program")
    # Acyclicity: walk up from manager; if we reach rep_id, it's a cycle
    if rep_id is not None:
        current = manager_id
        visited = set()
        while current is not None:
            if current == rep_id:
                raise_error(ERR_REP_HIERARCHY_CYCLE,
                            "manager chain would create a cycle")
            if current in visited:
                break  # existing cycle elsewhere, not our problem
            visited.add(current)
            current_rep = db["reps"].get(current)
            current = current_rep.get("manager_id") if current_rep else None
    else:
        # New rep: just check manager_id != rep_id (impossible for new, but be safe)
        pass


@bp.route("/reps", methods=["POST"])
def create_rep():
    caller = authorized(ADMIN_ONLY)
    body = get_body()

    program_id = req_str(body, "program_id")
    name = req_str(body, "name")
    employee_ref = req_str(body, "employee_ref")
    manager_id = opt_nullable_str(body, "manager_id", None)

    # Priority 3: program exists
    program = db["programs"].get(program_id)
    if program is None:
        raise_error(ERR_NOT_FOUND, f"program not found: {program_id}")

    # Priority 7: employee_ref unique per program
    for r in db["reps"].values():
        if r["program_id"] == program_id and r["employee_ref"] == employee_ref:
            raise_error(ERR_DUPLICATE_EMPLOYEE_REF,
                        f"employee_ref {employee_ref} already used in program")

    # Priority 8: manager checks
    if manager_id is not None:
        _check_manager_valid(None, manager_id, program_id)

    rep = new_entity({
        "program_id": program_id,
        "name": name,
        "employee_ref": employee_ref,
        "manager_id": manager_id,
    })
    db["reps"][rep["id"]] = rep
    return success_object(serialize(rep), 201)


@bp.route("/reps/<repId>", methods=["GET"])
def get_rep(repId):
    caller = authorized(ALL_ROLES)
    rep = require_path_resource("reps", repId)
    return success_object(serialize(rep))


@bp.route("/reps/<repId>", methods=["PUT"])
def update_rep(repId):
    caller = authorized(ADMIN_ONLY)
    body = get_body()
    rep = require_path_resource("reps", repId)

    changed = False

    new_name = opt_str(body, "name")
    if new_name is not None and new_name != rep["name"]:
        rep["name"] = new_name
        changed = True

    if "manager_id" in body:
        new_manager_id = opt_nullable_str(body, "manager_id")
        if new_manager_id != rep.get("manager_id"):
            if new_manager_id is not None:
                _check_manager_valid(repId, new_manager_id, rep["program_id"])
            rep["manager_id"] = new_manager_id
            changed = True

    if changed:
        touch(rep)

    return success_object(serialize(rep))


@bp.route("/reps", methods=["GET"])
def list_reps():
    caller = authorized(ALL_ROLES)
    limit, offset = parse_pagination()

    items = list(db["reps"].values())

    program_id = request.args.get("program_id")
    manager_id = request.args.get("manager_id")

    if program_id:
        items = [r for r in items if r["program_id"] == program_id]
    if manager_id:
        items = [r for r in items if r.get("manager_id") == manager_id]

    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(r) for r in page], total, limit, offset)
