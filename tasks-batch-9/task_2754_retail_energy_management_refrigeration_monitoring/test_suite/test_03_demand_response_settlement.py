"""Demand-response settlement: per-interval rounding and the incentive ledger."""
import pytest

from prd_bench_local_runner.testing import get_success_data
from test_helpers import factories as f, fixtures as fx
from test_helpers.test_users import make_energy_manager_headers

TOU_RATES = {
    "utility_name": "Midland Power",
    "rate_schedule_code": "TOU-GS3",
    "rate_family": "TOU_DEMAND",
    "demand_charge_per_kw": 14.50,
    "rate_on_peak": 0.1450,
    "rate_off_peak": 0.0800,
}

# Three eligible on-peak non-event intervals: mean 1270.17 kW.
BASELINE_INTERVALS = [
    f.demand_interval("2026-08-04T14:00:00Z", 1290.5, True),
    f.demand_interval("2026-08-04T15:00:00Z", 1275.0, True),
    f.demand_interval("2026-08-04T16:00:00Z", 1245.0, True),
]

# Four quarter-hour intervals inside the curtailment window.
WINDOW_INTERVALS = [
    f.demand_interval("2026-08-05T14:00:00Z", 1050.0, True, is_dr_event_day=True),
    f.demand_interval("2026-08-05T14:15:00Z", 1020.5, True, is_dr_event_day=True),
    f.demand_interval("2026-08-05T14:30:00Z", 1100.0, True, is_dr_event_day=True),
    f.demand_interval("2026-08-05T14:45:00Z", 1080.0, True, is_dr_event_day=True),
]

EVENT = {
    "program_code": "CPP-2026",
    "curtailment_start_iso": "2026-08-05T14:00:00Z",
    "curtailment_end_iso": "2026-08-05T15:00:00Z",
    "target_reduction_kw": 200.0,
}


def _completed_over_performing_event(api, store_code, extra_intervals=()):
    """A notified, activated and clock-completed event over an over-performing run."""
    ctx = fx.setup_commissioned_store(api, code=store_code)
    account = fx.create_account(api, ctx["store_id"], **TOU_RATES)
    fx.ingest_intervals(
        api, account["id"], BASELINE_INTERVALS + list(extra_intervals) + WINDOW_INTERVALS
    )
    event = fx.create_event(api, account["id"], **EVENT)
    ctx["account"] = account
    ctx["account_id"] = account["id"]
    ctx["event_id"] = event["id"]
    ctx["notified"] = fx.notify_event(api, event["id"])
    fx.set_clock(api, EVENT["curtailment_start_iso"])
    fx.activate_event(api, event["id"])
    fx.set_clock(api, EVENT["curtailment_end_iso"])
    return ctx


class TestSettlementRoundsEachIntervalBeforeSumming:
    def test_delivered_total_sums_already_rounded_per_interval_figures(self, api):
        """Rounding per interval yields 207.54, not the 207.55 of one final round.

        The PRD states: "`total_reduction_kwh` is the sum of those already-rounded
        per-interval figures — the rounding happens per interval and the sum is
        exact, which is not the same answer as summing the raw products and
        rounding once at the end."

        Design: Difficulty/combinatorial_formula/dr_settlement_round_per_interval_then_sum
        """
        ctx = _completed_over_performing_event(
            api,
            "STR-CF2",
            extra_intervals=[
                f.demand_interval("2026-08-03T14:00:00Z", 1500.0, True, is_dr_event_day=True),
                f.demand_interval("2026-08-04T02:00:00Z", 1600.0, False),
            ],
        )

        assert ctx["notified"]["baseline_kw"] == pytest.approx(1270.17, abs=0.01)

        settled = fx.settle_event(api, ctx["event_id"])

        assert settled["total_reduction_kwh"] == pytest.approx(207.54, abs=0.001)
        assert settled["total_reduction_kwh"] != pytest.approx(207.55, abs=0.001)
        assert settled["event_state"] == "COMPLETED"
        assert settled["settlement_state"] == "SETTLED"

    def test_performance_and_incentive_follow_the_rounded_total(self, api):
        """Obligation, performance and incentive all descend from 207.54 kWh.

        The PRD states: "The contracted obligation over the same window is
        `target_reduction_kw` multiplied by a quarter of an hour and by the number
        of intervals in the settlement set, rounded half up to two decimal places,
        and `performance_pct` is the delivered total divided by that obligation,
        multiplied by one hundred and rounded half up to one decimal place."

        Design: Difficulty/combinatorial_formula/dr_settlement_round_per_interval_then_sum
        """
        ctx = _completed_over_performing_event(api, "STR-CF2")

        settled = fx.settle_event(api, ctx["event_id"])

        # 200.0 kW x 0.25 h x 4 intervals = 200.00 kWh of obligation.
        assert settled["performance_pct"] == pytest.approx(103.8, abs=0.05)
        assert settled["incentive_usd"] == pytest.approx(87.17, abs=0.01)
        assert settled["penalty_usd"] == pytest.approx(0.00, abs=0.01)

    def test_the_settlement_credits_the_account_ledger(self, api):
        """Settlement credits dr_incentive_accrued_usd by exactly the incentive.

        The PRD states: "On settlement the account's `dr_incentive_accrued_usd` is
        credited by exactly `incentive_usd`; that ledger must at all times equal
        the sum of `incentive_usd` across the account's events whose
        `settlement_state` is `SETTLED`."

        Design: Difficulty/combinatorial_formula/dr_settlement_round_per_interval_then_sum
        """
        ctx = _completed_over_performing_event(api, "STR-CF2")

        settled = fx.settle_event(api, ctx["event_id"])
        account = fx.read_account(api, ctx["account_id"])

        assert account["dr_incentive_accrued_usd"] == pytest.approx(87.17, abs=0.01)
        assert account["dr_incentive_accrued_usd"] == pytest.approx(
            settled["incentive_usd"], abs=0.01
        )


class TestIncentiveLedgerConservedOnReversal:
    def test_reversal_debits_exactly_what_the_settlement_credited(self, api):
        """The ledger returns to 0.00 with no rounding drift.

        The PRD states: "The reversal debits the account's
        `dr_incentive_accrued_usd` by exactly the amount that event credited,
        which keeps the ledger identity intact, and it deliberately retains
        `incentive_usd`, `penalty_usd` and `performance_pct` on the event as
        evidence of what was originally computed."

        Design: Difficulty/compensating_invariant/dr_incentive_ledger_conserved_on_settlement_reversal
        """
        ctx = _completed_over_performing_event(api, "STR-CI1")
        assert ctx["account"]["dr_incentive_accrued_usd"] == pytest.approx(0.00, abs=0.01)

        fx.settle_event(api, ctx["event_id"])
        after_settle = fx.read_account(api, ctx["account_id"])
        assert after_settle["dr_incentive_accrued_usd"] == pytest.approx(87.17, abs=0.01)

        get_success_data(
            api.reverse_demand_response_settlement(
                ctx["event_id"],
                f.reversal_payload("interval data restated by the utility"),
                make_energy_manager_headers("u_manager_ci1"),
            )
        )
        after_reversal = fx.read_account(api, ctx["account_id"])

        assert after_reversal["dr_incentive_accrued_usd"] == pytest.approx(0.00, abs=0.001)
        assert after_reversal["dr_incentive_accrued_usd"] >= 0.0

    def test_reversal_retains_the_original_settlement_evidence(self, api):
        """The event keeps its incentive, penalty and performance after reversal.

        The PRD states: "The participation dimension stays at `COMPLETED`
        throughout." and the reversal "deliberately retains `incentive_usd`,
        `penalty_usd` and `performance_pct` on the event as evidence of what was
        originally computed."

        Design: Difficulty/compensating_invariant/dr_incentive_ledger_conserved_on_settlement_reversal
        """
        ctx = _completed_over_performing_event(api, "STR-CI1")
        fx.settle_event(api, ctx["event_id"])

        reversed_event = get_success_data(
            api.reverse_demand_response_settlement(
                ctx["event_id"],
                f.reversal_payload("interval data restated by the utility"),
                make_energy_manager_headers("u_manager_ci1"),
            )
        )

        assert reversed_event["settlement_state"] == "REVERSED"
        assert reversed_event["event_state"] == "COMPLETED"
        assert reversed_event["incentive_usd"] == pytest.approx(87.17, abs=0.01)
        assert reversed_event["penalty_usd"] == pytest.approx(0.00, abs=0.01)
        assert reversed_event["performance_pct"] == pytest.approx(103.8, abs=0.05)
        assert reversed_event["total_reduction_kwh"] == pytest.approx(207.54, abs=0.001)
        assert reversed_event["reversal_reason"] == "interval data restated by the utility"
