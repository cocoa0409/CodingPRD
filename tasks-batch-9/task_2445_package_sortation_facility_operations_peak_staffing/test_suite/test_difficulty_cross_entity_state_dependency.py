"""Cross-entity state dependencies: a transition that is legal for the resource
named in the request but blocked by the live state of a different entity it
references.

Three distinct entity pairs are exercised here — (TrailerAppointment, DockDoor),
(StaffAssignment, Worker) and (PackageException, SortChute) — and in each case
the blocking entity is moved back so the identical call succeeds.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_DOOR_OUT_OF_SERVICE,
    ERR_NO_ELIGIBLE_CHUTE,
    ERR_WORKER_NOT_CLEARED,
)
from test_helpers.constants import CLOCK_STARTUP_UTC, REQUIRED_TRAINING_SESSIONS
from test_helpers.fixtures import parse_instant
from test_helpers.test_users import (
    INBOUND_COORDINATOR_HEADERS,
    LABOR_PLANNER_HEADERS,
    SORT_SUPERVISOR_HEADERS,
    make_worker_headers,
)


# ─── (TrailerAppointment, DockDoor) ───────────────────

def _arrived_appointment_whose_door_went_out_of_service(world, facility):
    """An appointment sitting in a perfectly legal `ARRIVED`, whose inbound door
    was taken out of service after the booking was made."""
    center_id = facility["center"]["id"]
    door_id = facility["inbound_door"]["id"]
    appointment = world.arrived_appointment(
        center_id, door_id, manifest_package_count=1500
    )
    assert appointment["status"] == "ARRIVED"
    assert appointment["unload_sequence_rank"] == 1
    door = world.take_door_out_of_service(door_id)
    assert door["status"] == "OUT_OF_SERVICE"
    return appointment


def test_start_unload_rejected_while_the_booked_door_is_out_of_service(
    world, api, facility
):
    """PRD §3.1: "Taking a door out of service does not disturb the windows of appointments already booked on it, but it does block work: while the door is `OUT_OF_SERVICE`, starting an unload on an appointment booked to it is refused with `ERR_DOOR_OUT_OF_SERVICE`."

    Design: Difficulty/cross_entity_state_dependency/start_unload_blocked_by_out_of_service_door
    """
    appointment = _arrived_appointment_whose_door_went_out_of_service(world, facility)

    response = api.start_unload(appointment["id"], INBOUND_COORDINATOR_HEADERS)
    validate_error(response, ERR_DOOR_OUT_OF_SERVICE)

    untouched = world.appointment(appointment["id"])
    assert untouched["status"] == "ARRIVED"
    assert untouched["unload_sequence_rank"] == 1
    assert untouched["unloaded_at"] is None
    assert untouched["window_start"] == appointment["window_start"]
    assert untouched["window_end"] == appointment["window_end"]
    assert world.center(facility["center"]["id"])["ops_posture"] == "OPEN"


def test_start_unload_succeeds_once_the_door_is_returned_to_service(
    world, api, facility
):
    """PRD §3.3: "That requires the appointment to still be `ARRIVED`, the door named by `door_id` to still be `ACTIVE` (otherwise `ERR_DOOR_OUT_OF_SERVICE`), and the center not to be frozen."

    Design: Difficulty/cross_entity_state_dependency/start_unload_blocked_by_out_of_service_door
    """
    appointment = _arrived_appointment_whose_door_went_out_of_service(world, facility)
    validate_error(
        api.start_unload(appointment["id"], INBOUND_COORDINATOR_HEADERS),
        ERR_DOOR_OUT_OF_SERVICE,
    )

    door = world.return_door_to_service(facility["inbound_door"]["id"])
    assert door["status"] == "ACTIVE"

    started = validate_success(
        api.start_unload(appointment["id"], INBOUND_COORDINATOR_HEADERS)
    )
    assert started["status"] == "UNLOADING"

    reread = world.appointment(appointment["id"])
    assert reread["status"] == "UNLOADING"
    assert reread["unload_sequence_rank"] is None
    assert world.center(facility["center"]["id"])["ops_posture"] == "OPEN"


# ─── (StaffAssignment, Worker) ────────────────────────

def _cleared_worker_assigned_to_a_line(world, facility):
    """A `CLEARED` worker legally placed on a line of an approved plan: enough to
    be scheduled, not yet enough to clock in."""
    center_id = facility["center"]["id"]
    plan = world.create_approved_plan(center_id)
    assert plan["status"] == "APPROVED"
    worker = world.create_cleared_worker(center_id)
    assert worker["status"] == "CLEARED"
    assert worker["training_sessions_completed"] == 0
    assignment = world.create_assignment(
        plan["id"], worker["id"], facility["chute"]["id"]
    )
    assert assignment["status"] == "ASSIGNED"
    return worker, assignment


def test_check_in_rejected_while_the_assigned_worker_is_only_cleared(
    world, api, facility
):
    """PRD §3.7: "It requires that the caller's `X-User-ID` equal the assignment's `worker_id` (`ERR_NOT_ASSIGNMENT_OWNER`), that the worker's own `status` be `CERTIFIED` — merely `CLEARED` is enough to be scheduled but not enough to work a line, and the difference is refused with `ERR_WORKER_NOT_CLEARED` — that the owning plan still be `APPROVED` or `AT_RISK` (`ERR_INVALID_SHIFT_PLAN_STATE`), and that the center not be `FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/check_in_blocked_until_worker_is_certified
    """
    worker, assignment = _cleared_worker_assigned_to_a_line(world, facility)

    response = api.check_in(assignment["id"], make_worker_headers(worker["id"]))
    validate_error(response, ERR_WORKER_NOT_CLEARED)

    assert world.worker(worker["id"])["status"] == "CLEARED"
    untouched = world.staff_assignment(assignment["id"])
    assert untouched["status"] == "ASSIGNED"
    assert untouched["checked_in_at"] is None
    assert untouched["checked_out_at"] is None


def test_certification_rejected_before_two_training_sessions_are_delivered(
    world, api, facility
):
    """PRD §3.6: "`CERTIFIED` moves a worker `CLEARED → CERTIFIED`, but only once training has actually been delivered: `training_sessions_completed` must be at least 2, and a premature certification is refused with `ERR_WORKER_NOT_CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/check_in_blocked_until_worker_is_certified
    """
    worker, _assignment = _cleared_worker_assigned_to_a_line(world, facility)

    premature = api.create_onboarding_event(
        worker["id"], f.onboarding_event_payload("CERTIFIED"), LABOR_PLANNER_HEADERS
    )
    validate_error(premature, ERR_WORKER_NOT_CLEARED)

    still_cleared = world.worker(worker["id"])
    assert still_cleared["status"] == "CLEARED"
    assert still_cleared["training_sessions_completed"] == 0

    for _ in range(REQUIRED_TRAINING_SESSIONS):
        world.record_event(worker["id"], "TRAINING_SESSION_COMPLETED")
    trained = world.worker(worker["id"])
    assert trained["training_sessions_completed"] == REQUIRED_TRAINING_SESSIONS
    assert trained["status"] == "CLEARED"


def test_check_in_succeeds_on_the_same_assignment_once_the_worker_is_certified(
    world, api, facility
):
    """PRD §3.7: "Clocking in advances the assignment `ASSIGNED → CHECKED_IN` and stamps `checked_in_at` with the logical clock."

    Design: Difficulty/cross_entity_state_dependency/check_in_blocked_until_worker_is_certified
    """
    worker, assignment = _cleared_worker_assigned_to_a_line(world, facility)
    validate_error(
        api.check_in(assignment["id"], make_worker_headers(worker["id"])),
        ERR_WORKER_NOT_CLEARED,
    )

    for _ in range(REQUIRED_TRAINING_SESSIONS):
        world.record_event(worker["id"], "TRAINING_SESSION_COMPLETED")
    certified = world.record_event(worker["id"], "CERTIFIED")
    assert certified["status"] == "CERTIFIED"

    checked_in = validate_success(
        api.check_in(assignment["id"], make_worker_headers(worker["id"]))
    )
    assert checked_in["status"] == "CHECKED_IN"
    assert parse_instant(checked_in["checked_in_at"]) == parse_instant(
        CLOCK_STARTUP_UTC
    )
    assert world.staff_assignment(assignment["id"])["status"] == "CHECKED_IN"


# ─── (PackageException, SortChute) ────────────────────

def _open_missort_while_the_target_lane_chute_is_congested(world, facility):
    """Two destinations mapped onto one chute, packages sorted into the first, a
    mis-sort batch pulled back out of it, and the chute jammed into `CONGESTED`
    so every mapping on it is `SUSPENDED`."""
    center_id = facility["center"]["id"]
    chute_id = facility["chute"]["id"]
    lane_west = facility["lane"]
    lane_east = world.create_lane(
        center_id, forecast_hourly_volume=200, service_class="EXPRESS"
    )
    east_mapping = world.map_lane_to_chute(chute_id, lane_east["id"])

    world.create_loading_load(
        center_id,
        facility["inbound_door"]["id"],
        facility["outbound_door"]["id"],
        lane_west["id"],
        small_count=100,
    )
    appointment = world.unloading_appointment(
        center_id, facility["inbound_door"]["id"], manifest_package_count=500
    )
    world.jam_hold(appointment["id"], chute_id, jam_reason="SECONDARY_CHUTE_JAM")

    exception = world.create_exception(
        center_id,
        exception_type="MISSORT",
        package_count=40,
        from_destination_lane_id=lane_west["id"],
    )
    assert exception["status"] == "OPEN"
    assert world.chute(chute_id)["status"] == "CONGESTED"
    assert world.assignment(east_mapping["id"])["status"] == "SUSPENDED"
    assert world.center(center_id)["ops_posture"] == "RESTRICTED"
    return {
        "appointment": appointment,
        "exception": exception,
        "lane_east": lane_east,
        "east_mapping": east_mapping,
    }


def test_reroute_rejected_while_the_target_lane_only_chute_is_congested(
    world, api, facility
):
    """PRD §3.8: "A chute assignment qualifies when its `destination_lane_id` is the target lane, its `status` is `ACTIVE`, its window covers the logical clock with the usual half-open convention (`window_start` at or before the clock and `window_end` strictly after it), and the chute it occupies has `status` `ACTIVE` — a `CONGESTED` chute is not eligible, because a jammed line cannot absorb re-laned packages."

    Design: Difficulty/cross_entity_state_dependency/reroute_blocked_while_target_lane_chute_is_congested
    """
    built = _open_missort_while_the_target_lane_chute_is_congested(world, facility)
    center_id = facility["center"]["id"]

    response = api.resolve_package_exception(
        built["exception"]["id"],
        f.resolve_exception_payload(
            "REROUTE", to_destination_lane_id=built["lane_east"]["id"]
        ),
        SORT_SUPERVISOR_HEADERS,
    )
    validate_error(response, ERR_NO_ELIGIBLE_CHUTE)

    still_open = world.exception(built["exception"]["id"])
    assert still_open["status"] == "OPEN"
    assert still_open["resolution"] is None
    assert still_open["resolved_via_chute_id"] is None
    assert still_open["resolved_at"] is None

    center = world.center(center_id)
    assert center["exception_hold_count"] == 40
    assert center["missort_corrected_count"] == 0
    assert world.lane(built["lane_east"]["id"])["sorted_package_count"] == 0
    world.assert_ledgers(center_id)


def test_reroute_succeeds_after_the_resume_returns_the_chute_to_active(
    world, api, facility
):
    """PRD §3.8: "A reroute carries three additional requirements: `to_destination_lane_id` must be present and name a lane whose `status` is `ACTIVE`; that lane must have at least one chute assignment on record in any status, otherwise `ERR_LANE_NOT_ASSIGNED_TO_CHUTE`; and the pool of chutes actually able to take the packages right now must be non-empty, otherwise `ERR_NO_ELIGIBLE_CHUTE`."

    Design: Difficulty/cross_entity_state_dependency/reroute_blocked_while_target_lane_chute_is_congested
    """
    built = _open_missort_while_the_target_lane_chute_is_congested(world, facility)
    center_id = facility["center"]["id"]
    chute_id = facility["chute"]["id"]
    validate_error(
        api.resolve_package_exception(
            built["exception"]["id"],
            f.resolve_exception_payload(
                "REROUTE", to_destination_lane_id=built["lane_east"]["id"]
            ),
            SORT_SUPERVISOR_HEADERS,
        ),
        ERR_NO_ELIGIBLE_CHUTE,
    )

    resumed = world.resume_unload(built["appointment"]["id"], chute_id)
    assert resumed["status"] == "UNLOADING"
    assert world.chute(chute_id)["status"] == "ACTIVE"
    revived = world.assignment(built["east_mapping"]["id"])
    assert revived["status"] == "ACTIVE"
    assert revived["suspended_reason"] is None

    resolved = validate_success(
        api.resolve_package_exception(
            built["exception"]["id"],
            f.resolve_exception_payload(
                "REROUTE", to_destination_lane_id=built["lane_east"]["id"]
            ),
            SORT_SUPERVISOR_HEADERS,
        )
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "REROUTE"
    assert resolved["resolved_via_chute_id"] == chute_id

    center = world.center(center_id)
    assert center["exception_hold_count"] == 0
    assert center["missort_corrected_count"] == 40
    assert world.lane(built["lane_east"]["id"])["sorted_package_count"] == 40
    world.assert_ledgers(center_id)
