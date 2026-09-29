"""Interval geometry: which windows collide and which merely touch.

Reservation occupation is half-open, so two bookings that share an instant do
not compete for the same energy, while a remedy outage window is closed and
inclusive and carries a trailing buffer that keeps a discharge test away.
"""
import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_capacity_test_payload,
    create_soc_reservation_payload,
)
from test_helpers.fixtures import (
    ASSET_MANAGER,
    TRADER,
    approved_claim,
    completed_test,
    hold_reservation,
    lightly_cycled_plant,
    refresh_asset,
    refresh_reservation,
    reference_plant,
    set_clock,
)


class TestAdjacentReservationWindows:
    """Two 40 MWh bookings back to back at 04:00, then a straddling probe."""

    def _two_adjacent_holds(self):
        set_clock("2026-08-01T00:00:00Z")
        asset = reference_plant()
        early = hold_reservation(
            asset["id"],
            purpose="ENERGY_ARBITRAGE",
            reserved_mwh=40.0,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-10T04:00:00Z",
        )
        late = hold_reservation(
            asset["id"],
            purpose="ANCILLARY",
            reserved_mwh=40.0,
            window_start="2026-08-10T04:00:00Z",
            window_end="2026-08-10T08:00:00Z",
        )
        return asset, early, late

    def test_windows_that_touch_at_an_instant_do_not_compete(self):
        """Eighty megawatt-hours are held on a seventy megawatt-hour envelope, legally.

        PRD: "A held reservation of the same asset overlaps the request when its `window_start` is strictly earlier than the requested `window_end` and its `window_end` is strictly later than the requested `window_start` — the half-open geometry means two windows that merely touch at an instant do not overlap."

        Design: Difficulty/resource_temporal_overlap/half_open_reservation_windows_allow_adjacency_and_capacity_preempts_only_arbitrage
        """
        asset, early, late = self._two_adjacent_holds()

        assert early["status"] == "HELD"
        assert late["status"] == "HELD"
        after = refresh_asset(asset["id"])
        assert after["reserved_mwh_total"] == pytest.approx(80.0, abs=0.01)
        assert after["free_dispatchable_mwh"] == pytest.approx(0.0, abs=0.01)

    def test_purpose_fixes_each_holding_s_standing_in_the_pool(self):
        """Arbitrage ranks third, ancillary second, capacity first.

        PRD: "`purpose` is one of `ENERGY_ARBITRAGE`, `ANCILLARY` or `CAPACITY`, and it also fixes the reservation's standing in the pool: `priority_rank` is set to 1 for `CAPACITY`, 2 for `ANCILLARY` and 3 for `ENERGY_ARBITRAGE`, and a lower rank preempts a higher one."

        Design: Difficulty/resource_temporal_overlap/half_open_reservation_windows_allow_adjacency_and_capacity_preempts_only_arbitrage
        """
        asset, early, late = self._two_adjacent_holds()

        assert early["priority_rank"] == 3
        assert late["priority_rank"] == 2

    def test_a_request_straddling_the_shared_instant_overlaps_both(self):
        """A two-minute window across 04:00 competes with all eighty held megawatt-hours.

        PRD: "An `ANCILLARY` or `ENERGY_ARBITRAGE` request never preempts anything: if it does not fit, it is rejected with `ERR_SOC_INSUFFICIENT` immediately."

        Design: Difficulty/resource_temporal_overlap/half_open_reservation_windows_allow_adjacency_and_capacity_preempts_only_arbitrage
        """
        asset, early, late = self._two_adjacent_holds()

        response = api_client.create_soc_reservation(
            create_soc_reservation_payload(
                asset["id"],
                refresh_asset(asset["id"])["version"],
                purpose="ENERGY_ARBITRAGE",
                reserved_mwh=5.0,
                window_start="2026-08-10T03:59:00Z",
                window_end="2026-08-10T04:01:00Z",
            ),
            TRADER,
        )

        validate_error(response, "ERR_SOC_INSUFFICIENT")

    def test_a_capacity_request_preempts_the_arbitrage_hold_only(self):
        """The overlapping arbitrage booking is released; the adjacent ancillary one is not.

        PRD: "A capacity obligation outranks arbitrage, so the candidates are the overlapping held reservations whose `purpose` is `ENERGY_ARBITRAGE`, taken in descending `priority_rank` order, then ascending `window_start`, then ascending `created_at`."

        Design: Difficulty/resource_temporal_overlap/half_open_reservation_windows_allow_adjacency_and_capacity_preempts_only_arbitrage
        """
        asset, early, late = self._two_adjacent_holds()

        capacity = hold_reservation(
            asset["id"],
            purpose="CAPACITY",
            reserved_mwh=40.0,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-10T04:00:00Z",
        )

        assert capacity["status"] == "HELD"
        assert capacity["priority_rank"] == 1
        preempted = refresh_reservation(early["id"])
        assert preempted["status"] == "RELEASED"
        assert preempted["released_reason"] == "CAPACITY_PREEMPTION"
        assert refresh_reservation(late["id"])["status"] == "HELD"

    def test_preemption_leaves_the_pool_exactly_as_full_as_before(self):
        """One forty megawatt-hour hold replaces another, so the totals are unchanged.

        PRD: "`reserved_mwh_total` becomes the sum of `reserved_mwh` over every reservation of this asset whose `status` is `HELD`, regardless of window, rounded half up to 3 decimal places — note the asymmetry with the acceptance test, which sums only the overlapping subset."

        Design: Difficulty/resource_temporal_overlap/half_open_reservation_windows_allow_adjacency_and_capacity_preempts_only_arbitrage
        """
        asset, early, late = self._two_adjacent_holds()

        hold_reservation(
            asset["id"],
            purpose="CAPACITY",
            reserved_mwh=40.0,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-10T04:00:00Z",
        )

        after = refresh_asset(asset["id"])
        assert after["reserved_mwh_total"] == pytest.approx(80.0, abs=0.01)
        assert after["free_dispatchable_mwh"] == pytest.approx(0.0, abs=0.01)
        rows, meta = validate_paginated(
            api_client.list_soc_reservations(
                TRADER, {"asset_id": asset["id"], "status": "HELD"}
            )
        )
        assert meta["total_count"] == 2


class TestRemedyOutageWindowAgainstCapacityTests:
    """A three-day install from 2026-09-01 plus a two-day trailing buffer."""

    def _plant_awaiting_a_remedy(self):
        set_clock("2026-08-01T00:00:00Z")
        asset = lightly_cycled_plant()
        test = completed_test(
            asset["id"],
            scheduled_date="2026-08-01T00:00:00Z",
            measured_capacity_mwh=90.0,
        )
        claim = approved_claim(
            asset["id"],
            test["id"],
            remedy_install_date="2026-09-01T00:00:00Z",
            remedy_outage_days=3,
        )
        return asset, test, claim

    def _schedule(self, asset, scheduled_date):
        return api_client.create_capacity_test(
            create_capacity_test_payload(asset["id"], scheduled_date=scheduled_date),
            ASSET_MANAGER,
        )

    def test_the_approved_claim_pins_the_outage_window(self):
        """Approval records the install date and the outage length the crew needs.

        PRD: "The approval branch requires both `remedy_install_date`, the date the augmentation racks will be installed, and `remedy_outage_days`, the length in days of the outage window that begins on that date and which must be at least 1; `denial_reason` must be absent."

        Design: Difficulty/resource_temporal_overlap/remedy_outage_window_is_closed_inclusive_with_trailing_buffer_against_capacity_tests
        """
        asset, test, claim = self._plant_awaiting_a_remedy()

        assert test["warranty_claim_triggered"] is True
        assert claim["status"] == "APPROVED"
        assert claim["remedy_install_date"] == "2026-09-01T00:00:00Z"
        assert claim["remedy_outage_days"] == 3

    def test_a_test_on_the_install_date_itself_collides(self):
        """The outage window is closed at its opening instant.

        PRD: "Scheduling also has to respect the augmentation crew: a test window must not fall inside the outage window of any warranty claim of this asset whose `status` is `APPROVED` or `REMEDIED`, where that window is the closed inclusive interval beginning at the claim's `remedy_install_date` and running for its `remedy_outage_days` plus a further trailing buffer of 2 days."

        Design: Difficulty/resource_temporal_overlap/remedy_outage_window_is_closed_inclusive_with_trailing_buffer_against_capacity_tests
        """
        asset, test, claim = self._plant_awaiting_a_remedy()

        response = self._schedule(asset, "2026-09-01T00:00:00Z")

        validate_error(response, "ERR_REMEDY_OUTAGE_CONFLICT")

    def test_the_last_day_of_the_trailing_buffer_still_collides(self):
        """Three outage days plus two buffer days reach 2026-09-06 inclusive.

        PRD: "A collision is refused with `ERR_REMEDY_OUTAGE_CONFLICT` (HTTP 409), and the same check is applied again when the test is started, because a remedy may have been approved in the meantime."

        Design: Difficulty/resource_temporal_overlap/remedy_outage_window_is_closed_inclusive_with_trailing_buffer_against_capacity_tests
        """
        asset, test, claim = self._plant_awaiting_a_remedy()

        response = self._schedule(asset, "2026-09-06T00:00:00Z")

        validate_error(response, "ERR_REMEDY_OUTAGE_CONFLICT")

    def test_the_day_after_the_buffer_schedules_normally(self):
        """One day past the closed window the discharge crew is free to test again.

        PRD: "A scheduled test is created with `status` `SCHEDULED`, `warranty_claim_triggered` false, `test_energy_throughput_mwh` 0.0, and `measured_capacity_mwh`, `measured_soh_pct`, `expected_soh_pct` and `soh_deficit_pct` all null; it returns HTTP 201."

        Design: Difficulty/resource_temporal_overlap/remedy_outage_window_is_closed_inclusive_with_trailing_buffer_against_capacity_tests
        """
        asset, test, claim = self._plant_awaiting_a_remedy()

        scheduled = validate_success(
            self._schedule(asset, "2026-09-07T00:00:00Z"), 201
        )

        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["warranty_claim_triggered"] is False
        assert scheduled["measured_capacity_mwh"] is None

    def test_only_the_accepted_scheduling_created_a_test(self):
        """Two collisions write nothing, leaving the completed test and the new one.

        PRD: "Checks run in a fixed order, and the first failing check decides the response; no later check runs, and no partial write survives a rejection."

        Design: Difficulty/resource_temporal_overlap/remedy_outage_window_is_closed_inclusive_with_trailing_buffer_against_capacity_tests
        """
        asset, test, claim = self._plant_awaiting_a_remedy()

        self._schedule(asset, "2026-09-01T00:00:00Z")
        self._schedule(asset, "2026-09-06T00:00:00Z")
        self._schedule(asset, "2026-09-07T00:00:00Z")

        rows, meta = validate_paginated(
            api_client.list_capacity_tests(ASSET_MANAGER, {"asset_id": asset["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["status"] for row in rows} == {"COMPLETED", "SCHEDULED"}
