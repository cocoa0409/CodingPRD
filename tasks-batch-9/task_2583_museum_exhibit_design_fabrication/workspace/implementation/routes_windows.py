"""InstallWindow endpoints: buffers, the two interval geometries and zone occupancy
(PRD §3.9)."""

from flask import Blueprint

import calc
import helpers
import serializers
from auth import (ALL_ROLES, ROLE_FABRICATION_LEAD, ROLE_MUSEUM_OPERATIONS,
                  ROLE_PROJECT_MANAGER, caller_id, check_segregation, endpoint)
from envelope import (list_response, object_response, pagination, query_bool_filter,
                      query_filter)
from errors import ApiError
from helpers import touch
from store import db, new_row, order_created
from validate import body_object, v_bool, v_datetime, v_enum, v_id, v_num, v_str

bp = Blueprint("windows", __name__)

WORK_CLASSES = ("QUIET", "NOISY", "DUST_GENERATING", "CRANE_ACCESS")
WINDOW_DECISIONS = ("APPROVE", "DENY")
OCCUPYING_STATUSES = ("REQUESTED", "APPROVED", "IN_PROGRESS")


@bp.route("/install-windows", methods=["POST"])
@endpoint(roles=[ROLE_FABRICATION_LEAD, ROLE_PROJECT_MANAGER])
def create_window():
    body = body_object()
    project_id = v_id(body, "project_id")
    zone_id = v_id(body, "zone_id")
    work_class = v_enum(body, "work_class", WORK_CLASSES)
    noise_dba = v_num(body, "noise_dba", ge=0, le=130)
    starts_at = v_datetime(body, "starts_at")
    ends_at = v_datetime(body, "ends_at")
    requires_closure = v_bool(body, "requires_gallery_closure", required=False, default=False)

    project = helpers.get_project(project_id)
    zone = helpers.get_zone(zone_id)
    helpers.require_same_project(project, zone)

    # Step 9: a zero-length or inverted range is refused.
    if not ends_at > starts_at:
        raise ApiError("ERR_INVALID_TIME_RANGE")
    helpers.require_phase(project, ("FABRICATION", "INSTALLATION"))
    helpers.require_not_frozen(project)

    pre_minutes, settling_minutes = calc.window_buffers(
        work_class, zone["dust_settling_buffer_minutes"])
    effective_start, effective_end = calc.effective_bounds(
        starts_at, ends_at, pre_minutes, settling_minutes)

    window = new_row("windows", {
        "project_id": project["id"],
        "zone_id": zone["id"],
        "work_class": work_class,
        "noise_dba": noise_dba,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "requires_gallery_closure": requires_closure,
        "pre_access_buffer_minutes": pre_minutes,
        "settling_buffer_minutes": settling_minutes,
        "effective_start_at": effective_start,
        "effective_end_at": effective_end,
        "status": "REQUESTED",
        "denial_reason": None,
        "requested_by_user_id": caller_id(),
    })
    db.windows[window["id"]] = window
    # Requesting a window does not change the zone's occupancy_state.
    return object_response(serializers.window_json(window), 201)


@bp.route("/exhibit-projects/<pid>/install-windows", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_project_windows(pid):
    project = helpers.get_project(pid)
    limit, offset = pagination()
    status = query_filter("status")
    zone_id = query_filter("zone_id")
    closure = query_bool_filter("requires_gallery_closure")
    rows = helpers.rows_of_project(db.windows, project["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if zone_id is not None:
        rows = [r for r in rows if r["zone_id"] == zone_id]
    if closure is not None:
        rows = [r for r in rows if r["requires_gallery_closure"] == closure]
    return list_response(rows, serializers.window_json, limit, offset)


@bp.route("/install-windows/<window_id>", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def get_window(window_id):
    window = helpers.get_window(window_id)
    return object_response(serializers.window_json(window))


@bp.route("/install-windows/<window_id>/decision", methods=["POST"])
@endpoint(roles=[ROLE_MUSEUM_OPERATIONS])
def decide_window(window_id):
    window = helpers.get_window(window_id)
    project = helpers.owning_project(window)
    # Step 3: the caller may not be the requester.
    check_segregation(window["requested_by_user_id"])
    body = body_object()
    decision = v_enum(body, "decision", WINDOW_DECISIONS)
    denial_reason = v_str(body, "denial_reason", None, None, required=False, default=None)

    helpers.require_not_frozen(project)
    if window["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_WINDOW_STATE")

    if decision == "DENY":
        window["status"] = "DENIED"
        window["denial_reason"] = denial_reason
        touch(window)
        return object_response(serializers.window_json(window))

    zone = db.zones[window["zone_id"]]
    # First noise — but a closed gallery has no visitors to disturb, so the ceiling
    # does not apply at all when the window requires a closure.
    if not window["requires_gallery_closure"]:
        if calc.D(window["noise_dba"]) > calc.D(zone["max_noise_dba"]):
            raise ApiError("ERR_NOISE_LIMIT_EXCEEDED")
    # Second occupancy.
    if zone["occupancy_state"] == "CLOSED":
        raise ApiError("ERR_ZONE_CLOSED_FOR_WORK")
    if window["requires_gallery_closure"] and not zone["closure_allowed"]:
        raise ApiError("ERR_ZONE_CLOSED_FOR_WORK")
    # Third the per-zone buffered, half-open conflict.
    for other in helpers.windows_of_zone(zone["id"]):
        if other["id"] == window["id"] or other["status"] not in OCCUPYING_STATUSES:
            continue
        if calc.windows_conflict(window, other):
            raise ApiError("ERR_ZONE_WINDOW_CONFLICT")
    # Fourth, and only for a closure request, the project-wide closed-interval sweep.
    if window["requires_gallery_closure"]:
        participants = [w for w in helpers.rows_of_project(db.windows, project["id"])
                        if w["id"] != window["id"]
                        and w["requires_gallery_closure"]
                        and w["status"] in ("APPROVED", "IN_PROGRESS")]
        participants.append(window)
        if calc.closure_capacity_peak(participants) > project["max_concurrent_closures"]:
            raise ApiError("ERR_CLOSURE_CAPACITY_EXCEEDED")

    window["status"] = "APPROVED"
    touch(window)
    return object_response(serializers.window_json(window))


@bp.route("/install-windows/<window_id>/start", methods=["POST"])
@endpoint(roles=[ROLE_MUSEUM_OPERATIONS])
def start_window(window_id):
    window = helpers.get_window(window_id)
    project = helpers.owning_project(window)
    helpers.require_phase(project, ("INSTALLATION",))
    if window["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_WINDOW_STATE")
    if db.now() < window["starts_at"]:
        raise ApiError("ERR_INVALID_WINDOW_STATE", "The window has not started yet.")

    window["status"] = "IN_PROGRESS"
    zone = db.zones[window["zone_id"]]
    zone["occupancy_state"] = "CLOSED" if window["requires_gallery_closure"] else "PARTIAL_CLOSURE"
    touch(zone)
    touch(window)
    return object_response(serializers.window_json(window))


@bp.route("/install-windows/<window_id>/complete", methods=["POST"])
@endpoint(roles=[ROLE_MUSEUM_OPERATIONS])
def complete_window(window_id):
    window = helpers.get_window(window_id)
    if window["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_WINDOW_STATE")

    cases = helpers.cases_of_zone(window["zone_id"])
    loaded = []
    for case in cases:
        reserved = [a for a in helpers.artifacts_assigned_to_case(case["id"])
                    if a["placement_status"] == "RESERVED"]
        if reserved:
            loaded.append((case, reserved))
    for case, _reserved in loaded:
        if case["mount_status"] != "MOUNT_INSTALLED":
            raise ApiError("ERR_MOUNT_NOT_INSTALLED")

    window["status"] = "COMPLETED"
    zone = db.zones[window["zone_id"]]
    zone["occupancy_state"] = "OPERATING"
    touch(zone)
    # Ascending order of the case's created_at, then the object's created_at.
    for case, reserved in loaded:
        for artifact in sorted(reserved, key=order_created):
            artifact["placement_status"] = "PLACED"
            touch(artifact)
    touch(window)
    return object_response(serializers.window_json(window))


@bp.route("/install-windows/<window_id>/cancel", methods=["POST"])
@endpoint(roles=[ROLE_MUSEUM_OPERATIONS, ROLE_FABRICATION_LEAD])
def cancel_window(window_id):
    window = helpers.get_window(window_id)
    body = body_object(required=False)
    denial_reason = v_str(body, "denial_reason", None, None, required=False, default=None)
    if window["status"] not in ("REQUESTED", "APPROVED"):
        raise ApiError("ERR_INVALID_WINDOW_STATE")
    window["status"] = "CANCELLED"
    if denial_reason is not None:
        window["denial_reason"] = denial_reason
    touch(window)
    # A CANCELLED window stops occupying its zone at once.
    return object_response(serializers.window_json(window))
