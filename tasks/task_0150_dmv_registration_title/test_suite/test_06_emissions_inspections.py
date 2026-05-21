"""Emissions inspection scheduling, slot overlap, start/record, odometer.

PRD §3.5.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    EMISSIONS_EXPIRY_DAYS,
    EMISSIONS_SLOT_BUFFER_MINUTES,
    ApiErrorId,
    TEST_USERS,
    add_minutes,
    advance_clock_to,
    assert_emissions_inspection,
    cancel_emissions_inspection,
    create_emissions_inspection_payload,
    create_owner,
    create_transfer_application,
    create_vehicle,
    current_clock,
    get_transfer_application,
    get_vehicle,
    iso_utc,
    parse_iso,
    post_salvage_event,
    record_emissions_result,
    record_emissions_result_payload,
    schedule_emissions_inspection,
    start_emissions_inspection,
    validate_error,
    validate_success,
    verify_vin,
)


class TestEmissionsScheduling:

    def test_schedule_inspection_initial_state(self, api):
        """PRD §3.5: "The inspection's status starts as SCHEDULED, its
        result_recorded_at and odometer_reading null."
        """
        vehicle = create_vehicle()
        inspection = schedule_emissions_inspection(vehicle["id"])
        assert_emissions_inspection(inspection)
        assert inspection["status"] == "SCHEDULED"
        assert inspection["result_recorded_at"] is None
        assert inspection["odometer_reading"] is None

    def test_schedule_end_must_be_after_start(self, api):
        """PRD §3.5: "scheduled_end strictly later than
        scheduled_start."

        Claim: scheduled_end <= scheduled_start → ERR_VALIDATION.
        """
        vehicle = create_vehicle()
        start = add_minutes(current_clock(), 60)
        end = start  # same instant
        resp = api.create_emissions_inspection(
            create_emissions_inspection_payload(
                vehicle_id=vehicle["id"],
                station_id="STATION-X",
                scheduled_start=iso_utc(start),
                scheduled_end=iso_utc(end),
            ),
            TEST_USERS["emissions_inspector_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestEmissionsSlotOverlap:

    def test_abutting_slot_collides_due_to_buffer(self, api):
        """PRD §3.5: "the new inspection's slot at the given station_id
        must not overlap any other non-cancelled inspection's
        half-open interval [start, end + 15 minutes) at that station;
        an overlap is rejected with ERR_INSPECTION_SLOT_OVERLAP."

        Claim: scheduling B with start == A.end at the same station
        falls inside A's buffered window [A.start, A.end + 15m).
        """
        v1 = create_vehicle()
        v2 = create_vehicle()
        station = "STATION-OVERLAP-A"
        a_start = add_minutes(current_clock(), 120)
        a_end = add_minutes(a_start, 30)
        resp_a = api.create_emissions_inspection(
            create_emissions_inspection_payload(
                vehicle_id=v1["id"], station_id=station,
                scheduled_start=iso_utc(a_start),
                scheduled_end=iso_utc(a_end),
            ),
            TEST_USERS["emissions_inspector_headers"],
        )
        validate_success(resp_a, expected_status=201)
        # B starts exactly when A ended — inside A's buffer window.
        resp_b = api.create_emissions_inspection(
            create_emissions_inspection_payload(
                vehicle_id=v2["id"], station_id=station,
                scheduled_start=iso_utc(a_end),
                scheduled_end=iso_utc(add_minutes(a_end, 30)),
            ),
            TEST_USERS["emissions_inspector_headers"],
        )
        validate_error(resp_b, ApiErrorId.ERR_INSPECTION_SLOT_OVERLAP.value)

    def test_slot_exactly_at_buffer_end_succeeds(self, api):
        """PRD §3.5: "half-open interval [start, end + 15 minutes)" —
        the right boundary at end+15m is EXCLUDED, so a new inspection
        starting at exactly that instant should succeed.
        """
        v1 = create_vehicle()
        v2 = create_vehicle()
        station = "STATION-OVERLAP-B"
        a_start = add_minutes(current_clock(), 180)
        a_end = add_minutes(a_start, 30)
        resp_a = api.create_emissions_inspection(
            create_emissions_inspection_payload(
                vehicle_id=v1["id"], station_id=station,
                scheduled_start=iso_utc(a_start),
                scheduled_end=iso_utc(a_end),
            ),
            TEST_USERS["emissions_inspector_headers"],
        )
        validate_success(resp_a, expected_status=201)
        # B starts at A.end + 15 minutes — exactly at the right
        # boundary of the half-open buffer.
        b_start = add_minutes(a_end, EMISSIONS_SLOT_BUFFER_MINUTES)
        resp_b = api.create_emissions_inspection(
            create_emissions_inspection_payload(
                vehicle_id=v2["id"], station_id=station,
                scheduled_start=iso_utc(b_start),
                scheduled_end=iso_utc(add_minutes(b_start, 30)),
            ),
            TEST_USERS["emissions_inspector_headers"],
        )
        validate_success(resp_b, expected_status=201)

    def test_non_overlap_different_station_succeeds(self, api):
        """PRD §3.5: "the new inspection's slot at the given station_id
        must not overlap any other non-cancelled inspection's
        half-open interval [start, end + 15 minutes) at that station."

        Claim: overlap check is per-station_id; two abutting bookings
        at different stations both succeed.
        """
        v1 = create_vehicle()
        v2 = create_vehicle()
        a_start = add_minutes(current_clock(), 240)
        a_end = add_minutes(a_start, 30)
        resp_a = api.create_emissions_inspection(
            create_emissions_inspection_payload(
                vehicle_id=v1["id"], station_id="STATION-DIFF-1",
                scheduled_start=iso_utc(a_start),
                scheduled_end=iso_utc(a_end),
            ),
            TEST_USERS["emissions_inspector_headers"],
        )
        validate_success(resp_a, expected_status=201)
        resp_b = api.create_emissions_inspection(
            create_emissions_inspection_payload(
                vehicle_id=v2["id"], station_id="STATION-DIFF-2",
                scheduled_start=iso_utc(a_start),
                scheduled_end=iso_utc(a_end),
            ),
            TEST_USERS["emissions_inspector_headers"],
        )
        validate_success(resp_b, expected_status=201)


class TestInspectionStart:

    def test_start_during_grace_window_succeeds(self, api):
        """PRD §3.5: "the current time is at or after the inspection's
        scheduled_start minus 15 minutes (a 15-minute early-arrival
        grace window)."
        """
        vehicle = create_vehicle()
        start_dt = add_minutes(current_clock(), 30)
        end_dt = add_minutes(start_dt, 30)
        inspection_resp = api.create_emissions_inspection(
            create_emissions_inspection_payload(
                vehicle_id=vehicle["id"], station_id="STATION-GRACE-1",
                scheduled_start=iso_utc(start_dt),
                scheduled_end=iso_utc(end_dt),
            ),
            TEST_USERS["emissions_inspector_headers"],
        )
        inspection = validate_success(inspection_resp, expected_status=201)
        # Advance clock to start - 15 minutes (the grace window).
        advance_clock_to(add_minutes(start_dt, -15))
        resp = api.start_emissions_inspection(
            inspection["id"],
            TEST_USERS["emissions_inspector_headers"],
        )
        validate_success(resp, expected_status=200)

    def test_start_before_grace_window_rejected(self, api):
        """PRD §3.5: "the current time is at or after the inspection's
        scheduled_start minus 15 minutes."

        Claim: starting before scheduled_start - 15m → ERR_INVALID_STATE
        (the from-state precondition fails).
        """
        vehicle = create_vehicle()
        start_dt = add_minutes(current_clock(), 60)
        end_dt = add_minutes(start_dt, 30)
        inspection_resp = api.create_emissions_inspection(
            create_emissions_inspection_payload(
                vehicle_id=vehicle["id"], station_id="STATION-GRACE-2",
                scheduled_start=iso_utc(start_dt),
                scheduled_end=iso_utc(end_dt),
            ),
            TEST_USERS["emissions_inspector_headers"],
        )
        inspection = validate_success(inspection_resp, expected_status=201)
        # Do not advance the clock; current time is 60m before
        # scheduled_start, which is well outside the 15m grace.
        resp = api.start_emissions_inspection(
            inspection["id"],
            TEST_USERS["emissions_inspector_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_start_blocked_when_title_status_salvage_pending(self, api):
        """PRD §3.5: "An EmissionsInspector advances SCHEDULED to
        IN_PROGRESS provided three conditions hold ... Vehicle.title_
        status is not SALVAGE_PENDING_REBUILD. The second precondition
        is enforced as ERR_VEHICLE_SALVAGE_LOCKED."
        """
        vehicle = create_vehicle()
        inspection = schedule_emissions_inspection(vehicle["id"])
        # Now flip the vehicle to SALVAGE_PENDING_REBUILD via salvage
        # event. PRD §3.3 says this also cancels the inspection
        # (cascade). The /start call should re-read state and reject.
        post_salvage_event(vehicle["id"], severity="PARTIAL")
        advance_clock_to(parse_iso(inspection["scheduled_start"]))
        resp = api.start_emissions_inspection(
            inspection["id"],
            TEST_USERS["emissions_inspector_headers"],
        )
        # PRD priority 8 (salvage-block-on-start) → 409 with that error.
        # The cascade may have already pre-cancelled the inspection, in
        # which case ERR_INVALID_STATE fires earlier (priority 6).
        body = resp.json().get("data", {}) or {}
        assert resp.status_code == 409
        assert body.get("error_id") in (
            ApiErrorId.ERR_VEHICLE_SALVAGE_LOCKED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        )


class TestRecordResult:

    def _drive_to_in_progress(self, vehicle_id: str):
        """Helper — schedule + start so the inspection is IN_PROGRESS."""
        inspection = schedule_emissions_inspection(vehicle_id)
        advance_clock_to(parse_iso(inspection["scheduled_start"]))
        start_emissions_inspection(inspection["id"])
        return inspection

    def test_record_passed_stamps_expires_at_for_gasoline(self, api):
        """PRD §3.5: "Recording PASSED stamps result_recorded_at, sets
        Vehicle.emissions_expires_at to the recorded time plus 730 days
        for GASOLINE, DIESEL, and HYBRID fuel types."
        """
        vehicle = create_vehicle(fuel_type="GASOLINE")
        inspection = self._drive_to_in_progress(vehicle["id"])
        record_emissions_result(
            inspection["id"], outcome="PASSED", odometer_reading=10000,
        )
        v_after = get_vehicle(vehicle["id"])
        assert v_after["emissions_expires_at"] is not None
        # Check the expiry is ~730 days out from current clock.
        expires = parse_iso(v_after["emissions_expires_at"])
        # Result was recorded at the current clock; allow a small drift.
        days_out = (expires - current_clock()).days
        assert EMISSIONS_EXPIRY_DAYS - 2 <= days_out <= EMISSIONS_EXPIRY_DAYS + 2, (
            f"emissions_expires_at should be ~730 days from now, "
            f"got days_out={days_out}"
        )

    def test_record_passed_for_electric_sets_null(self, api):
        """PRD §3.5: "and explicitly to null for ELECTRIC vehicles,
        which are exempt from emissions expiry."
        """
        vehicle = create_vehicle(fuel_type="ELECTRIC")
        inspection = self._drive_to_in_progress(vehicle["id"])
        record_emissions_result(
            inspection["id"], outcome="PASSED", odometer_reading=10000,
        )
        v_after = get_vehicle(vehicle["id"])
        assert v_after["emissions_expires_at"] is None

    def test_record_failed_rejects_linked_application(self, api):
        """PRD §3.5: "Recording FAILED instead rejects every linked
        EmissionsInspection-bound transfer application by transitioning
        it to REJECTED with rejection_reason set to EMISSIONS_FAILED."
        """
        owner = create_owner()
        vehicle = create_vehicle()
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type="TITLE_TRANSFER",
        )
        verify_vin(vehicle["id"], app["id"])
        inspection = self._drive_to_in_progress(vehicle["id"])
        record_emissions_result(
            inspection["id"], outcome="FAILED", odometer_reading=10000,
        )
        app_after = get_transfer_application(app["id"])
        assert app_after["status"] == "REJECTED"
        assert app_after["rejection_reason"] == "EMISSIONS_FAILED"

    def test_record_passed_advances_linked_application(self, api):
        """PRD §3.5: "The same PASSED event advances any linked
        TransferApplication whose status is EMISSIONS_PENDING and which
        was last updated within the last 30 days to EMISSIONS_PASSED."
        """
        owner = create_owner()
        vehicle = create_vehicle()
        app = create_transfer_application(
            owner["id"], vehicle["id"], application_type="TITLE_TRANSFER",
        )
        verify_vin(vehicle["id"], app["id"])
        inspection = self._drive_to_in_progress(vehicle["id"])
        record_emissions_result(
            inspection["id"], outcome="PASSED", odometer_reading=10000,
        )
        app_after = get_transfer_application(app["id"])
        assert app_after["status"] == "EMISSIONS_PASSED"


class TestOdometerRollback:

    def test_odometer_lower_than_prior_passed_rejected(self, api):
        """PRD §3.5: "If a prior PASSED inspection exists on this
        vehicle, the new odometer_reading must be at least equal to the
        prior PASSED inspection's odometer reading; a lower reading is
        rejected with ERR_ODOMETER_ROLLBACK."
        """
        vehicle = create_vehicle()
        # First PASSED inspection: odometer 50_000.
        ins_1 = schedule_emissions_inspection(vehicle["id"])
        advance_clock_to(parse_iso(ins_1["scheduled_start"]))
        start_emissions_inspection(ins_1["id"])
        record_emissions_result(ins_1["id"], outcome="PASSED",
                                odometer_reading=50_000)
        # Second inspection scheduled at a slot in the future (well past
        # buffer).
        ins_2_start = add_minutes(current_clock(), 120)
        ins_2_resp = api.create_emissions_inspection(
            create_emissions_inspection_payload(
                vehicle_id=vehicle["id"], station_id="STATION-ROLL-1",
                scheduled_start=iso_utc(ins_2_start),
                scheduled_end=iso_utc(add_minutes(ins_2_start, 30)),
            ),
            TEST_USERS["emissions_inspector_headers"],
        )
        ins_2 = validate_success(ins_2_resp, expected_status=201)
        advance_clock_to(ins_2_start)
        start_emissions_inspection(ins_2["id"])
        # Lower odometer reading triggers ERR_ODOMETER_ROLLBACK.
        resp = api.record_emissions_result(
            ins_2["id"],
            record_emissions_result_payload(
                outcome="PASSED", odometer_reading=49_999,
            ),
            TEST_USERS["emissions_inspector_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ODOMETER_ROLLBACK.value)


class TestCancellation:

    def test_cancel_scheduled_inspection_204(self, api):
        """PRD §2.10: "A successful DELETE returns HTTP 204."
        PRD §3.5: "A SCHEDULED inspection can be cancelled outright by
        either the Applicant or the EmissionsInspector, which flips its
        status to CANCELLED."
        """
        vehicle = create_vehicle()
        inspection = schedule_emissions_inspection(vehicle["id"])
        resp = api.cancel_emissions_inspection(
            inspection["id"],
            TEST_USERS["emissions_inspector_headers"],
        )
        assert resp.status_code == 204
