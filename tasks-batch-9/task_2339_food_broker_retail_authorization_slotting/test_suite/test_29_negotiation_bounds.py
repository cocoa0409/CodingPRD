"""Offers ratchet toward each other, strictly, and only three counters are allowed."""

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

OPENING_FEE_PER_STORE_CENTS = 50000
MAX_NEGOTIATION_ROUNDS = 3


@pytest.fixture
def proposed_deal_at_the_opening_ask(api):
    """A submitted deck with a broker offer of 50,000 per store on the table."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(api, retailer["id"])
    principal = bundle["principal"]
    item = fixtures.validated_item(api, principal["id"], retailer["id"])
    review = fixtures.opened_review(api, retailer["id"])
    presentation = fixtures.submitted_presentation(
        api, review["id"], principal["id"], [item["id"]]
    )
    deal = fixtures.proposed_deal(
        api,
        presentation["id"],
        fee_per_store_cents=OPENING_FEE_PER_STORE_CENTS,
        store_count_in_scope=400,
        item_count_in_scope=1,
        forecast_annual_units=0,
        amortization_periods=4,
    )
    return {"retailer": retailer, "principal": principal, "review": review, "deal": deal}


def counter(api, scope, fee):
    return api.counter_deal(
        scope["deal"]["id"],
        F.counter_payload(fee),
        make_retailer_buyer_headers(scope["retailer"]["id"]),
    )


def propose(api, scope, fee):
    return api.propose_deal(
        scope["deal"]["id"], F.propose_payload(fee), ACCOUNT_MANAGER_HEADERS
    )


def walk_to_the_third_counter(api, scope):
    """Counter, re-propose, counter, re-propose, counter — three legal retailer counters."""
    get_success_data(counter(api, scope, 60000), 200)
    get_success_data(propose(api, scope, 58000), 200)
    get_success_data(counter(api, scope, 59000), 200)
    get_success_data(propose(api, scope, 57000), 200)
    return get_success_data(counter(api, scope, 58500), 200)


class TestNegotiationBounds:
    def test_a_counter_equal_to_the_standing_offer_is_not_higher(
        self, api, proposed_deal_at_the_opening_ask
    ):
        """The guard is a strict inequality, so matching the offer is refused.

        PRD: "A retailer counter moves `PROPOSED` → `COUNTERED` with
        `counter_fee_per_store_cents` and an optional `counter_forecast_annual_units`; the
        counter must be strictly higher than the standing `current_fee_per_store_cents`,
        otherwise `ERR_COUNTER_NOT_HIGHER`, and `round_index` must still be below the three
        counters the system allows, otherwise `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

        Design: Corner/state_machines/negotiation_round_cap_and_monotonic_offer_guards_rejected
        """
        scope = proposed_deal_at_the_opening_ask

        validate_error(
            counter(api, scope, OPENING_FEE_PER_STORE_CENTS), ApiErrorId.COUNTER_NOT_HIGHER, 409
        )

        deal = fixtures.get_deal(api, scope["deal"]["id"])
        assert deal["state"] == DealState.PROPOSED
        assert deal["round_index"] == 0
        assert deal["current_fee_per_store_cents"] == OPENING_FEE_PER_STORE_CENTS

    def test_a_legal_counter_overwrites_the_standing_offer_and_counts_a_round(
        self, api, proposed_deal_at_the_opening_ask
    ):
        """Sixty thousand is strictly higher, so the retailer takes the offer side.

        PRD: "A successful counter increases `round_index` by one, overwrites
        `current_fee_per_store_cents`, replaces `forecast_annual_units` when
        `counter_forecast_annual_units` was supplied, sets `last_offer_side` to `RETAILER`, and
        re-evaluates the quote."

        Design: Corner/state_machines/negotiation_round_cap_and_monotonic_offer_guards_rejected
        """
        countered = get_success_data(counter(api, proposed_deal_at_the_opening_ask, 60000), 200)

        assert countered["state"] == DealState.COUNTERED
        assert countered["current_fee_per_store_cents"] == 60000
        assert countered["round_index"] == 1
        assert countered["last_offer_side"] == OfferSide.RETAILER

    def test_a_re_proposal_equal_to_the_counter_is_not_lower(
        self, api, proposed_deal_at_the_opening_ask
    ):
        """The broker must actually come down, and equality does not count.

        PRD: "The broker may then re-propose, moving `COUNTERED` → `PROPOSED` with a
        `proposed_fee_per_store_cents` that must be strictly lower than the standing counter,
        otherwise `ERR_PROPOSAL_NOT_LOWER`; the same presentation-status precondition applies,
        and the same side effects follow with `last_offer_side` back at `BROKER`."

        Design: Corner/state_machines/negotiation_round_cap_and_monotonic_offer_guards_rejected
        """
        scope = proposed_deal_at_the_opening_ask
        get_success_data(counter(api, scope, 60000), 200)

        validate_error(propose(api, scope, 60000), ApiErrorId.PROPOSAL_NOT_LOWER, 409)

        deal = fixtures.get_deal(api, scope["deal"]["id"])
        assert deal["state"] == DealState.COUNTERED
        assert deal["round_index"] == 1

    def test_three_counters_are_allowed(self, api, proposed_deal_at_the_opening_ask):
        """The loop runs to its cap with the offers converging each time.

        PRD: "Offers therefore ratchet toward each other, and the cycle terminates after at most
        three retailer counters."

        Design: Corner/state_machines/negotiation_round_cap_and_monotonic_offer_guards_rejected
        """
        third = walk_to_the_third_counter(api, proposed_deal_at_the_opening_ask)

        assert third["state"] == DealState.COUNTERED
        assert third["round_index"] == MAX_NEGOTIATION_ROUNDS
        assert third["current_fee_per_store_cents"] == 58500
        assert third["last_offer_side"] == OfferSide.RETAILER

    def test_the_fourth_counter_exhausts_the_cycle(self, api, proposed_deal_at_the_opening_ask):
        """round_index has reached the cap, so no further counter exists.

        PRD: "A retailer counter moves `PROPOSED` → `COUNTERED` with
        `counter_fee_per_store_cents` and an optional `counter_forecast_annual_units`; the
        counter must be strictly higher than the standing `current_fee_per_store_cents`,
        otherwise `ERR_COUNTER_NOT_HIGHER`, and `round_index` must still be below the three
        counters the system allows, otherwise `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

        Design: Corner/state_machines/negotiation_round_cap_and_monotonic_offer_guards_rejected
        """
        scope = proposed_deal_at_the_opening_ask
        walk_to_the_third_counter(api, scope)
        get_success_data(propose(api, scope, 56000), 200)

        validate_error(counter(api, scope, 57500), ApiErrorId.NEGOTIATION_ROUNDS_EXHAUSTED, 409)

    def test_the_exhausted_deal_is_left_acceptable_by_the_retailer(
        self, api, proposed_deal_at_the_opening_ask
    ):
        """The last word is the broker's, so the buyer may still close it.

        PRD: "A `RetailerBuyer` accepts a deal in `PROPOSED` state, which is legal only while
        `last_offer_side` is `BROKER`; a `BrokerAccountManager` accepts a deal in `COUNTERED`
        state, which is legal only while `last_offer_side` is `RETAILER`."

        Design: Corner/state_machines/negotiation_round_cap_and_monotonic_offer_guards_rejected
        """
        scope = proposed_deal_at_the_opening_ask
        walk_to_the_third_counter(api, scope)
        get_success_data(propose(api, scope, 56000), 200)
        validate_error(counter(api, scope, 57500), ApiErrorId.NEGOTIATION_ROUNDS_EXHAUSTED, 409)

        deal = fixtures.get_deal(api, scope["deal"]["id"])
        assert deal["state"] == DealState.PROPOSED
        assert deal["current_fee_per_store_cents"] == 56000
        assert deal["round_index"] == MAX_NEGOTIATION_ROUNDS
        assert deal["last_offer_side"] == OfferSide.BROKER
