"""Venue build-outs, on-site hosts and host rosters (PRD 3.7, 2.10)."""
from datetime import timedelta

from flask import Blueprint, g

import calc
import services
from auth import CLIENT_SERVICE_AGENT, FINANCE_CONTROLLER, OPERATIONS_MANAGER, guard
from common import get_assignment, get_booking, get_build, get_event, get_host, listing
from errors import (
    ERR_ASSIGNMENT_SCOPE_MISMATCH,
    ERR_BUILD_ZONE_CONFLICT,
    ERR_HOST_CAPACITY_EXCEEDED,
    ERR_INVALID_ASSIGNMENT_STATE,
    ERR_INVALID_BOOKING_STATE,
    ERR_INVALID_BUILD_STATE,
    ERR_INVALID_EVENT_STATE,
    ERR_ZONE_NOT_AT_VENUE,
    fail,
)
from response import object_response
from store import (
    create_record,
    db,
    host_assignment_json,
    hospitality_build_json,
    logical_now,
    on_site_host_json,
    touch,
)
from validation import (
    bad,
    body,
    opt_int,
    req_datetime,
    req_id,
    req_int,
    req_string,
    req_string_array,
)

bp = Blueprint("venue", __name__)

LIVE_BUILD_STATES = ("PLANNED", "APPROVED", "READY")
BUFFER = timedelta(minutes=calc.BUILD_BUFFER_MINUTES)


# --- HospitalityBuild -------------------------------------------------------


@bp.route("/hospitality-builds", methods=["POST"])
@guard(OPERATIONS_MANAGER)
def create_build():
    data = body()
    event_id = req_id(data, "event_id")
    zone_code = req_string(data, "zone_code")
    window_start = req_datetime(data, "service_window_start")
    window_end = req_datetime(data, "service_window_end")
    space_units = req_int(data, "space_units", minimum=1)
    catering_covers = req_int(data, "catering_covers", minimum=0)
    staff_count = req_int(data, "staff_count", minimum=0)
    build_cost_cents = req_int(data, "build_cost_cents", minimum=0)
    catering_cost_cents = req_int(data, "catering_cost_cents", minimum=0)
    staffing_cost_cents = req_int(data, "staffing_cost_cents", minimum=0)
    if window_end <= window_start:
        bad("Field `service_window_end` must be strictly after `service_window_start`.")

    event = get_event(event_id)
    if event["status"] not in calc.LIVE_EVENT_STATUSES:
        fail(ERR_INVALID_EVENT_STATE, "Build-outs cannot be planned against this fixture.")

    # PRD 2.10: closed windows, each existing occupancy inflated 90 minutes both sides.
    for other in calc.builds_of_event(event_id):
        if other["zone_code"] != zone_code:
            continue
        if other["build_state"] not in LIVE_BUILD_STATES:
            continue
        if (
            window_start <= other["service_window_end"] + BUFFER
            and window_end >= other["service_window_start"] - BUFFER
        ):
            fail(ERR_BUILD_ZONE_CONFLICT, "This zone is already occupied around that window.")

    if zone_code not in event["hospitality_zone_codes"]:
        fail(ERR_ZONE_NOT_AT_VENUE, "That zone is not one of the fixture's hospitality zones.")

    build = create_record(
        db.hospitality_builds,
        {
            "event_id": event_id,
            "zone_code": zone_code,
            "service_window_start": window_start,
            "service_window_end": window_end,
            "space_units": space_units,
            "catering_covers": catering_covers,
            "staff_count": staff_count,
            "build_cost_cents": build_cost_cents,
            "catering_cost_cents": catering_cost_cents,
            "staffing_cost_cents": staffing_cost_cents,
            "build_state": "PLANNED",
            "approved_by_user_id": None,
            "total_cost_cents": build_cost_cents + catering_cost_cents + staffing_cost_cents,
        },
    )
    return object_response(hospitality_build_json(build), 201)


@bp.route("/hospitality-builds/<build_id>", methods=["GET"])
@guard(OPERATIONS_MANAGER, FINANCE_CONTROLLER, CLIENT_SERVICE_AGENT)
def read_build(build_id):
    return object_response(hospitality_build_json(get_build(build_id)))


@bp.route("/hospitality-builds", methods=["GET"])
@guard(OPERATIONS_MANAGER, FINANCE_CONTROLLER, CLIENT_SERVICE_AGENT)
def list_builds():
    return listing(
        calc.all_of(db.hospitality_builds),
        hospitality_build_json,
        ("event_id", "build_state", "zone_code"),
    )


@bp.route("/hospitality-builds/<build_id>/approve", methods=["POST"])
@guard(FINANCE_CONTROLLER)
def approve_build(build_id):
    build = get_build(build_id)
    body()
    event = get_event(build["event_id"])
    if event["status"] not in calc.LIVE_EVENT_STATUSES:
        fail(ERR_INVALID_EVENT_STATE, "Spend cannot be approved against this fixture.")
    if build["build_state"] != "PLANNED":
        fail(ERR_INVALID_BUILD_STATE, "Only a planned build can be approved.")

    build["build_state"] = "APPROVED"
    build["approved_by_user_id"] = g.user_id
    build["total_cost_cents"] = (
        build["build_cost_cents"] + build["catering_cost_cents"] + build["staffing_cost_cents"]
    )
    touch(build)
    return object_response(hospitality_build_json(build))


@bp.route("/hospitality-builds/<build_id>/ready", methods=["POST"])
@guard(OPERATIONS_MANAGER)
def ready_build(build_id):
    build = get_build(build_id)
    body()
    if build["build_state"] != "APPROVED":
        fail(ERR_INVALID_BUILD_STATE, "Only an approved build can be declared ready.")
    if build["staff_count"] < 1 or build["catering_covers"] < 1:
        fail(
            ERR_INVALID_BUILD_STATE,
            "A build that is neither staffed nor catered cannot be declared ready.",
        )

    build["build_state"] = "READY"
    touch(build)
    return object_response(hospitality_build_json(build))


# --- OnSiteHost -------------------------------------------------------------


@bp.route("/on-site-hosts", methods=["POST"])
@guard(OPERATIONS_MANAGER)
def create_host():
    data = body()
    full_name = req_string(data, "full_name")
    languages = req_string_array(data, "languages")
    max_concurrent_bookings = opt_int(data, "max_concurrent_bookings", default=1, minimum=1)

    host = create_record(
        db.on_site_hosts,
        {
            "full_name": full_name,
            "languages": languages,
            "max_concurrent_bookings": max_concurrent_bookings,
            "active_assignment_count": 0,
        },
    )
    return object_response(on_site_host_json(host), 201)


@bp.route("/on-site-hosts/<host_id>", methods=["GET"])
@guard(OPERATIONS_MANAGER, CLIENT_SERVICE_AGENT)
def read_host(host_id):
    return object_response(on_site_host_json(get_host(host_id)))


# --- HostAssignment ---------------------------------------------------------


def _capacity_exceeded(host, shift_start, shift_end):
    """Aggregate half-open capacity test (PRD 2.10)."""
    live = []
    for assignment in calc.assignments_of_host(host["id"]):
        if assignment["assignment_state"] != "ASSIGNED":
            continue
        if assignment["shift_start"] < shift_end and assignment["shift_end"] > shift_start:
            live.append(assignment)
    if not live:
        return 1 > host["max_concurrent_bookings"]

    instants = [shift_start]
    for assignment in live:
        moment = assignment["shift_start"]
        if shift_start < moment < shift_end:
            instants.append(moment)
    for moment in instants:
        overlapping = 0
        for assignment in live:
            if assignment["shift_start"] <= moment < assignment["shift_end"]:
                overlapping += 1
        if overlapping + 1 > host["max_concurrent_bookings"]:
            return True
    return False


@bp.route("/host-assignments", methods=["POST"])
@guard(CLIENT_SERVICE_AGENT, OPERATIONS_MANAGER)
def create_assignment():
    data = body()
    host_id = req_id(data, "on_site_host_id")
    booking_id = req_id(data, "booking_id")
    build_id = req_id(data, "hospitality_build_id")
    shift_start = req_datetime(data, "shift_start")
    shift_end = req_datetime(data, "shift_end")
    if shift_end <= shift_start:
        bad("Field `shift_end` must be strictly after `shift_start`.")

    booking = get_booking(booking_id)
    build = get_build(build_id)
    host = get_host(host_id)

    if booking["fulfillment_status"] not in ("ALLOCATED", "CREDENTIALED"):
        fail(ERR_INVALID_BOOKING_STATE, "Only a booking holding inventory can be hosted.")
    if build["build_state"] not in ("APPROVED", "READY"):
        fail(ERR_INVALID_BUILD_STATE, "This build cannot be staffed.")

    booking_event = calc.event_of_booking(booking)
    same_event = booking_event is not None and booking_event["id"] == build["event_id"]
    inside_window = (
        shift_start >= build["service_window_start"] and shift_end <= build["service_window_end"]
    )
    if not same_event or not inside_window:
        fail(
            ERR_ASSIGNMENT_SCOPE_MISMATCH,
            "The build must serve the booking's fixture and contain the whole shift.",
        )

    if _capacity_exceeded(host, shift_start, shift_end):
        fail(ERR_HOST_CAPACITY_EXCEEDED, "The host is already at capacity across that shift.")

    assignment = create_record(
        db.host_assignments,
        {
            "on_site_host_id": host_id,
            "booking_id": booking_id,
            "hospitality_build_id": build_id,
            "shift_start": shift_start,
            "shift_end": shift_end,
            "assignment_state": "ASSIGNED",
            "released_at": None,
        },
    )
    services.recompute_host(host)
    services.refresh_itinerary(booking)
    return object_response(host_assignment_json(assignment), 201)


@bp.route("/host-assignments/<assignment_id>", methods=["GET"])
@guard(OPERATIONS_MANAGER, CLIENT_SERVICE_AGENT)
def read_assignment(assignment_id):
    return object_response(host_assignment_json(get_assignment(assignment_id)))


@bp.route("/host-assignments", methods=["GET"])
@guard(OPERATIONS_MANAGER, CLIENT_SERVICE_AGENT)
def list_assignments():
    return listing(
        calc.all_of(db.host_assignments),
        host_assignment_json,
        ("on_site_host_id", "booking_id", "hospitality_build_id", "assignment_state"),
    )


@bp.route("/host-assignments/<assignment_id>/release", methods=["POST"])
@guard(OPERATIONS_MANAGER, CLIENT_SERVICE_AGENT)
def release_assignment(assignment_id):
    assignment = get_assignment(assignment_id)
    body()
    if assignment["assignment_state"] != "ASSIGNED":
        fail(ERR_INVALID_ASSIGNMENT_STATE, "This assignment has already been stood down.")

    assignment["assignment_state"] = "RELEASED"
    assignment["released_at"] = logical_now()
    touch(assignment)

    host = db.on_site_hosts.get(assignment["on_site_host_id"])
    if host is not None:
        services.recompute_host(host)
    booking = db.bookings.get(assignment["booking_id"])
    if booking is not None:
        services.refresh_itinerary(booking)
    return object_response(host_assignment_json(assignment))
