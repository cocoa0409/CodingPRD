"""Derived arithmetic and the immediacy of the writes it produces.

Every figure asserted here is recomputed from the PRD's own definitions, and
the reads that follow a write are issued straight afterwards, because the
platform's consistency model gives no window in which they could disagree.
"""
import pytest
from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import create_telemetry_sample_payload
from test_helpers.fixtures import (
    ASSET_MANAGER,
    DISPATCH_DAY_CLOCK,
    SAFETY_OFFICER,
    TRADER,
    append_sample,
    assess_obligation,
    cleared_bid,
    complete_dispatch,
    enrol_obligation,
    executing_dispatch,
    hold_reservation,
    provision_asset,
    record_unavailability,
    refresh_asset,
    refresh_dispatch,
    set_clock,
)
from test_helpers.test_users import make_site_controller_headers


def _executing_delivery(instructed_mw=20.0, setpoint_end="2026-08-10T15:00:00Z"):
    """Bring one plant to an executing 20 MW instruction on the delivery day."""
    set_clock(DISPATCH_DAY_CLOCK)
    asset = provision_asset()
    reservation = hold_reservation(
        asset["id"],
        reserved_mwh=40.0,
        window_start="2026-08-10T12:00:00Z",
        window_end="2026-08-10T20:00:00Z",
    )
    bid = cleared_bid(
        asset["id"],
        reservation["id"],
        cleared_price_usd_per_mwh=45.00,
        cleared_mw=instructed_mw,
        offer_mw=instructed_mw,
    )
    dispatch = executing_dispatch(
        bid["id"],
        asset["id"],
        instructed_mw=instructed_mw,
        setpoint_start="2026-08-10T14:00:00Z",
        setpoint_end=setpoint_end,
    )
    return asset, dispatch


class TestTelemetryVectorArithmetic:
    """A sample's apparent power is a vector magnitude, not a pair of scalars."""

    def test_apparent_power_is_the_vector_magnitude(self):
        """20.0 MW with 12.0 MVAr gives 23.324 MVA and clears both limits.

        PRD: "`apparent_mva` is the square root of the sum of the squares of `measured_mw` and `measured_mvar`, rounded half up to 3 decimal places."

        Design: Corner/calculations/telemetry_apparent_mva_and_deviation_correct_result
        """
        asset, dispatch = _executing_delivery()

        response = api_client.create_telemetry_sample(
            create_telemetry_sample_payload(
                dispatch["id"],
                1,
                "2026-08-10T14:15:00Z",
                measured_mw=20.0,
                measured_mvar=12.0,
                soc_mwh_reading=75.0,
                max_cell_temp_c=40.0,
            ),
            make_site_controller_headers(asset["id"]),
        )

        sample = validate_success(response, expected_status=201)
        assert sample["apparent_mva"] == pytest.approx(23.324, abs=0.01)

    def test_on_target_sample_has_no_deviation_and_sits_in_the_deadband(self):
        """A sample measuring exactly the instructed power scores a zero ratio.

        PRD: "`error_ratio` is `deviation_mw` divided by `instructed_mw`, rounded half up to 4 decimal places, and it is the per-sample term the performance score averages."

        Design: Corner/calculations/telemetry_apparent_mva_and_deviation_correct_result
        """
        asset, dispatch = _executing_delivery()

        sample = append_sample(
            dispatch["id"],
            asset["id"],
            1,
            "2026-08-10T14:15:00Z",
            measured_mw=20.0,
            measured_mvar=12.0,
            soc_mwh_reading=75.0,
            max_cell_temp_c=40.0,
        )

        assert sample["deviation_mw"] == pytest.approx(0.0, abs=0.01)
        assert sample["error_ratio"] == pytest.approx(0.0, abs=0.01)
        assert sample["within_deadband"] is True
        assert sample["thermal_escalation"] == "NONE"


class TestThermalWarningThreshold:
    """The warning band opens at 65.0 degrees and is inclusive at that mark."""

    def _sample_below_the_threshold(self):
        asset, dispatch = _executing_delivery()
        below = append_sample(
            dispatch["id"],
            asset["id"],
            1,
            "2026-08-10T14:15:00Z",
            measured_mw=20.0,
            soc_mwh_reading=75.0,
            max_cell_temp_c=64.99,
        )
        return asset, dispatch, below

    def _sample_at_the_threshold(self):
        asset, dispatch, below = self._sample_below_the_threshold()
        at = append_sample(
            dispatch["id"],
            asset["id"],
            2,
            "2026-08-10T14:30:00Z",
            measured_mw=20.0,
            soc_mwh_reading=70.0,
            max_cell_temp_c=65.0,
        )
        return asset, dispatch, at

    def test_one_hundredth_below_the_threshold_stays_in_band_none(self):
        """64.99 degrees is below the warning band and opens no event.

        PRD: "`thermal_escalation` bands the cell temperature: it is `RUNAWAY` when `max_cell_temp_c` is at or above 75.0 degrees Celsius, `WARNING` when it is at or above 65.0 degrees Celsius but below the runaway threshold, and `NONE` below 65.0."

        Design: Corner/calculations/thermal_band_constant_applied_at_exact_warning_threshold
        """
        asset, dispatch, below = self._sample_below_the_threshold()

        assert below["thermal_escalation"] == "NONE"

        plant = refresh_asset(asset["id"])
        assert plant["safety_state"] == "NORMAL"
        assert plant["market_state"] == "AVAILABLE"

        data, meta = validate_paginated(
            api_client.list_safety_events(SAFETY_OFFICER, params={"asset_id": asset["id"]})
        )
        assert meta["total_count"] == 0
        assert data == []

    def test_exactly_at_the_threshold_auto_opens_a_system_event(self):
        """65.0 degrees enters the warning band and the platform reports itself.

        PRD: "Either way the event's `source` is `TELEMETRY_AUTO`, its `opened_by_user_id` is the literal string `SYSTEM`, its `source_dispatch_id` is the sample's `dispatch_id` and its `source_sample_index` is the sample's `sample_index`."

        Design: Corner/calculations/thermal_band_constant_applied_at_exact_warning_threshold
        """
        asset, dispatch, at = self._sample_at_the_threshold()

        assert at["thermal_escalation"] == "WARNING"

        data, meta = validate_paginated(
            api_client.list_safety_events(SAFETY_OFFICER, params={"asset_id": asset["id"]})
        )
        assert meta["total_count"] == 1
        event = data[0]
        assert event["source"] == "TELEMETRY_AUTO"
        assert event["opened_by_user_id"] == "SYSTEM"
        assert event["event_type"] == "THERMAL_ANOMALY"
        assert event["severity"] == "WARNING"
        assert event["imposed_safety_state"] == "ELEVATED"
        assert event["source_dispatch_id"] == dispatch["id"]
        assert event["source_sample_index"] == 2

    def test_the_warning_band_derates_without_suspending_the_plant(self):
        """An elevated posture leaves the market axis alone.

        PRD: "On the `NORMAL → ELEVATED` transition — a `WARNING`-severity non-runaway event, or a telemetry sample crossing 65.0 degrees Celsius — `market_state` is untouched: an elevated posture derates the plant, it does not suspend it."

        Design: Corner/calculations/thermal_band_constant_applied_at_exact_warning_threshold
        """
        asset, dispatch, at = self._sample_at_the_threshold()

        plant = refresh_asset(asset["id"])
        assert plant["safety_state"] == "ELEVATED"
        assert plant["market_state"] == "AVAILABLE"
        assert plant["suspension_reason"] is None


class TestErrorRatioRoundingOrder:
    """The ratio is rounded to four places before the deadband compares it."""

    def _delivery_with_a_borderline_sample(self):
        asset, dispatch = _executing_delivery()
        first = append_sample(
            dispatch["id"],
            asset["id"],
            1,
            "2026-08-10T14:15:00Z",
            measured_mw=20.0,
            soc_mwh_reading=75.0,
            max_cell_temp_c=30.0,
        )
        second = append_sample(
            dispatch["id"],
            asset["id"],
            2,
            "2026-08-10T14:30:00Z",
            measured_mw=19.5996,
            soc_mwh_reading=70.1,
            max_cell_temp_c=30.0,
        )
        return asset, dispatch, first, second

    def test_deviation_rounds_to_three_places_before_the_ratio_is_formed(self):
        """A 19.5996 MW reading deviates by 0.400 MW, not by 0.4004 MW.

        PRD: "`deviation_mw` is the absolute difference between `measured_mw` and the instruction's `instructed_mw`, rounded half up to 3 decimal places."

        Design: Corner/calculations/error_ratio_rounding_precedes_the_deadband_comparison
        """
        asset, dispatch, first, second = self._delivery_with_a_borderline_sample()

        assert first["error_ratio"] == pytest.approx(0.0, abs=0.01)
        assert first["within_deadband"] is True
        assert second["deviation_mw"] == pytest.approx(0.4, abs=0.01)

    def test_the_rounded_ratio_lands_inside_the_deadband(self):
        """0.400 over 20.0 rounds to exactly 0.0200, which the deadband admits.

        PRD: "`within_deadband` is true when `error_ratio` is at most 0.02, inclusive at the boundary."

        Design: Corner/calculations/error_ratio_rounding_precedes_the_deadband_comparison
        """
        asset, dispatch, first, second = self._delivery_with_a_borderline_sample()

        assert second["error_ratio"] == pytest.approx(0.02, abs=0.0001)
        assert second["within_deadband"] is True

    def test_the_provisional_score_averages_the_rounded_ratios(self):
        """Both samples count as inside the band, so the composite reaches 99.30.

        PRD: "`deadband_pct` is the count of samples whose `within_deadband` is true divided by the total number of scored samples, multiplied by 100, rounded half up to 2 decimal places."

        Design: Corner/calculations/error_ratio_rounding_precedes_the_deadband_comparison
        """
        asset, dispatch, first, second = self._delivery_with_a_borderline_sample()

        completed = complete_dispatch(dispatch["id"], asset["id"])

        assert completed["accuracy_score"] == pytest.approx(99.00, abs=0.01)
        assert completed["deadband_pct"] == pytest.approx(100.00, abs=0.01)
        assert completed["composite_score"] == pytest.approx(99.30, abs=0.01)
        assert completed["non_performance_charge_usd"] == pytest.approx(0.00, abs=0.01)

    def test_the_delivery_credits_the_ledgers_from_the_measured_stream(self):
        """Two quarter-hour readings deliver 9.9 MWh and move the plant's books.

        PRD: "`equivalent_full_cycles_ytd` is `cumulative_throughput_mwh` divided by twice `available_energy_mwh`, rounded half up to 4 decimal places, and it is recomputed after every change to either input."

        Design: Corner/calculations/error_ratio_rounding_precedes_the_deadband_comparison
        """
        asset, dispatch, first, second = self._delivery_with_a_borderline_sample()

        completed = complete_dispatch(dispatch["id"], asset["id"])
        assert completed["delivered_mwh"] == pytest.approx(9.9, abs=0.01)

        plant = refresh_asset(asset["id"])
        assert plant["soc_mwh"] == pytest.approx(70.1, abs=0.01)
        assert plant["cumulative_throughput_mwh"] == pytest.approx(9.9, abs=0.01)
        assert plant["equivalent_full_cycles_ytd"] == pytest.approx(0.0495, abs=0.0001)


class TestAvailabilityTierBoundary:
    """The penalty multiplier's first tier is inclusive at 90.0 percent."""

    YEAR_END_CLOCK = "2026-12-31T00:00:00Z"

    def _obligation_at_the_tier_boundary(self):
        set_clock(self.YEAR_END_CLOCK)
        asset = provision_asset()
        obligation = enrol_obligation(
            asset["id"],
            program_name="PJM RPM",
            program_year=2026,
            committed_mw=20.0,
            availability_hours_required=8000.0,
            penalty_rate_usd_per_mw_hour=150.00,
        )
        return asset, obligation

    def test_recording_unavailability_does_not_assess(self):
        """Posted hours accumulate while every assessed figure waits.

        PRD: "That operation adds the delta to `unavailable_hours`, rounding the result half up to 2 decimal places, and does nothing else: `availability_pct`, `shortfall_hours`, `penalty_exposure_usd` and `status` all keep the values the last assessment left them with until an assessment is actually run."

        Design: Corner/calculations/availability_pct_exactly_at_tier_one_threshold_uses_unit_multiplier
        """
        asset, obligation = self._obligation_at_the_tier_boundary()

        assert obligation["status"] == "ACTIVE"
        assert obligation["unavailable_hours"] == pytest.approx(0.0, abs=0.01)

        posted = record_unavailability(obligation["id"], 876.0, reason="FORCED_OUTAGE")

        assert posted["unavailable_hours"] == pytest.approx(876.0, abs=0.01)
        assert posted["availability_pct"] is None

    def test_availability_exactly_at_tier_one_uses_the_unit_multiplier(self):
        """90.00 percent availability is inside the first tier, so nothing scales.

        PRD: "The penalty multiplier is tiered on availability, with each tier boundary inclusive on its upper side: it is 1.0 when `availability_pct` is at least 90.0, 1.5 when `availability_pct` is below 90.0 but at least 80.0, and 2.0 when `availability_pct` is below 80.0."

        Design: Corner/calculations/availability_pct_exactly_at_tier_one_threshold_uses_unit_multiplier
        """
        asset, obligation = self._obligation_at_the_tier_boundary()
        record_unavailability(obligation["id"], 876.0, reason="FORCED_OUTAGE")

        assessed = assess_obligation(obligation["id"], mode="FINAL")

        assert assessed["measured_available_hours"] == pytest.approx(7884.0, abs=0.01)
        assert assessed["availability_pct"] == pytest.approx(90.0, abs=0.01)
        assert assessed["shortfall_hours"] == pytest.approx(116.0, abs=0.01)
        assert assessed["penalty_exposure_usd"] == pytest.approx(348000.00, abs=0.01)
        assert assessed["status"] == "SHORTFALL"
        assert assessed["assessment_mode"] == "FINAL"
        assert assessed["derated_committed_mw"] is None

    def test_one_tenth_below_the_tier_raises_the_multiplier_and_the_status(self):
        """Nine more unavailable hours drop the plant a tier and penalise it.

        PRD: "An assessment producing positive shortfall hours settles the obligation as `SHORTFALL` when `availability_pct` is at least 90.0 and as `PENALIZED` when it is below that tier."

        Design: Corner/calculations/availability_pct_exactly_at_tier_one_threshold_uses_unit_multiplier
        """
        asset, obligation = self._obligation_at_the_tier_boundary()
        record_unavailability(obligation["id"], 876.0, reason="FORCED_OUTAGE")
        assess_obligation(obligation["id"], mode="FINAL")

        second_post = record_unavailability(
            obligation["id"], 9.0, reason="FORCED_OUTAGE"
        )
        assert second_post["unavailable_hours"] == pytest.approx(885.0, abs=0.01)

        assessed = assess_obligation(obligation["id"], mode="FINAL")

        assert assessed["measured_available_hours"] == pytest.approx(7875.0, abs=0.01)
        assert assessed["availability_pct"] == pytest.approx(89.9, abs=0.01)
        assert assessed["shortfall_hours"] == pytest.approx(125.0, abs=0.01)
        assert assessed["penalty_exposure_usd"] == pytest.approx(562500.00, abs=0.01)
        assert assessed["status"] == "PENALIZED"


class TestCompletionCarriesTheSettledLedger:
    """Completion returns the derived quantities in its own response body."""

    def _delivery_ready_to_complete(self):
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        reservation = hold_reservation(
            asset["id"],
            reserved_mwh=40.0,
            window_start="2026-08-10T12:00:00Z",
            window_end="2026-08-10T20:00:00Z",
        )
        bid = cleared_bid(
            asset["id"],
            reservation["id"],
            cleared_price_usd_per_mwh=45.00,
            cleared_mw=10.0,
            offer_mw=10.0,
        )
        dispatch = executing_dispatch(
            bid["id"],
            asset["id"],
            instructed_mw=10.0,
            setpoint_start="2026-08-10T12:00:00Z",
            setpoint_end="2026-08-10T14:00:00Z",
        )
        append_sample(
            dispatch["id"],
            asset["id"],
            1,
            "2026-08-10T13:00:00Z",
            measured_mw=10.0,
            measured_mvar=4.0,
            soc_mwh_reading=78.0,
            max_cell_temp_c=40.0,
        )
        return asset, dispatch

    def test_completion_response_already_carries_its_derived_quantities(self):
        """Nothing in the completion body waits for a later aggregation pass.

        PRD: "The scoring axis moves `NOT_SCORED → PROVISIONAL` and the provisional variant of the performance score is applied."

        Design: Corner/consistency_model/completion_response_already_carries_the_settled_ledger
        """
        asset, dispatch = self._delivery_ready_to_complete()

        completed = complete_dispatch(dispatch["id"], asset["id"])

        assert completed["execution_status"] == "COMPLETED"
        assert completed["scoring_status"] == "PROVISIONAL"
        assert completed["delivered_mwh"] == pytest.approx(2.5, abs=0.01)
        assert completed["soc_delta_mwh"] == pytest.approx(-2.5, abs=0.01)
        assert completed["composite_score"] == pytest.approx(100.00, abs=0.01)

    def test_the_asset_read_that_follows_agrees_with_the_completion(self):
        """The plant's ledgers already carry the delivery when the next read lands.

        PRD: "The asset's `soc_mwh` becomes its previous value plus `soc_delta_mwh`, rounded half up to 3 decimal places."

        Design: Corner/consistency_model/completion_response_already_carries_the_settled_ledger
        """
        asset, dispatch = self._delivery_ready_to_complete()

        complete_dispatch(dispatch["id"], asset["id"])

        plant = refresh_asset(asset["id"])
        assert plant["soc_mwh"] == pytest.approx(77.5, abs=0.01)
        assert plant["cumulative_throughput_mwh"] == pytest.approx(2.5, abs=0.01)
        assert plant["equivalent_full_cycles_ytd"] == pytest.approx(0.0125, abs=0.0001)

    def test_the_instruction_read_repeats_its_own_write(self):
        """Reading the instruction back returns the figures completion produced.

        PRD: "Delivered energy is aggregated from on-time telemetry only: taking the samples of this instruction whose `sampled_at` is at or before `setpoint_end`, `delivered_mwh` is the sum of each sample's `measured_mw` multiplied by a fixed sample width of one quarter of an hour, rounded half up to 3 decimal places."

        Design: Corner/consistency_model/completion_response_already_carries_the_settled_ledger
        """
        asset, dispatch = self._delivery_ready_to_complete()

        completed = complete_dispatch(dispatch["id"], asset["id"])
        stored = refresh_dispatch(completed["id"], headers=ASSET_MANAGER)

        assert stored["delivered_mwh"] == pytest.approx(completed["delivered_mwh"], abs=0.01)
        assert stored["composite_score"] == pytest.approx(completed["composite_score"], abs=0.01)


class TestReservationIsVisibleInTheAggregatesImmediately:
    """A hold shows up in the plant's aggregates on the very next read."""

    def test_the_pool_is_empty_before_the_hold(self):
        """A freshly commissioned plant reserves nothing and offers 70.0 MWh.

        PRD: "`reserved_mwh_total` starts at 0.0."

        Design: Corner/consistency_model/reservation_write_is_visible_in_the_asset_aggregates_immediately
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()

        assert asset["reserved_mwh_total"] == pytest.approx(0.0, abs=0.01)
        assert asset["free_dispatchable_mwh"] == pytest.approx(70.0, abs=0.01)

    def test_the_hold_is_created_held_at_its_purpose_rank(self):
        """The create response is the reservation, ranked by its purpose.

        PRD: "A new reservation is created with `status` `HELD`, `consumed_mwh` of 0.0 and `released_reason` of null, and the response is HTTP 201."

        Design: Corner/consistency_model/reservation_write_is_visible_in_the_asset_aggregates_immediately
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()

        reservation = hold_reservation(
            asset["id"],
            purpose="ENERGY_ARBITRAGE",
            reserved_mwh=40.0,
            window_start="2026-08-10T12:00:00Z",
            window_end="2026-08-10T20:00:00Z",
        )

        assert reservation["status"] == "HELD"
        assert reservation["priority_rank"] == 3

    def test_the_next_asset_read_shows_the_hold_and_the_bumped_version(self):
        """No lag and no re-read loop: the aggregates move with the write.

        PRD: "The asset's `reserved_mwh_total` and `free_dispatchable_mwh` are recomputed and its `version` increases by one."

        Design: Corner/consistency_model/reservation_write_is_visible_in_the_asset_aggregates_immediately
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        version_before = asset["version"]

        reservation = hold_reservation(
            asset["id"],
            reserved_mwh=40.0,
            window_start="2026-08-10T12:00:00Z",
            window_end="2026-08-10T20:00:00Z",
        )

        plant = refresh_asset(asset["id"])
        assert plant["reserved_mwh_total"] == pytest.approx(40.0, abs=0.01)
        assert plant["free_dispatchable_mwh"] == pytest.approx(30.0, abs=0.01)
        assert plant["version"] == version_before + 1

        data, meta = validate_paginated(
            api_client.list_soc_reservations(
                TRADER,
                params={
                    "asset_id": asset["id"],
                    "status": "HELD",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in data] == [reservation["id"]]
