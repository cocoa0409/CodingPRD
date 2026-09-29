"""A promotion may not be committed while its authorization is bleeding voids."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    AuthorizationState,
    ApiErrorId,
    CreditPosture,
    EntryKind,
    PromotionEventType,
    PromotionState,
    fixtures,
    get_success_data,
    validate_error,
)
from test_helpers.assertions import expected_void_rate_bps

STORE_COUNT = 1000
DISTRIBUTED_STORE_COUNT = 700
AT_RISK_THRESHOLD_BPS = 1500
WINDOW_START = "2026-09-20T10:00:00Z"
WINDOW_END = "2026-09-20T14:00:00Z"
PLANNED_FUNDING_CENTS = 250000


@pytest.fixture
def at_risk_authorization_with_planned_promotion(api):
    """A faultless planned promotion hanging off an authorization pushed to 3,000 bps void."""
    scope = fixtures.awarded_authorization_without_deal(
        api,
        retailer_overrides={"at_risk_void_rate_bps": AT_RISK_THRESHOLD_BPS},
        default_store_count=STORE_COUNT,
    )
    promotion = fixtures.create_promotion(
        api,
        scope["authorization"]["id"],
        event_type=PromotionEventType.PRICE_FEATURE,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        planned_funding_cents=PLANNED_FUNDING_CENTS,
    )
    snapshot = fixtures.post_period(
        api,
        scope["authorization"]["id"],
        scope["retailer"]["id"],
        period_index=1,
        reported_store_count=STORE_COUNT,
        distributed_store_count=DISTRIBUTED_STORE_COUNT,
        reported_case_volume=4000,
    )
    scope["promotion"] = promotion
    scope["snapshot"] = snapshot
    return scope


def attempt_commit(api, scope):
    return api.commit_promotion(scope["promotion"]["id"], ACCOUNT_MANAGER_HEADERS)


class TestPromotionCommitBlockedWhileAtRisk:
    def test_the_short_posting_puts_the_parent_authorization_at_risk(
        self, api, at_risk_authorization_with_planned_promotion
    ):
        """Three hundred void stores out of a thousand is double the chain's tolerance.

        PRD: "An `AUTHORIZED` authorization moves to `AT_RISK` when the recomputed
        `void_rate_bps` is at or above the chain's `at_risk_void_rate_bps`; an `AT_RISK`
        authorization returns to `AUTHORIZED` when a later posting, or a reversal, yields a rate
        strictly below that threshold."

        Design: Difficulty/cross_entity_state_dependency/promotion_commit_blocked_while_authorization_is_at_risk
        """
        authorization = fixtures.get_authorization(
            api, at_risk_authorization_with_planned_promotion["authorization"]["id"]
        )

        assert authorization["void_store_count"] == 300
        assert authorization["void_rate_bps"] == 3000
        assert authorization["void_rate_bps"] == expected_void_rate_bps(300, STORE_COUNT)
        assert authorization["void_rate_bps"] >= AT_RISK_THRESHOLD_BPS
        assert authorization["authorization_state"] == AuthorizationState.AT_RISK

    def test_the_faultless_promotion_is_refused_because_of_its_parent(
        self, api, at_risk_authorization_with_planned_promotion
    ):
        """Nothing is wrong with the event itself; only the authorization's state blocks it.

        PRD: "The authorization must be `AUTHORIZED`: an `AT_RISK` authorization is refused with
        `ERR_AUTHORIZATION_AT_RISK`, and one that is `PENDING_SETUP` or `DISCONTINUED` with
        `ERR_AUTHORIZATION_NOT_AUTHORIZED`."

        Design: Difficulty/cross_entity_state_dependency/promotion_commit_blocked_while_authorization_is_at_risk
        """
        promotion = fixtures.get_promotion(
            api, at_risk_authorization_with_planned_promotion["promotion"]["id"]
        )
        assert promotion["state"] == PromotionState.PLANNED
        assert promotion["planned_funding_cents"] == PLANNED_FUNDING_CENTS
        assert promotion["committed_at"] is None

        response = attempt_commit(api, at_risk_authorization_with_planned_promotion)
        validate_error(response, ApiErrorId.AUTHORIZATION_AT_RISK, 409)

    def test_the_refused_commit_leaves_the_event_planned(
        self, api, at_risk_authorization_with_planned_promotion
    ):
        """No slot is taken and no commitment instant is stamped.

        PRD: "On success `committed_at` is stamped from the logical clock and the buffered
        window occupies one of the store's slots."

        Design: Difficulty/cross_entity_state_dependency/promotion_commit_blocked_while_authorization_is_at_risk
        """
        attempt_commit(api, at_risk_authorization_with_planned_promotion)

        promotion = fixtures.get_promotion(
            api, at_risk_authorization_with_planned_promotion["promotion"]["id"]
        )
        assert promotion["state"] == PromotionState.PLANNED
        assert promotion["committed_at"] is None
        assert promotion["actual_funding_cents"] == 0
        assert promotion["settled_funding_cents"] == 0

    def test_reversing_the_offending_period_returns_the_parent_to_authorized(
        self, api, at_risk_authorization_with_planned_promotion
    ):
        """The append-only reversal un-manufactures the risk entirely.

        PRD: "The reversal decrements `periods_reported` by one and recomputes the counters from
        the new latest live posting; it rolls back the deal's `recovered_cents`,
        `unamortized_balance_cents` and `periods_posted`; when the deal had already closed it
        reopens it, moving `RECOVERED` → `AMORTIZING` and each linked authorization's
        `settlement_state` from `SLOTTING_RECOVERED` back to `SLOTTING_AMORTIZING`; it
        recomputes `void_rate_bps`, moving `AT_RISK` → `AUTHORIZED` and `RECOVERY_HOLD` →
        `AMORTIZING` when the rate has dropped back below the threshold; it re-derives the
        principal's aggregates and `credit_posture`; and it advances the authorization's
        `version` by one."

        PRD: "When no live posting exists, `void_rate_bps` is 0."

        Design: Difficulty/cross_entity_state_dependency/promotion_commit_blocked_while_authorization_is_at_risk
        """
        scope = at_risk_authorization_with_planned_promotion
        reversal = fixtures.reverse_period(api, scope["snapshot"]["id"], scope["retailer"]["id"])

        assert reversal["entry_kind"] == EntryKind.REVERSAL
        assert reversal["reverses_snapshot_id"] == scope["snapshot"]["id"]

        authorization = fixtures.get_authorization(api, scope["authorization"]["id"])
        assert authorization["periods_reported"] == 0
        assert authorization["void_rate_bps"] == 0
        assert authorization["authorization_state"] == AuthorizationState.AUTHORIZED

    def test_the_identical_commit_then_succeeds(
        self, api, at_risk_authorization_with_planned_promotion
    ):
        """The dependency is live in both directions: block, then clear, then commit.

        PRD: "Committing an event with the retailer moves `state` from `PLANNED` to `COMMITTED`
        and imposes three conditions."

        Design: Difficulty/cross_entity_state_dependency/promotion_commit_blocked_while_authorization_is_at_risk
        """
        scope = at_risk_authorization_with_planned_promotion
        validate_error(attempt_commit(api, scope), ApiErrorId.AUTHORIZATION_AT_RISK, 409)

        fixtures.reverse_period(api, scope["snapshot"]["id"], scope["retailer"]["id"])

        committed = get_success_data(attempt_commit(api, scope), 200)
        assert committed["state"] == PromotionState.COMMITTED
        assert committed["committed_at"] is not None

    def test_the_principal_at_risk_count_and_posture_track_both_directions(
        self, api, at_risk_authorization_with_planned_promotion
    ):
        """One at-risk authorization drives WATCH; the reversal takes the count back to zero.

        PRD: "Leaving `AT_RISK` cascades symmetrically: the linked deal moves `RECOVERY_HOLD` →
        `AMORTIZING` once no other authorization linked to it is still at risk,
        `at_risk_authorization_count` decreases by one, and `credit_posture` is re-derived."

        Design: Difficulty/cross_entity_state_dependency/promotion_commit_blocked_while_authorization_is_at_risk
        """
        scope = at_risk_authorization_with_planned_promotion
        before = fixtures.get_principal(api, scope["principal"]["id"])
        assert before["at_risk_authorization_count"] == 1
        assert before["credit_posture"] == CreditPosture.WATCH

        fixtures.reverse_period(api, scope["snapshot"]["id"], scope["retailer"]["id"])

        after = fixtures.get_principal(api, scope["principal"]["id"])
        assert after["at_risk_authorization_count"] == 0
        assert after["credit_posture"] == CreditPosture.NORMAL
