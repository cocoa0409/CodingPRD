"""The at-risk void-rate threshold at, and one store short of, the boundary."""

import pytest

from test_helpers import (
    UPC_1,
    UPC_2,
    AuthorizationState,
    CreditPosture,
    SettlementStateAuthorization,
    fixtures,
)
from test_helpers.assertions import (
    assert_at_risk_threshold,
    assert_principal_aggregates,
    expected_void_rate_bps,
)

AUTHORIZED_STORES = 10000
AT_RISK_THRESHOLD_BPS = 1500


@pytest.fixture
def two_authorizations(api):
    """Two items win slots at a 12,000 store chain with 10,000 stores each in scope."""
    retailer = fixtures.create_retailer(
        api, total_store_count=12000, at_risk_void_rate_bps=AT_RISK_THRESHOLD_BPS
    )
    bundle = fixtures.active_principal(api, retailer["id"])
    principal = bundle["principal"]
    first_item = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_1)
    second_item = fixtures.validated_item(
        api, principal["id"], retailer["id"], upc=UPC_2, description="Mini Pizzas 8ct"
    )
    review = fixtures.opened_review(api, retailer["id"], new_item_slots=2)
    fixtures.submitted_presentation(
        api, review["id"], principal["id"], [first_item["id"], second_item["id"]]
    )
    review = fixtures.lock_and_decide(
        api,
        review["id"],
        retailer["id"],
        [first_item["id"], second_item["id"]],
        default_store_count=AUTHORIZED_STORES,
    )
    authorizations = fixtures.authorizations_for_review(api, review["id"])
    by_item = {authorization["item_id"]: authorization for authorization in authorizations}
    return {
        "retailer": retailer,
        "principal": principal,
        "at_threshold": by_item[first_item["id"]],
        "below_threshold": by_item[second_item["id"]],
    }


class TestAtRiskThresholdBoundary:
    def test_a_rate_exactly_at_the_threshold_moves_the_authorization_to_at_risk(
        self, api, two_authorizations
    ):
        """1,500 void stores out of 10,000 is exactly 1,500 basis points, and that is enough.

        PRD: "An `AUTHORIZED` authorization moves to `AT_RISK` when the recomputed
        `void_rate_bps` is at or above the chain's `at_risk_void_rate_bps`; an `AT_RISK`
        authorization returns to `AUTHORIZED` when a later posting, or a reversal, yields a
        rate strictly below that threshold."

        Design: Difficulty/boundary_precision_check/void_rate_exactly_at_at_risk_threshold_flips_authorization_state
        """
        retailer_id = two_authorizations["retailer"]["id"]
        fixtures.post_period(
            api,
            two_authorizations["at_threshold"]["id"],
            retailer_id,
            period_index=1,
            reported_store_count=AUTHORIZED_STORES,
            distributed_store_count=8500,
            reported_case_volume=25000,
        )

        authorization = fixtures.get_authorization(api, two_authorizations["at_threshold"]["id"])
        assert authorization["void_store_count"] == 1500
        assert authorization["void_rate_bps"] == 1500
        assert authorization["void_rate_bps"] == expected_void_rate_bps(1500, AUTHORIZED_STORES)
        assert authorization["authorization_state"] == AuthorizationState.AT_RISK
        assert_at_risk_threshold(authorization, AT_RISK_THRESHOLD_BPS)

    def test_one_more_distributed_store_keeps_the_authorization_authorized(
        self, api, two_authorizations
    ):
        """1,499 void stores is 1,499 basis points, strictly below the threshold.

        PRD: "The threshold is inclusive in one direction and strict in the other."

        Design: Difficulty/boundary_precision_check/void_rate_exactly_at_at_risk_threshold_flips_authorization_state
        """
        retailer_id = two_authorizations["retailer"]["id"]
        fixtures.post_period(
            api,
            two_authorizations["below_threshold"]["id"],
            retailer_id,
            period_index=1,
            reported_store_count=AUTHORIZED_STORES,
            distributed_store_count=8501,
            reported_case_volume=25000,
        )

        authorization = fixtures.get_authorization(api, two_authorizations["below_threshold"]["id"])
        assert authorization["void_store_count"] == 1499
        assert authorization["void_rate_bps"] == 1499
        assert authorization["authorization_state"] == AuthorizationState.AUTHORIZED
        assert_at_risk_threshold(authorization, AT_RISK_THRESHOLD_BPS)

    def test_the_settlement_dimension_does_not_move_with_the_at_risk_flag(
        self, api, two_authorizations
    ):
        """Neither award had a deal, so both stay UNBILLED with no slotting share.

        PRD: "Note that the two dimensions really are independent: an `AT_RISK`
        authorization stays `SLOTTING_AMORTIZING`, and a `DISCONTINUED` one may perfectly
        well be `SLOTTING_RECOVERED`."

        Design: Difficulty/boundary_precision_check/void_rate_exactly_at_at_risk_threshold_flips_authorization_state
        """
        retailer_id = two_authorizations["retailer"]["id"]
        for authorization, distributed in (
            (two_authorizations["at_threshold"], 8500),
            (two_authorizations["below_threshold"], 8501),
        ):
            fixtures.post_period(
                api,
                authorization["id"],
                retailer_id,
                period_index=1,
                reported_store_count=AUTHORIZED_STORES,
                distributed_store_count=distributed,
                reported_case_volume=25000,
            )

        at_threshold = fixtures.get_authorization(api, two_authorizations["at_threshold"]["id"])
        below_threshold = fixtures.get_authorization(
            api, two_authorizations["below_threshold"]["id"]
        )
        assert at_threshold["authorization_state"] == AuthorizationState.AT_RISK
        assert below_threshold["authorization_state"] == AuthorizationState.AUTHORIZED
        assert at_threshold["settlement_state"] == SettlementStateAuthorization.UNBILLED
        assert below_threshold["settlement_state"] == SettlementStateAuthorization.UNBILLED
        assert at_threshold["slotting_share_cents"] == 0
        assert below_threshold["slotting_share_cents"] == 0

    def test_a_single_at_risk_authorization_puts_the_principal_on_watch(
        self, api, two_authorizations
    ):
        """One at-risk count is enough for WATCH even with no slotting liability at all.

        PRD: "failing that it is `WATCH` when `at_risk_authorization_count` is 1 or more, or
        `liability_ratio_bps` is 5,000 or more, being fifty percent of the budget; and
        otherwise it is `NORMAL`."

        Design: Difficulty/boundary_precision_check/void_rate_exactly_at_at_risk_threshold_flips_authorization_state
        """
        retailer_id = two_authorizations["retailer"]["id"]
        for authorization, distributed in (
            (two_authorizations["at_threshold"], 8500),
            (two_authorizations["below_threshold"], 8501),
        ):
            fixtures.post_period(
                api,
                authorization["id"],
                retailer_id,
                period_index=1,
                reported_store_count=AUTHORIZED_STORES,
                distributed_store_count=distributed,
                reported_case_volume=25000,
            )

        principal = fixtures.get_principal(api, two_authorizations["principal"]["id"])
        assert principal["at_risk_authorization_count"] == 1
        assert principal["open_slotting_liability_cents"] == 0
        assert principal["liability_ratio_bps"] == 0
        assert principal["credit_posture"] == CreditPosture.WATCH
        assert_principal_aggregates(principal)
