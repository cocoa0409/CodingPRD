"""StaffMembers and CabinAssignments. PRD §3.2."""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from services import validate, serialize, recompute
from services.store import base_fields, require, touch, paginate

bp = Blueprint("staff", __name__)

ROLE_KINDS = {"COUNSELOR", "CIT"}


@bp.route("/camps/<cid>/staff", methods=["POST"])
def create_staff(cid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    camp = require(db.camps, cid)
    body = get_json_body()

    full_name = validate.require_str(body, "full_name")
    role_kind = validate.require_enum(body, "role_kind", ROLE_KINDS)
    cleared = validate.optional_bool(body, "is_background_cleared", False)

    s = base_fields()
    s.update({
        "camp_id": camp["id"],
        "full_name": full_name,
        "role_kind": role_kind,
        "is_background_cleared": cleared,
    })
    db.staff_members[s["id"]] = s
    return response.success(serialize.staff_member(s), 201)


@bp.route("/camps/<cid>/staff", methods=["GET"])
def list_staff(cid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    require(db.camps, cid)
    limit, offset = parse_pagination()

    camp_id_f = request.args.get("camp_id")
    items = [s for s in db.staff_members.values() if s["camp_id"] == cid]
    if camp_id_f is not None:
        items = [s for s in items if s["camp_id"] == camp_id_f]

    page, total = paginate(items, limit, offset)
    return response.success_list([serialize.staff_member(s) for s in page], limit, offset, total)


@bp.route("/staff/<sid>", methods=["GET"])
def get_staff(sid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    s = require(db.staff_members, sid)
    return response.success(serialize.staff_member(s), 200)


@bp.route("/cabin-assignments", methods=["POST"])
def create_cabin_assignment():
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    body = get_json_body()

    if "cabin_id" not in body or not isinstance(body.get("cabin_id"), str):
        raise validate.bad_request("cabin_id is required.")
    if "staff_member_id" not in body or not isinstance(body.get("staff_member_id"), str):
        raise validate.bad_request("staff_member_id is required.")

    cabin = db.cabins.get(body["cabin_id"])
    if cabin is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Cabin not found.")
    staff = db.staff_members.get(body["staff_member_id"])
    if staff is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "StaffMember not found.")

    # Only background-cleared staff may be assigned (ERR_STAFF_NOT_CLEARED, p8).
    if not staff["is_background_cleared"]:
        raise ApiError(errors.ERR_STAFF_NOT_CLEARED, 422, "StaffMember is not background-cleared.")

    ca = base_fields()
    ca.update({
        "cabin_id": cabin["id"],
        "staff_member_id": staff["id"],
        "status": "ACTIVE",
    })
    db.cabin_assignments[ca["id"]] = ca

    # Recompute the cabin staffing then the session posture (PRD §3.2).
    recompute.recompute_cabin_staffing(cabin, bump_version=True)
    session = db.sessions[cabin["session_id"]]
    recompute.recompute_session_posture(session, bump_version=True)

    return response.success(serialize.cabin_assignment(ca), 201)


@bp.route("/cabin-assignments", methods=["GET"])
def list_cabin_assignments():
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    limit, offset = parse_pagination()

    cabin_id_f = request.args.get("cabin_id")
    staff_id_f = request.args.get("staff_member_id")
    status_f = request.args.get("status")

    items = list(db.cabin_assignments.values())
    if cabin_id_f is not None:
        items = [ca for ca in items if ca["cabin_id"] == cabin_id_f]
    if staff_id_f is not None:
        items = [ca for ca in items if ca["staff_member_id"] == staff_id_f]
    if status_f is not None:
        items = [ca for ca in items if ca["status"] == status_f]

    page, total = paginate(items, limit, offset)
    return response.success_list([serialize.cabin_assignment(ca) for ca in page], limit, offset, total)


@bp.route("/cabin-assignments/<aid>", methods=["GET"])
def get_cabin_assignment(aid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    ca = require(db.cabin_assignments, aid)
    return response.success(serialize.cabin_assignment(ca), 200)


@bp.route("/cabin-assignments/<aid>/release", methods=["POST"])
def release_cabin_assignment(aid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    ca = require(db.cabin_assignments, aid)

    if ca["status"] != "ACTIVE":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "CabinAssignment is not ACTIVE.")

    cabin = db.cabins[ca["cabin_id"]]

    # A release is refused if it would leave any cabin holding ENROLLED campers
    # no longer staffable (ERR_CABIN_UNDERSTAFFED). Simulate by computing the
    # cabin's would-be staffing without this assignment. (PRD §3.2)
    has_enrolled = any(
        a["cabin_id"] == cabin["id"] and a["enroll_status"] == "ENROLLED"
        for a in db.applications.values()
    )
    if has_enrolled:
        ca["status"] = "RELEASED"
        recompute.recompute_cabin_staffing(cabin)  # no version bump yet
        if not cabin["is_staffable"]:
            # roll back
            ca["status"] = "ACTIVE"
            recompute.recompute_cabin_staffing(cabin)
            raise ApiError(errors.ERR_CABIN_UNDERSTAFFED, 422,
                           "Release would leave an enrolled cabin understaffed.")
        # already released; finalise with version bumps below
        touch(cabin)
        session = db.sessions[cabin["session_id"]]
        recompute.recompute_session_posture(session, bump_version=True)
        touch(ca)
        return response.success(serialize.cabin_assignment(ca), 200)

    ca["status"] = "RELEASED"
    recompute.recompute_cabin_staffing(cabin, bump_version=True)
    session = db.sessions[cabin["session_id"]]
    recompute.recompute_session_posture(session, bump_version=True)
    touch(ca)
    return response.success(serialize.cabin_assignment(ca), 200)
