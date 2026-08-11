from flask import Blueprint

import db
from errors import raise_err
from middleware import (
    MISSING, get_auth, require_role, actor_member, require_group_moderator,
    validate, v_str, v_zip, v_enum, v_int,
)
from response import ok, get_body
from services import new_entity, touch, ser_group

bp = Blueprint("groups", __name__)

READ_ROLES = ("Member", "GroupModerator", "PlatformAdmin")


@bp.post("/v1/groups")
def create_group():
    role, _uid = get_auth()
    require_role(role, ("PlatformAdmin",))
    body = get_body()
    fields = validate(body, {
        "name": (True, v_str),
        "zip_code": (True, v_zip),
        "join_policy": (False, v_enum("OPEN", "APPROVAL_REQUIRED")),
        "capacity": (False, v_int(2, 10000)),
    })
    group = new_entity()
    group.update({
        "name": fields["name"],
        "zip_code": fields["zip_code"],
        "join_policy": fields["join_policy"] if fields["join_policy"] is not MISSING else "OPEN",
        "capacity": fields["capacity"] if fields["capacity"] is not MISSING else 150,
    })
    db.store.groups[group["id"]] = group
    return ok(ser_group(group), status=201)


@bp.get("/v1/groups/<group_id>")
def get_group(group_id):
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    group = db.store.groups.get(group_id)
    if group is None:
        raise_err("ERR_GROUP_NOT_FOUND", "no group with the given id")
    return ok(ser_group(group))


@bp.put("/v1/groups/<group_id>")
def update_group(group_id):
    role, uid = get_auth()
    require_role(role, ("GroupModerator", "PlatformAdmin"))
    body = get_body()
    fields = validate(body, {
        "name": (False, v_str),
        "join_policy": (False, v_enum("OPEN", "APPROVAL_REQUIRED")),
        "capacity": (False, v_int(2, 10000)),
        "expected_group_version": (True, v_int()),
    })
    if role == "GroupModerator":
        actor_member(role, uid)
    group = db.store.groups.get(group_id)
    if group is None:
        raise_err("ERR_GROUP_NOT_FOUND", "no group with the given id")
    require_group_moderator(role, uid, group["id"])
    if fields["expected_group_version"] != group["version"]:
        raise_err("ERR_STALE_VERSION", "group version has advanced; re-read and resubmit")
    if fields["name"] is not MISSING:
        group["name"] = fields["name"]
    if fields["join_policy"] is not MISSING:
        group["join_policy"] = fields["join_policy"]
    if fields["capacity"] is not MISSING:
        group["capacity"] = fields["capacity"]
    touch(group)
    return ok(ser_group(group))
