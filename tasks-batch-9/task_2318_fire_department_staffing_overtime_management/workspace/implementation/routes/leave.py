"""Leave requests: filing and revocation."""

import calc
import domain
import validation as V
from auth import ALL_ROLES, authenticate
from envelope import created_object, ok_list, ok_object
from errors import ApiError
from flask import Blueprint
from store import db

bp = Blueprint("leave", __name__)


@bp.route("/fire-ops/leave-requests", methods=["POST"])
def create_leave_request():
    user_id, _role = authenticate(("Firefighter",))
    body = V.parse_body()
    data = V.validate(
        body,
        [
            V.spec("firefighter_id", "id"),
            V.spec("duty_shift_id", "id"),
            V.spec("leave_type", "enum", values=V.LEAVE_TYPES),
            V.spec("requested_hours", "number", exclusive_minimum=0, maximum=24),
        ],
    )
    member = domain.require(
        db.firefighters, data["firefighter_id"], "ERR_FIREFIGHTER_NOT_FOUND"
    )
    shift = domain.require(db.duty_shifts, data["duty_shift_id"], "ERR_DUTY_SHIFT_NOT_FOUND")
    if user_id != member["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if member["station_id"] != shift["station_id"]:
        raise ApiError("ERR_STATION_SCOPE_MISMATCH")

    leave_request = db.new(
        {
            "firefighter_id": member["id"],
            "duty_shift_id": shift["id"],
            "leave_type": data["leave_type"],
            "requested_hours": calc.num(data["requested_hours"]),
            "status": "QUEUED",
            "decision_order_index": None,
            "denial_reason": None,
            "backfill_vacancy_id": None,
        }
    )
    db.leave_requests[leave_request["id"]] = leave_request
    return created_object(leave_request)


@bp.route("/fire-ops/leave-requests/<leave_request_id>", methods=["GET"])
def get_leave_request(leave_request_id):
    authenticate(ALL_ROLES)
    leave_request = domain.require(
        db.leave_requests, leave_request_id, "ERR_LEAVE_REQUEST_NOT_FOUND"
    )
    return ok_object(leave_request)


@bp.route("/fire-ops/leave-requests", methods=["GET"])
def list_leave_requests():
    authenticate(ALL_ROLES)
    from routes.common import apply_filters, f, nulls_last, sorted_by

    items = list(db.leave_requests.values())
    items = apply_filters(
        items,
        {
            "firefighter_id": f("firefighter_id"),
            "duty_shift_id": f("duty_shift_id"),
            "status": f("status"),
            "leave_type": f("leave_type"),
        },
    )
    items = sorted_by(items, lambda e: (nulls_last(e["decision_order_index"]),))
    return ok_list(items)


@bp.route("/fire-ops/leave-requests/<leave_request_id>/revoke", methods=["POST"])
def revoke_leave_request(leave_request_id):
    user_id, _role = authenticate(("Firefighter",))
    leave_request = domain.require(
        db.leave_requests, leave_request_id, "ERR_LEAVE_REQUEST_NOT_FOUND"
    )
    if user_id != leave_request["firefighter_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if leave_request["status"] != "APPROVED":
        raise ApiError("ERR_LEAVE_NOT_REVOCABLE")
    shift = db.duty_shifts.get(leave_request["duty_shift_id"])
    if shift is None:
        raise ApiError("ERR_DUTY_SHIFT_NOT_FOUND")
    domain.require_active_shift(shift)

    backfill = db.vacancies.get(leave_request.get("backfill_vacancy_id"))
    if backfill is not None and backfill["status"] == "FILLED":
        raise ApiError("ERR_LEAVE_ALREADY_BACKFILLED")

    leave_request["status"] = "REVOKED"
    db.touch(leave_request)

    for asg in db.shift_assignments.values():
        if asg["relieved_by_leave_request_id"] != leave_request["id"]:
            continue
        if asg["status"] != "RELIEVED":
            continue
        asg["status"] = "SCHEDULED"
        asg["relieved_by_leave_request_id"] = None
        db.touch(asg)

    if backfill is not None and backfill["status"] in ("OPEN", "OFFERING"):
        domain.cancel_vacancy_and_rescind(backfill, "CANCELLED")

    domain.recompute_member_work_periods(leave_request["firefighter_id"])
    domain.recompute_shift(shift)
    db.touch(shift)
    station = domain.station_of_shift(shift)
    if station is not None:
        domain.recompute_station(station)
    return ok_object(leave_request)
