"""Movement execution gates (arrive/start/complete), gauge sequencing, gauge
immutability, vapor-control permits, and demurrage variants (PRD §2.5, §2.7,
§2.8, §3.6, §3.7, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_gauge_ticket,
    is_valid_uuid,
    setup_lease_with_allocation,
    setup_vru_in_progress_movement,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    MANAGER,
    OPERATOR,
    SCHEDULER,
    create_approved_permit,
    create_resource,
    drive_movement_to_completed,
    drive_scheduled_movement_to_completed,
    get_movement,
    get_tank,
    nominate_movement,
    record_gauge,
    schedule_movement,
    set_clock,
    setup_completed_movement,
)


class TestArriveTransition:
    def test_arrive_from_nominated_rejected(self, api):
        """PRD §3.6: "The arrival of the vessel, rail cut, or truck is recorded
        by an arrive action, moving the movement from `SCHEDULED` to `ARRIVED`
        and stamping `actual_arrival_at` with the logical clock."
        PRD §2.9: "then state-machine from-state matching (`ERR_INVALID_STATE`)"
        — arrive from NOMINATED is not a declared edge.

        Design: Corner/state_machines/movement_arrive_from_nominated_rejected
        """
        bundle = setup_lease_with_allocation(customer_name="Transition Co")
        movement = nominate_movement(bundle["lease"]["id"], bundle["tank"]["id"])
        resp = api.arrive_movement(movement["id"], SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        after = get_movement(movement["id"])
        assert after["status"] == "NOMINATED"
        assert after.get("actual_arrival_at") is None, "rejected arrive must not stamp arrival"


class TestGaugeSequencing:
    def _arrived_with_opening(self, api):
        bundle = setup_lease_with_allocation(customer_name="Gauge Seq Co")
        resource = create_resource("DOCK")
        movement = nominate_movement(bundle["lease"]["id"], bundle["tank"]["id"])
        schedule_movement(movement["id"], resource["id"])
        set_clock("2026-05-10T08:00:00Z")
        validate_success(api.arrive_movement(movement["id"], SCHEDULER))
        record_gauge(movement["id"], "OPENING", 0)
        return bundle, movement

    def test_duplicate_opening_rejected(self, api):
        """PRD §3.7: "Gauge sequencing is strict: at most one `OPENING` and at
        most one `CLOSING` ticket exist per movement; a `CLOSING` requires an
        existing `OPENING`; an `OPENING` ticket may only be recorded while the
        movement is `ARRIVED` or `IN_PROGRESS`; and a `CLOSING` ticket only
        while the movement is `IN_PROGRESS`. Any violation — a duplicate, a
        closing-before-opening, or a ticket outside its permitted status — is
        rejected with `ERR_GAUGE_SEQUENCE_INVALID` (HTTP 409)."

        Design: Corner/state_machines/gauge_duplicate_opening_rejected
        """
        bundle, movement = self._arrived_with_opening(api)
        resp = api.create_gauge_ticket(
            movement["id"],
            {"ticket_type": "OPENING", "observed_volume_bbl": 5, "observed_temp_f": 61,
             "observed_at": "2026-05-10T08:06:00Z"},
            {"X-User-ID": "gauger-1", "X-User-Role": "Gauger", "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_GAUGE_SEQUENCE_INVALID)
        assert resp.status_code == 409
        tickets, meta = validate_paginated(api.list_gauge_tickets(movement["id"], MANAGER))
        assert len(tickets) == 1, f"rejected duplicate must not persist; got {len(tickets)} tickets"

    def test_gauge_ticket_is_append_only(self, api):
        """PRD §2.5: "The single exception is the `GaugeTicket`: gauge tickets
        are append-only measurement records and carry only `id` and
        `created_at`; neither `updated_at` nor `version` exists on a gauge
        ticket."
        PRD §3.7: "the server pins `recorded_by_user_id` from the caller's
        `X-User-ID`."

        Design: Corner/entities/gauge_ticket_immutable_no_version_field
        """
        bundle, movement = self._arrived_with_opening(api)
        tickets, _ = validate_paginated(api.list_gauge_tickets(movement["id"], MANAGER))
        assert len(tickets) == 1
        ticket = tickets[0]
        assert_gauge_ticket(ticket)
        assert is_valid_uuid(ticket["id"])
        assert ticket["recorded_by_user_id"] == "gauger-1"


class TestStartPermitGates:
    def _vru_arrived_no_permit(self, api, clock="2026-05-10T12:31:00Z"):
        """VRU_REQUIRED tank, no vapor permit; movement ARRIVED with OPENING
        gauge recorded; clock moved past the window end + 30 minute grace."""
        bundle = setup_lease_with_allocation(
            product_grade="GASOLINE", customer_name="Quantum Refining",
            tank_overrides={"vapor_control_class": "VRU_REQUIRED"})
        resource = create_resource("DOCK")
        movement = nominate_movement(bundle["lease"]["id"], bundle["tank"]["id"],
                                     product_grade="GASOLINE")
        schedule_movement(movement["id"], resource["id"])
        set_clock("2026-05-10T08:00:00Z")
        validate_success(api.arrive_movement(movement["id"], SCHEDULER))
        record_gauge(movement["id"], "OPENING", 0)
        set_clock(clock)
        return bundle, movement

    def test_missing_permit_error_returned(self, api):
        """PRD §3.6: "Second, if the tank's `vapor_control_class` is
        `VRU_REQUIRED`, an `APPROVED` permit of `permit_type` `VAPOR_CONTROL`
        must exist for the tank; if none exists the start is rejected with
        `ERR_VAPOR_PERMIT_REQUIRED`". The permit check runs before the window
        lapse check ("Third, the logical clock must not have passed the end of
        the occupation window by more than the late grace allowance of 30
        minutes"), so with no permit and a lapsed window the safety-tier error
        wins.

        Design: Difficulty/priority_pair_validation_conflict/start_missing_permit_beats_window_lapsed
        """
        _, movement = self._vru_arrived_no_permit(api)
        resp = api.start_movement(movement["id"], SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_VAPOR_PERMIT_REQUIRED)
        assert resp.status_code == 409

    def test_rejected_start_leaves_movement_arrived(self, api):
        """PRD §3.6: "if none exists the start is rejected with
        `ERR_VAPOR_PERMIT_REQUIRED`". The rejected start leaves the movement
        ARRIVED, and the temporal-tier ERR_WINDOW_LAPSED is not returned even
        though the clock (12:31) is past window_end (12:00) + 30 minutes.

        Design: Difficulty/priority_pair_validation_conflict/start_missing_permit_beats_window_lapsed
        """
        _, movement = self._vru_arrived_no_permit(api)
        resp = api.start_movement(movement["id"], SCHEDULER)
        err = validate_error(resp, ApiErrorId.ERR_VAPOR_PERMIT_REQUIRED)
        assert err["error_id"] != "ERR_WINDOW_LAPSED"
        assert get_movement(movement["id"])["status"] == "ARRIVED"

    def test_permit_not_yet_valid_rejected(self, api):
        """PRD §3.6: "if one exists but its `valid_from` to `valid_until`
        window does not cover the current logical time — including the case
        where the permit has lazily become `EXPIRED` — the start is rejected
        with `ERR_PERMIT_WINDOW_INSUFFICIENT` (HTTP 409)."
        The permit is APPROVED but valid only 2026-05-20..2026-05-25 while the
        clock is 2026-05-10, so the coverage check fails (not the existence
        check).

        Design: Corner/validations/permit_not_yet_valid_window_insufficient
        """
        bundle = setup_lease_with_allocation(
            product_grade="GASOLINE", customer_name="Coverage Co",
            tank_overrides={"vapor_control_class": "VRU_REQUIRED"})
        create_approved_permit(bundle["tank"]["id"], valid_from="2026-05-20T00:00:00Z",
                               valid_until="2026-05-25T00:00:00Z")
        resource = create_resource("DOCK")
        movement = nominate_movement(bundle["lease"]["id"], bundle["tank"]["id"],
                                     product_grade="GASOLINE")
        schedule_movement(movement["id"], resource["id"])
        set_clock("2026-05-10T08:00:00Z")
        validate_success(api.arrive_movement(movement["id"], SCHEDULER))
        record_gauge(movement["id"], "OPENING", 0)
        resp = api.start_movement(movement["id"], SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_INSUFFICIENT)
        assert resp.status_code == 409
        assert get_movement(movement["id"])["status"] == "ARRIVED"


class TestPermitRevokeCascade:
    def test_revoke_suspends_in_progress_movement(self, api):
        """PRD §2.8: "Revoking an approved permit — an action that accepts an
        optional free-text `revoked_reason` — has a cascading safety effect:
        every movement on the permit's tank that is currently `IN_PROGRESS` —
        where the tank's `vapor_control_class` is `VRU_REQUIRED` — transitions
        to `SUSPENDED`."

        Design: Corner/state_machines/permit_revoke_suspends_in_progress_movement
        """
        bundle = setup_vru_in_progress_movement(customer_name="Vapor Co")
        assert bundle["movement"]["status"] == "IN_PROGRESS"
        revoked = validate_success(api.revoke_permit(
            bundle["permit"]["id"], MANAGER, payload={"revoked_reason": "VRU fault detected"}))
        assert revoked["status"] == "REVOKED"
        movement = get_movement(bundle["movement"]["id"])
        assert movement["status"] == "SUSPENDED", "revoke must cascade-suspend the movement"

    def test_resume_requires_valid_permit(self, api):
        """PRD §3.6: "A resume action moves it back to `IN_PROGRESS`,
        re-checking the same vapor-permit conditions as at start: no approved
        vapor permit yields `ERR_VAPOR_PERMIT_REQUIRED`, and a permit whose
        window does not cover the current time yields
        `ERR_PERMIT_WINDOW_INSUFFICIENT`."

        Design: Corner/state_machines/movement_resume_requires_valid_permit
        """
        bundle = setup_vru_in_progress_movement(customer_name="Resume Co")
        api.revoke_permit(bundle["permit"]["id"], MANAGER)
        movement = get_movement(bundle["movement"]["id"])
        assert movement["status"] == "SUSPENDED"
        # No approved permit now: resume is rejected.
        resp = api.resume_movement(movement["id"], SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_VAPOR_PERMIT_REQUIRED)
        assert resp.status_code == 409
        # A fresh approved permit covering the current time lets resume pass.
        create_approved_permit(bundle["tank"]["id"], valid_from="2026-05-10T08:00:00Z",
                               valid_until="2026-05-11T00:00:00Z")
        resumed = validate_success(api.resume_movement(movement["id"], SCHEDULER))
        assert resumed["status"] == "IN_PROGRESS"


class TestDemurrageVariants:
    def _vessel_30h_scenario(self):
        """100-bbl VESSEL movement, 30h window (2026-05-10T00:00 ->
        2026-05-11T06:00), arrival at window start, completion 26h later."""
        bundle = setup_lease_with_allocation(product_grade="GASOLINE", customer_name="Beacon Fuels",
                                             allocated_bbl=40000,
                                             lease_overrides={
                                                 "committed_capacity_bbl": 50000,
                                                 "min_monthly_throughput_bbl": 500,
                                                 "throughput_fee_per_bbl": 0.40,
                                                 "shortfall_fee_per_bbl": 0.40,
                                                 "excess_loss_rate_per_bbl": 40.00})
        bundle["resource"] = create_resource("DOCK")
        movement = nominate_movement(
            bundle["lease"]["id"], bundle["tank"]["id"], declared_volume_bbl=100,
            product_grade="GASOLINE",
            window_start="2026-05-10T00:00:00Z", window_end="2026-05-11T06:00:00Z")
        return bundle, movement

    def test_estimate_from_window_at_schedule(self, api):
        """PRD §3.9: "The scheduled estimate, computed when a movement is
        scheduled and stored as `demurrage_estimated_amount`, is
        forward-looking: it takes the exact rational duration in hours from
        `window_start` to `window_end`, subtracts the mode's free hours, clamps
        the result below at zero, multiplies by the mode's hourly rate, and
        rounds half-up to 2 decimal places."
        VESSEL: 24 free hours at 1,200.00 per hour; a 30h window yields
        (30 - 24) * 1200.00 == 7200.00.

        Design: Difficulty/dual_variant_calc/demurrage_estimate_vs_actual_settlement
        """
        bundle, movement = self._vessel_30h_scenario()
        scheduled = schedule_movement(movement["id"], bundle["resource"]["id"])
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["demurrage_estimated_amount"] == pytest.approx(7200.00, abs=0.01)

    def test_actual_settlement_differs_from_estimate(self, api):
        """PRD §3.9: "The actual settlement, computed at completion and stored
        as `demurrage_actual_amount`, is chronological: it measures the elapsed
        time from `actual_arrival_at` to `actual_complete_at`, rounds that
        elapsed time up to the next whole hour (the ceiling of the elapsed
        seconds divided by 3600), subtracts the free hours, clamps below at
        zero — where elapsed time exactly equal to the free hours yields a zero
        charge — multiplies by the hourly rate, and rounds half-up to 2 decimal
        places. Because one variant reads the requested window and the other
        reads actual timestamps, the same movement can legitimately carry two
        different amounts."
        26h actual elapsed: (26 - 24) * 1200.00 == 2400.00, diverging from the
        7200.00 window estimate on the same movement.

        Design: Difficulty/dual_variant_calc/demurrage_estimate_vs_actual_settlement
        """
        bundle, movement = self._vessel_30h_scenario()
        completed = drive_movement_to_completed(
            movement["id"], bundle["resource"]["id"],
            opening_volume=0, closing_volume=100,
            arrive_clock="2026-05-10T00:00:00Z", complete_clock="2026-05-11T02:00:00Z",
            open_observed_at="2026-05-10T00:05:00Z", close_observed_at="2026-05-11T01:30:00Z")
        assert completed["status"] == "COMPLETED"
        after = get_movement(movement["id"])
        assert after["demurrage_actual_amount"] == pytest.approx(2400.00, abs=0.01)
        assert after["demurrage_estimated_amount"] == pytest.approx(7200.00, abs=0.01)
        assert after["demurrage_estimated_amount"] != after["demurrage_actual_amount"]


class TestDemurrageFreeHoursBoundary:
    def _vessel_24h_scenario(self):
        """100-bbl VESSEL movement, 24h window; arrival 2026-05-10T08:00,
        completion exactly 2026-05-11T08:00 (elapsed exactly 24h)."""
        bundle = setup_lease_with_allocation(customer_name="Vertex Energy")
        bundle["resource"] = create_resource("DOCK")
        movement = nominate_movement(
            bundle["lease"]["id"], bundle["tank"]["id"], declared_volume_bbl=100,
            window_start="2026-05-10T08:00:00Z", window_end="2026-05-11T08:00:00Z")
        return bundle, movement

    def test_zero_charge_at_exactly_free_hours(self, api):
        """PRD §3.9: "The actual settlement, computed at completion and stored
        as `demurrage_actual_amount`, is chronological: it measures the elapsed
        time from `actual_arrival_at` to `actual_complete_at`, rounds that
        elapsed time up to the next whole hour (the ceiling of the elapsed
        seconds divided by 3600), subtracts the free hours, clamps below at
        zero — where elapsed time exactly equal to the free hours yields a zero
        charge — multiplies by the hourly rate, and rounds half-up to 2 decimal
        places." VESSEL free hours are 24; 24h00m elapsed yields 0.00.

        Design: Difficulty/boundary_precision_check/demurrage_zero_at_exact_free_hours
        """
        bundle, movement = self._vessel_24h_scenario()
        completed = drive_movement_to_completed(
            movement["id"], bundle["resource"]["id"],
            opening_volume=0, closing_volume=100,
            arrive_clock="2026-05-10T08:00:00Z", complete_clock="2026-05-11T08:00:00Z",
            open_observed_at="2026-05-10T08:05:00Z", close_observed_at="2026-05-11T07:30:00Z")
        assert completed["status"] == "COMPLETED"
        assert completed["demurrage_actual_amount"] == pytest.approx(0.00, abs=0.01), (
            f"elapsed == free hours must yield zero charge, got {completed['demurrage_actual_amount']}"
        )

    def test_estimate_also_zero_at_free_hours_window(self, api):
        """PRD §3.9: "The scheduled estimate, computed when a movement is
        scheduled and stored as `demurrage_estimated_amount`, is
        forward-looking: it takes the exact rational duration in hours from
        `window_start` to `window_end`, subtracts the mode's free hours, clamps
        the result below at zero, multiplies by the mode's hourly rate, and
        rounds half-up to 2 decimal places."
        A 24h VESSEL window (window == free hours) estimates 0.00, and the
        movement still completes normally.

        Design: Difficulty/boundary_precision_check/demurrage_zero_at_exact_free_hours
        """
        bundle, movement = self._vessel_24h_scenario()
        scheduled = schedule_movement(movement["id"], bundle["resource"]["id"])
        assert scheduled["demurrage_estimated_amount"] == pytest.approx(0.00, abs=0.01)
        completed = drive_scheduled_movement_to_completed(
            movement["id"],
            opening_volume=0, closing_volume=100,
            arrive_clock="2026-05-10T08:00:00Z", complete_clock="2026-05-11T08:00:00Z",
            open_observed_at="2026-05-10T08:05:00Z", close_observed_at="2026-05-11T07:30:00Z")
        assert completed["status"] == "COMPLETED"
        assert completed["demurrage_actual_amount"] == pytest.approx(0.00, abs=0.01)


class TestTruckDwell:
    def test_truck_mode_uses_truck_constants(self, api):
        """PRD §3.9: "`TRUCK` movements receive 4 free hours and accrue at
        60.00 per hour; truck charges are reported as dwell rather than
        demurrage on the monthly statement, but the arithmetic is identical."
        A 4h window estimates max(0, 4-4) * 60.00 == 0.00; 6h of actual dwell
        settles at (6 - 4) * 60.00 == 120.00 (VESSEL's 24 free hours would have
        yielded 0.00).

        Design: Corner/calculations/truck_dwell_uses_mode_constants
        """
        bundle = setup_lease_with_allocation(customer_name="Truck Co")
        bay = create_resource("TRUCK_BAY", concurrent_capacity=2)
        movement = nominate_movement(
            bundle["lease"]["id"], bundle["tank"]["id"], declared_volume_bbl=100,
            mode="TRUCK",
            window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T12:00:00Z")
        scheduled = schedule_movement(movement["id"], bay["id"])
        assert scheduled["demurrage_estimated_amount"] == pytest.approx(0.00, abs=0.01)
        completed = drive_scheduled_movement_to_completed(
            movement["id"],
            opening_volume=0, closing_volume=100,
            arrive_clock="2026-05-10T08:00:00Z", complete_clock="2026-05-10T14:00:00Z",
            open_observed_at="2026-05-10T08:05:00Z", close_observed_at="2026-05-10T13:30:00Z")
        assert completed["demurrage_actual_amount"] == pytest.approx(120.00, abs=0.01)
