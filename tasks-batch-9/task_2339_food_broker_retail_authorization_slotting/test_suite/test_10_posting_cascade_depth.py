"""One distribution posting propagates through authorization, deal and principal."""

import pytest

from test_helpers import (
    AmortizationMethod,
    AuthorizationState,
    CreditPosture,
    DealState,
    EntryKind,
    SettlementStateAuthorization,
    fixtures,
)
from test_helpers.assertions import (
    assert_slotting_money_conserved,
    assert_store_counts_conserved,
    expected_liability_ratio_bps,
    expected_straight_amortization,
    expected_void_rate_bps,
)

STORE_COUNT = 400
PERIODS = 6
BUDGET_CENTS = 20000000
ACCEPTED_FEE_CENTS = 5125000
PERIOD_AMOUNT_CENTS = 854166
REMAINING_CENTS = 4270834


@pytest.fixture
def amortizing_scope(api):
    """An accepted six-period deal whose single authorization is live at a 1,500 bps chain."""
    return fixtures.amortizing_deal(
        api,
        fee_per_store_cents=12500,
        store_count_in_scope=STORE_COUNT,
        item_count_in_scope=1,
        forecast_annual_units=0,
        amortization_periods=PERIODS,
        amortization_method=AmortizationMethod.FORECAST_STRAIGHT,
        retailer_overrides={"at_risk_void_rate_bps": 1500},
        principal_overrides={"slotting_budget_cents": BUDGET_CENTS},
    )


def post_the_short_period(api, scope):
    """Report 400 stores but only 340 distributed, which is exactly 1,500 basis points void."""
    return fixtures.post_period(
        api,
        scope["authorization"]["id"],
        scope["retailer"]["id"],
        period_index=1,
        reported_store_count=STORE_COUNT,
        distributed_store_count=340,
        reported_case_volume=9000,
    )


class TestPostingCascadeDepth:
    def test_the_state_before_the_posting_is_a_healthy_amortizing_deal(self, api, amortizing_scope):
        """Nothing is at risk and the posture is normal before the period lands.

        PRD: "The third hop re-derives the principal: `slotting_committed_cents`,
        `open_slotting_liability_cents` and `liability_ratio_bps` are recomputed and
        `credit_posture` is re-derived, which may move the principal from `NORMAL` to `WATCH`
        or `RESTRICTED` in the very request that accepted the deal."

        Design: Difficulty/transitive_cascade/snapshot_post_cascades_authorization_deal_and_principal_posture
        """
        principal = fixtures.get_principal(api, amortizing_scope["principal"]["id"])

        assert principal["slotting_committed_cents"] == ACCEPTED_FEE_CENTS
        assert principal["open_slotting_liability_cents"] == ACCEPTED_FEE_CENTS
        assert principal["liability_ratio_bps"] == 2562
        assert principal["at_risk_authorization_count"] == 0
        assert principal["credit_posture"] == CreditPosture.NORMAL

    def test_level_one_the_ledger_entry_records_the_period_amount(self, api, amortizing_scope):
        """The posting itself carries the floored one-sixth share of the accepted fee.

        PRD: "The `POSTING` entry is persisted immutably and the authorization's
        `periods_reported` increases by one."

        Design: Difficulty/transitive_cascade/snapshot_post_cascades_authorization_deal_and_principal_posture
        """
        entry = post_the_short_period(api, amortizing_scope)

        assert entry["entry_kind"] == EntryKind.POSTING
        assert entry["period_index"] == 1
        assert entry["reported_store_count"] == STORE_COUNT
        assert entry["distributed_store_count"] == 340
        assert entry["amortized_amount_cents"] == PERIOD_AMOUNT_CENTS
        assert entry["amortized_amount_cents"] == expected_straight_amortization(
            ACCEPTED_FEE_CENTS, PERIODS
        )

    def test_level_two_the_authorization_counters_and_at_risk_flag_move(
        self, api, amortizing_scope
    ):
        """Sixty void stores out of four hundred is exactly the chain's threshold.

        PRD: "The authorization's distribution counters are recomputed from the new latest
        live posting."

        Design: Difficulty/transitive_cascade/snapshot_post_cascades_authorization_deal_and_principal_posture
        """
        post_the_short_period(api, amortizing_scope)

        authorization = fixtures.get_authorization(api, amortizing_scope["authorization"]["id"])
        assert authorization["distributed_store_count"] == 340
        assert authorization["void_store_count"] == 60
        assert authorization["pending_store_count"] == 0
        assert authorization["void_rate_bps"] == 1500
        assert authorization["void_rate_bps"] == expected_void_rate_bps(60, STORE_COUNT)
        assert authorization["authorization_state"] == AuthorizationState.AT_RISK
        assert authorization["periods_reported"] == 1
        assert_store_counts_conserved(authorization)

    def test_level_three_the_deal_amortizes_first_and_is_then_put_on_hold(
        self, api, amortizing_scope
    ):
        """Because the period is applied before the risk decision, a balance remains to hold.

        PRD: "The linked deal moves `AMORTIZING` → `RECOVERY_HOLD` when an authorization
        entered `AT_RISK` in step 4 and the deal still carries a balance above zero."

        Design: Difficulty/transitive_cascade/snapshot_post_cascades_authorization_deal_and_principal_posture
        """
        post_the_short_period(api, amortizing_scope)

        deal = fixtures.get_deal(api, amortizing_scope["deal"]["id"])
        assert deal["recovered_cents"] == PERIOD_AMOUNT_CENTS
        assert deal["unamortized_balance_cents"] == REMAINING_CENTS
        assert deal["periods_posted"] == 1
        assert deal["state"] == DealState.RECOVERY_HOLD
        assert_slotting_money_conserved(deal)

        authorization = fixtures.get_authorization(api, amortizing_scope["authorization"]["id"])
        # The hold is a deal-level state; the settlement dimension keeps amortizing.
        assert authorization["settlement_state"] == SettlementStateAuthorization.SLOTTING_AMORTIZING

    def test_level_four_the_principal_posture_moves_to_watch(self, api, amortizing_scope):
        """One at-risk authorization is enough for WATCH even at a 2,135 bps ratio.

        PRD: "The principal's aggregates, `at_risk_authorization_count`, `liability_ratio_bps`
        and `credit_posture` are re-derived."

        Design: Difficulty/transitive_cascade/snapshot_post_cascades_authorization_deal_and_principal_posture
        """
        post_the_short_period(api, amortizing_scope)

        principal = fixtures.get_principal(api, amortizing_scope["principal"]["id"])
        assert principal["at_risk_authorization_count"] == 1
        assert principal["open_slotting_liability_cents"] == REMAINING_CENTS
        assert principal["liability_ratio_bps"] == 2135
        assert principal["liability_ratio_bps"] == expected_liability_ratio_bps(
            REMAINING_CENTS, 0, BUDGET_CENTS
        )
        # The ratio alone would still read NORMAL; the at-risk count is what drives WATCH.
        assert principal["liability_ratio_bps"] < 5000
        assert principal["credit_posture"] == CreditPosture.WATCH

    def test_the_step_ordering_is_what_leaves_a_balance_to_hold(self, api, amortizing_scope):
        """A deal still carrying five sixths of its fee is held, not closed.

        PRD: "An accepted posting runs six steps in exactly this order, and the ordering is
        the whole point of step 4."

        Design: Difficulty/transitive_cascade/snapshot_post_cascades_authorization_deal_and_principal_posture
        """
        post_the_short_period(api, amortizing_scope)

        deal = fixtures.get_deal(api, amortizing_scope["deal"]["id"])
        assert deal["accepted_fee_cents"] == ACCEPTED_FEE_CENTS
        assert deal["recovered_cents"] + deal["unamortized_balance_cents"] == ACCEPTED_FEE_CENTS
        assert deal["written_off_cents"] == 0
        assert deal["unamortized_balance_cents"] > 0
        assert deal["state"] == DealState.RECOVERY_HOLD
