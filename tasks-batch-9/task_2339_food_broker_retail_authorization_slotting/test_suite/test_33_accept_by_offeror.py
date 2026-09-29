"""Whoever holds the standing offer may not accept it — and that is a state guard, not RBAC."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    ApiErrorId,
    DealState,
    OfferSide,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
    validate_error,
)
from test_helpers import factories as F
from test_helpers.assertions import assert_version_unchanged

FEE_PER_STORE_CENTS = 12500
STORE_COUNT = 400
ACCEPTED_FEE_CENTS = 5125000


@pytest.fixture
def decided_review_with_a_standing_broker_offer(api):
    """A deal in PROPOSED whose last offer came from the broker, ready to be accepted."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(api, retailer["id"])
    principal = bundle["principal"]
    item = fixtures.validated_item(api, principal["id"], retailer["id"])
    review = fixtures.opened_review(api, retailer["id"])
    presentation = fixtures.submitted_presentation(api, review["id"], principal["id"], [item["id"]])
    deal = fixtures.proposed_deal(
        api,
        presentation["id"],
        fee_per_store_cents=FEE_PER_STORE_CENTS,
        store_count_in_scope=STORE_COUNT,
        item_count_in_scope=1,
        forecast_annual_units=0,
        amortization_periods=6,
    )
    review = fixtures.lock_and_decide(api, review["id"], retailer["id"], [item["id"]])
    return {
        "retailer": retailer,
        "principal": principal,
        "review": review,
        "presentation": presentation,
        "deal": deal,
    }


def accept_as(api, scope, headers):
    principal = fixtures.get_principal(api, scope["principal"]["id"])
    return api.accept_deal(
        scope["deal"]["id"], F.accept_payload(principal["version"]), headers
    )


def buyer_headers(scope):
    return make_retailer_buyer_headers(scope["retailer"]["id"])


class TestAcceptByOfferor:
    def test_the_broker_may_not_accept_its_own_standing_offer(
        self, api, decided_review_with_a_standing_broker_offer
    ):
        """last_offer_side is BROKER, so the broker branch of accept does not apply.

        PRD: "In either direction, an attempt by the side that made the standing offer is
        rejected with `ERR_ACCEPT_BY_OFFEROR`."

        Design: Corner/state_machines/deal_accept_by_the_offeror_itself_is_rejected
        """
        scope = decided_review_with_a_standing_broker_offer
        assert scope["deal"]["last_offer_side"] == OfferSide.BROKER

        response = accept_as(api, scope, ACCOUNT_MANAGER_HEADERS)

        validate_error(response, ApiErrorId.ACCEPT_BY_OFFEROR, 409)

    def test_the_refusal_is_a_state_guard_and_not_a_role_denial(
        self, api, decided_review_with_a_standing_broker_offer
    ):
        """The account manager is a permitted caller; only the runtime data forbids it.

        PRD: "Acceptance is deliberately asymmetric: a party may never accept its own standing
        offer."

        PRD: "The offeror rule on acceptance, `ERR_ACCEPT_BY_OFFEROR` (409), belongs to this band
        as well."

        Design: Corner/state_machines/deal_accept_by_the_offeror_itself_is_rejected
        """
        scope = decided_review_with_a_standing_broker_offer

        response = accept_as(api, scope, ACCOUNT_MANAGER_HEADERS)

        assert response.status_code == 409
        assert ApiErrorId.ROLE_FORBIDDEN not in response.text

    def test_the_refused_acceptance_leaves_the_deal_and_the_principal_untouched(
        self, api, decided_review_with_a_standing_broker_offer
    ):
        """The version pin the caller read is still current afterwards.

        PRD: "Acceptance freezes `accepted_fee_cents` at the standing `quoted_fee_cents`, sets
        `unamortized_balance_cents` to that same figure, and computes
        `cost_per_forecast_unit_cents` as `accepted_fee_cents` divided by `forecast_annual_units`,
        rounded half up to two decimal places — null when `forecast_annual_units` is zero."

        Design: Corner/state_machines/deal_accept_by_the_offeror_itself_is_rejected
        """
        scope = decided_review_with_a_standing_broker_offer
        before = fixtures.get_principal(api, scope["principal"]["id"])

        validate_error(accept_as(api, scope, ACCOUNT_MANAGER_HEADERS), ApiErrorId.ACCEPT_BY_OFFEROR, 409)

        deal = fixtures.get_deal(api, scope["deal"]["id"])
        assert deal["state"] == DealState.PROPOSED
        assert deal["accepted_fee_cents"] == 0
        assert_version_unchanged(before, fixtures.get_principal(api, scope["principal"]["id"]))

    def test_the_other_side_closes_the_same_deal(
        self, api, decided_review_with_a_standing_broker_offer
    ):
        """The buyer holds no standing offer, so the buyer may accept.

        PRD: "The deal does not rest in `ACCEPTED`: the system advances it `ACCEPTED` →
        `AMORTIZING` inside the same request, which is where the cascade of §3.6 fires, and the
        principal's `version` advances by one."

        Design: Corner/state_machines/deal_accept_by_the_offeror_itself_is_rejected
        """
        scope = decided_review_with_a_standing_broker_offer
        validate_error(accept_as(api, scope, ACCOUNT_MANAGER_HEADERS), ApiErrorId.ACCEPT_BY_OFFEROR, 409)

        accepted = get_success_data(accept_as(api, scope, buyer_headers(scope)), 200)

        assert accepted["state"] == DealState.AMORTIZING
        assert accepted["accepted_fee_cents"] == ACCEPTED_FEE_CENTS
        assert accepted["last_offer_side"] == OfferSide.BROKER

    def test_an_amortizing_deal_has_no_accept_transition_left(
        self, api, decided_review_with_a_standing_broker_offer
    ):
        """A third attempt is refused by the machine rather than by the offeror rule.

        PRD: "The target must be in a state from which the requested transition exists, and
        companion resources must be in the states the transition names — covering `status` on
        principals, agreements and reviews, `catalog_state` on items, `status` on presentations,
        `state` on deals and promotion events, both `authorization_state` and `settlement_state`
        on authorizations, and both `settlement_state` and `dispute_state` on deductions."

        Design: Corner/state_machines/deal_accept_by_the_offeror_itself_is_rejected
        """
        scope = decided_review_with_a_standing_broker_offer
        get_success_data(accept_as(api, scope, buyer_headers(scope)), 200)

        response = accept_as(api, scope, buyer_headers(scope))

        validate_error(response, ApiErrorId.INVALID_STATE, 409)
