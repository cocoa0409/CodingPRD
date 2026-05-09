"""AccessGrant endpoints."""

from flask import Blueprint

import db
from audit import write_audit
from auth import require_role, is_owner_or_co_owner
from envelope import success_object, success_array, empty_204
from errors import ApiError
from serialize import s_grant
from util import (get_json_body, require_fields, stamp_create, stamp_update,
                  actor_id, actor_role)


bp = Blueprint("access_grants", __name__)


def _audit_grant(g, action, before=None, after=None):
    write_audit(entity_type="ACCESS_GRANT", entity_id=g["id"], action=action,
                before=before, after=after)


@bp.post("/objectives/<id>/access-grants")
def grant_access(id):
    require_role("PlatformAdmin", "Manager", "Employee")
    o = db.objectives.get(id)
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    aid = actor_id()
    arole = actor_role()
    if arole != "PlatformAdmin" and not is_owner_or_co_owner(o, aid):
        raise ApiError("ERR_NOT_OWNER", 403, "must be owner or co-owner")
    body = get_json_body()
    require_fields(body, "user_id")
    uid = body["user_id"]
    if uid not in db.users:
        raise ApiError("ERR_USER_NOT_FOUND", 404, "user not found")
    # Duplicate ACTIVE grant
    for g in db.access_grants.values():
        if (g["objective_id"] == id and g["user_id"] == uid
                and g["status"] == "ACTIVE"):
            raise ApiError("ERR_DUPLICATE_GRANT", 409, "grant already exists")
    grant = {
        "objective_id": id,
        "user_id": uid,
        "granted_by_user_id": aid,
        "status": "ACTIVE",
    }
    stamp_create(grant)
    db.access_grants[grant["id"]] = grant
    _audit_grant(grant, "CREATE", after=s_grant(grant))
    return success_object(s_grant(grant), status=201)


@bp.delete("/objectives/<id>/access-grants/<user_id>")
def revoke_access(id, user_id):
    require_role("PlatformAdmin", "Manager", "Employee")
    o = db.objectives.get(id)
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    aid = actor_id()
    arole = actor_role()
    if arole != "PlatformAdmin" and not is_owner_or_co_owner(o, aid):
        raise ApiError("ERR_NOT_OWNER", 403, "must be owner or co-owner")
    target = None
    for g in db.access_grants.values():
        if (g["objective_id"] == id and g["user_id"] == user_id
                and g["status"] == "ACTIVE"):
            target = g
            break
    if target is None:
        raise ApiError("ERR_GRANT_NOT_FOUND", 404, "active grant not found")
    before = s_grant(target)
    target["status"] = "REVOKED"
    stamp_update(target)
    _audit_grant(target, "DELETE", before=before, after=s_grant(target))
    return empty_204()


@bp.get("/objectives/<id>/access-grants")
def list_grants(id):
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    o = db.objectives.get(id)
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    aid = actor_id()
    arole = actor_role()
    # Per spec, list-ACTIVE is readable by Owner, PlatformAdmin, HRBP
    if arole == "Manager" or arole == "Employee":
        if not is_owner_or_co_owner(o, aid):
            raise ApiError("ERR_FORBIDDEN", 403, "not owner")
    items = [g for g in db.access_grants.values()
             if g["objective_id"] == id and g["status"] == "ACTIVE"]
    items.sort(key=lambda g: g["created_at"])
    return success_array([s_grant(g) for g in items], len(items), 10, 0)
