"""Garage bay allocation: slot occupancy, release, and terminal lockdown."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_booking, approve_booking, make_garage_assignment, day_version,
    setup_open_day_with_block,
    create_garage_assignment_payload,
    TEST_USERS,
)

OPS = TEST_USERS["trackops_headers"]


def _two_approved_bookings():
    env = setup_open_day_with_block("2026-09-07")
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    first = make_booking(tid, tdid, rbid, "orgA16")
    second = make_booking(tid, tdid, rbid, "orgB16")
    approve_booking(tid, tdid, rbid, first["id"])
    approve_booking(tid, tdid, rbid, second["id"])
    return env, first, second


def test_duplicate_active_bay_rejected(api):
    """PRD §3.8: "The guards fire in order: the version check first, rejecting
    a stale view with `ERR_STALE_VERSION` (412) since a prior assignment may
    have consumed the last free bay since the client read capacity; then day
    liveness with `ERR_TRACK_DAY_NOT_LIVE` (409); then posture with
    `ERR_TRACK_SUSPENDED` (409); then occupancy, where a bay already `ACTIVE`
    on the day rejects with `ERR_BAY_OCCUPIED` (409)."

    Design: Difficulty/resource_temporal_overlap/garage_bay_slot_occupancy_atomic
    """
    env, first, second = _two_approved_bookings()
    tid, tdid = env["track"]["id"], env["day"]["id"]
    garage = make_garage_assignment(tid, tdid, first["id"], bay_number=2,
                                    power_hookups=1)
    assert garage["status"] == "ACTIVE"
    # The second assignment carries the day's current version, so only the
    # occupancy rule can reject it.
    payload = create_garage_assignment_payload(
        booking_id=second["id"], bay_number=2, power_hookups=0,
        water_hookup=False, expected_track_day_version=day_version(tid, tdid))
    resp = api.create_garage_assignment(tid, tdid, payload, OPS)
    validate_error(resp, ApiErrorId.ERR_BAY_OCCUPIED)


def test_released_bay_can_be_reassigned(api):
    """PRD §3.8: "Releasing a bay — explicitly by `TrackOps`, or implicitly
    when the booking is cancelled — moves the assignment from `ACTIVE` to the
    terminal `RELEASED` state and frees the bay for reassignment."

    Design: Difficulty/resource_temporal_overlap/garage_bay_slot_occupancy_atomic
    """
    env, first, second = _two_approved_bookings()
    tid, tdid = env["track"]["id"], env["day"]["id"]
    garage = make_garage_assignment(tid, tdid, first["id"], bay_number=2,
                                    power_hookups=1)
    payload = create_garage_assignment_payload(
        booking_id=second["id"], bay_number=2, power_hookups=0,
        water_hookup=False, expected_track_day_version=day_version(tid, tdid))
    validate_error(api.create_garage_assignment(tid, tdid, payload, OPS),
                   ApiErrorId.ERR_BAY_OCCUPIED)
    released = validate_success(api.release_garage_assignment(
        tid, tdid, garage["id"], OPS))
    assert released["status"] == "RELEASED"
    reassigned = make_garage_assignment(tid, tdid, second["id"], bay_number=2,
                                        power_hookups=0)
    assert reassigned["status"] == "ACTIVE", "release frees the bay"


def test_garage_release_is_terminal(api):
    """PRD §3.8: "Releasing a bay — explicitly by `TrackOps`, or implicitly
    when the booking is cancelled — moves the assignment from `ACTIVE` to the
    terminal `RELEASED` state and frees the bay for reassignment." PRD §2.9:
    "State-machine preconditions — the resource stands in a state that permits
    the requested transition, on every state-transition endpoint:
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/garage_release_is_terminal
    """
    env, first, _second = _two_approved_bookings()
    tid, tdid = env["track"]["id"], env["day"]["id"]
    garage = make_garage_assignment(tid, tdid, first["id"], bay_number=1,
                                    power_hookups=1)
    validate_success(api.release_garage_assignment(tid, tdid, garage["id"], OPS))
    resp = api.release_garage_assignment(tid, tdid, garage["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
