"""Stay assignments: list/read, check-in, check-out, no-show, cancel
(PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from authz import (
    ADMIN, FACILITIES, HOUSEKEEPING, FINANCE, COORDINATOR, require_roles,
    check_group_ownership,
)
from cascades import (
    cancel_reserved_assignment, check_in_assignment, check_out_assignment,
    no_show_assignment,
)
from db import store
from errors import ApiError, invalid_state
from respond import success
from serialize import ser_assignment
from store_ops import get_or_404, paginate, sorted_by_creation, touch
from timeutil import as_instant

bp = Blueprint("stays", __name__)

READ_ROLES = [ADMIN, FACILITIES, HOUSEKEEPING, FINANCE, COORDINATOR]


@bp.route("/stay-assignments", methods=["GET"])
def list_assignments():
    require_roles(READ_ROLES)
    revision_id = request.args.get("revision_id")
    group_id = request.args.get("group_id")
    room_id = request.args.get("room_id")
    participant_id = request.args.get("participant_id")
    status = request.args.get("status")
    items = [
        a for a in store.assignments.values()
        if (revision_id is None or a["revision_id"] == revision_id)
        and (group_id is None or a["group_id"] == group_id)
        and (room_id is None or a["room_id"] == room_id)
        and (participant_id is None or a["participant_id"] == participant_id)
        and (status is None or a["status"] == status)
    ]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_assignment(a) for a in page], response_type="array", pagination=pagination)


@bp.route("/stay-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    require_roles(READ_ROLES)
    return success(ser_assignment(get_or_404(store.assignments, aid)))


@bp.route("/stay-assignments/<aid>/check-in", methods=["POST"])
def check_in(aid):
    require_roles([ADMIN])
    a = get_or_404(store.assignments, aid)
    if a["status"] != "RESERVED":
        raise invalid_state("Assignment must be RESERVED to check in")
    group = store.groups[a["group_id"]]
    if group["status"] not in ("CONFIRMED", "IN_HOUSE"):
        raise invalid_state("Group must be CONFIRMED or IN_HOUSE to check in")
    room = store.rooms[a["room_id"]]
    if room["status"] not in ("RESERVED", "OCCUPIED"):
        raise invalid_state("Room must be RESERVED or OCCUPIED to check in")
    building = store.buildings[room["building_id"]]
    if building["status"] != "TURN_ACTIVE":
        raise ApiError("ERR_BUILDING_NOT_RELEASED", 409,
                       "Host building is not TURN_ACTIVE")
    now = store.clock
    if not (as_instant(a["checkin_at"]) <= now < as_instant(a["checkout_at"])):
        raise ApiError("ERR_OUTSIDE_CHECKIN_WINDOW", 422,
                       "Logical clock is outside the planned [checkin_at, checkout_at) window")
    check_in_assignment(a)
    return success(ser_assignment(a))


@bp.route("/stay-assignments/<aid>/check-out", methods=["POST"])
def check_out(aid):
    require_roles([ADMIN])
    a = get_or_404(store.assignments, aid)
    if a["status"] != "CHECKED_IN":
        raise invalid_state("Assignment must be CHECKED_IN to check out")
    check_out_assignment(a)
    return success(ser_assignment(a))


@bp.route("/stay-assignments/<aid>/mark-no-show", methods=["POST"])
def mark_no_show(aid):
    require_roles([ADMIN])
    a = get_or_404(store.assignments, aid)
    if a["status"] != "RESERVED":
        raise invalid_state("Assignment must be RESERVED to mark no-show")
    if not store.clock > as_instant(a["checkin_at"]) + timedelta(hours=24):
        raise ApiError("ERR_OUTSIDE_CHECKIN_WINDOW", 422,
                       "No-show is allowed only more than 24 hours after checkin_at")
    no_show_assignment(a)
    room = store.rooms[a["room_id"]]
    touch(store.buildings[room["building_id"]])
    return success(ser_assignment(a))


@bp.route("/stay-assignments/<aid>/cancel", methods=["POST"])
def cancel_assignment(aid):
    uid, role = require_roles([COORDINATOR, ADMIN])
    a = get_or_404(store.assignments, aid)
    check_group_ownership(uid, role, a["group_id"])
    revision = store.revisions.get(a["revision_id"])
    if revision is not None and revision["status"] == "SUPERSEDED":
        raise ApiError("ERR_REVISION_SUPERSEDED", 409,
                       "Assignment belongs to a SUPERSEDED revision")
    if a["status"] != "RESERVED":
        raise invalid_state("Assignment must be RESERVED to cancel")
    cancel_reserved_assignment(a)
    room = store.rooms[a["room_id"]]
    touch(store.buildings[room["building_id"]])
    return success(ser_assignment(a))
