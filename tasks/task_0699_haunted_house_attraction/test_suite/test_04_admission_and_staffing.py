"""Admission gating: entry windows, scare-zone staffing, waiver sufficiency, and
actor shift-window check-in."""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    setup_admission_ready, setup_venue_attraction_slot,
    create_venue, create_attraction, create_pricing_rule, create_time_slot,
    create_staffed_zone, create_paid_reservation, set_clock,
    create_scare_zone_payload, create_actor_shift_payload,
    TEST_USERS,
)

BOX = TEST_USERS["box_office_headers"]
OPS = TEST_USERS["ops_headers"]
ACTOR = TEST_USERS["actor_headers"]


def test_admit_rejected_when_scare_zone_understaffed(api):
    """PRD 3.7: "Every scare zone of each ticketed attraction must be STAFFED, or
    admission is rejected with ERR_ZONE_UNDERSTAFFED."

    A RESERVED+PAID reservation inside its window cannot be admitted while the
    attraction's only scare zone is UNDERSTAFFED (no actor checked in); admission is
    rejected ERR_ZONE_UNDERSTAFFED and the reservation stays RESERVED.

    Design: Difficulty/cross_entity_state_dependency/cesd_admit_requires_scare_zone_staffed
    """
    set_clock("2026-10-31T18:30:00Z")
    venue = create_venue()
    attraction = create_attraction(venue["id"])
    create_pricing_rule(attraction["id"])
    # Zone requires 2 actors but none check in -> UNDERSTAFFED.
    get_success_data(
        api.create_scare_zone(attraction["id"], create_scare_zone_payload(min_actors=2), OPS)
    )
    slot = create_time_slot(attraction["id"])
    guest, reservation, ticket = create_paid_reservation(venue["id"], slot["id"])

    res = api.admit_reservation(reservation["id"], BOX)
    validate_error(res, "ERR_ZONE_UNDERSTAFFED")
    refreshed = validate_success(api.get_reservation(reservation["id"], BOX), 200)
    assert refreshed["entry_status"] == "RESERVED"


def test_admit_succeeds_when_zone_staffed_inside_window(api):
    """PRD 3.7: "Every scare zone of each ticketed attraction must be STAFFED, or
    admission is rejected with ERR_ZONE_UNDERSTAFFED. ... On success the reservation
    moves to ADMITTED".

    With the zone STAFFED and the clock inside the window, admission succeeds and the
    reservation moves to ADMITTED — the positive counterpart to the understaffed block.

    Design: Difficulty/cross_entity_state_dependency/cesd_admit_requires_scare_zone_staffed
    """
    venue, attraction, slot, zone, guest, reservation, ticket = setup_admission_ready()
    admitted = validate_success(api.admit_reservation(reservation["id"], BOX), 200)
    assert admitted["entry_status"] == "ADMITTED"


def test_admit_rejected_at_window_end_exclusive(api):
    """PRD 3.7: "It is permitted only while the logical clock lies within the
    reservation's entry window — at or after the earliest ticketed slot's
    window_start and strictly before the latest ticketed slot's window_end; outside
    that window admission is rejected with ERR_OUTSIDE_ENTRY_WINDOW."

    With the clock set exactly to slot.window_end (19:00:00Z), admission is rejected
    ERR_OUTSIDE_ENTRY_WINDOW because the upper bound is exclusive; the reservation
    stays RESERVED.

    Design: Difficulty/boundary_precision_check/bpc_entry_window_end_exclusive_on_admit
    """
    # Build at 18:30 (inside window) then advance the clock to window_end.
    venue, attraction, slot, zone, guest, reservation, ticket = setup_admission_ready(
        clock="2026-10-31T18:30:00Z"
    )
    set_clock("2026-10-31T19:00:00Z")

    res = api.admit_reservation(reservation["id"], BOX)
    validate_error(res, "ERR_OUTSIDE_ENTRY_WINDOW")
    refreshed = validate_success(api.get_reservation(reservation["id"], BOX), 200)
    assert refreshed["entry_status"] == "RESERVED"


def test_admit_succeeds_one_second_before_window_end(api):
    """PRD 3.7: "permitted only while the logical clock lies within the reservation's
    entry window — at or after the earliest ticketed slot's window_start and strictly
    before the latest ticketed slot's window_end".

    At 18:59:59Z — one second before the exclusive window_end 19:00:00Z — admission
    is inside the window and succeeds, pinning the boundary precisely.

    Design: Difficulty/boundary_precision_check/bpc_entry_window_end_exclusive_on_admit
    """
    venue, attraction, slot, zone, guest, reservation, ticket = setup_admission_ready(
        clock="2026-10-31T18:30:00Z"
    )
    set_clock("2026-10-31T18:59:59Z")
    admitted = validate_success(api.admit_reservation(reservation["id"], BOX), 200)
    assert admitted["entry_status"] == "ADMITTED"


def test_admit_rejected_when_waiver_required_but_absent(api):
    """PRD 3.3: "at admission the guest's standing waiver — when the attraction's
    requires_waiver is true — must be SIGNED, not expired, and carry a max_scare_level
    at least equal to the attraction's scare_level; otherwise admission is rejected
    with ERR_WAIVER_REQUIRED."

    A waiver-required attraction (scare_level 3) admitting a guest with no SIGNED
    waiver is rejected ERR_WAIVER_REQUIRED.

    Design: Corner/state_machines/admit_requires_waiver_when_attraction_requires_it
    """
    venue, attraction, slot, zone, guest, reservation, ticket = setup_admission_ready(
        clock="2026-10-31T18:30:00Z",
        att_overrides={"requires_waiver": True, "scare_level": 3},
        ticket_overrides={"max_scare_level": 5},
    )
    res = api.admit_reservation(reservation["id"], BOX)
    validate_error(res, "ERR_WAIVER_REQUIRED")


def test_check_in_rejected_before_shift_window(api):
    """PRD 3.8: "An actor checks in to their own SCHEDULED shift, permitted only while
    the logical clock lies within the shift window — at or after shift_start and
    strictly before shift_end; outside that window check-in is rejected with
    ERR_OUTSIDE_SHIFT_WINDOW."

    Check-in at clock 17:00 for a shift [18:00,19:00) is rejected
    ERR_OUTSIDE_SHIFT_WINDOW; the shift stays SCHEDULED.

    Design: Corner/state_machines/check_in_outside_shift_window_returns_outside_shift_window
    """
    set_clock("2026-10-31T17:00:00Z")
    venue = create_venue()
    attraction = create_attraction(venue["id"])
    zone = get_success_data(
        api.create_scare_zone(attraction["id"], create_scare_zone_payload(name="Z", min_actors=1), OPS)
    )
    shift = get_success_data(
        api.create_actor_shift(
            zone["id"],
            create_actor_shift_payload("actor-3", "2026-10-31T18:00:00Z", "2026-10-31T19:00:00Z"),
            OPS,
        )
    )
    res = api.check_in_shift(shift["id"], ACTOR)
    validate_error(res, "ERR_OUTSIDE_SHIFT_WINDOW")
    refreshed = validate_success(api.get_actor_shift(shift["id"], OPS), 200)
    assert refreshed["status"] == "SCHEDULED"
