"""Block routes."""

from flask import Blueprint, request

import db
import errors
import services.core as svc
from middleware import require_roles
from response import success_object, success_list
from routes.watch_groups import _pagination

bp = Blueprint("blocks", __name__)

ALL_ROLES = ("ProgramCoordinator", "LiaisonOfficer", "BlockCaptain", "Member")


def _serialize_block(b):
    return {
        "id": b["id"],
        "watch_group_id": b["watch_group_id"],
        "street_segment": b["street_segment"],
        "household_count": b["household_count"],
        "registration_status": b["registration_status"],
        "risk_heat_score": b["risk_heat_score"],
        "last_incident_at": b.get("last_incident_at"),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


@bp.route("/watch/watch-groups/<gid>/blocks", methods=["POST"])
def create_block(gid):
    user_id, role = require_roles("ProgramCoordinator")
    g = db.watch_groups.get(gid)
    if not g:
        raise errors.not_found("WatchGroup not found")

    body = request.get_json(force=True, silent=True) or {}
    street_segment = body.get("street_segment")
    household_count = body.get("household_count")

    # Field-level validation
    if not street_segment or not isinstance(street_segment, str):
        raise errors.invalid_request("street_segment is required")
    if household_count is None or not isinstance(household_count, int) or household_count < 1:
        raise errors.invalid_request("household_count must be >= 1")

    # Uniqueness: street_segment unique within group among non-DEREGISTERED blocks
    for b in db.blocks.values():
        if (b["watch_group_id"] == gid
                and b["registration_status"] != "DEREGISTERED"
                and b["street_segment"].lower() == street_segment.lower()):
            raise errors.constraint_violation("Duplicate street_segment in this group")

    record = {
        "watch_group_id": gid,
        "street_segment": street_segment,
        "household_count": household_count,
        "registration_status": "PENDING",
        "risk_heat_score": 0,
        "last_incident_at": None,
    }
    svc.stamp_new(record)
    db.blocks[record["id"]] = record
    return success_object(_serialize_block(record), 201)


@bp.route("/watch/watch-groups/<gid>/blocks", methods=["GET"])
def list_blocks(gid):
    user_id, role = require_roles(*ALL_ROLES)
    g = db.watch_groups.get(gid)
    if not g:
        raise errors.not_found("WatchGroup not found")

    items = [b for b in db.blocks.values() if b["watch_group_id"] == gid]

    status_filter = request.args.get("registration_status")
    if status_filter:
        items = [b for b in items if b["registration_status"] == status_filter]

    items.sort(key=lambda b: b["created_at"])
    limit, offset = _pagination()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list([_serialize_block(b) for b in items], limit, offset, total)


@bp.route("/watch/blocks/<id>", methods=["GET"])
def get_block(id):
    user_id, role = require_roles(*ALL_ROLES)
    b = db.blocks.get(id)
    if not b:
        raise errors.not_found("Block not found")
    return success_object(_serialize_block(b))


@bp.route("/watch/blocks/<id>/register", methods=["POST"])
def register_block(id):
    user_id, role = require_roles("ProgramCoordinator")
    b = db.blocks.get(id)
    if not b:
        raise errors.not_found("Block not found")

    # State check
    if b["registration_status"] != "PENDING":
        raise errors.invalid_state("Block is not PENDING")

    g = db.watch_groups.get(b["watch_group_id"])
    if not g:
        raise errors.not_found("WatchGroup not found")

    # Precondition: certification_status != REVOKED
    if g["certification_status"] == "REVOKED":
        raise errors.invalid_state("Group certification is REVOKED")

    # household_count >= 1 (should always be true from creation)
    if b["household_count"] < 1:
        raise errors.invalid_request("household_count must be >= 1")

    # No other REGISTERED block with same street_segment (case-insensitive)
    for other in db.blocks.values():
        if (other["id"] != b["id"]
                and other["watch_group_id"] == b["watch_group_id"]
                and other["registration_status"] == "REGISTERED"
                and other["street_segment"].lower() == b["street_segment"].lower()):
            raise errors.constraint_violation("Another REGISTERED block has the same street_segment")

    b["registration_status"] = "REGISTERED"
    svc.touch(b)

    # Posture recompute (may trigger DORMANT -> FORMATION)
    svc.recompute_posture(b["watch_group_id"])

    return success_object(_serialize_block(b))


@bp.route("/watch/blocks/<id>/deregister", methods=["POST"])
def deregister_block(id):
    user_id, role = require_roles("ProgramCoordinator")
    b = db.blocks.get(id)
    if not b:
        raise errors.not_found("Block not found")

    if b["registration_status"] != "REGISTERED":
        raise errors.invalid_state("Block is not REGISTERED")

    # No open incident reports
    for ir in db.incident_reports.values():
        if ir["block_id"] == id and ir["review_status"] in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"):
            raise errors.invalid_state("Block has open incident reports")

    # No ACTIVE captain assignment
    for ca in db.captain_assignments.values():
        if ca["block_id"] == id and ca["assignment_status"] == "ACTIVE":
            raise errors.invalid_state("Block has an ACTIVE captain assignment")

    b["registration_status"] = "DEREGISTERED"
    svc.touch(b)

    # Cascade: withdraw all ACTIVE members on this block
    svc.cascade_block_deregistration(b)

    # Posture recompute
    svc.recompute_posture(b["watch_group_id"])

    return success_object(_serialize_block(b))
