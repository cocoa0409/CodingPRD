"""GroupMembership endpoints."""

from flask import Blueprint, request

import db
from common import (
    require_role, get_json_body, stamp_common_create, bump,
    success, must_exist, get_pagination, paginate_list, clock_now_dt,
)
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_CAPACITY_EXCEEDED, ERR_FORBIDDEN,
)
from routes.small_group import _roster_count

bp = Blueprint("group_memberships", __name__)

ROLES = {"LEADER", "CO_LEADER", "MEMBER"}


@bp.route("/group-memberships", methods=["POST"])
def create_membership():
    require_role({"Coordinator", "PlatformAdmin"})
    body = get_json_body()
    for k in ("group_id", "member_id"):
        if k not in body or body[k] is None:
            raise_err(ERR_INVALID_REQUEST, f"{k} is required")
    role_val = body.get("role") if body.get("role") is not None else "MEMBER"
    if role_val not in ROLES:
        raise_err(ERR_INVALID_REQUEST, "invalid role")

    group = db.small_groups.get(body["group_id"])
    if group is None:
        raise_err(ERR_NOT_FOUND, "group_id not found")
    member = db.members.get(body["member_id"])
    if member is None:
        raise_err(ERR_NOT_FOUND, "member_id not found")

    # Rung 9: capacity — strictly less-than.
    current = _roster_count(group["id"])
    if current >= group["capacity"]:
        raise_err(ERR_CAPACITY_EXCEEDED, "group roster is at capacity")

    joined_on = clock_now_dt().strftime("%Y-%m-%d")

    rec = {
        "group_id": group["id"],
        "member_id": member["id"],
        "role": role_val,
        "status": "ACTIVE",
        "joined_on": joined_on,
    }
    stamp_common_create(rec)
    db.group_memberships[rec["id"]] = rec

    group["roster_count"] = _roster_count(group["id"])
    bump(group)
    return success(rec, 201)


@bp.route("/group-memberships/<gmid>", methods=["GET"])
def get_membership(gmid):
    role, user_id = require_role({"Coordinator", "Member", "PlatformAdmin"})
    rec = must_exist(db.group_memberships, gmid, "GroupMembership")
    if role == "Member" and rec["member_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Member may only view their own memberships")
    return success(rec, 200)


@bp.route("/group-memberships/<gmid>/deactivate", methods=["POST"])
def deactivate_membership(gmid):
    require_role({"Coordinator", "PlatformAdmin"})
    rec = must_exist(db.group_memberships, gmid, "GroupMembership")
    if rec["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "membership must be ACTIVE to deactivate")
    rec["status"] = "PAST"
    bump(rec)
    group = db.small_groups.get(rec["group_id"])
    if group is not None:
        group["roster_count"] = _roster_count(group["id"])
        bump(group)
    return success(rec, 200)


@bp.route("/group-memberships", methods=["GET"])
def list_memberships():
    role, user_id = require_role({"Coordinator", "Member", "PlatformAdmin"})
    limit, offset = get_pagination()
    items = list(db.group_memberships.values())
    if role == "Member":
        items = [gm for gm in items if gm["member_id"] == user_id]
    for k in ("group_id", "member_id", "status"):
        v = request.args.get(k)
        if v:
            items = [gm for gm in items if gm.get(k) == v]
    page, meta = paginate_list(items, limit, offset)
    return success(page, 200, meta_extra=meta)
