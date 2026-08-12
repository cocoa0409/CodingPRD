"""Resource temporal overlap: half-open wave windows and crew bucket
capacity (PRD 3.3, 3.4)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, assign_contractor, book_appointment,
    create_installed_account, create_program, create_wave, create_work_order,
    get_success_data, send_and_deliver_notification,
    setup_program_wave_contractor, validate_error, validate_success,
)

PM = TEST_USERS["program_manager_headers"]
SCHED = TEST_USERS["scheduler_headers"]


def test_adjacent_wave_window_allowed(api):
    """PRD §3.3: "requires the wave's half-open window not to intersect any
    other wave of the same program in `OPEN` or `LOCKED` status — adjacency,
    where one wave's `window_end` equals the other's `window_start`, is
    permitted — failing with `ERR_WAVE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/wave_window_halfopen_overlap
    """
    prog = create_program()
    wave1 = create_wave(prog["id"], wave_number=1,
                        window_start="2026-05-01T00:00:00Z",
                        window_end="2026-06-01T00:00:00Z")
    assert wave1["status"] == "OPEN"
    wave2 = create_wave(prog["id"], open_it=False, wave_number=2,
                        window_start="2026-06-01T00:00:00Z",
                        window_end="2026-07-01T00:00:00Z")
    resp = api.open_wave(wave2["id"], PM)
    data = validate_success(resp)
    assert data["status"] == "OPEN"


def test_intersecting_wave_window_rejected(api):
    """PRD §3.3: "requires the wave's half-open window not to intersect any
    other wave of the same program in `OPEN` or `LOCKED` status — adjacency,
    where one wave's `window_end` equals the other's `window_start`, is
    permitted — failing with `ERR_WAVE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/wave_window_halfopen_overlap
    """
    prog = create_program()
    create_wave(prog["id"], wave_number=1,
                window_start="2026-05-01T00:00:00Z",
                window_end="2026-06-01T00:00:00Z")
    wave3 = create_wave(prog["id"], open_it=False, wave_number=3,
                        window_start="2026-05-15T00:00:00Z",
                        window_end="2026-06-15T00:00:00Z")
    resp = api.open_wave(wave3["id"], PM)
    validate_error(resp, ApiErrorId.ERR_WAVE_WINDOW_OVERLAP.value)
    w3 = get_success_data(api_client.get_wave(wave3["id"], PM))
    assert w3["status"] == "DRAFT"


def _capacity_one_with_filler():
    """Contractor capacity 1; filler work order already BOOKED
    2026-05-06 AM; a second notified work order ready to book."""
    prog, wave, contr = setup_program_wave_contractor(
        contractor_overrides={"crew_capacity_per_window": 1})
    acctF, _ = create_installed_account()
    woF = create_work_order(wave["id"], acctF["id"])
    assign_contractor(woF["id"], contr["id"])
    send_and_deliver_notification(woF["id"], delivered_at="2026-04-28T10:00:00Z")
    book_appointment(woF["id"], slot_date="2026-05-06", window="AM")
    acctG, _ = create_installed_account()
    woG = create_work_order(wave["id"], acctG["id"])
    assign_contractor(woG["id"], contr["id"])
    send_and_deliver_notification(woG["id"], delivered_at="2026-04-28T10:00:00Z")
    woG = get_success_data(api_client.get_work_order(woG["id"], SCHED))
    return prog, wave, contr, woG


def test_second_booking_same_bucket_rejected(api):
    """PRD §3.4: "its crew bucket — the count of that contractor's
    appointments in `BOOKED` or `CONFIRMED` status on the same (`slot_date`,
    `window`) — must be strictly below `crew_capacity_per_window`
    (`ERR_CREW_WINDOW_FULL`)."

    Design: Difficulty/resource_temporal_overlap/crew_window_bucket_capacity
    """
    prog, wave, contr, woG = _capacity_one_with_filler()
    resp = api.create_appointment({
        "work_order_id": woG["id"], "slot_date": "2026-05-06", "window": "AM",
        "expected_work_order_version": woG["version"]}, SCHED)
    validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_FULL.value)
    after = get_success_data(api_client.get_work_order(woG["id"], SCHED))
    assert after["lifecycle_status"] == "NOTIFIED"


def test_same_date_other_window_booked(api):
    """PRD §3.4: "its crew bucket — the count of that contractor's
    appointments in `BOOKED` or `CONFIRMED` status on the same (`slot_date`,
    `window`) — must be strictly below `crew_capacity_per_window`
    (`ERR_CREW_WINDOW_FULL`)."

    Design: Difficulty/resource_temporal_overlap/crew_window_bucket_capacity
    """
    prog, wave, contr, woG = _capacity_one_with_filler()
    # Same date, PM window: the bucket key includes the window, so it is free.
    resp = api.create_appointment({
        "work_order_id": woG["id"], "slot_date": "2026-05-06", "window": "PM",
        "expected_work_order_version": woG["version"]}, SCHED)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "BOOKED"
    assert data["window"] == "PM"
    after = get_success_data(api_client.get_work_order(woG["id"], SCHED))
    assert after["lifecycle_status"] == "SCHEDULED"
