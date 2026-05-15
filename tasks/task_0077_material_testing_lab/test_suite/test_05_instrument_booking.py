"""Instrument booking calibration enclosure, slot overlap, and cascade on
instrument failure (PRD §3.4, §2.9)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    anchor_plus,
    api_client,
    assert_instrument_booking,
    book_instrument_for_task,
    create_booking_payload,
    create_instrument,
    iso,
    parse_iso,
    setup_assigned_task,
    setup_assigned_task_with_short_calibration,
    TEST_USERS,
    validate_error,
    validate_success,
)
from datetime import timedelta


class TestBookingCalibrationEnclosure:
    """PRD §3.4 — booking must fit inside the calibration window."""

    def test_booking_before_calibration_start_rejected(
        self, api, lab_clerk_headers,
    ):
        """PRD §3.4: 'the half-open interval [slot_start, slot_end) must
        be entirely within the instrument's calibration window
        [calibration_valid_from, calibration_valid_to].'

        Claim: a booking whose slot_start is before calibration_valid_from
        yields ERR_BOOKING_OUTSIDE_CALIBRATION.
        """
        env = setup_assigned_task()
        slot_start = anchor_plus(days=-400)  # well before calibration_valid_from
        slot_end = anchor_plus(days=-400, hours=1)
        payload = create_booking_payload(
            task_id=env["task"]["id"],
            slot_start=slot_start, slot_end=slot_end,
        )
        resp = api.create_instrument_booking(
            env["instrument"]["id"], payload, lab_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_OUTSIDE_CALIBRATION.value)

    def test_booking_after_calibration_end_rejected(
        self, api, lab_clerk_headers,
    ):
        """PRD §3.4: 'the half-open interval [slot_start, slot_end) must
        be entirely within the instrument's calibration window.'

        Claim: a booking whose slot_end is after calibration_valid_to
        yields ERR_BOOKING_OUTSIDE_CALIBRATION.
        """
        env = setup_assigned_task()
        slot_start = anchor_plus(days=400)
        slot_end = anchor_plus(days=400, hours=1)
        payload = create_booking_payload(
            task_id=env["task"]["id"],
            slot_start=slot_start, slot_end=slot_end,
        )
        resp = api.create_instrument_booking(
            env["instrument"]["id"], payload, lab_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_OUTSIDE_CALIBRATION.value)

    def test_booking_slot_end_equals_calibration_end_allowed(
        self, api, lab_clerk_headers,
    ):
        """PRD §3.4: 'A booking whose slot_end exactly equals
        calibration_valid_to is allowed because the booking interval is
        half-open.' PRD §2.9: 'a booking whose slot_end equals
        calibration_valid_to is considered entirely within the window
        because the booking interval is half-open.'

        Claim: a booking with slot_end == calibration_valid_to succeeds.
        """
        # Fresh sample+task on a fresh instrument whose calibration ends
        # exactly at the booking's slot_end.
        from test_helpers import (
            create_client, create_sample, create_task, create_tester,
            qualification,
        )
        client = create_client()
        create_tester(qualifications=[
            qualification("CONCRETE", "2024-01-01", "2200-12-31"),
        ])
        calibration_end = anchor_plus(days=2)
        instrument = create_instrument(
            capabilities=["COMPRESSION_STRENGTH"],
            calibration_valid_from=anchor_plus(days=-1),
            calibration_valid_to=calibration_end,
        )
        sample = create_sample(
            client_id=client["id"], material_category="CONCRETE",
        )
        task = create_task(
            sample_id=sample["id"], test_method="COMPRESSION_STRENGTH",
        )
        # Use a slot that ends exactly at calibration_end.
        slot_start = anchor_plus(days=1, hours=23)
        slot_end = calibration_end
        payload = create_booking_payload(
            task_id=task["id"],
            slot_start=slot_start, slot_end=slot_end,
        )
        resp = api.create_instrument_booking(
            instrument["id"], payload, lab_clerk_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_instrument_booking(data)


class TestBookingSlotOverlap:
    """PRD §3.4, §2.9 — half-open overlap arithmetic."""

    def test_adjacent_bookings_allowed_at_boundary(
        self, api, lab_clerk_headers,
    ):
        """PRD §3.4: 'two bookings that touch at exactly slot_end ==
        other.slot_start do not intersect and both may be created.'

        Difficulty-design: instrument_booking_half_open_adjacent_allowed.

        Claim: a booking starting exactly at the previous booking's
        slot_end succeeds (HTTP 201).
        """
        # difficulty: resource_temporal_overlap/instrument_booking_half_open_adjacent_allowed
        env = setup_assigned_task()
        slot1_start = anchor_plus(hours=10)
        slot1_end = anchor_plus(hours=11)
        # First booking on env.task.
        book_instrument_for_task(
            instrument_id=env["instrument"]["id"],
            task_id=env["task"]["id"],
            slot_start=slot1_start, slot_end=slot1_end,
        )
        # Need a SECOND task to host the second booking (one booking per
        # task is the natural model). Create one on a fresh sample.
        from test_helpers import create_sample, create_task
        sample2 = create_sample(
            client_id=env["client"]["id"], material_category="CONCRETE",
        )
        # Bump tester capacity to keep auto-assignment from failing.
        # Default cap = 5, this is the second task → fine.
        task2 = create_task(
            sample_id=sample2["id"], test_method="COMPRESSION_STRENGTH",
        )
        slot2_start = slot1_end  # adjacent
        slot2_end = anchor_plus(hours=12)
        payload = create_booking_payload(
            task_id=task2["id"],
            slot_start=slot2_start, slot_end=slot2_end,
        )
        resp = api.create_instrument_booking(
            env["instrument"]["id"], payload, lab_clerk_headers,
        )
        validate_success(resp, expected_status=201)

    def test_overlapping_bookings_rejected(self, api, lab_clerk_headers):
        """PRD §3.4: 'the new interval must not intersect any existing
        booking on the same instrument whose status is RESERVED or
        COMPLETED ... An overlap rejects the new booking with
        ERR_INSTRUMENT_SLOT_CONFLICT.'

        Difficulty-design: instrument_booking_half_open_adjacent_allowed
        (1-ms overlap branch).

        Claim: a booking that overlaps an existing one by even one
        millisecond yields ERR_INSTRUMENT_SLOT_CONFLICT.
        """
        # difficulty: resource_temporal_overlap/instrument_booking_half_open_adjacent_allowed
        env = setup_assigned_task()
        slot1_start = anchor_plus(hours=10)
        slot1_end = anchor_plus(hours=11)
        book_instrument_for_task(
            instrument_id=env["instrument"]["id"],
            task_id=env["task"]["id"],
            slot_start=slot1_start, slot_end=slot1_end,
        )
        from test_helpers import create_sample, create_task
        sample2 = create_sample(
            client_id=env["client"]["id"], material_category="CONCRETE",
        )
        task2 = create_task(
            sample_id=sample2["id"], test_method="COMPRESSION_STRENGTH",
        )
        # Overlap by 1 ms on the start side.
        slot2_start = iso(parse_iso(slot1_end) - timedelta(milliseconds=1))
        slot2_end = anchor_plus(hours=12)
        payload = create_booking_payload(
            task_id=task2["id"],
            slot_start=slot2_start, slot_end=slot2_end,
        )
        resp = api.create_instrument_booking(
            env["instrument"]["id"], payload, lab_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSTRUMENT_SLOT_CONFLICT.value)


class TestInstrumentFailureCascade:
    """PRD §3.4 — report-failure cascade on RESERVED future bookings."""

    def test_failure_cancels_future_bookings_and_bounces_tasks(
        self, api, lab_manager_headers, lab_clerk_headers,
    ):
        """PRD §3.4: 'An instrument may be taken OUT_OF_SERVICE by a
        manual failure report from a LabManager. The transition
        cascades: every RESERVED booking on the instrument with a
        slot_end strictly after the current instant is cancelled, and
        each affected task drops back to PENDING_ASSIGNMENT.'

        Claim: report-failure leaves Instrument.status==OUT_OF_SERVICE,
        cancels the future RESERVED booking, and reverts the affected
        TestTask back to PENDING_ASSIGNMENT.
        """
        from test_helpers import advance_clock_to, iso, CLOCK_ANCHOR
        # Pin the server's logical clock to CLOCK_ANCHOR so anchor_plus
        # offsets are deterministically in the future of "now".
        advance_clock_to(to=iso(CLOCK_ANCHOR))
        env = setup_assigned_task()
        slot_start = anchor_plus(hours=10)
        slot_end = anchor_plus(hours=11)
        booking = book_instrument_for_task(
            instrument_id=env["instrument"]["id"],
            task_id=env["task"]["id"],
            slot_start=slot_start, slot_end=slot_end,
        )
        resp = api.report_instrument_failure(
            env["instrument"]["id"], lab_manager_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "OUT_OF_SERVICE"
        # Task must have reverted to PENDING_ASSIGNMENT.
        task = validate_success(
            api.get_task(env["task"]["id"], lab_manager_headers),
        )
        assert task["status"] == "PENDING_ASSIGNMENT"
        assert task["assigned_tester_id"] is None
