"""Reservation overlap regimes: press windows are half-open (adjacency free)
while machine blocks carry a four-hour cool-down buffer (PRD §2.9)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_machine_reservation,
    assert_press_reservation,
    create_machine_reservation_payload,
    create_press_reservation_payload,
    get_success_data,
    setup_booked_job,
    validate_error,
)

PM = TEST_USERS["project_manager_headers"]


def _booked_job():
    return setup_booked_job(company_name="Press Co", part_number="PN-1101")


def test_press_window_starting_at_existing_end_is_allowed(api):
    """PRD §2.9: "A new window conflicts with an existing `RESERVED` window on
    the same press unless the new window ends at or before the existing
    window's start, or starts at or after the existing window's end; a
    conflicting booking is rejected with `ERR_PRESS_DOUBLE_BOOKED`.
    Back-to-back adjacency is therefore allowed: a window starting exactly
    when another ends does not conflict."

    Design: Difficulty/resource_temporal_overlap/press_half_open_adjacency_vs_overlap
    """
    ctx = _booked_job()
    job_id = ctx["job"]["id"]
    first = get_success_data(api_client.create_press_reservation(
        create_press_reservation_payload(
            job_id, press_id="PRESS_500T",
            start_time="2026-08-10T08:00:00Z", end_time="2026-08-10T12:00:00Z",
        ), PM))
    assert_press_reservation(first)

    adjacent = get_success_data(api_client.create_press_reservation(
        create_press_reservation_payload(
            job_id, press_id="PRESS_500T",
            start_time="2026-08-10T12:00:00Z", end_time="2026-08-10T16:00:00Z",
        ), PM))
    assert_press_reservation(adjacent)
    assert adjacent["status"] == "RESERVED", (
        "half-open semantics: start == existing end must not conflict"
    )


def test_press_window_overlapping_existing_is_rejected(api):
    """PRD §2.9: "A new window conflicts with an existing `RESERVED` window on
    the same press unless the new window ends at or before the existing
    window's start, or starts at or after the existing window's end; a
    conflicting booking is rejected with `ERR_PRESS_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/press_half_open_adjacency_vs_overlap
    """
    ctx = _booked_job()
    job_id = ctx["job"]["id"]
    existing = get_success_data(api_client.create_press_reservation(
        create_press_reservation_payload(
            job_id, press_id="PRESS_500T",
            start_time="2026-08-10T08:00:00Z", end_time="2026-08-10T12:00:00Z",
        ), PM))

    res = api_client.create_press_reservation(
        create_press_reservation_payload(
            job_id, press_id="PRESS_500T",
            start_time="2026-08-10T11:00:00Z", end_time="2026-08-10T13:00:00Z",
        ), PM)
    error = validate_error(res, ApiErrorId.ERR_PRESS_DOUBLE_BOOKED)
    assert error["error_id"] == "ERR_PRESS_DOUBLE_BOOKED"
    assert res.status_code == 409

    untouched = get_success_data(api_client.get_press_reservation(existing["id"], PM))
    assert untouched["status"] == "RESERVED"


def test_machine_block_back_to_back_conflicts_inside_cooldown(api):
    """PRD §2.9: "A new block conflicts with an existing `RESERVED` block on
    the same machine unless the new block starts at or after the existing
    block's end plus four hours, or the existing block starts at or after the
    new block's end plus four hours; conflicts are rejected with
    `ERR_MACHINE_WINDOW_CONFLICT`. Consequently a block starting exactly when
    another block ends still conflicts — it falls inside the cool-down —
    while a block starting exactly four hours after that end is allowed."

    Design: Difficulty/resource_temporal_overlap/machine_cooldown_buffer_blocks_back_to_back
    """
    ctx = _booked_job()
    job_id = ctx["job"]["id"]
    existing = get_success_data(api_client.create_machine_reservation(
        create_machine_reservation_payload(
            job_id, machine_id="CNC_1",
            start_time="2026-08-03T08:00:00Z", end_time="2026-08-03T12:00:00Z",
        ), PM))
    assert_machine_reservation(existing)

    res = api_client.create_machine_reservation(
        create_machine_reservation_payload(
            job_id, machine_id="CNC_1",
            start_time="2026-08-03T12:00:00Z", end_time="2026-08-03T16:00:00Z",
        ), PM)
    error = validate_error(res, ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT)
    assert error["error_id"] == "ERR_MACHINE_WINDOW_CONFLICT"
    assert res.status_code == 409

    untouched = get_success_data(api_client.get_machine_reservation(existing["id"], PM))
    assert untouched["status"] == "RESERVED"


def test_machine_block_starting_exactly_at_buffer_end_is_allowed(api):
    """PRD §2.9: "Consequently a block starting exactly when another block
    ends still conflicts — it falls inside the cool-down — while a block
    starting exactly four hours after that end is allowed."
    PRD §2.9: "`duration_hours` is the block's length in hours, computed to a
    precision of one hundredth of an hour."

    Design: Difficulty/resource_temporal_overlap/machine_cooldown_buffer_blocks_back_to_back
    """
    ctx = _booked_job()
    job_id = ctx["job"]["id"]
    existing = get_success_data(api_client.create_machine_reservation(
        create_machine_reservation_payload(
            job_id, machine_id="CNC_1",
            start_time="2026-08-03T08:00:00Z", end_time="2026-08-03T12:00:00Z",
        ), PM))

    after_buffer = get_success_data(api_client.create_machine_reservation(
        create_machine_reservation_payload(
            job_id, machine_id="CNC_1",
            start_time="2026-08-03T16:00:00Z", end_time="2026-08-03T20:00:00Z",
        ), PM))
    assert_machine_reservation(after_buffer)
    assert after_buffer["status"] == "RESERVED", (
        "start exactly at existing end + 4h cool-down must be allowed"
    )
    assert after_buffer["duration_hours"] == pytest.approx(4.0, abs=0.001)

    untouched = get_success_data(api_client.get_machine_reservation(existing["id"], PM))
    assert untouched["status"] == "RESERVED"
