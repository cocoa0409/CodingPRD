"""Group-seat conservation on cancel and optimistic-concurrency (stale version)
rejections on the two capacity-bearing writes.

Queue A (Difficulty): compensating_invariant (group seats).
Queue B (Corner): cross_cutting (OCC on enrollment and group class).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_active_enrollment, add_active_enrollment,
)
import test_helpers as th

COORD = TEST_USERS["coordinator_headers"]


# --- ci_group_seats_conserved_on_cancel ---
def test_cancel_group_session_releases_seat(api):
    """PRD §3.6: "if the session is a group session it decrements the class's
    `seats_taken` by 1, freeing the seat for another patient."

    Reserving a seat raises seats_taken to 1; cancelling the group session
    restores seats_taken to 0.

    Design: Difficulty/compensating_invariant/ci_group_seats_conserved_on_cancel
    """
    ctx = setup_active_enrollment(api)
    gc = th.make_group_class_ok(api, ctx, room_id="ROOM-2",
                                scheduled_start="2026-05-22T13:00:00Z", scheduled_end="2026-05-22T14:00:00Z",
                                capacity=3, topic="Meal Planning")
    seat = th.reserve_seat_ok(api, ctx, gc["id"], ctx["enrollment_id"])
    th.cancel(api, ctx, seat["id"])
    updated = th.get_group_class(api, gc["id"])
    assert updated["seats_taken"] == 0, \
        f"seats_taken must return to 0 after cancel, got {updated['seats_taken']}"


def test_group_seat_count_conserved_across_reserve_and_cancel(api):
    """PRD §3.5: "A class's `seats_taken` is defined as the count of group sessions
    referencing that class whose `encounter_status` is `SCHEDULED`, `CHECKED_IN`,
    `COMPLETED`, or `NO_SHOW`; a `CANCELLED` group session releases its seat and
    drops out of this count."

    seats_taken is exactly 1 while the reservation stands and exactly 0 once the
    group session is cancelled — a conserved quantity.

    Design: Difficulty/compensating_invariant/ci_group_seats_conserved_on_cancel
    """
    ctx = setup_active_enrollment(api)
    gc = th.make_group_class_ok(api, ctx, room_id="ROOM-2",
                                scheduled_start="2026-05-22T13:00:00Z", scheduled_end="2026-05-22T14:00:00Z",
                                capacity=3, topic="Meal Planning")
    seat = th.reserve_seat_ok(api, ctx, gc["id"], ctx["enrollment_id"])
    reserved = th.get_group_class(api, gc["id"])
    assert reserved["seats_taken"] == 1, f"seats_taken must be 1 while reserved, got {reserved['seats_taken']}"
    th.cancel(api, ctx, seat["id"])
    released = th.get_group_class(api, gc["id"])
    assert released["seats_taken"] == 0, f"seats_taken must be 0 after cancel, got {released['seats_taken']}"


# --- Queue B: occ_session_schedule_stale_enrollment_version ---
def test_schedule_with_stale_enrollment_version_rejected(api):
    """PRD §2.6: "If `expected_enrollment_version` does not equal the enrollment's
    current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)
    and the pool is left untouched."

    The first schedule advances the enrollment version; a second create still
    carrying the pre-first-schedule version is stale.

    Design: Corner/cross_cutting/occ_session_schedule_stale_enrollment_version
    """
    ctx = setup_active_enrollment(api)
    stale_version = ctx["enrollment_version"]
    th.schedule_individual_session_ok(api, ctx, "2026-05-29T09:00:00Z", "2026-05-29T10:00:00Z",
                                      expected_version=stale_version)
    resp = th.schedule_individual_session(api, ctx, "2026-05-29T11:00:00Z", "2026-05-29T12:00:00Z",
                                          expected_version=stale_version)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# --- Queue B: occ_group_seat_stale_class_version ---
def test_reserve_seat_with_stale_class_version_rejected(api):
    """PRD §2.6: "If `expected_group_class_version` does not equal the class's
    current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)
    and no seat is consumed."

    The first reservation advances the class version; a second reservation still
    carrying the pre-first-reservation version is stale.

    Design: Corner/cross_cutting/occ_group_seat_stale_class_version
    """
    ctx = setup_active_enrollment(api)
    other = add_active_enrollment(api, ctx)
    gc = th.make_group_class_ok(api, ctx, room_id="ROOM-8",
                                scheduled_start="2026-05-30T13:00:00Z", scheduled_end="2026-05-30T14:00:00Z",
                                capacity=3, topic="OCC Class")
    stale_version = gc["version"]
    th.reserve_seat_ok(api, ctx, gc["id"], ctx["enrollment_id"], expected_group_class_version=stale_version)
    resp = th.reserve_seat(api, ctx, gc["id"], other["id"], expected_group_class_version=stale_version)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
