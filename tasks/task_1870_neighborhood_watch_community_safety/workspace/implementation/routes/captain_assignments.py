"""BlockCaptainAssignment routes."""

from flask import Blueprint, request

import db
import errors
import services.core as svc
from middleware import require_roles
from response import success_object, success_list
from routes.watch_groups import _pagination

bp = Blueprint("captain_assignments", __name__)

ALL_ROLES = ("ProgramCoordinator", "LiaisonOfficer", "BlockCaptain", "Member")


def _serialize_ca(ca):
    return {
        "id": ca["id"],
        "block_id": ca["block_id"],
        "member_id": ca["member_id"],
        "assignment_status": ca["assignment_status"],
        "assigned_at": ca.get("assigned_at"),
        "relieved_at": ca.get("relieved_at"),
        "created_at": ca["created_at"],
        "updated_at": ca["updated_at"],
        "version": ca["version"],
    }


@bp.route("/watch/blocks/<block_id>/captain-assignments", methods=["POST"])
def create_assignment(block_id):
    user_id, role = require_roles("ProgramCoordinator")

    # Existence: block first
    b = db.blocks.get(block_id)
    if not b:
        raise errors.not_found("Block not found")

    body = request.get_json(force=True, silent=True) or {}
    member_id = body.get("member_id")
    expected_block_version = body.get("expected_block_version")

    if not member_id:
        raise errors.invalid_request("member_id is required")
    if expected_block_version is None:
        raise errors.invalid_request("expected_block_version is required")

    # OCC check
    if expected_block_version != b["version"]:
        raise errors.stale_version(
            f"Block version mismatch: expected {expected_block_version}, current {b['version']}"
        )

    # Member must exist
    m = db.members.get(member_id)
    if not m:
        raise errors.not_found("Member not found")

    # Referential integrity: member must be ACTIVE member of a block in the same watch group
    if m["membership_status"] != "ACTIVE":
        raise errors.referential("Member is not ACTIVE")
    if m["watch_group_id"] != b["watch_group_id"]:
        raise errors.referential("Member does not belong to the same watch group as the block")

    # Cardinality: member may hold at most one ACTIVE captain assignment
    for ca in db.captain_assignments.values():
        if ca["member_id"] == member_id and ca["assignment_status"] == "ACTIVE":
            raise errors.constraint_violation("Member already holds an ACTIVE captain assignment")

    # Supersede: relieve any existing ACTIVE assignment on this block
    for ca in db.captain_assignments.values():
        if ca["block_id"] == block_id and ca["assignment_status"] == "ACTIVE":
            ca["assignment_status"] = "RELIEVED"
            ca["relieved_at"] = db.now_iso()
            svc.touch(ca)

    now_iso = db.now_iso()
    record = {
        "block_id": block_id,
        "member_id": member_id,
        "assignment_status": "ACTIVE",
        "assigned_at": now_iso,
        "relieved_at": None,
    }
    svc.stamp_new(record)
    db.captain_assignments[record["id"]] = record

    # Increment block version
    svc.touch(b)

    # Posture recompute
    svc.recompute_posture(b["watch_group_id"])

    return success_object(_serialize_ca(record), 201)


@bp.route("/watch/blocks/<block_id>/captain-assignments", methods=["GET"])
def list_block_assignments(block_id):
    user_id, role = require_roles(*ALL_ROLES)
    b = db.blocks.get(block_id)
    if not b:
        raise errors.not_found("Block not found")

    items = [ca for ca in db.captain_assignments.values() if ca["block_id"] == block_id]

    status_filter = request.args.get("assignment_status")
    if status_filter:
        items = [ca for ca in items if ca["assignment_status"] == status_filter]

    items.sort(key=lambda ca: ca["created_at"])
    limit, offset = _pagination()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list([_serialize_ca(ca) for ca in items], limit, offset, total)


@bp.route("/watch/captain-assignments", methods=["GET"])
def list_all_assignments():
    user_id, role = require_roles(*ALL_ROLES)

    items = list(db.captain_assignments.values())

    # Filters
    mid = request.args.get("member_id")
    if mid:
        items = [ca for ca in items if ca["member_id"] == mid]
    bid = request.args.get("block_id")
    if bid:
        items = [ca for ca in items if ca["block_id"] == bid]
    st = request.args.get("assignment_status")
    if st:
        items = [ca for ca in items if ca["assignment_status"] == st]

    items.sort(key=lambda ca: ca["created_at"])
    limit, offset = _pagination()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list([_serialize_ca(ca) for ca in items], limit, offset, total)


@bp.route("/watch/captain-assignments/<id>", methods=["GET"])
def get_assignment(id):
    user_id, role = require_roles(*ALL_ROLES)
    ca = db.captain_assignments.get(id)
    if not ca:
        raise errors.not_found("CaptainAssignment not found")
    return success_object(_serialize_ca(ca))


@bp.route("/watch/captain-assignments/<id>/relieve", methods=["POST"])
def relieve_assignment(id):
    user_id, role = require_roles("ProgramCoordinator")
    ca = db.captain_assignments.get(id)
    if not ca:
        raise errors.not_found("CaptainAssignment not found")

    if ca["assignment_status"] != "ACTIVE":
        raise errors.invalid_state("Assignment is not ACTIVE")

    ca["assignment_status"] = "RELIEVED"
    ca["relieved_at"] = db.now_iso()
    svc.touch(ca)

    # Posture recompute
    b = db.blocks.get(ca["block_id"])
    if b:
        svc.recompute_posture(b["watch_group_id"])

    return success_object(_serialize_ca(ca))
