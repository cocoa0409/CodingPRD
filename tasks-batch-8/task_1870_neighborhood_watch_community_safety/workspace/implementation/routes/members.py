"""Member routes."""

from flask import Blueprint, request

import db
import errors
import services.core as svc
from middleware import require_roles, get_auth
from response import success_object, success_list
from routes.watch_groups import _pagination

bp = Blueprint("members", __name__)

ALL_ROLES = ("ProgramCoordinator", "LiaisonOfficer", "BlockCaptain", "Member")

VALID_CHANNELS = {"SMS", "EMAIL", "PHONE_TREE"}
VALID_VISIBILITY = {"GROUP_ONLY", "LIAISON_VISIBLE", "PROGRAM_WIDE"}

STRIKE_LIMIT = 3


def _serialize_member(m):
    return {
        "id": m["id"],
        "watch_group_id": m["watch_group_id"],
        "block_id": m["block_id"],
        "full_name": m["full_name"],
        "contact_channel": m["contact_channel"],
        "roster_visibility": m["roster_visibility"],
        "membership_status": m["membership_status"],
        "bias_training_completed_at": m.get("bias_training_completed_at"),
        "strike_count": m["strike_count"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


@bp.route("/watch/members", methods=["POST"])
def create_member():
    user_id, role = require_roles("ProgramCoordinator", "BlockCaptain")
    body = request.get_json(force=True, silent=True) or {}

    watch_group_id = body.get("watch_group_id")
    block_id = body.get("block_id")
    full_name = body.get("full_name")
    contact_channel = body.get("contact_channel")
    roster_visibility = body.get("roster_visibility", "GROUP_ONLY")

    # Field-level validation
    if not full_name or not isinstance(full_name, str):
        raise errors.invalid_request("full_name is required")
    if not contact_channel or contact_channel not in VALID_CHANNELS:
        raise errors.invalid_request("contact_channel must be SMS, EMAIL, or PHONE_TREE")
    if roster_visibility not in VALID_VISIBILITY:
        raise errors.invalid_request("roster_visibility must be GROUP_ONLY, LIAISON_VISIBLE, or PROGRAM_WIDE")

    # Existence
    g = db.watch_groups.get(watch_group_id) if watch_group_id else None
    if not g:
        raise errors.not_found("WatchGroup not found")
    b = db.blocks.get(block_id) if block_id else None
    if not b:
        raise errors.not_found("Block not found")

    # Posture gate
    if g["posture"] == "FROZEN":
        raise errors.posture_gated("Member writes are rejected while group is FROZEN")

    # Referential integrity: block must belong to group
    if b["watch_group_id"] != watch_group_id:
        raise errors.referential("Block does not belong to the specified watch group")

    record = {
        "watch_group_id": watch_group_id,
        "block_id": block_id,
        "full_name": full_name,
        "contact_channel": contact_channel,
        "roster_visibility": roster_visibility,
        "membership_status": "ACTIVE",
        "bias_training_completed_at": None,
        "strike_count": 0,
    }
    svc.stamp_new(record)
    db.members[record["id"]] = record

    # Participation score recompute
    svc.recompute_posture(watch_group_id)

    return success_object(_serialize_member(record), 201)


@bp.route("/watch/members", methods=["GET"])
def list_members():
    user_id, role = require_roles(*ALL_ROLES)

    items = list(db.members.values())

    # Roster visibility scoping for LiaisonOfficer
    if role == "LiaisonOfficer":
        scoped = []
        for m in items:
            gid = m["watch_group_id"]
            if m["roster_visibility"] in ("LIAISON_VISIBLE", "PROGRAM_WIDE"):
                scoped.append(m)
            elif svc.has_active_agreement(gid, {"ROSTER_CONTACTS", "FULL"}):
                scoped.append(m)
        items = scoped

    # Filters
    wg = request.args.get("watch_group_id")
    if wg:
        items = [m for m in items if m["watch_group_id"] == wg]
    bid = request.args.get("block_id")
    if bid:
        items = [m for m in items if m["block_id"] == bid]
    ms = request.args.get("membership_status")
    if ms:
        items = [m for m in items if m["membership_status"] == ms]

    items.sort(key=lambda m: m["created_at"])
    limit, offset = _pagination()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list([_serialize_member(m) for m in items], limit, offset, total)


@bp.route("/watch/members/<id>", methods=["GET"])
def get_member(id):
    user_id, role = require_roles(*ALL_ROLES)
    m = db.members.get(id)
    if not m:
        raise errors.not_found("Member not found")

    # LiaisonOfficer visibility check on single-member read
    if role == "LiaisonOfficer":
        gid = m["watch_group_id"]
        if m["roster_visibility"] not in ("LIAISON_VISIBLE", "PROGRAM_WIDE"):
            if not svc.has_active_agreement(gid, {"ROSTER_CONTACTS", "FULL"}):
                raise errors.not_found("Member not found")

    return success_object(_serialize_member(m))


@bp.route("/watch/members/<id>/suspend", methods=["POST"])
def suspend_member(id):
    user_id, role = require_roles("ProgramCoordinator")
    m = db.members.get(id)
    if not m:
        raise errors.not_found("Member not found")

    if m["membership_status"] != "ACTIVE":
        raise errors.invalid_state("Member is not ACTIVE")

    m["membership_status"] = "SUSPENDED"
    svc.touch(m)

    # Cascade: revoke ACTIVE captain assignments
    svc.cascade_member_suspension(m)

    # Posture recompute
    svc.recompute_posture(m["watch_group_id"])

    return success_object(_serialize_member(m))


@bp.route("/watch/members/<id>/reinstate", methods=["POST"])
def reinstate_member(id):
    user_id, role = require_roles("ProgramCoordinator")
    m = db.members.get(id)
    if not m:
        raise errors.not_found("Member not found")

    g = db.watch_groups.get(m["watch_group_id"])
    if not g:
        raise errors.not_found("WatchGroup not found")

    # Posture gate
    if g["posture"] == "FROZEN":
        raise errors.posture_gated("Member reinstate rejected while group is FROZEN")

    if m["membership_status"] != "SUSPENDED":
        raise errors.invalid_state("Member is not SUSPENDED")

    m["membership_status"] = "ACTIVE"
    m["strike_count"] = 0
    svc.touch(m)

    svc.recompute_posture(m["watch_group_id"])

    return success_object(_serialize_member(m))


@bp.route("/watch/members/<id>/withdraw", methods=["POST"])
def withdraw_member(id):
    user_id, role = get_auth()
    if role not in ("ProgramCoordinator", "Member"):
        raise errors.unauthorized()

    m = db.members.get(id)
    if not m:
        raise errors.not_found("Member not found")

    # Member can only withdraw self; ProgramCoordinator can withdraw anyone
    if role == "Member" and user_id != m["id"]:
        raise errors.unauthorized("Members may only withdraw themselves")

    if m["membership_status"] == "ACTIVE":
        # Withdrawal from ACTIVE: relieve captain assignments
        svc.cascade_member_withdrawal(m)
    elif m["membership_status"] == "SUSPENDED":
        # SUSPENDED -> WITHDRAWN only by coordinator
        if role != "ProgramCoordinator":
            raise errors.unauthorized("Only a coordinator may withdraw a SUSPENDED member")
    else:
        raise errors.invalid_state("Member is not ACTIVE or SUSPENDED")

    m["membership_status"] = "WITHDRAWN"
    svc.touch(m)

    # Posture recompute
    svc.recompute_posture(m["watch_group_id"])

    return success_object(_serialize_member(m))
