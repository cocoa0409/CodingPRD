"""Two full negotiation loops, then acceptance by the side that is not the offeror."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    UPC_1,
    AmortizationMethod,
    ApiErrorId,
    AuthorizationState,
    CreditPosture,
    DealState,
    OfferSide,
    SettlementStateAuthorization,
    fixtures,
    make_retailer_buyer_headers,
    validate_error,
)
from test_helpers import factories as F
from test_helpers.assertions import (
    assert_quote_ladder,
    assert_slotting_money_conserved,
    assert_version_bumped_by,
    expected_liability_ratio_bps,
)

STORE_COUNT = 100
BUDGET_CENTS = 20000000
STANDING_COUNTER_CENTS = 58000
ACCEPTED_FEE_CENTS = 5887000


@pytest.fixture
def countered_deal(api):
    """A deal driven through propose 50000, counter 60000, propose 55000, counter 58000.

    Two full loops leave the retailer holding the standing offer, and the review is
    decided while the deal is still live so the award links to it.
    """
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(
        api, retailer["id"], principal_overrides={"slotting_budget_cents": BUDGET_CENTS}
    )
    principal = bundle["principal"]
    item = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_1)
    review = fixtures.opened_review(api, retailer["id"], new_item_slots=2)
    presentation = fixtures.submitted_presentation(
        api, review["id"], principal["id"], [item["id"]]
    )
    deal = fixtures.create_deal(
        api,
        presentation["id"],
        requested_fee_per_store_cents=50000,
        store_count_in_scope=STORE_COUNT,
        item_count_in_scope=1,
        forecast_annual_units=0,
        amortization_periods=4,
        amortization_method=AmortizationMethod.FORECAST_STRAIGHT,
    )
    fixtures.propose(api, deal["id"], 50000)
    fixtures.counter(api, deal["id"], retailer["id"], 60000)
    fixtures.propose(api, deal["id"], 55000)
    deal = fixtures.counter(api, deal["id"], retailer["id"], STANDING_COUNTER_CENTS)
    review = fixtures.lock_and_decide(api, review["id"], retailer["id"], [item["id"]])
    return {
        "retailer": retailer,
        "principal": principal,
        "item": item,
        "review": review,
        "presentation": presentation,
        "deal": deal,
    }


class TestNegotiationCycleThenNonOfferorAcceptance:
    def test_only_the_retailer_counters_advance_the_round_counter(self, api, countered_deal):
        """Two counters and two proposals leave the loop counter at two.

        PRD: "A successful counter increases `round_index` by one, overwrites
        `current_fee_per_store_cents`, replaces `forecast_annual_units` when
        `counter_forecast_annual_units` was supplied, sets `last_offer_side` to `RETAILER`,
        and re-evaluates the quote."

        Design: Difficulty/non_linear_state_machine/slotting_deal_negotiation_cycle_then_acceptance_by_non_offeror
        """
        deal = fixtures.get_deal(api, countered_deal["deal"]["id"])

        assert deal["state"] == DealState.COUNTERED
        assert deal["round_index"] == 2
        assert deal["last_offer_side"] == OfferSide.RETAILER
        assert deal["current_fee_per_store_cents"] == STANDING_COUNTER_CENTS

    def test_the_cycle_revisits_both_states_and_ratchets_the_fee_toward_the_middle(
        self, api, countered_deal
    ):
        """Each counter is strictly higher and each re-proposal strictly lower than the last.

        PRD: "Offers therefore ratchet toward each other, and the cycle terminates after at
        most three retailer counters."

        Design: Difficulty/non_linear_state_machine/slotting_deal_negotiation_cycle_then_acceptance_by_non_offeror
        """
        deal_id = countered_deal["deal"]["id"]
        retailer_id = countered_deal["retailer"]["id"]

        # A re-proposal must come down from the standing 58,000-cent counter.
        response = api.propose_deal(deal_id, F.propose_payload(60000), ACCOUNT_MANAGER_HEADERS)
        validate_error(response, ApiErrorId.PROPOSAL_NOT_LOWER, 409)

        reproposed = fixtures.propose(api, deal_id, 57000)
        assert reproposed["state"] == DealState.PROPOSED
        assert reproposed["last_offer_side"] == OfferSide.BROKER
        # Re-proposing does not advance the loop counter; only counters do.
        assert reproposed["round_index"] == 2

        # A counter that is not strictly higher than the standing offer is refused.
        response = api.counter_deal(
            deal_id, F.counter_payload(57000), make_retailer_buyer_headers(retailer_id)
        )
        validate_error(response, ApiErrorId.COUNTER_NOT_HIGHER, 409)

        third = fixtures.counter(api, deal_id, retailer_id, 59000)
        assert third["state"] == DealState.COUNTERED
        assert third["round_index"] == 3
        assert third["current_fee_per_store_cents"] == 59000

    def test_the_offeror_may_not_accept_its_own_standing_offer(self, api, countered_deal):
        """With the retailer holding the offer, a buyer acceptance is rejected.

        PRD: "In either direction, an attempt by the side that made the standing offer is
        rejected with `ERR_ACCEPT_BY_OFFEROR`."

        Design: Difficulty/non_linear_state_machine/slotting_deal_negotiation_cycle_then_acceptance_by_non_offeror
        """
        principal = fixtures.get_principal(api, countered_deal["principal"]["id"])
        response = api.accept_deal(
            countered_deal["deal"]["id"],
            F.accept_payload(principal["version"]),
            make_retailer_buyer_headers(countered_deal["retailer"]["id"]),
        )
        validate_error(response, ApiErrorId.ACCEPT_BY_OFFEROR, 409)

        deal = fixtures.get_deal(api, countered_deal["deal"]["id"])
        assert deal["state"] == DealState.COUNTERED
        assert deal["last_offer_side"] == OfferSide.RETAILER

    def test_the_broker_accepts_the_retailer_counter_and_the_ladder_freezes(
        self, api, countered_deal
    ):
        """The 58,000-cent counter puts the net above the tier-1 ceiling, so 150 bps apply.

        PRD: "A `RetailerBuyer` accepts a deal in `PROPOSED` state, which is legal only while
        `last_offer_side` is `BROKER`; a `BrokerAccountManager` accepts a deal in `COUNTERED`
        state, which is legal only while `last_offer_side` is `RETAILER`."

        Design: Difficulty/non_linear_state_machine/slotting_deal_negotiation_cycle_then_acceptance_by_non_offeror
        """
        deal = fixtures.accept_as_broker(
            api, countered_deal["deal"]["id"], countered_deal["principal"]["id"]
        )

        assert deal["gross_fee_cents"] == 5800000
        assert deal["volume_credit_cents"] == 0
        assert deal["net_before_admin_cents"] == 5800000
        assert deal["admin_fee_cents"] == 87000
        assert deal["quoted_fee_cents"] == ACCEPTED_FEE_CENTS
        assert deal["accepted_fee_cents"] == ACCEPTED_FEE_CENTS
        assert_quote_ladder(deal, STANDING_COUNTER_CENTS, STORE_COUNT, 1, 0)

    def test_acceptance_does_not_rest_in_accepted_and_carries_no_unit_cost(
        self, api, countered_deal
    ):
        """A zero forecast leaves the per-unit cost null, and the deal lands in AMORTIZING.

        PRD: "The deal does not rest in `ACCEPTED`: the system advances it `ACCEPTED` →
        `AMORTIZING` inside the same request, which is where the cascade of §3.6 fires, and
        the principal's `version` advances by one."

        Design: Difficulty/non_linear_state_machine/slotting_deal_negotiation_cycle_then_acceptance_by_non_offeror
        """
        before = fixtures.get_principal(api, countered_deal["principal"]["id"])
        deal = fixtures.accept_as_broker(
            api, countered_deal["deal"]["id"], countered_deal["principal"]["id"]
        )

        assert deal["state"] == DealState.AMORTIZING
        assert deal["cost_per_forecast_unit_cents"] is None
        assert deal["unamortized_balance_cents"] == ACCEPTED_FEE_CENTS
        assert deal["recovered_cents"] == 0
        assert_slotting_money_conserved(deal)

        after = fixtures.get_principal(api, countered_deal["principal"]["id"])
        assert_version_bumped_by(before, after, 1)

    def test_the_acceptance_cascade_moves_the_authorization_and_the_principal(
        self, api, countered_deal
    ):
        """The single linked authorization takes the whole fee as its slotting share.

        PRD: "The first hop moves every authorization linked to that deal on both dimensions
        at once: `authorization_state` from `PENDING_SETUP` to `AUTHORIZED`, and
        `settlement_state` from `UNBILLED` to `SLOTTING_AMORTIZING`."

        Design: Difficulty/non_linear_state_machine/slotting_deal_negotiation_cycle_then_acceptance_by_non_offeror
        """
        deal = fixtures.accept_as_broker(
            api, countered_deal["deal"]["id"], countered_deal["principal"]["id"]
        )

        authorization = fixtures.authorization_for_deal(api, deal["id"])
        assert authorization["authorization_state"] == AuthorizationState.AUTHORIZED
        assert authorization["settlement_state"] == SettlementStateAuthorization.SLOTTING_AMORTIZING
        assert authorization["slotting_share_cents"] == ACCEPTED_FEE_CENTS

        principal = fixtures.get_principal(api, countered_deal["principal"]["id"])
        assert principal["slotting_committed_cents"] == ACCEPTED_FEE_CENTS
        assert principal["open_slotting_liability_cents"] == ACCEPTED_FEE_CENTS
        assert principal["liability_ratio_bps"] == 2943
        assert principal["liability_ratio_bps"] == expected_liability_ratio_bps(
            ACCEPTED_FEE_CENTS, 0, BUDGET_CENTS
        )
        assert principal["credit_posture"] == CreditPosture.NORMAL
