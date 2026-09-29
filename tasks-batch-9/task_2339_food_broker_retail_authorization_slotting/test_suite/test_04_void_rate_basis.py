"""The same distribution report measured under both pinned void-rate bases."""

import pytest

from test_helpers import UPC_1, AuthorizationState, VoidRateBasis, fixtures
from test_helpers.assertions import (
    assert_store_counts_conserved,
    assert_voids_report,
    expected_void_rate_bps,
)

REPORTED = 380
DISTRIBUTED = 340
AUTHORIZED_STORES = 400


@pytest.fixture
def two_chains_one_principal(api):
    """One principal wins a slot at a store-count-basis chain and a reported-basis chain.

    Neither award has a live negotiation, so both authorizations auto-advance to
    AUTHORIZED and are ready to receive a period.
    """
    store_count_chain = fixtures.create_retailer(
        api,
        name="Bigmart",
        chain_code="BIGMART",
        total_store_count=1200,
        void_rate_basis_default=VoidRateBasis.STORE_COUNT_BASIS,
        at_risk_void_rate_bps=1500,
    )
    reported_chain = fixtures.create_retailer(
        api,
        name="Valufresh",
        chain_code="VALUFRESH",
        total_store_count=1200,
        void_rate_basis_default=VoidRateBasis.REPORTED_BASIS,
        at_risk_void_rate_bps=1500,
    )
    principal = fixtures.create_principal(api)
    fixtures.create_agreement(api, principal["id"], store_count_chain["id"])
    fixtures.create_agreement(api, principal["id"], reported_chain["id"])
    principal = fixtures.set_principal_active(api, principal["id"])
    item = fixtures.validated_item(api, principal["id"], store_count_chain["id"], upc=UPC_1)

    authorizations = {}
    # Both decks are opened and submitted while the clock is still before the shared
    # submission deadline; only then is the clock advanced to lock and decide.
    for key, chain in (("store_count", store_count_chain), ("reported", reported_chain)):
        review = fixtures.opened_review(api, chain["id"])
        fixtures.submitted_presentation(api, review["id"], principal["id"], [item["id"]])
        authorizations[key] = {"chain": chain, "review": review}
    for leg in authorizations.values():
        review = fixtures.lock_and_decide(
            api,
            leg["review"]["id"],
            leg["chain"]["id"],
            [item["id"]],
            default_store_count=AUTHORIZED_STORES,
        )
        leg["authorization"] = fixtures.authorizations_for_review(api, review["id"])[0]
    return {"principal": principal, "item": item, **authorizations}


def post_the_same_period(api, leg):
    return fixtures.post_period(
        api,
        leg["authorization"]["id"],
        leg["chain"]["id"],
        period_index=1,
        reported_store_count=REPORTED,
        distributed_store_count=DISTRIBUTED,
        reported_case_volume=5000,
    )


class TestVoidRateBasisDivergence:
    def test_the_basis_is_pinned_from_the_chain_default_at_award_time(self, api, two_chains_one_principal):
        """Each authorization carries the basis its own chain declared.

        PRD: "Its `void_rate_basis` is copied from the chain's `void_rate_basis_default` at
        award time and is never re-read afterwards — later changes to the chain's default do
        not retroactively change how an existing authorization measures voids."

        Design: Difficulty/dual_variant_calc/void_rate_store_count_basis_vs_reported_basis_divergence
        """
        store_count_leg = two_chains_one_principal["store_count"]
        reported_leg = two_chains_one_principal["reported"]

        assert store_count_leg["authorization"]["void_rate_basis"] == VoidRateBasis.STORE_COUNT_BASIS
        assert reported_leg["authorization"]["void_rate_basis"] == VoidRateBasis.REPORTED_BASIS
        assert store_count_leg["authorization"]["authorized_store_count"] == AUTHORIZED_STORES
        assert reported_leg["authorization"]["authorized_store_count"] == AUTHORIZED_STORES

    def test_store_count_basis_counts_unreported_stores_as_voids(self, api, two_chains_one_principal):
        """Sixty of four hundred authorized stores are void, exactly at the threshold.

        PRD: "Every store the chain never reported on counts as a void, because the
        denominator is the authorized store count."

        Design: Difficulty/dual_variant_calc/void_rate_store_count_basis_vs_reported_basis_divergence
        """
        leg = two_chains_one_principal["store_count"]
        post_the_same_period(api, leg)

        authorization = fixtures.get_authorization(api, leg["authorization"]["id"])
        assert authorization["distributed_store_count"] == DISTRIBUTED
        assert authorization["void_store_count"] == 60
        assert authorization["pending_store_count"] == 0
        assert authorization["void_rate_bps"] == 1500
        assert authorization["void_rate_bps"] == expected_void_rate_bps(60, AUTHORIZED_STORES)
        assert authorization["authorization_state"] == AuthorizationState.AT_RISK
        assert_store_counts_conserved(authorization)

    def test_reported_basis_treats_unreported_stores_as_pending(self, api, two_chains_one_principal):
        """Only the forty reported-but-undistributed stores are void: 1,052 basis points.

        PRD: "Here `pending_store_count` is `authorized_store_count` less
        `distributed_store_count` less `void_store_count`: stores the chain never reported on
        are pending, not void."

        Design: Difficulty/dual_variant_calc/void_rate_store_count_basis_vs_reported_basis_divergence
        """
        leg = two_chains_one_principal["reported"]
        post_the_same_period(api, leg)

        authorization = fixtures.get_authorization(api, leg["authorization"]["id"])
        assert authorization["distributed_store_count"] == DISTRIBUTED
        assert authorization["void_store_count"] == 40
        assert authorization["pending_store_count"] == 20
        assert authorization["void_rate_bps"] == 1052
        assert authorization["void_rate_bps"] == expected_void_rate_bps(40, REPORTED)
        assert authorization["authorization_state"] == AuthorizationState.AUTHORIZED
        assert_store_counts_conserved(authorization)

    def test_the_same_snapshot_puts_one_chain_at_risk_and_leaves_the_other_healthy(
        self, api, two_chains_one_principal
    ):
        """Identical counts, opposite outcomes — which is why the basis is pinned.

        PRD: "The same snapshot can therefore put an authorization at risk under one basis
        and leave it healthy under the other, which is precisely why the basis is pinned at
        award time."

        Design: Difficulty/dual_variant_calc/void_rate_store_count_basis_vs_reported_basis_divergence
        """
        store_count_leg = two_chains_one_principal["store_count"]
        reported_leg = two_chains_one_principal["reported"]
        post_the_same_period(api, store_count_leg)
        post_the_same_period(api, reported_leg)

        at_risk = fixtures.get_authorization(api, store_count_leg["authorization"]["id"])
        healthy = fixtures.get_authorization(api, reported_leg["authorization"]["id"])
        assert at_risk["authorization_state"] == AuthorizationState.AT_RISK
        assert healthy["authorization_state"] == AuthorizationState.AUTHORIZED
        assert at_risk["void_rate_bps"] > healthy["void_rate_bps"]

    def test_the_voids_report_shows_the_counterfactual_basis_both_ways(self, api, two_chains_one_principal):
        """Each report names the convention not in use and the rate it would have produced.

        PRD: "and — so a buyer can see what the other measurement convention would have said
        — a `counterfactual_basis` naming the basis not in use together with the
        `counterfactual_void_rate_bps` that basis would have produced from the same latest
        live posting."

        Design: Difficulty/dual_variant_calc/void_rate_store_count_basis_vs_reported_basis_divergence
        """
        store_count_leg = two_chains_one_principal["store_count"]
        reported_leg = two_chains_one_principal["reported"]
        post_the_same_period(api, store_count_leg)
        post_the_same_period(api, reported_leg)

        store_count_report = fixtures.get_voids_report(api, store_count_leg["authorization"]["id"])
        reported_report = fixtures.get_voids_report(api, reported_leg["authorization"]["id"])

        assert_voids_report(store_count_report)
        assert_voids_report(reported_report)
        assert store_count_report["void_rate_basis"] == VoidRateBasis.STORE_COUNT_BASIS
        assert store_count_report["void_rate_bps"] == 1500
        assert store_count_report["is_at_risk"] is True
        assert store_count_report["counterfactual_basis"] == VoidRateBasis.REPORTED_BASIS
        assert store_count_report["counterfactual_void_rate_bps"] == 1052

        assert reported_report["void_rate_basis"] == VoidRateBasis.REPORTED_BASIS
        assert reported_report["void_rate_bps"] == 1052
        assert reported_report["is_at_risk"] is False
        assert reported_report["counterfactual_basis"] == VoidRateBasis.STORE_COUNT_BASIS
        assert reported_report["counterfactual_void_rate_bps"] == 1500
        assert store_count_report["at_risk_void_rate_bps"] == 1500
        assert reported_report["latest_period_index"] == 1
