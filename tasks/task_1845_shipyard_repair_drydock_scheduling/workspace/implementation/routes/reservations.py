"""DockReservation endpoints: booking (with vessel fit, window, and dock-slot
conflict checks plus OCC on the project), activation, and cancellation."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DOCK_SLOT_CONFLICT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PROJECT_NOT_CONTRACTED,
    ERR_RESERVATION_WINDOW_INVALID,
    ERR_STALE_VERSION,
    ERR_VESSEL_EXCEEDS_DOCK_LIMITS,
)
from middleware import require_roles
from response import success_list, success_object
from services import project_ops
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    dec,
    get_json_body,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_int,
    require_string,
    require_ts,
    sort_by_created_at,
)

bp = Blueprint("reservations", __name__)

READ_ROLES = ("YardAdmin", "ProjectManager", "CommercialApprover", "EnvironmentalOfficer")

TURNAROUND = timedelta(hours=project_ops.TURNAROUND_BUFFER_HOURS)


def get_reservation_or_404(reservation_id: str) -> dict:
    reservation = db.reservations.get(reservation_id)
    if reservation is None:
        raise_err(ERR_NOT_FOUND, "DockReservation id does not exist")
    return reservation


@bp.route("/v1/dock-reservations", methods=["POST"])
@require_roles("ProjectManager")
def create_reservation(_user_id: str, _role: str):
    body = get_json_body()
    # Rung 3: well-formedness.
    project_id = require_string(body, "project_id")
    start_utc = require_ts(body, "start_utc")
    end_utc = require_ts(body, "end_utc")
    expected_project_version = require_int(body, "expected_project_version")

    # Rung 4: referenced project exists.
    project = db.projects.get(project_id)
    if project is None:
        raise_err(ERR_NOT_FOUND, "RepairProject id does not exist")

    # Rung 5: optimistic concurrency on the project version.
    if expected_project_version != project["version"]:
        raise_err(
            ERR_STALE_VERSION,
            "expected_project_version does not match the project's current version",
        )

    start_dt = parse_iso8601(start_utc, "start_utc")
    end_dt = parse_iso8601(end_utc, "end_utc")
    dock = db.docks[project["dock_id"]]
    vessel = db.vessels[project["vessel_id"]]

    # Rung 8: inclusive vessel fit check.
    if (
        dec(vessel["length_m"]) > dec(dock["max_length_m"])
        or dec(vessel["beam_m"]) > dec(dock["max_beam_m"])
        or dec(vessel["draft_m"]) > dec(dock["max_depth_m"])
    ):
        raise_err(ERR_VESSEL_EXCEEDS_DOCK_LIMITS, "Vessel dimensions exceed the dock limits")
    # Rung 8: window must be strictly positive.
    if not (end_dt > start_dt):
        raise_err(ERR_RESERVATION_WINDOW_INVALID, "end_utc must be strictly after start_utc")

    # Rung 9: half-open occupied window [start_utc, end_utc + 12h) must not
    # intersect any BOOKED/ACTIVE reservation of the same dock.
    new_occupied_end = end_dt + TURNAROUND
    for other in db.reservations.values():
        if other["dock_id"] != dock["id"] or other["status"] not in ("BOOKED", "ACTIVE"):
            continue
        other_start = parse_iso8601(other["start_utc"], "start_utc")
        other_occupied_end = parse_iso8601(other["end_utc"], "end_utc") + TURNAROUND
        if start_dt < other_occupied_end and other_start < new_occupied_end:
            raise_err(
                ERR_DOCK_SLOT_CONFLICT,
                "Reservation window (plus turnaround buffer) intersects another booking",
            )

    reservation = {
        "project_id": project_id,
        "dock_id": dock["id"],
        "start_utc": start_utc,
        "end_utc": end_utc,
        "status": "BOOKED",
        "dockage_fee_cents": project_ops.compute_dockage_fee(dock, vessel, start_dt, end_dt),
        "activated_at_utc": None,
        "released_at_utc": None,
    }
    db.stamp_new(reservation)
    db.reservations[reservation["id"]] = reservation
    # A booking is a legitimate write against the project: version +1.
    db.touch(project)
    return success_object(serialize(reservation), 201)


@bp.route("/v1/dock-reservations", methods=["GET"])
@require_roles(*READ_ROLES)
def list_reservations(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.reservations.values()))
    items = apply_filters(items, ["dock_id", "project_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/v1/dock-reservations/<reservation_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_reservation(reservation_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_reservation_or_404(reservation_id)))


@bp.route("/v1/dock-reservations/<reservation_id>/activate", methods=["POST"])
@require_roles("ProjectManager")
def activate_reservation(reservation_id: str, _user_id: str, _role: str):
    reservation = get_reservation_or_404(reservation_id)
    # Rung 5: transition defined only from BOOKED.
    if reservation["status"] != "BOOKED":
        raise_err(ERR_INVALID_STATE, "activate requires a BOOKED reservation")
    project = db.projects[reservation["project_id"]]
    if project["status"] != "CONTRACTED":
        raise_err(ERR_PROJECT_NOT_CONTRACTED, "Parent project must be CONTRACTED to dock in")
    now = db.clock_dt()
    start_dt = parse_iso8601(reservation["start_utc"], "start_utc")
    end_dt = parse_iso8601(reservation["end_utc"], "end_utc")
    if not (start_dt <= now < end_dt):
        raise_err(ERR_INVALID_STATE, "Current logical time is outside the reservation window")

    reservation["status"] = "ACTIVE"
    reservation["activated_at_utc"] = project_ops.logical_now_iso()
    db.touch(reservation)

    # Parent project: CONTRACTED -> IN_DOCK with full schedule establishment.
    project["status"] = "IN_DOCK"
    project["actual_dock_in_utc"] = project_ops.logical_now_iso()
    project_ops.refresh_project_derived(project, include_bid=False)
    db.touch(project)
    return success_object(serialize(reservation))


@bp.route("/v1/dock-reservations/<reservation_id>/cancel", methods=["POST"])
@require_roles("ProjectManager")
def cancel_reservation(reservation_id: str, _user_id: str, _role: str):
    reservation = get_reservation_or_404(reservation_id)
    if reservation["status"] != "BOOKED":
        raise_err(ERR_INVALID_STATE, "only a BOOKED reservation may be cancelled")
    reservation["status"] = "CANCELLED"
    db.touch(reservation)
    return success_object(serialize(reservation))
