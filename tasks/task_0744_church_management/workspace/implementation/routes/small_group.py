"""SmallGroup endpoints."""

from flask import Blueprint, request

import db
from common import (
    require_role, get_json_body, stamp_common_create, bump,
    success, must_exist, get_pagination, paginate_list,
)
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_MEMBERSHIP_INELIGIBLE,
    ERR_FORBIDDEN,
)

bp = Blueprint("small_groups", __name__)

MINISTRY_AREAS = {"WORSHIP", "STUDY", "OUTREACH", "CARE", "YOUTH"}


def _roster_count(gid):
    return sum(
        1 for gm in db.group_memberships.values()
        if gm.get("group_id") == gid and gm.get("status") == "ACTIVE"
    )


@bp.route("/small-groups", methods=["POST"])
def create_group():
    require_role({"Coordinator", "PlatformAdmin"})
    body = get_json_body()
    for k in ("name", "leader_member_id", "ministry_area", "capacity"):
        if k not in body or body[k] is None:
            raise_err(ERR_INVALID_REQUEST, f"{k} is required")
    if not isinstance(body["name"], str) or body["name"] == "":
        raise_err(ERR_INVALID_REQUEST, "name must be a non-empty string")
    if body["ministry_area"] not in MINISTRY_AREAS:
        raise_err(ERR_INVALID_REQUEST, "invalid ministry_area")
    if not isinstance(body["capacity"], int) or isinstance(body["capacity"], bool):
        raise_err(ERR_INVALID_REQUEST, "capacity must be an integer")
    if body["capacity"] <= 0:
        raise_err(ERR_INVALID_REQUEST, "capacity must be > 0")

    leader = db.members.get(body["leader_member_id"])
    if leader is None:
        raise_err(ERR_NOT_FOUND, "leader_member_id not found")
    if leader.get("membership_status") not in ("REGULAR", "MEMBER"):
        raise_err(ERR_MEMBERSHIP_INELIGIBLE, "leader must be REGULAR or MEMBER")

    rec = {
        "name": body["name"],
        "leader_member_id": leader["id"],
        "ministry_area": body["ministry_area"],
        "capacity": body["capacity"],
        "status": "ACTIVE",
        "roster_count": 0,
    }
    stamp_common_create(rec)
    db.small_groups[rec["id"]] = rec
    return success(rec, 201)


@bp.route("/small-groups/<gid>", methods=["GET"])
def get_group(gid):
    require_role({"Coordinator", "Member", "PlatformAdmin"})
    rec = must_exist(db.small_groups, gid, "SmallGroup")
    out = dict(rec)
    out["roster_count"] = _roster_count(gid)
    return success(out, 200)


@bp.route("/small-groups", methods=["GET"])
def list_groups():
    require_role({"Coordinator", "Member", "PlatformAdmin"})
    limit, offset = get_pagination()
    items = list(db.small_groups.values())
    for k in ("leader_member_id", "ministry_area", "status"):
        v = request.args.get(k)
        if v:
            items = [g for g in items if g.get(k) == v]
    out = []
    for g in items:
        go = dict(g)
        go["roster_count"] = _roster_count(g["id"])
        out.append(go)
    page, meta = paginate_list(out, limit, offset)
    return success(page, 200, meta_extra=meta)
