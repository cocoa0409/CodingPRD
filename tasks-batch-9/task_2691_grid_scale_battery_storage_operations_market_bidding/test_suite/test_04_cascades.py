"""Two deep cascades: an ingested measurement and a completed capacity test.

One runaway telemetry sample must unwind the plant's whole market position, and
one capacity test must restate the plant's energy, its capacity obligation and
every offer still in draft.
"""
from datetime import datetime

import pytest
from prd_bench_local_runner.testing import validate_paginated

from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    ASSET_MANAGER,
    MARKET_OPERATOR,
    accept_dispatch,
    append_sample,
    cleared_bid,
    draft_bid,
    enrol_obligation,
    execute_dispatch,
    hold_reservation,
    issue_dispatch,
    refresh_asset,
    refresh_bid,
    refresh_dispatch,
    refresh_obligation,
    refresh_reservation,
    reference_plant,
    set_clock,
    short_warranty_plant,
    start_test,
    finish_test,
    schedule_test,
    submitted_bid,
)


def _instant(value):
    """The instant an ISO 8601 UTC timestamp denotes.

    The PRD pins three fractional digits for `created_at` and `updated_at` only;
    for the cascade's own stamps it says the field "records the current logical
    instant", so these assertions compare instants rather than spellings.
    """
    assert isinstance(value, str), f"expected an ISO 8601 UTC string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _live_market_position():
    """A plant with two offers, two reservations and two instructions in flight."""
    set_clock("2026-08-10T00:00:00Z")
    asset = reference_plant()
    obligation = enrol_obligation(
        asset["id"],
        headers=MARKET_OPERATOR,
        program_name="RA-2026",
        program_year=2026,
        committed_mw=20.0,
        availability_hours_required=8000.0,
        penalty_rate_usd_per_mw_hour=150.00,
        obligation_duration_hours=4.0,
    )
    arbitrage = hold_reservation(
        asset["id"],
        purpose="ENERGY_ARBITRAGE",
        reserved_mwh=40.0,
        window_start="2026-08-10T12:00:00Z",
        window_end="2026-08-10T20:00:00Z",
    )
    day_ahead = cleared_bid(asset["id"], arbitrage["id"], offer_mw=20.0)
    executing = issue_dispatch(
        day_ahead["id"],
        asset["id"],
        instructed_mw=20.0,
        setpoint_start="2026-08-10T14:00:00Z",
        setpoint_end="2026-08-10T15:00:00Z",
    )
    accept_dispatch(executing["id"])
    execute_dispatch(executing["id"], asset["id"])
    pending = issue_dispatch(
        day_ahead["id"],
        asset["id"],
        instructed_mw=10.0,
        setpoint_start="2026-08-10T15:00:00Z",
        setpoint_end="2026-08-10T16:00:00Z",
    )
    ancillary = hold_reservation(
        asset["id"],
        purpose="ANCILLARY",
        reserved_mwh=20.0,
        window_start="2026-08-11T00:00:00Z",
        window_end="2026-08-11T08:00:00Z",
    )
    real_time = submitted_bid(
        asset["id"],
        ancillary["id"],
        market_type="REAL_TIME",
        product="REG_UP",
        direction="DISCHARGE",
        delivery_start="2026-08-11T00:00:00Z",
        delivery_end="2026-08-11T04:00:00Z",
        offer_mw=5.0,
    )
    set_clock("2026-08-10T14:20:00Z")
    return {
        "asset": asset,
        "obligation": obligation,
        "arbitrage": arbitrage,
        "ancillary": ancillary,
        "day_ahead": day_ahead,
        "real_time": real_time,
        "executing": executing,
        "pending": pending,
    }


def _auto_events(asset_id):
    """Every safety event the platform opened for itself on this asset."""
    response = api_client.list_safety_events(ASSET_MANAGER, {"asset_id": asset_id})
    events, _meta = validate_paginated(response)
    return [event for event in events if event["source"] == "TELEMETRY_AUTO"]


def _runaway_sample(position):
    """The 80 degree measurement that starts the cascade."""
    return append_sample(
        position["executing"]["id"],
        position["asset"]["id"],
        1,
        "2026-08-10T14:15:00Z",
        measured_mw=20.0,
        measured_mvar=0.0,
        soc_mwh_reading=75.0,
        max_cell_temp_c=80.0,
    )


class TestTelemetryRunawayCascade:
    def test_a_runaway_reading_opens_a_system_reported_safety_event(self):
        """An 80 degree cell temperature bands as RUNAWAY and files its own critical event.

        PRD: "Either way the event's `source` is `TELEMETRY_AUTO`, its `opened_by_user_id` is the literal string `SYSTEM`, its `source_dispatch_id` is the sample's `dispatch_id` and its `source_sample_index` is the sample's `sample_index`."

        Design: Difficulty/transitive_cascade/telemetry_runaway_cascades_six_levels_through_bids_reservations_dispatches_and_obligation
        """
        position = _live_market_position()

        sample = _runaway_sample(position)

        assert sample["thermal_escalation"] == "RUNAWAY"
        assert sample["apparent_mva"] == pytest.approx(20.0, abs=0.01)
        auto_events = _auto_events(position["asset"]["id"])
        assert len(auto_events) == 1
        event = auto_events[0]
        assert event["source"] == "TELEMETRY_AUTO"
        assert event["event_type"] == "THERMAL_RUNAWAY"
        assert event["severity"] == "CRITICAL"
        assert event["opened_by_user_id"] == "SYSTEM"
        assert event["imposed_safety_state"] == "LOCKOUT"
        assert event["source_dispatch_id"] == position["executing"]["id"]
        assert event["source_sample_index"] == 1

    def test_the_lockout_suspends_the_plant_from_the_market(self):
        """The imposed lockout pulls the plant out of the market and timestamps the suspension.

        PRD: "Link two fires because the recomputed posture is `ALARM` or `LOCKOUT`: the asset's `market_state` moves `AVAILABLE → SUSPENDED`, `suspension_reason` becomes `SAFETY_ALARM` when the posture is `ALARM` and `SAFETY_LOCKOUT` when it is `LOCKOUT`, and `suspended_at` records the current logical instant."

        Design: Difficulty/transitive_cascade/telemetry_runaway_cascades_six_levels_through_bids_reservations_dispatches_and_obligation
        """
        position = _live_market_position()

        _runaway_sample(position)
        after = refresh_asset(position["asset"]["id"])

        assert after["safety_state"] == "LOCKOUT"
        assert after["market_state"] == "SUSPENDED"
        assert after["suspension_reason"] == "SAFETY_LOCKOUT"
        assert _instant(after["suspended_at"]) == _instant("2026-08-10T14:20:00Z")

    def test_suspension_withdraws_every_live_offer_and_releases_their_energy(self):
        """Both the cleared day-ahead offer and the submitted regulation offer are withdrawn.

        PRD: "Link four fires because those offers became `WITHDRAWN`: each withdrawn offer's backing reservation, if its `status` is `HELD`, moves to `RELEASED` with `released_reason` of `BID_WITHDRAWN`, and the asset's `reserved_mwh_total` and `free_dispatchable_mwh` are recomputed."

        Design: Difficulty/transitive_cascade/telemetry_runaway_cascades_six_levels_through_bids_reservations_dispatches_and_obligation
        """
        position = _live_market_position()
        before = refresh_asset(position["asset"]["id"])

        _runaway_sample(position)

        assert before["reserved_mwh_total"] == pytest.approx(60.0, abs=0.01)
        assert before["free_dispatchable_mwh"] == pytest.approx(10.0, abs=0.01)
        for bid_id in (position["day_ahead"]["id"], position["real_time"]["id"]):
            bid = refresh_bid(bid_id)
            assert bid["status"] == "WITHDRAWN"
            assert bid["withdrawn_reason"] == "ASSET_SUSPENDED"
        for reservation_id in (
            position["arbitrage"]["id"],
            position["ancillary"]["id"],
        ):
            reservation = refresh_reservation(reservation_id)
            assert reservation["status"] == "RELEASED"
            assert reservation["released_reason"] == "BID_WITHDRAWN"
        after = refresh_asset(position["asset"]["id"])
        assert after["reserved_mwh_total"] == pytest.approx(0.0, abs=0.01)
        assert after["free_dispatchable_mwh"] == pytest.approx(70.0, abs=0.01)

    def test_suspension_fails_live_instructions_and_opens_the_availability_accrual(self):
        """The executing and pending instructions both fail, and the capacity clock starts.

        PRD: "Link six fires because `market_state` is now `SUSPENDED`: every capacity obligation of this asset whose `status` is `ACTIVE`, `SHORTFALL` or `PENALIZED` and whose `program_year` equals the calendar year of the current logical instant has its `accrual_started_at` set to that instant, opening an unavailability accrual."

        Design: Difficulty/transitive_cascade/telemetry_runaway_cascades_six_levels_through_bids_reservations_dispatches_and_obligation
        """
        position = _live_market_position()

        _runaway_sample(position)

        for dispatch_id in (position["executing"]["id"], position["pending"]["id"]):
            dispatch = refresh_dispatch(dispatch_id)
            assert dispatch["execution_status"] == "FAILED"
            assert dispatch["failure_reason"] == "ASSET_SUSPENDED"
        obligation = refresh_obligation(position["obligation"]["id"])
        assert _instant(obligation["accrual_started_at"]) == _instant(
            "2026-08-10T14:20:00Z"
        )
        assert obligation["unavailable_hours"] == pytest.approx(0.0, abs=0.01)
        assert obligation["status"] == "ACTIVE"


def _tested_plant():
    """A short-warranty plant carrying an obligation and a drafted offer."""
    set_clock("2026-08-01T00:00:00Z")
    asset = short_warranty_plant()
    obligation = enrol_obligation(
        asset["id"],
        program_name="RA-2026",
        program_year=2026,
        committed_mw=24.0,
        availability_hours_required=8000.0,
        penalty_rate_usd_per_mw_hour=150.00,
        obligation_duration_hours=4.0,
    )
    reservation = hold_reservation(asset["id"], reserved_mwh=40.0)
    bid = draft_bid(asset["id"], reservation["id"], offer_mw=20.0)
    test = schedule_test(asset["id"], scheduled_date="2026-08-01T00:00:00Z")
    start_test(test["id"], asset["id"])
    return {
        "asset": asset,
        "obligation": obligation,
        "bid": bid,
        "test": test,
    }


class TestCapacityTestCompletionCascade:
    def test_completion_writes_the_degradation_verdict(self):
        """A 90 MWh discharge beats the warranty floor of 80 percent, so nothing is claimable.

        PRD: "Completion then cascades in four links. Link one writes the test's `expected_soh_pct`, `measured_soh_pct`, `soh_deficit_pct` and `warranty_claim_triggered` in the pinned order above."

        Design: Difficulty/transitive_cascade/capacity_test_completion_cascades_four_levels_into_obligation_deration_and_draft_bid_reprice
        """
        plant = _tested_plant()

        completed = finish_test(
            plant["test"]["id"], plant["asset"]["id"], measured_capacity_mwh=90.0
        )

        assert completed["status"] == "COMPLETED"
        assert completed["expected_soh_pct"] == pytest.approx(80.00, abs=0.01)
        assert completed["measured_soh_pct"] == pytest.approx(90.00, abs=0.01)
        assert completed["soh_deficit_pct"] == pytest.approx(0.00, abs=0.01)
        assert completed["warranty_claim_triggered"] is False
        assert completed["test_energy_throughput_mwh"] == pytest.approx(90.0, abs=0.01)

    def test_completion_restates_the_plant_energy_ledger(self):
        """State of health drops to 90 percent, available energy to 90 MWh, cycles to 0.9444.

        PRD: "Link two fires because the test completed: the asset's `soh_pct` becomes the test's `measured_soh_pct`, its `cumulative_throughput_mwh` takes the test's throughput credit, and then `available_energy_mwh` and `equivalent_full_cycles_ytd` are recomputed in that order, with `free_dispatchable_mwh` recomputed last of all, after `available_energy_mwh`."

        Design: Difficulty/transitive_cascade/capacity_test_completion_cascades_four_levels_into_obligation_deration_and_draft_bid_reprice
        """
        plant = _tested_plant()

        finish_test(plant["test"]["id"], plant["asset"]["id"], measured_capacity_mwh=90.0)
        after = refresh_asset(plant["asset"]["id"])

        assert plant["asset"]["available_energy_mwh"] == pytest.approx(100.0, abs=0.01)
        assert plant["asset"]["equivalent_full_cycles_ytd"] == pytest.approx(0.4, abs=0.01)
        assert after["soh_pct"] == pytest.approx(90.00, abs=0.01)
        assert after["cumulative_throughput_mwh"] == pytest.approx(170.0, abs=0.01)
        assert after["available_energy_mwh"] == pytest.approx(90.0, abs=0.01)
        assert after["equivalent_full_cycles_ytd"] == pytest.approx(0.9444, abs=0.01)

    def test_shrunken_available_energy_derates_the_capacity_obligation(self):
        """A 24 MW commitment no longer fits four hours of 90 MWh, so the obligation derates.

        PRD: "Link three fires because `available_energy_mwh` changed: every capacity obligation of this asset whose `status` is `ACTIVE` or `SHORTFALL` and whose `committed_mw` is now strictly greater than `available_energy_mwh` divided by `obligation_duration_hours` moves to `SHORTFALL`, records `derated_committed_mw` as `available_energy_mwh` divided by `obligation_duration_hours` rounded half up to 3 decimal places, and has its `penalty_exposure_usd` recomputed under the `PRELIMINARY` variant, processed in ascending `program_year` order and, among ties, ascending `created_at`."

        Design: Difficulty/transitive_cascade/capacity_test_completion_cascades_four_levels_into_obligation_deration_and_draft_bid_reprice
        """
        plant = _tested_plant()

        finish_test(plant["test"]["id"], plant["asset"]["id"], measured_capacity_mwh=90.0)
        obligation = refresh_obligation(plant["obligation"]["id"])

        assert plant["obligation"]["status"] == "ACTIVE"
        assert plant["obligation"]["derated_committed_mw"] is None
        assert obligation["status"] == "SHORTFALL"
        assert obligation["derated_committed_mw"] == pytest.approx(22.5, abs=0.01)
        # Link three enumerates exactly three effects — the status move, the
        # derated commitment and the recomputed exposure — so `assessment_mode`
        # and `availability_pct` are not asserted here: the PRD writes them in
        # the assess operation of §3.8, not in this cascade.
        assert obligation["shortfall_hours"] == pytest.approx(0.0, abs=0.01)
        assert obligation["penalty_exposure_usd"] == pytest.approx(0.00, abs=0.01)

    def test_drafted_offers_are_repriced_against_the_new_plant_figures(self):
        """The drafted offer's floor climbs from 37.00 to 42.60 as the warranty adder switches on.

        PRD: "Link four fires because `available_energy_mwh`, `cumulative_throughput_mwh` and `equivalent_full_cycles_ytd` all changed: every offer of this asset whose `status` is `DRAFT` has its `offer_price_usd_per_mwh`, `expected_energy_mwh` and `cycle_debit_efc` recomputed, processed in ascending `delivery_start` order and, among ties, ascending `created_at`."

        Design: Difficulty/transitive_cascade/capacity_test_completion_cascades_four_levels_into_obligation_deration_and_draft_bid_reprice
        """
        plant = _tested_plant()

        finish_test(plant["test"]["id"], plant["asset"]["id"], measured_capacity_mwh=90.0)
        bid = refresh_bid(plant["bid"]["id"])

        assert plant["bid"]["offer_price_usd_per_mwh"] == pytest.approx(37.00, abs=0.01)
        assert plant["bid"]["cycle_debit_efc"] == pytest.approx(0.4, abs=0.01)
        assert bid["status"] == "DRAFT"
        assert bid["offer_price_usd_per_mwh"] == pytest.approx(42.60, abs=0.01)
        assert bid["cycle_debit_efc"] == pytest.approx(0.4444, abs=0.01)
