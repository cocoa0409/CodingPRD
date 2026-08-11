from flask import Blueprint, request

import cardsvc
import constants as C
import derive
import serializers
import validation as V
from envelope import object_response, paginate
from errors import ApiError
from lookups import body_row, check_billing_freeze, freeze_for_site, path_row, require_record_state
from store import db
from timeutil import add_minutes

bp = Blueprint("assignments", __name__)


@bp.post("/livescan/device-assignments")
def create_assignment():
    data = V.body()
    device = body_row("devices", data.get("device_id")) if data.get("device_id") else None
    site = body_row("sites", data.get("site_id")) if data.get("site_id") else None

    window_start = V.req_instant(data, "window_start")
    window_end = V.req_instant(data, "window_end")
    if device is None:
        V.bad_request("device_id is required")
    if site is None:
        V.bad_request("site_id is required")
    if window_end <= window_start:
        V.bad_request("window_end must be strictly after window_start")

    check_billing_freeze(freeze_for_site(site))

    # rung 21 -- buffered exclusive occupancy; the buffer boundary is strict in
    # the operator's favour (a gap of exactly 30 minutes is accepted).
    buffer_minutes = C.DEVICE_ASSIGNMENT_BUFFER_MINUTES
    for other in db.device_assignments.values():
        if other["device_id"] != device["id"]:
            continue
        if derive.assignment_status(other) not in ("SCHEDULED", "ACTIVE"):
            continue
        if (
            window_start < add_minutes(other["window_end"], buffer_minutes)
            and add_minutes(window_end, buffer_minutes) > other["window_start"]
        ):
            raise ApiError(
                "ERR_DEVICE_ASSIGNMENT_CONFLICT",
                "the candidate window collides with an existing roster entry",
            )

    row = db.create(
        "device_assignments",
        {
            "device_id": device["id"],
            "site_id": site["id"],
            "window_start": window_start,
            "window_end": window_end,
            "status": "SCHEDULED",
            "calibration_expires_at_snapshot": device["calibration_expires_at"],
            "billable_print_count": 0,
            "tainted_print_count": 0,
        },
    )
    return object_response(serializers.device_assignment(row), 201)


@bp.get("/livescan/device-assignments/<id>")
def read_assignment(id):
    return object_response(serializers.device_assignment(path_row("device_assignments", id)))


@bp.get("/livescan/device-assignments")
def list_assignments():
    rows = list(db.device_assignments.values())
    device_id = request.args.get("device_id")
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    if device_id is not None:
        rows = [r for r in rows if r["device_id"] == device_id]
    if site_id is not None:
        rows = [r for r in rows if r["site_id"] == site_id]
    if status is not None:
        rows = [r for r in rows if derive.assignment_status(r) == status]
    return paginate(rows, serializers.device_assignment)


@bp.post("/livescan/device-assignments/<id>/release")
def release_assignment(id):
    assignment = path_row("device_assignments", id)
    current = derive.assignment_status(assignment)
    require_record_state(current in ("SCHEDULED", "ACTIVE"), "assignment is %s" % current)

    if current == "ACTIVE":
        assignment["billable_print_count"] = cardsvc.billable_count_for_assignment(assignment)
    assignment["status"] = "RELEASED"
    db.touch(assignment)
    return object_response(serializers.device_assignment(assignment))
