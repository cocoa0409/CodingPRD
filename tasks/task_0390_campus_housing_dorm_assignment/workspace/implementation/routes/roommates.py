"""Roommate group and membership routes."""

from flask import Blueprint, request

import db
import errors
import response
import common
from middleware import authenticate, require_role
from services import core

bp = Blueprint("roommates", __name__)

ALL_ROLES = ("HousingOfficer", "Student", "ResidentAdvisor")


def _own(principal, student_id):
    if principal.user_id != student_id:
        raise errors.forbidden("Caller does not own this resource.")


def _accepted_count(group_id):
    return sum(
        1 for m in db.roommate_memberships.values()
        if m["group_id"] == group_id and m["membership_status"] == "ACCEPTED"
    )


# --------------------------------------------------------------------------
# Groups
# --------------------------------------------------------------------------
@bp.route("/roommate-groups", methods=["POST"])
def create_group():
    principal = authenticate()
    require_role(principal, ("Student",))
    body = common.get_body()
    common.require_fields(body, ["cycle_id", "owner_student_id", "target_size"])
    cycle_id = body["cycle_id"]
    owner_id = body["owner_student_id"]
    target_size = common.require_int(body, "target_size")
    if target_size < 2 or target_size > 3:
        raise errors.invalid_request("target_size must be between 2 and 3.")

    with db.LOCK:
        _own(principal, owner_id)
        core.get_or_404(db.housing_cycles, cycle_id)
        core.get_or_404(db.students, owner_id)

        group = core.init_record({
            "cycle_id": cycle_id,
            "owner_student_id": owner_id,
            "target_size": target_size,
            "accepted_member_count": 1,
            "status": "FORMING",
        })
        db.roommate_groups[group["id"]] = group

        membership = core.init_record({
            "group_id": group["id"],
            "student_id": owner_id,
            "membership_status": "ACCEPTED",
        })
        db.roommate_memberships[membership["id"]] = membership
        return response.object_response(core.serialize(group), status=201)


@bp.route("/roommate-groups/<group_id>", methods=["GET"])
def get_group(group_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        rec = core.get_or_404(db.roommate_groups, group_id)
        return response.object_response(core.serialize(rec))


@bp.route("/roommate-groups", methods=["GET"])
def list_groups():
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        limit, offset = common.parse_pagination()
        items = list(db.roommate_groups.values())
        for key in ("cycle_id", "owner_student_id"):
            val = request.args.get(key)
            if val is not None:
                items = [g for g in items if g.get(key) == val]
        items = common.sort_by_created(items)
        page, total = common.paginate(items, limit, offset)
        return response.array_response(
            [core.serialize(g) for g in page], limit, offset, total
        )


@bp.route("/roommate-groups/<group_id>/lock", methods=["POST"])
def lock_group(group_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        group = core.get_or_404(db.roommate_groups, group_id)
        _own(principal, group["owner_student_id"])
        if group["status"] != "FORMING":
            raise errors.invalid_state("Group is not FORMING.")
        if group["accepted_member_count"] != group["target_size"]:
            raise errors.group_size_invalid("accepted_member_count != target_size.")
        group["status"] = "LOCKED"
        core.touch(group)
        return response.object_response(core.serialize(group))


@bp.route("/roommate-groups/<group_id>/reopen", methods=["POST"])
def reopen_group(group_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        group = core.get_or_404(db.roommate_groups, group_id)
        _own(principal, group["owner_student_id"])
        if group["status"] != "LOCKED":
            raise errors.invalid_state("Group is not LOCKED.")
        # No application referencing this group may be SUBMITTED/OFFERED/ACCEPTED.
        for a in db.applications.values():
            if (a["roommate_group_id"] == group_id
                    and a["status"] in ("SUBMITTED", "OFFERED", "ACCEPTED")):
                raise errors.precondition_not_met(
                    "An application referencing this group is active."
                )
        group["status"] = "FORMING"
        core.touch(group)
        return response.object_response(core.serialize(group))


@bp.route("/roommate-groups/<group_id>/disband", methods=["POST"])
def disband_group(group_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        group = core.get_or_404(db.roommate_groups, group_id)
        _own(principal, group["owner_student_id"])
        if group["status"] not in ("FORMING", "LOCKED"):
            raise errors.invalid_state("Group is not in a disbandable state.")
        for a in db.applications.values():
            if (a["roommate_group_id"] == group_id
                    and a["status"] in ("OFFERED", "ACCEPTED")):
                raise errors.precondition_not_met(
                    "An application referencing this group is OFFERED/ACCEPTED."
                )
        group["status"] = "DISBANDED"
        core.touch(group)
        # Remove all INVITED/ACCEPTED memberships.
        for m in db.roommate_memberships.values():
            if m["group_id"] == group_id and m["membership_status"] in ("INVITED", "ACCEPTED"):
                m["membership_status"] = "REMOVED"
                core.touch(m)
        # SUBMITTED applications keep competing solo (group cleared).
        for a in db.applications.values():
            if a["roommate_group_id"] == group_id and a["status"] == "SUBMITTED":
                a["roommate_group_id"] = None
                core.touch(a)
        group["accepted_member_count"] = _accepted_count(group_id)
        return response.object_response(core.serialize(group))


# --------------------------------------------------------------------------
# Memberships
# --------------------------------------------------------------------------
@bp.route("/roommate-groups/<group_id>/memberships", methods=["POST"])
def invite_member(group_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        group = core.get_or_404(db.roommate_groups, group_id)
        _own(principal, group["owner_student_id"])
        body = common.get_body()
        common.require_fields(body, ["student_id"])
        student_id = body["student_id"]
        core.get_or_404(db.students, student_id)

        if group["status"] != "FORMING":
            raise errors.invalid_state("Group is not FORMING.")
        # Duplicate membership check.
        for m in db.roommate_memberships.values():
            if (m["group_id"] == group_id and m["student_id"] == student_id
                    and m["membership_status"] in ("INVITED", "ACCEPTED")):
                raise errors.duplicate_membership()

        membership = core.init_record({
            "group_id": group_id,
            "student_id": student_id,
            "membership_status": "INVITED",
        })
        db.roommate_memberships[membership["id"]] = membership
        return response.object_response(core.serialize(membership), status=201)


@bp.route("/roommate-groups/<group_id>/memberships", methods=["GET"])
def list_group_memberships(group_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        core.get_or_404(db.roommate_groups, group_id)
        limit, offset = common.parse_pagination()
        items = [m for m in db.roommate_memberships.values() if m["group_id"] == group_id]
        items = common.sort_by_created(items)
        page, total = common.paginate(items, limit, offset)
        return response.array_response(
            [core.serialize(m) for m in page], limit, offset, total
        )


@bp.route("/roommate-memberships/<membership_id>", methods=["GET"])
def get_membership(membership_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        rec = core.get_or_404(db.roommate_memberships, membership_id)
        return response.object_response(core.serialize(rec))


@bp.route("/roommate-memberships", methods=["GET"])
def list_memberships():
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        limit, offset = common.parse_pagination()
        items = list(db.roommate_memberships.values())
        for key in ("group_id", "student_id"):
            val = request.args.get(key)
            if val is not None:
                items = [m for m in items if m.get(key) == val]
        items = common.sort_by_created(items)
        page, total = common.paginate(items, limit, offset)
        return response.array_response(
            [core.serialize(m) for m in page], limit, offset, total
        )


def _get_membership_in_group(group_id, membership_id):
    group = core.get_or_404(db.roommate_groups, group_id)
    membership = core.get_or_404(db.roommate_memberships, membership_id)
    if membership["group_id"] != group_id:
        raise errors.not_found("Membership does not belong to this group.")
    return group, membership


@bp.route("/roommate-groups/<group_id>/memberships/<membership_id>/accept", methods=["POST"])
def accept_membership(group_id, membership_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        group, membership = _get_membership_in_group(group_id, membership_id)
        _own(principal, membership["student_id"])
        if membership["membership_status"] != "INVITED":
            raise errors.invalid_state("Membership is not INVITED.")
        if group["status"] != "FORMING":
            raise errors.invalid_state("Group is not FORMING.")
        if group["accepted_member_count"] >= group["target_size"]:
            raise errors.group_size_invalid("Group is already full.")
        membership["membership_status"] = "ACCEPTED"
        core.touch(membership)
        group["accepted_member_count"] += 1
        core.touch(group)
        return response.object_response(core.serialize(membership))


@bp.route("/roommate-groups/<group_id>/memberships/<membership_id>/decline", methods=["POST"])
def decline_membership(group_id, membership_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        group, membership = _get_membership_in_group(group_id, membership_id)
        _own(principal, membership["student_id"])
        if membership["membership_status"] != "INVITED":
            raise errors.invalid_state("Membership is not INVITED.")
        if group["status"] != "FORMING":
            raise errors.invalid_state("Group is not FORMING.")
        membership["membership_status"] = "DECLINED"
        core.touch(membership)
        return response.object_response(core.serialize(membership))


@bp.route("/roommate-groups/<group_id>/memberships/<membership_id>/remove", methods=["POST"])
def remove_membership(group_id, membership_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        group, membership = _get_membership_in_group(group_id, membership_id)
        _own(principal, group["owner_student_id"])
        if membership["membership_status"] != "ACCEPTED":
            raise errors.invalid_state("Membership is not ACCEPTED.")
        if group["status"] != "FORMING":
            raise errors.invalid_state("Group is not FORMING.")
        if membership["student_id"] == group["owner_student_id"]:
            raise errors.forbidden("Owner cannot remove their own membership.")
        membership["membership_status"] = "REMOVED"
        core.touch(membership)
        group["accepted_member_count"] -= 1
        core.touch(group)
        return response.object_response(core.serialize(membership))
