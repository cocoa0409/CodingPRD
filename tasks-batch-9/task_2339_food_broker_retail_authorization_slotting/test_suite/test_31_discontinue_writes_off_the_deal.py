"""A live promotion blocks a void, and the void then charges off its deal."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    AuthorizationState,
    ApiErrorId,
    CreditPosture,
    DealState,
    PromotionEventType,
    PromotionState,
    SettlementStateAuthorization,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
    validate_error,
)
from test_helpers.assertions import assert_slotting_money_conserved

FEE_PER_STORE_CENTS = 12500
STORE_COUNT = 400
ACCEPTED_FEE_CENTS = 5125000
PLANNED_FUNDING_CENTS = 250000
DISCONTINUE_REASON = "Chain-wide void after reset"


@pytest.fixture
def amortizing_authorization_with_a_committed_promotion(api):
    """An accepted deal at 5,125,000 with nothing amortized and one COMMITTED event."""
    scope = fixtures.amortizing_deal(
        api,
        fee_per_store_cents=FEE_PER_STORE_CENTS,
        store_count_in_scope=STORE_COUNT,
        amortization_periods=6,
    )
    promotion = fixtures.create_promotion(
        api,
        scope["authorization"]["id"],
        event_type=PromotionEventType.PRICE_FEATURE,
        window_start="2026-09-20T10:00:00Z",
        window_end="2026-09-20T14:00:00Z",
        planned_funding_cents=PLANNED_FUNDING_CENTS,
    )
    scope["promotion"] = fixtures.commit_promotion(api, promotion["id"])
    return scope


def discontinue(api, scope):
    return api.discontinue_authorization(
        scope["authorization"]["id"],
        {"discontinue_reason": DISCONTINUE_REASON},
        make_retailer_buyer_headers(scope["retailer"]["id"]),
    )


def cancel_the_promotion(api, scope):
    return get_success_data(
        api.cancel_promotion(scope["promotion"]["id"], ACCOUNT_MANAGER_HEADERS), 200
    )


class TestDiscontinueWritesOffTheDeal:
    def test_a_committed_promotion_blocks_the_void(
        self, api, amortizing_authorization_with_a_committed_promotion
    ):
        """A child event in COMMITTED refuses the parent's discontinue.

        PRD: "From `AUTHORIZED` or `AT_RISK` the move is blocked while any promotion event of
        that authorization is still `COMMITTED` or `EXECUTED`, reported as
        `ERR_AUTHORIZATION_HAS_LIVE_PROMOTION`."

        Design: Corner/state_machines/discontinue_blocked_by_live_promotion_then_writes_off_the_deal
        """
        scope = amortizing_authorization_with_a_committed_promotion
        assert scope["promotion"]["state"] == PromotionState.COMMITTED

        validate_error(
            discontinue(api, scope), ApiErrorId.AUTHORIZATION_HAS_LIVE_PROMOTION, 409
        )

        authorization = fixtures.get_authorization(api, scope["authorization"]["id"])
        assert authorization["authorization_state"] == AuthorizationState.AUTHORIZED

    def test_cancelling_the_event_releases_the_block(
        self, api, amortizing_authorization_with_a_committed_promotion
    ):
        """Cancellation from COMMITTED gives back the slot the event was holding.

        PRD: "Cancellation moves `state` to `CANCELLED` from either `PLANNED` or `COMMITTED`,
        with no precondition in either case."

        Design: Corner/state_machines/discontinue_blocked_by_live_promotion_then_writes_off_the_deal
        """
        scope = amortizing_authorization_with_a_committed_promotion
        validate_error(discontinue(api, scope), ApiErrorId.AUTHORIZATION_HAS_LIVE_PROMOTION, 409)

        cancelled = cancel_the_promotion(api, scope)
        assert cancelled["state"] == PromotionState.CANCELLED

        discontinued = get_success_data(discontinue(api, scope), 200)
        assert discontinued["authorization_state"] == AuthorizationState.DISCONTINUED
        assert discontinued["discontinue_reason"] == DISCONTINUE_REASON

    def test_the_void_charges_off_the_whole_remaining_balance(
        self, api, amortizing_authorization_with_a_committed_promotion
    ):
        """Nothing was ever amortized, so the entire accepted fee is written off.

        PRD: "In all cases, when this was the linked deal's last authorization not yet
        discontinued and `unamortized_balance_cents` is still above zero, the deal is charged
        off: it moves from `AMORTIZING` or `RECOVERY_HOLD` to `WRITTEN_OFF`, its
        `written_off_cents` absorbs the whole remaining balance and drives
        `unamortized_balance_cents` to zero, and every authorization linked to it moves
        `settlement_state` from `SLOTTING_AMORTIZING` to `SLOTTING_WRITTEN_OFF`."

        Design: Corner/state_machines/discontinue_blocked_by_live_promotion_then_writes_off_the_deal
        """
        scope = amortizing_authorization_with_a_committed_promotion
        cancel_the_promotion(api, scope)
        get_success_data(discontinue(api, scope), 200)

        deal = fixtures.get_deal(api, scope["deal"]["id"])
        assert deal["state"] == DealState.WRITTEN_OFF
        assert deal["accepted_fee_cents"] == ACCEPTED_FEE_CENTS
        assert deal["written_off_cents"] == ACCEPTED_FEE_CENTS
        assert deal["unamortized_balance_cents"] == 0
        assert deal["recovered_cents"] == 0
        assert_slotting_money_conserved(deal)

    def test_the_settlement_dimension_follows_the_deal(
        self, api, amortizing_authorization_with_a_committed_promotion
    ):
        """The authorization is voided on one axis and written off on the other.

        PRD: "Note that the two dimensions really are independent: an `AT_RISK` authorization
        stays `SLOTTING_AMORTIZING`, and a `DISCONTINUED` one may perfectly well be
        `SLOTTING_RECOVERED`."

        Design: Corner/state_machines/discontinue_blocked_by_live_promotion_then_writes_off_the_deal
        """
        scope = amortizing_authorization_with_a_committed_promotion
        cancel_the_promotion(api, scope)
        get_success_data(discontinue(api, scope), 200)

        authorization = fixtures.get_authorization(api, scope["authorization"]["id"])
        assert authorization["authorization_state"] == AuthorizationState.DISCONTINUED
        assert authorization["settlement_state"] == (
            SettlementStateAuthorization.SLOTTING_WRITTEN_OFF
        )

    def test_a_written_off_deal_leaves_the_liability_sets(
        self, api, amortizing_authorization_with_a_committed_promotion
    ):
        """Open liability drops to nothing and the posture returns to normal.

        PRD: "The principal's `slotting_committed_cents` and `open_slotting_liability_cents` are
        recomputed — a written-off deal leaves both sets — and `credit_posture` is re-derived."

        Design: Corner/state_machines/discontinue_blocked_by_live_promotion_then_writes_off_the_deal
        """
        scope = amortizing_authorization_with_a_committed_promotion
        cancel_the_promotion(api, scope)
        get_success_data(discontinue(api, scope), 200)

        principal = fixtures.get_principal(api, scope["principal"]["id"])
        assert principal["open_slotting_liability_cents"] == 0
        assert principal["at_risk_authorization_count"] == 0
        assert principal["credit_posture"] == CreditPosture.NORMAL
        assert principal["liability_ratio_bps"] == 0
