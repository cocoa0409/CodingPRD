"""Two state machines that are not simple pipelines.

A storage asset carries a safety axis and a market axis that move on their own
schedules, and a market offer negotiates round a genuine cycle that terminates
on an exhausted revision allowance rather than on a terminal state.
"""
import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    CLOSING_OFFICER,
    CRITICAL_CLOSURE,
    TRADER,
    close_event,
    draft_bid,
    hold_reservation,
    open_safety_event,
    reference_plant,
    refresh_asset,
    refresh_bid,
    refresh_safety_event,
    run_revision_cycle,
    set_clock,
    submit_bid,
    unclear_bid,
)


class TestParallelSafetyAndMarketAxes:
    def test_an_advisory_event_moves_neither_axis(self):
        """Off-gas at 45 degrees is logged but imposes nothing on the plant's posture.

        PRD: "`THERMAL_RUNAWAY` imposes `LOCKOUT` whatever its severity, and for every other event type a `CRITICAL` severity imposes `ALARM`, a `WARNING` imposes `ELEVATED`, and an `ADVISORY` imposes `NONE` and therefore contributes nothing to the asset's posture."

        Design: Difficulty/non_linear_state_machine/storage_asset_parallel_safety_and_market_axes_move_independently
        """
        set_clock("2026-08-01T00:00:00Z")
        asset = reference_plant()

        event = open_safety_event(
            asset["id"],
            event_type="OFFGAS_DETECTED",
            severity="ADVISORY",
            detected_max_cell_temp_c=45.0,
        )
        after = refresh_asset(asset["id"])

        assert event["imposed_safety_state"] == "NONE"
        assert event["status"] == "OPEN"
        assert after["safety_state"] == "NORMAL"
        assert after["market_state"] == "AVAILABLE"

    def test_a_warning_derates_the_safety_axis_and_leaves_the_market_axis_alone(self):
        """A 66 degree thermal anomaly shrinks sellable power without suspending the market.

        PRD: "It is *derived*: it is the most severe `imposed_safety_state` among that asset's safety events whose `status` is `OPEN` or `SUPPRESSION_ACTIVE`, where severity ascends `NORMAL`, `ELEVATED`, `ALARM`, `LOCKOUT`."

        Design: Difficulty/non_linear_state_machine/storage_asset_parallel_safety_and_market_axes_move_independently
        """
        set_clock("2026-08-01T00:00:00Z")
        asset = reference_plant()
        open_safety_event(
            asset["id"],
            event_type="OFFGAS_DETECTED",
            severity="ADVISORY",
            detected_max_cell_temp_c=45.0,
        )

        warning = open_safety_event(
            asset["id"],
            event_type="THERMAL_ANOMALY",
            severity="WARNING",
            detected_max_cell_temp_c=66.0,
        )
        after = refresh_asset(asset["id"])

        assert warning["imposed_safety_state"] == "ELEVATED"
        assert after["safety_state"] == "ELEVATED"
        assert after["market_state"] == "AVAILABLE"
        assert after["suspension_reason"] is None

    def test_a_critical_alarm_suspends_the_market_axis(self):
        """Smoke at 70 degrees raises the safety axis to ALARM and pulls the plant out of the market.

        PRD: "Link two fires because the recomputed posture is `ALARM` or `LOCKOUT`: the asset's `market_state` moves `AVAILABLE → SUSPENDED`, `suspension_reason` becomes `SAFETY_ALARM` when the posture is `ALARM` and `SAFETY_LOCKOUT` when it is `LOCKOUT`, and `suspended_at` records the current logical instant."

        Design: Difficulty/non_linear_state_machine/storage_asset_parallel_safety_and_market_axes_move_independently
        """
        set_clock("2026-08-01T00:00:00Z")
        asset = reference_plant()

        critical = open_safety_event(
            asset["id"],
            event_type="SMOKE_DETECTED",
            severity="CRITICAL",
            detected_max_cell_temp_c=70.0,
        )
        after = refresh_asset(asset["id"])

        assert critical["imposed_safety_state"] == "ALARM"
        assert after["safety_state"] == "ALARM"
        assert after["market_state"] == "SUSPENDED"
        assert after["suspension_reason"] == "SAFETY_ALARM"

    def test_closing_the_critical_event_falls_back_to_the_remaining_warning(self):
        """With the alarm closed the posture falls to the still-open warning and the market resumes.

        PRD: "Whenever the recomputed posture is neither `ALARM` nor `LOCKOUT` and the asset was suspended, `market_state` moves `SUSPENDED → AVAILABLE`, `suspension_reason` and `suspended_at` return to null, and every capacity obligation of this asset whose `accrual_started_at` is not null closes its accrual: `unavailable_hours` becomes its previous value plus the number of hours between `accrual_started_at` and the current logical instant, rounded half up to 2 decimal places, and `accrual_started_at` returns to null."

        Design: Difficulty/non_linear_state_machine/storage_asset_parallel_safety_and_market_axes_move_independently
        """
        set_clock("2026-08-01T00:00:00Z")
        asset = reference_plant()
        advisory = open_safety_event(
            asset["id"],
            event_type="OFFGAS_DETECTED",
            severity="ADVISORY",
            detected_max_cell_temp_c=45.0,
        )
        warning = open_safety_event(
            asset["id"],
            event_type="THERMAL_ANOMALY",
            severity="WARNING",
            detected_max_cell_temp_c=66.0,
        )
        critical = open_safety_event(
            asset["id"],
            event_type="SMOKE_DETECTED",
            severity="CRITICAL",
            detected_max_cell_temp_c=70.0,
        )

        closed = close_event(critical["id"], headers=CLOSING_OFFICER, **CRITICAL_CLOSURE)
        after = refresh_asset(asset["id"])

        assert closed["status"] == "CLOSED"
        assert after["safety_state"] == "ELEVATED"
        assert after["market_state"] == "AVAILABLE"
        assert after["suspension_reason"] is None
        assert after["suspended_at"] is None
        assert refresh_safety_event(advisory["id"])["status"] == "OPEN"
        assert refresh_safety_event(warning["id"])["status"] == "OPEN"


class TestOfferNegotiationCycle:
    """A 20 MW day-ahead offer priced at 37.00 dollars, negotiated three times."""

    def _drafted_offer(self):
        set_clock("2026-08-01T00:00:00Z")
        asset = reference_plant()
        reservation = hold_reservation(asset["id"], reserved_mwh=40.0)
        bid = draft_bid(asset["id"], reservation["id"], offer_mw=20.0)
        return asset, bid

    def test_an_uncleared_offer_returns_to_draft_with_one_allowance_spent(self):
        """Failing to clear reopens the offer for re-pricing inside the same window.

        PRD: "Revision closes the negotiation loop `DRAFT → SUBMITTED → UNCLEARED → DRAFT`."

        Design: Difficulty/non_linear_state_machine/market_bid_revision_cycle_reaches_revision_limit
        """
        asset, bid = self._drafted_offer()

        assert bid["revision_count"] == 0
        assert bid["offer_price_usd_per_mwh"] == pytest.approx(37.00, abs=0.01)

        revised = run_revision_cycle(bid["id"], offer_mw=21.0)

        assert revised["status"] == "DRAFT"
        assert revised["revision_count"] == 1
        assert revised["offer_mw"] == pytest.approx(21.0, abs=0.01)
        assert revised["submitted_by_user_id"] is None

    def test_each_revision_recomputes_the_offer_footprint(self):
        """Re-offering 22 MW restates the booked energy at 88 MWh and the cycle debit at 0.44.

        PRD: "On success `revision_count` increases by one, whichever of `offer_mw` and `price_adder_usd_per_mwh` was supplied replaces the stored value, `submitted_by_user_id` returns to null, and `expected_energy_mwh`, `cycle_debit_efc` and `offer_price_usd_per_mwh` are recomputed against the asset's *current* `available_energy_mwh`, `equivalent_full_cycles_ytd` and `cumulative_throughput_mwh` — the cycle-scarcity multiplier that applies now may sit in a different tier from the one that applied at first submission."

        Design: Difficulty/non_linear_state_machine/market_bid_revision_cycle_reaches_revision_limit
        """
        asset, bid = self._drafted_offer()

        run_revision_cycle(bid["id"], offer_mw=21.0)
        second = run_revision_cycle(bid["id"], offer_mw=22.0)
        third = run_revision_cycle(bid["id"], price_adder_usd_per_mwh=2.00)

        assert second["revision_count"] == 2
        assert second["expected_energy_mwh"] == pytest.approx(88.0, abs=0.01)
        assert second["cycle_debit_efc"] == pytest.approx(0.44, abs=0.01)
        assert third["revision_count"] == 3
        assert third["offer_price_usd_per_mwh"] == pytest.approx(39.00, abs=0.01)

    def test_the_fourth_revision_is_refused_and_leaves_no_trace(self):
        """A three-times-revised offer must be withdrawn rather than re-priced again.

        PRD: "The loop is bounded: `revision_count` must be strictly below 3, so the fourth revision of the same offer is refused with `ERR_REVISION_LIMIT_REACHED` (HTTP 409) and the offer must be withdrawn instead."

        Design: Difficulty/non_linear_state_machine/market_bid_revision_cycle_reaches_revision_limit
        """
        asset, bid = self._drafted_offer()
        run_revision_cycle(bid["id"], offer_mw=21.0)
        run_revision_cycle(bid["id"], offer_mw=22.0)
        run_revision_cycle(bid["id"], price_adder_usd_per_mwh=2.00)
        submit_bid(bid["id"])
        unclear_bid(bid["id"])

        response = api_client.revise_market_bid(bid["id"], {"offer_mw": 23.0}, TRADER)

        validate_error(response, "ERR_REVISION_LIMIT_REACHED")
        after = refresh_bid(bid["id"])
        assert after["status"] == "UNCLEARED"
        assert after["revision_count"] == 3
        assert after["offer_mw"] == pytest.approx(22.0, abs=0.01)
