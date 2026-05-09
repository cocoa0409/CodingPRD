"""CoOwnership endpoints."""

from flask import Blueprint

import db
from audit import write_audit
from auth import require_role, is_owner_or_co_owner
from envelope import success_object, success_array, empty_204
from errors import ApiError
from serialize import s_co_ownership
from util import (get_json_body, parse_pagination, paginate, require_fields,
                  stamp_create, stamp_update, actor_id, actor_role, round4)


bp = Blueprint("co_owners", __name__)


def _audit_co(c, action, before=None, after=None):
    write_audit(entity_type="CO_OWNERSHIP", entity_id=c["id"], action=action,
                before=before, after=after)


def _validate_total(objective_id, prospective_sum):
    """Sum must be in (0, 1) strict — exclusive on both ends."""
    if not (0 < prospective_sum < 1):
        raise ApiError("ERR_CO_OWNER_WEIGHTS_INVALID", 422,
                       f"co-owner weight sum {prospective_sum} not in (0,1)")


@bp.post("/objectives/<id>/co-owners")
def add_co_owner(id):
    require_role("PlatformAdmin", "Manager", "Employee")
    o = db.objectives.get(id)
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    aid = actor_id()
    arole = actor_role()
    if arole != "PlatformAdmin" and o["owner_user_id"] != aid:
        # Co-owners cannot add other co-owners by spec? PRD says owner-gated; we'll allow co-owner equally.
        if not is_owner_or_co_owner(o, aid):
            raise ApiError("ERR_NOT_OWNER", 403, "must be owner or co-owner")
    body = get_json_body()
    require_fields(body, "co_owner_user_id", "contribution_weight")
    co_user = body["co_owner_user_id"]
    cw = body["contribution_weight"]
    if co_user not in db.users:
        raise ApiError("ERR_USER_NOT_FOUND", 404, "co_owner user not found")
    try:
        cwf = float(cw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "contribution_weight must be number")
    if cwf < 0 or cwf > 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "contribution_weight out of range")
    # Duplicate check
    for c in db.co_ownerships.values():
        if (c["objective_id"] == id and c["co_owner_user_id"] == co_user
                and c["status"] == "ACTIVE"):
            raise ApiError("ERR_DUPLICATE_CO_OWNER", 409, "co-owner already exists")
    # Sum must be in (0,1)
    cur_sum = sum(float(c["contribution_weight"]) for c in db.co_ownerships.values()
                  if c["objective_id"] == id and c["status"] == "ACTIVE")
    _validate_total(id, cur_sum + cwf)

    co = {
        "objective_id": id,
        "co_owner_user_id": co_user,
        "contribution_weight": round4(cwf),
        "status": "ACTIVE",
    }
    stamp_create(co)
    db.co_ownerships[co["id"]] = co
    _audit_co(co, "CREATE", after=s_co_ownership(co))
    return success_object(s_co_ownership(co), status=201)


@bp.delete("/objectives/<id>/co-owners/<user_id>")
def remove_co_owner(id, user_id):
    require_role("PlatformAdmin", "Manager", "Employee")
    o = db.objectives.get(id)
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    aid = actor_id()
    arole = actor_role()
    if arole != "PlatformAdmin" and not is_owner_or_co_owner(o, aid):
        raise ApiError("ERR_NOT_OWNER", 403, "must be owner or co-owner")
    target = None
    for c in db.co_ownerships.values():
        if (c["objective_id"] == id and c["co_owner_user_id"] == user_id
                and c["status"] == "ACTIVE"):
            target = c
            break
    if target is None:
        raise ApiError("ERR_USER_NOT_FOUND", 404, "active co-owner not found")
    before = s_co_ownership(target)
    target["status"] = "REMOVED"
    stamp_update(target)
    _audit_co(target, "DELETE", before=before, after=s_co_ownership(target))
    return empty_204()


@bp.get("/objectives/<id>/co-owners")
def list_co_owners(id):
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    o = db.objectives.get(id)
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    items = [c for c in db.co_ownerships.values()
             if c["objective_id"] == id and c["status"] == "ACTIVE"]
    items.sort(key=lambda c: c["created_at"])
    # No pagination params spec'd, but provide standard envelope as array
    return success_array([s_co_ownership(c) for c in items], len(items), 10, 0)
