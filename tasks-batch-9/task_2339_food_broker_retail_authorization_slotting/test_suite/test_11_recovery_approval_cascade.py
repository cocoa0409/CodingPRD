"""Approving a promotional billback pushes conceded money out to the promotion event."""

import pytest

from test_helpers import (
    CreditPosture,
    DeductionReasonCode,
    DeductionSettlementState,
    DisputeState,
    PromotionState,
    fixtures,
)
from test_helpers.assertions import (
    assert_deduction_money_conserved,
    expected_promo_billback_recovery,
)

WINDOW_START = "2026-09-10T10:00:00Z"
WINDOW_END = "2026-09-10T14:00:00Z"
EXECUTE_AT = "2026-09-11T00:00:00Z"
PLANNED_FUNDING_CENTS = 320000
CLAIM_CENTS = 500000


def build_scope(api, actual_funding_cents, planned_funding_cents=PLANNED_FUNDING_CENTS):
    """Award a slot with no deal, execute one promotion, then take a billback against it."""
    scope = fixtures.awarded_authorization_without_deal(
        api, retailer_overrides={"deduction_dispute_window_days": 90}
    )
    promotion = fixtures.executed_promotion(
        api,
        scope["authorization"]["id"],
        WINDOW_START,
        WINDOW_END,
        planned_funding_cents,
        actual_funding_cents,
        EXECUTE_AT,
    )
    deduction = fixtures.create_deduction(
        api,
        scope["retailer"]["id"],
        scope["principal"]["id"],
        reason_code=DeductionReasonCode.PROMO_BILLBACK,
        amount_cents=CLAIM_CENTS,
        deduction_date="2026-09-11",
        promotion_event_id=promotion["id"],
    )
    fixtures.file_claim(api, deduction["id"], CLAIM_CENTS)
    deduction = fixtures.substantiate_twice(
        api,
        deduction["id"],
        ["PROMO-FUNDING-LEDGER-9001", "SIGNED-PROMO-AGREEMENT-9002"],
    )
    scope["promotion"] = promotion
    scope["deduction"] = deduction
    return scope


@pytest.fixture
def billback_scope(api):
    """A 500,000-cent billback against a promotion that proved 320,000 cents of funding."""
    return build_scope(api, PLANNED_FUNDING_CENTS)


class TestRecoveryApprovalCascade:
    def test_the_setup_leaves_an_executed_promotion_with_nothing_settled(
        self, api, billback_scope
    ):
        """Execution records the proven funding; nothing has been settled against it yet.

        PRD: "Once persisted, `actual_funding_cents` becomes the proven funding figure that a
        promotional billback deduction is netted against."

        Design: Difficulty/transitive_cascade/recovery_approval_cascades_promotion_and_authorization_trade_spend
        """
        promotion = fixtures.get_promotion(api, billback_scope["promotion"]["id"])
        assert promotion["state"] == PromotionState.EXECUTED
        assert promotion["actual_funding_cents"] == PLANNED_FUNDING_CENTS
        assert promotion["settled_funding_cents"] == 0

        authorization = fixtures.get_authorization(api, billback_scope["authorization"]["id"])
        assert authorization["slotting_share_cents"] == 0
        assert authorization["promo_settled_funding_cents"] == 0
        assert authorization["trade_spend_total_cents"] == 0

    def test_level_one_the_claim_recovers_only_the_excess_over_proven_funding(
        self, api, billback_scope
    ):
        """500,000 claimed less 320,000 proven leaves 180,000 recoverable.

        PRD: "A `PROMO_BILLBACK` concedes whatever funding the broker can prove was delivered
        and recovers only the excess: the recoverable amount is the smaller of
        `claim_amount_cents` and the `amount_cents` less the substantiated funding, with that
        difference floored at zero, where substantiated funding is the linked promotion
        event's `actual_funding_cents` when that event's `state` is `EXECUTED` or `SETTLED`
        and zero otherwise — so a billback against an event that never executed is recoverable
        in full up to the claim."

        Design: Difficulty/transitive_cascade/recovery_approval_cascades_promotion_and_authorization_trade_spend
        """
        settled = fixtures.approve_recovery(api, billback_scope["deduction"]["id"])

        assert settled["settlement_state"] == DeductionSettlementState.RECOVERED
        assert settled["dispute_state"] == DisputeState.APPROVED
        assert settled["recovered_cents"] == 180000
        assert settled["recovered_cents"] == expected_promo_billback_recovery(
            CLAIM_CENTS, CLAIM_CENTS, PLANNED_FUNDING_CENTS
        )
        assert settled["conceded_cents"] == PLANNED_FUNDING_CENTS
        assert settled["open_cents"] == 0
        assert_deduction_money_conserved(settled)

    def test_level_two_the_conceded_money_settles_the_promotion_event(
        self, api, billback_scope
    ):
        """Conceded funding meets the proven figure exactly, so the event settles.

        PRD: "For a `PROMO_BILLBACK`, settlement cascades: the linked promotion event's
        `settled_funding_cents` increases by `conceded_cents`, and once that cumulative figure
        reaches or exceeds the event's `actual_funding_cents` the event moves `EXECUTED` →
        `SETTLED`, which in turn recomputes the authorization's `promo_settled_funding_cents`
        and `trade_spend_total_cents`."

        Design: Difficulty/transitive_cascade/recovery_approval_cascades_promotion_and_authorization_trade_spend
        """
        fixtures.approve_recovery(api, billback_scope["deduction"]["id"])

        promotion = fixtures.get_promotion(api, billback_scope["promotion"]["id"])
        assert promotion["settled_funding_cents"] == PLANNED_FUNDING_CENTS
        assert promotion["settled_funding_cents"] >= promotion["actual_funding_cents"]
        assert promotion["state"] == PromotionState.SETTLED

    def test_level_three_the_authorization_trade_spend_absorbs_the_settled_funding(
        self, api, billback_scope
    ):
        """With no slotting share, the whole trade spend is the settled promotion funding.

        PRD: "It is driven by deduction settlement (§3.9): once the event's
        `settled_funding_cents` reaches or exceeds its `actual_funding_cents`, the event
        settles, and the cascade recomputes the owning authorization's
        `promo_settled_funding_cents` — the sum of `actual_funding_cents` over that
        authorization's `SETTLED` events — and with it `trade_spend_total_cents`."

        Design: Difficulty/transitive_cascade/recovery_approval_cascades_promotion_and_authorization_trade_spend
        """
        fixtures.approve_recovery(api, billback_scope["deduction"]["id"])

        authorization = fixtures.get_authorization(api, billback_scope["authorization"]["id"])
        assert authorization["promo_settled_funding_cents"] == PLANNED_FUNDING_CENTS
        assert authorization["trade_spend_total_cents"] == PLANNED_FUNDING_CENTS
        assert (
            authorization["trade_spend_total_cents"]
            == authorization["slotting_share_cents"]
            + authorization["promo_settled_funding_cents"]
        )

    def test_the_principal_open_deduction_drains_on_settlement(self, api, billback_scope):
        """The deduction leaves the open set entirely, recovered and conceded parts alike.

        PRD: "In every case the principal's `open_deduction_cents` and `liability_ratio_bps`
        are recomputed and `credit_posture` re-derived."

        Design: Difficulty/transitive_cascade/recovery_approval_cascades_promotion_and_authorization_trade_spend
        """
        before = fixtures.get_principal(api, billback_scope["principal"]["id"])
        assert before["open_deduction_cents"] == CLAIM_CENTS

        fixtures.approve_recovery(api, billback_scope["deduction"]["id"])

        after = fixtures.get_principal(api, billback_scope["principal"]["id"])
        assert after["open_deduction_cents"] == 0
        assert after["liability_ratio_bps"] == 0
        assert after["credit_posture"] == CreditPosture.NORMAL

    def test_the_split_follows_proven_funding_and_not_the_claim(self, api):
        """A promotion that proved 400,000 cents concedes more and recovers only 100,000.

        PRD: "How much is recoverable depends entirely on the reason code."

        Design: Difficulty/transitive_cascade/recovery_approval_cascades_promotion_and_authorization_trade_spend
        """
        scope = build_scope(api, 400000, planned_funding_cents=400000)
        settled = fixtures.approve_recovery(api, scope["deduction"]["id"])

        assert settled["recovered_cents"] == 100000
        assert settled["recovered_cents"] == expected_promo_billback_recovery(
            CLAIM_CENTS, CLAIM_CENTS, 400000
        )
        assert settled["conceded_cents"] == 400000
        assert settled["settlement_state"] == DeductionSettlementState.RECOVERED
        assert_deduction_money_conserved(settled)

        promotion = fixtures.get_promotion(api, scope["promotion"]["id"])
        assert promotion["settled_funding_cents"] == 400000
        assert promotion["state"] == PromotionState.SETTLED

        authorization = fixtures.get_authorization(api, scope["authorization"]["id"])
        assert authorization["promo_settled_funding_cents"] == 400000
        assert authorization["trade_spend_total_cents"] == 400000
