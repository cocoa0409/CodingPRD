"""LaunchGridAssignment endpoints."""

from flask import Blueprint

import errors
import validate as V
from db import DB, new_id, wall_created_at, parse_dt
from middleware import require_role, get_auth
from response import success_object, success_list
from services import calc
from services.show import (
    serialize_assignment, touch, recompute_posture, perimeter_containment_planned,
    drone_release_if_unassigned,
)

bp = Blueprint("assignments", __name__)


def _get_assignment(assignment_id):
    a = DB.assignments.get(assignment_id)
    if a is None:
        raise errors.not_found("ERR_ASSIGNMENT_NOT_FOUND", "assignment not found")
    return a


@bp.route("/api/launch-grid-assignments", methods=["POST"])
def create_assignment():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["show_event_id", "drone_id", "grid_row", "grid_col"])
    require_role("FleetManager")
    show_id = body["show_event_id"]
    drone_id = body["drone_id"]
    if not isinstance(show_id, str):
        raise errors.validation("show_event_id must be a string")
    if not isinstance(drone_id, str):
        raise errors.validation("drone_id must be a string")
    row = V.req_int(body, "grid_row")
    col = V.req_int(body, "grid_col")
    if row < 0 or col < 0:
        raise errors.validation("grid_row/grid_col must be >= 0")

    show = DB.show_events.get(show_id)
    if show is None:
        raise errors.not_found("ERR_SHOW_NOT_FOUND", "show not found")
    drone = DB.drones.get(drone_id)
    if drone is None:
        raise errors.not_found("ERR_DRONE_NOT_FOUND", "drone not found")

    # state
    if show["lifecycle_status"] not in ("AUTHORIZED", "READY"):
        raise errors.conflict("ERR_INVALID_STATE", "show must be AUTHORIZED or READY for grid assignment")

    # drone flyable — the catalog enumerates exactly GROUNDED/IN_MAINTENANCE/
    # RETIRED/CHARGING; RESERVED drones fall through to the
    # double-booking/already-assigned checks below.
    if drone["status"] in ("GROUNDED", "IN_MAINTENANCE", "RETIRED", "CHARGING"):
        raise errors.conflict("ERR_DRONE_NOT_FLYABLE", "drone is not flyable")

    # derated charge
    effective = calc.battery_derated_charge(drone["charge_pct"], show["site_id"])
    if effective < calc.LAUNCH_MIN_CHARGE_PCT:
        raise errors.conflict("ERR_CHARGE_BELOW_MINIMUM", "derated charge below launch minimum")

    # drone double-booked across overlapping windows
    s_start = parse_dt(show["window_start"])
    s_end = parse_dt(show["window_end"])
    for aid in DB.insertion_order["assignments"]:
        other = DB.assignments[aid]
        if other["drone_id"] != drone_id or other["status"] != "ASSIGNED":
            continue
        if other["show_event_id"] == show_id:
            continue
        other_show = DB.show_events.get(other["show_event_id"])
        if other_show is None:
            continue
        o_start = parse_dt(other_show["window_start"])
        o_end = parse_dt(other_show["window_end"])
        if o_start < s_end and s_start < o_end:
            raise errors.conflict("ERR_DRONE_DOUBLE_BOOKED", "drone already assigned on an overlapping show")

    # uniqueness / capacity
    # slot occupancy within this show (non-VOIDED)
    for aid in DB.insertion_order["assignments"]:
        other = DB.assignments[aid]
        if other["show_event_id"] != show_id:
            continue
        if other["status"] in ("ASSIGNED", "FLOWN", "RECONCILED") \
                and other["grid_row"] == row and other["grid_col"] == col:
            raise errors.conflict("ERR_GRID_SLOT_OCCUPIED", "grid slot already occupied")
        if other["drone_id"] == drone_id and other["status"] == "ASSIGNED":
            raise errors.conflict("ERR_DRONE_ALREADY_ASSIGNED", "drone already assigned on this show")

    # grid bounds
    site = DB.sites.get(show["site_id"])
    if site is None:
        raise errors.not_found("ERR_SITE_NOT_FOUND", "site not found")
    if (row + 1) * 2.0 > site["ground_length_m"] or (col + 1) * 2.0 > site["ground_width_m"]:
        raise errors.conflict("ERR_GRID_OUT_OF_BOUNDS", "grid coordinates exceed site ground")

    # design capacity
    design = DB.designs.get(show.get("pinned_design_id") or "")
    if design is not None and show["assigned_count"] >= design["drone_count"]:
        raise errors.conflict("ERR_ASSIGNMENT_EXCEEDS_DESIGN", "grid already holds pinned design drone_count assignments")

    aid = new_id()
    ts = wall_created_at()
    assignment = {
        "id": aid, "show_event_id": show_id, "drone_id": drone_id,
        "grid_row": row, "grid_col": col,
        "status": "ASSIGNED",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    DB.assignments[aid] = assignment
    DB.insertion_order["assignments"].append(aid)

    if drone["status"] != "RESERVED":
        # AVAILABLE -> RESERVED; a drone already RESERVED by another
        # non-overlapping show keeps its state and version.
        drone["status"] = "RESERVED"
        touch(drone)

    show["assigned_count"] += 1
    # auto-advance AUTHORIZED -> READY when grid complete and perimeter VALID
    if (show["lifecycle_status"] == "AUTHORIZED" and design is not None
            and show["assigned_count"] == design["drone_count"]
            and perimeter_containment_planned(show) == "VALID"):
        show["lifecycle_status"] = "READY"
    recompute_posture(show)
    touch(show)
    return success_object(serialize_assignment(assignment), 201)


@bp.route("/api/launch-grid-assignments/<assignmentId>", methods=["GET"])
def get_assignment(assignmentId):
    get_auth()
    return success_object(serialize_assignment(_get_assignment(assignmentId)))


@bp.route("/api/launch-grid-assignments", methods=["GET"])
def list_assignments():
    get_auth()
    limit, offset = V.pagination_params()
    from flask import request
    show_id = V.opt_string(request.args, "show_event_id")
    drone_id = V.opt_string(request.args, "drone_id")
    status = V.opt_string(request.args, "status")
    items = [DB.assignments[i] for i in DB.insertion_order["assignments"]]
    if show_id is not None:
        items = [a for a in items if a["show_event_id"] == show_id]
    if drone_id is not None:
        items = [a for a in items if a["drone_id"] == drone_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_assignment(a) for a in page], limit, offset, total)


@bp.route("/api/launch-grid-assignments/<assignmentId>/void", methods=["POST"])
def void_assignment_endpoint(assignmentId):
    body = V.get_body()
    V.reject_system_fields(body)
    require_role("FleetManager")
    assignment = _get_assignment(assignmentId)
    if assignment["status"] != "ASSIGNED":
        raise errors.conflict("ERR_INVALID_STATE", "assignment must be ASSIGNED to void")

    assignment["status"] = "VOIDED"
    touch(assignment)
    drone = DB.drones.get(assignment["drone_id"])
    if drone is not None:
        drone_release_if_unassigned(drone)
    show = DB.show_events.get(assignment["show_event_id"])
    if show is not None:
        show["assigned_count"] = max(0, show["assigned_count"] - 1)
        if show["lifecycle_status"] == "READY":
            design = DB.designs.get(show.get("pinned_design_id") or "")
            needed = design["drone_count"] if design else None
            if needed is None or show["assigned_count"] < needed:
                show["lifecycle_status"] = "AUTHORIZED"
        recompute_posture(show)
        touch(show)
    return success_object(serialize_assignment(assignment))
