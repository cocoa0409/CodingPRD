"""Slotting money is conserved across an amortization posting and its reversal."""

import pytest

from test_helpers import (
    AmortizationMethod,
    AuthorizationState,
    DealState,
    EntryKind,
    SettlementStateAuthorization,
    fixtures,
)
from test_helpers.assertions import (
    assert_ledger_matches_recovered,
    assert_slotting_money_conserved,
    expected_liability_ratio_bps,
    expected_straight_amortization,
)

FEE_PER_STORE_CENTS = 12500
STORE_COUNT = 400
BUDGET_CENTS = 20000000
ACCEPTED_FEE_CENTS = 5125000
OPEN_LIABILITY_RATIO_BPS = 2562


@pytest.fixture
def single_period_deal(api):
    """One accepted deal that amortizes its whole balance in a single period."""
    return fixtures.amortizing_deal(
        api,
        fee_per_store_cents=FEE_PER_STORE_CENTS,
        store_count_in_scope=STORE_COUNT,
        item_count_in_scope=1,
        forecast_annual_units=0,
        amortization_periods=1,
        amortization_method=AmortizationMethod.FORECAST_STRAIGHT,
        principal_overrides={"slotting_budget_cents": BUDGET_CENTS},
    )


def post_the_only_period(api, scope):
    return fixtures.post_period(
        api,
        scope["authorization"]["id"],
        scope["retailer"]["id"],
        period_index=1,
        reported_store_count=STORE_COUNT,
        distributed_store_count=STORE_COUNT,
        reported_case_volume=9000,
    )


class TestSlottingMoneyConservation:
    def test_the_money_identity_holds_before_any_posting(self, api, single_period_deal):
        """Acceptance puts the whole fee in the unamortized column and nowhere else.

        PRD: "On a slotting deal, `accepted_fee_cents` always equals `recovered_cents` plus
        `unamortized_balance_cents` plus `written_off_cents` — after every amortization
        posting, every reversal and every write-off."

        Design: Difficulty/compensating_invariant/slotting_money_conserved_across_amortization_posting_and_reversal
        """
        deal = fixtures.get_deal(api, single_period_deal["deal"]["id"])

        assert deal["accepted_fee_cents"] == ACCEPTED_FEE_CENTS
        assert deal["recovered_cents"] == 0
        assert deal["unamortized_balance_cents"] == ACCEPTED_FEE_CENTS
        assert deal["written_off_cents"] == 0
        assert deal["state"] == DealState.AMORTIZING
        assert_slotting_money_conserved(deal)

        principal = fixtures.get_principal(api, single_period_deal["principal"]["id"])
        assert principal["open_slotting_liability_cents"] == ACCEPTED_FEE_CENTS
        assert principal["liability_ratio_bps"] == OPEN_LIABILITY_RATIO_BPS
        assert principal["liability_ratio_bps"] == expected_liability_ratio_bps(
            ACCEPTED_FEE_CENTS, 0, BUDGET_CENTS
        )

    def test_the_single_period_posting_recovers_the_whole_balance_and_closes_the_deal(
        self, api, single_period_deal
    ):
        """One period out of one trues up to the entire accepted fee.

        PRD: "On the final period, where `periods_posted` plus one equals
        `amortization_periods`, the amount is instead `accepted_fee_cents` less the base
        figure multiplied by one fewer than `amortization_periods`, which trues up the
        accumulated flooring in a single step."

        Design: Difficulty/compensating_invariant/slotting_money_conserved_across_amortization_posting_and_reversal
        """
        entry = post_the_only_period(api, single_period_deal)

        assert entry["entry_kind"] == EntryKind.POSTING
        assert entry["reverses_snapshot_id"] is None
        assert entry["is_reversed"] is False
        assert entry["amortized_amount_cents"] == ACCEPTED_FEE_CENTS
        assert entry["amortized_amount_cents"] == expected_straight_amortization(
            ACCEPTED_FEE_CENTS, 1
        )

        deal = fixtures.get_deal(api, single_period_deal["deal"]["id"])
        assert deal["recovered_cents"] == ACCEPTED_FEE_CENTS
        assert deal["unamortized_balance_cents"] == 0
        assert deal["periods_posted"] == 1
        assert deal["state"] == DealState.RECOVERED
        assert_slotting_money_conserved(deal)

    def test_closing_the_deal_moves_the_settlement_dimension_but_not_the_void_dimension(
        self, api, single_period_deal
    ):
        """Full distribution means a zero void rate, so no recovery hold is ever entered.

        PRD: "When the posting drives `unamortized_balance_cents` to zero, the deal moves to
        `RECOVERED` and every authorization linked to it moves `settlement_state` from
        `SLOTTING_AMORTIZING` to `SLOTTING_RECOVERED`."

        Design: Difficulty/compensating_invariant/slotting_money_conserved_across_amortization_posting_and_reversal
        """
        post_the_only_period(api, single_period_deal)

        authorization = fixtures.get_authorization(api, single_period_deal["authorization"]["id"])
        assert authorization["settlement_state"] == SettlementStateAuthorization.SLOTTING_RECOVERED
        assert authorization["void_store_count"] == 0
        assert authorization["void_rate_bps"] == 0
        assert authorization["authorization_state"] == AuthorizationState.AUTHORIZED
        assert fixtures.get_deal(api, single_period_deal["deal"]["id"])["state"] == DealState.RECOVERED

    def test_the_principal_liability_drains_when_the_deal_closes(self, api, single_period_deal):
        """A closed deal carries no unamortized balance, so it leaves the open-liability set.

        PRD: "`open_slotting_liability_cents` is the sum of `unamortized_balance_cents` over
        deals in `AMORTIZING` or `RECOVERY_HOLD`; `open_deduction_cents` is the sum of `open_cents`
        over deductions whose `settlement_state` is `OPEN`; `at_risk_authorization_count` is the
        number of authorizations on that principal's items whose `authorization_state` is
        `AT_RISK`."

        Design: Difficulty/compensating_invariant/slotting_money_conserved_across_amortization_posting_and_reversal
        """
        post_the_only_period(api, single_period_deal)

        principal = fixtures.get_principal(api, single_period_deal["principal"]["id"])
        assert principal["open_slotting_liability_cents"] == 0
        assert principal["liability_ratio_bps"] == 0
        assert principal["liability_ratio_bps"] == expected_liability_ratio_bps(0, 0, BUDGET_CENTS)

    def test_the_reversal_appends_a_negation_and_never_rewrites_the_reversed_row(
        self, api, single_period_deal
    ):
        """The cancelled posting keeps its own positive amount; a new row carries the minus.

        PRD: "A `RetailerBuyer` reverses a posting, which creates a new ledger entry with
        `entry_kind` at `REVERSAL`, `reverses_snapshot_id` pointing at the cancelled
        `POSTING`, that posting's `period_index` copied across, and `amortized_amount_cents`
        set to the negation of the reversed entry's amount; the reversed entry's
        `is_reversed` flag becomes true and nothing else about it is touched."

        Design: Difficulty/compensating_invariant/slotting_money_conserved_across_amortization_posting_and_reversal
        """
        posting = post_the_only_period(api, single_period_deal)
        reversal = fixtures.reverse_period(
            api, posting["id"], single_period_deal["retailer"]["id"]
        )

        assert reversal["entry_kind"] == EntryKind.REVERSAL
        assert reversal["reverses_snapshot_id"] == posting["id"]
        assert reversal["period_index"] == posting["period_index"]
        assert reversal["amortized_amount_cents"] == -ACCEPTED_FEE_CENTS

        ledger = fixtures.list_snapshots(
            api, authorization_id=single_period_deal["authorization"]["id"]
        )
        reversed_row = next(row for row in ledger if row["id"] == posting["id"])
        assert reversed_row["is_reversed"] is True
        assert reversed_row["amortized_amount_cents"] == ACCEPTED_FEE_CENTS
        assert reversed_row["entry_kind"] == EntryKind.POSTING

    def test_the_reversal_restores_the_pre_posting_figures_with_zero_drift(
        self, api, single_period_deal
    ):
        """Reopening the deal puts every counter back exactly where it started.

        PRD: "it rolls back the deal's `recovered_cents`, `unamortized_balance_cents` and
        `periods_posted`; when the deal had already closed it reopens it, moving `RECOVERED`
        → `AMORTIZING` and each linked authorization's `settlement_state` from
        `SLOTTING_RECOVERED` back to `SLOTTING_AMORTIZING`; it recomputes `void_rate_bps`, moving
        `AT_RISK` → `AUTHORIZED` and `RECOVERY_HOLD` → `AMORTIZING` when the rate has dropped back
        below the threshold; it re-derives the principal's aggregates and `credit_posture`; and it
        advances the authorization's `version` by one."

        Design: Difficulty/compensating_invariant/slotting_money_conserved_across_amortization_posting_and_reversal
        """
        posting = post_the_only_period(api, single_period_deal)
        fixtures.reverse_period(api, posting["id"], single_period_deal["retailer"]["id"])

        deal = fixtures.get_deal(api, single_period_deal["deal"]["id"])
        assert deal["recovered_cents"] == 0
        assert deal["unamortized_balance_cents"] == ACCEPTED_FEE_CENTS
        assert deal["periods_posted"] == 0
        assert deal["state"] == DealState.AMORTIZING
        assert_slotting_money_conserved(deal)

        authorization = fixtures.get_authorization(api, single_period_deal["authorization"]["id"])
        assert authorization["settlement_state"] == SettlementStateAuthorization.SLOTTING_AMORTIZING
        assert authorization["periods_reported"] == 0

        principal = fixtures.get_principal(api, single_period_deal["principal"]["id"])
        assert principal["open_slotting_liability_cents"] == ACCEPTED_FEE_CENTS
        assert principal["liability_ratio_bps"] == OPEN_LIABILITY_RATIO_BPS

    def test_the_signed_ledger_sum_tracks_recovered_cents_at_every_step(
        self, api, single_period_deal
    ):
        """Posting then reversal sums to 5,125,000 and then back to zero.

        PRD: "Whichever variant applies, the amount is recorded on the ledger entry as
        `amortized_amount_cents` — zero when the authorization has no linked deal — and
        added to the deal's `recovered_cents`, subtracted from its
        `unamortized_balance_cents`, with `periods_posted` increased by one."

        Design: Difficulty/compensating_invariant/slotting_money_conserved_across_amortization_posting_and_reversal
        """
        authorization_id = single_period_deal["authorization"]["id"]
        posting = post_the_only_period(api, single_period_deal)

        after_posting = fixtures.list_snapshots(api, authorization_id=authorization_id)
        assert_ledger_matches_recovered(
            fixtures.get_deal(api, single_period_deal["deal"]["id"]), after_posting
        )

        fixtures.reverse_period(api, posting["id"], single_period_deal["retailer"]["id"])
        after_reversal = fixtures.list_snapshots(api, authorization_id=authorization_id)
        assert len(after_reversal) == 2
        assert_ledger_matches_recovered(
            fixtures.get_deal(api, single_period_deal["deal"]["id"]), after_reversal
        )
