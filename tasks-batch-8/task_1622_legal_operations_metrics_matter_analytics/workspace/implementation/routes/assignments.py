from flask import Blueprint, request

from db import store, new_entity, touch
from errors import (
    ApiError, ERR_CAPACITY_EXCEEDED, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import object_response
from serializers import assignment_view
from validation import Payload, require_exists, list_page

bp = Blueprint("assignments", __name__, url_prefix="/legal-ops")

ALL = ("LegalOpsManager", "LegalOpsAnalyst", "LegalOpsExecutive")


def _capacity_load(counsel_id):
    """ACTIVE assignments whose parent matter is ACTIVE or ON_HOLD consume capacity."""
    total = 0
    for a in store.assignments.values():
        if a["counsel_id"] != counsel_id or a["status"] != "ACTIVE":
            continue
        m = store.matters.get(a["matter_id"])
        if m is not None and m["status"] in ("ACTIVE", "ON_HOLD"):
            total += a["allocated_hours"]
    return total


@bp.post("/matters/<mid>/assignments")
@require_roles("LegalOpsAnalyst")
def create_assignment(user_id, role, mid):
    matter = require_exists(store.matters, mid, "matter")
    p = Payload()
    counsel_id = p.req_str("counsel_id")
    hours = p.req_int("allocated_hours")
    counsel = None
    if counsel_id is not None:
        counsel = require_exists(store.counsel, counsel_id, "counsel")
    # Capacity check (priority 17) before payload-shape (20).
    if counsel is not None and hours is not None:
        if _capacity_load(counsel_id) + hours > counsel["annual_capacity_hours"]:
            raise ApiError(ERR_CAPACITY_EXCEEDED, 422, "Counsel allocation would exceed annual_capacity_hours")
    p.finish()
    if hours < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "allocated_hours must be >= 0")
    a = new_entity({
        "matter_id": mid,
        "counsel_id": counsel_id,
        "allocated_hours": hours,
        "status": "ACTIVE",
    })
    store.assignments[a["id"]] = a
    return object_response(assignment_view(a), 201)


@bp.get("/matters/<mid>/assignments")
@require_roles(*ALL)
def list_matter_assignments(user_id, role, mid):
    require_exists(store.matters, mid, "matter")
    items = [a for a in store.assignments.values() if a["matter_id"] == mid]
    return list_page(items, assignment_view)


@bp.get("/matter-assignments")
@require_roles(*ALL)
def list_assignments(user_id, role):
    items = list(store.assignments.values())
    for param in ("counsel_id", "matter_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a[param] == v]
    return list_page(items, assignment_view)


@bp.get("/matter-assignments/<aid>")
@require_roles(*ALL)
def get_assignment(user_id, role, aid):
    return object_response(assignment_view(require_exists(store.assignments, aid, "assignment")))


@bp.post("/matter-assignments/<aid>/release")
@require_roles("LegalOpsAnalyst")
def release_assignment(user_id, role, aid):
    a = require_exists(store.assignments, aid, "assignment")
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Assignment is not ACTIVE")
    matter = store.matters.get(a["matter_id"])
    if matter is not None and matter["status"] not in ("ACTIVE", "ON_HOLD"):
        raise ApiError(ERR_INVALID_STATE, 409, "Manual release requires matter ACTIVE or ON_HOLD")
    a["status"] = "RELEASED"
    touch(a)
    return object_response(assignment_view(a))
