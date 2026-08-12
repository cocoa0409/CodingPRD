from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    MISSING, get_auth, require_role, actor_member, require_active,
    require_group_moderator, validate, v_str, v_enum,
)
from response import ok, get_body, paginate, no_body_fields
from services import (
    new_entity, touch, ser_membership, group_member_count, withdraw_member_claims,
)

bp = Blueprint("memberships", __name__)

READ_ROLES = ("Member", "GroupModerator", "PlatformAdmin")


def _get_membership(membership_id):
    ms = db.store.memberships.get(membership_id)
    if ms is None:
        raise_err("ERR_MEMBERSHIP_NOT_FOUND", "no membership with the given id")
    return ms


@bp.post("/v1/memberships")
def create_membership():
    role, uid = get_auth()
    require_role(role, ("Member",))
    body = get_body()
    fields = validate(body, {"group_id": (True, v_str)})
    member = actor_member(role, uid)
    group = db.store.groups.get(fields["group_id"])
    if group is None:
        raise_err("ERR_GROUP_NOT_FOUND", "no group with the given id")
    require_active(member)
    for ms in db.store.memberships.values():
        if (ms["member_id"] == member["id"] and ms["group_id"] == group["id"]
                and ms["status"] in ("REQUESTED", "APPROVED")):
            raise_err("ERR_MEMBERSHIP_EXISTS", "a live membership already exists for this member and group")
    if group["join_policy"] == "OPEN" and group_member_count(group["id"]) >= group["capacity"]:
        raise_err("ERR_GROUP_FULL", "group roster is full")
    ms = new_entity()
    ms.update({
        "member_id": member["id"],
        "group_id": group["id"],
        "role": "MEMBER",
        "status": "REQUESTED",
    })
    db.store.memberships[ms["id"]] = ms
    if group["join_policy"] == "OPEN":
        # Inline auto-approve under the OPEN join policy.
        ms["status"] = "APPROVED"
        touch(ms)
        touch(group)  # member_count += 1; roster_status recomputed
    return ok(ser_membership(ms), status=201)


@bp.get("/v1/memberships/<membership_id>")
def get_membership(membership_id):
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    return ok(ser_membership(_get_membership(membership_id)))


@bp.get("/v1/memberships")
def list_memberships():
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    items = list(db.store.memberships.values())
    member_id = request.args.get("member_id")
    group_id = request.args.get("group_id")
    status = request.args.get("status")
    mrole = request.args.get("role")
    if member_id is not None:
        items = [m for m in items if m["member_id"] == member_id]
    if group_id is not None:
        items = [m for m in items if m["group_id"] == group_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if mrole is not None:
        items = [m for m in items if m["role"] == mrole]
    items.sort(key=lambda m: (m["created_at"], m["_seq"]))
    page, meta = paginate(items)
    return ok([ser_membership(m) for m in page], response_type="array", pagination=meta)


@bp.post("/v1/memberships/<membership_id>/approve")
def approve_membership(membership_id):
    role, uid = get_auth()
    require_role(role, ("GroupModerator", "PlatformAdmin"))
    body = get_body()
    fields = validate(body, {"role": (False, v_enum("MEMBER", "MODERATOR"))})
    if role == "GroupModerator":
        actor_member(role, uid)
    ms = _get_membership(membership_id)
    require_group_moderator(role, uid, ms["group_id"])
    if ms["status"] != "REQUESTED":
        raise_err("ERR_MEMBERSHIP_NOT_REQUESTED", "membership is not in REQUESTED")
    group = db.store.groups.get(ms["group_id"])
    if group is not None and group_member_count(group["id"]) >= group["capacity"]:
        raise_err("ERR_GROUP_FULL", "group roster is full")
    ms["status"] = "APPROVED"
    ms["role"] = fields["role"] if fields["role"] is not MISSING else "MEMBER"
    touch(ms)
    if group is not None:
        touch(group)
    return ok(ser_membership(ms))


@bp.post("/v1/memberships/<membership_id>/reject")
def reject_membership(membership_id):
    role, uid = get_auth()
    require_role(role, ("GroupModerator", "PlatformAdmin"))
    no_body_fields()
    if role == "GroupModerator":
        actor_member(role, uid)
    ms = _get_membership(membership_id)
    require_group_moderator(role, uid, ms["group_id"])
    if ms["status"] != "REQUESTED":
        raise_err("ERR_MEMBERSHIP_NOT_REQUESTED", "membership is not in REQUESTED")
    ms["status"] = "REJECTED"
    touch(ms)
    return ok(ser_membership(ms))


@bp.post("/v1/memberships/<membership_id>/leave")
def leave_membership(membership_id):
    role, uid = get_auth()
    require_role(role, ("Member",))
    no_body_fields()
    member = actor_member(role, uid)
    ms = _get_membership(membership_id)
    if ms["status"] != "APPROVED":
        raise_err("ERR_MEMBERSHIP_NOT_APPROVED", "membership is not in APPROVED")
    if ms["member_id"] != member["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "only the membership's member may leave it")
    ms["status"] = "LEFT"
    touch(ms)
    group = db.store.groups.get(ms["group_id"])
    if group is not None:
        touch(group)  # member_count -= 1; roster_status recomputed
    withdraw_member_claims(member["id"], group_id=ms["group_id"])
    return ok(ser_membership(ms))


@bp.post("/v1/memberships/<membership_id>/remove")
def remove_membership(membership_id):
    role, uid = get_auth()
    require_role(role, ("GroupModerator", "PlatformAdmin"))
    no_body_fields()
    if role == "GroupModerator":
        actor_member(role, uid)
    ms = _get_membership(membership_id)
    require_group_moderator(role, uid, ms["group_id"])
    if ms["status"] != "APPROVED":
        raise_err("ERR_MEMBERSHIP_NOT_APPROVED", "membership is not in APPROVED")
    ms["status"] = "REMOVED"
    touch(ms)
    group = db.store.groups.get(ms["group_id"])
    if group is not None:
        touch(group)
    withdraw_member_claims(ms["member_id"], group_id=ms["group_id"])
    return ok(ser_membership(ms))
