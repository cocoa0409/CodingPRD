"""One negotiation re-quoted three times, walking the credit cap and the admin tier ceiling."""

import pytest

from test_helpers import (
    ADMIN_BPS_TIER_1,
    ADMIN_TIER_1_MAX_CENTS,
    CREDIT_PER_FORECAST_UNIT_CENTS,
    DealState,
    OfferSide,
    VOLUME_CREDIT_CAP_BPS,
    fixtures,
)
from test_helpers.assertions import assert_quote_ladder

OPENING_FEE_PER_STORE_CENTS = 12500
COUNTER_FEE_PER_STORE_CENTS = 14000
FINAL_FEE_PER_STORE_CENTS = 13000
STORE_COUNT = 400
ITEM_COUNT = 1
OPENING_FORECAST_UNITS = 2000000
FINAL_FORECAST_UNITS = 200000
SLOTTING_BUDGET_CENTS = 20000000


@pytest.fixture
def negotiation_at_the_opening_ask(api):
    """A PROPOSED deal at 12,500 per store over 400 stores with a 2,000,000 case forecast."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(
        api,
        retailer["id"],
        principal_overrides={"slotting_budget_cents": SLOTTING_BUDGET_CENTS},
    )
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
        store_count_in_scope=STORE_COUNT,
        item_count_in_scope=ITEM_COUNT,
        forecast_annual_units=OPENING_FORECAST_UNITS,
        amortization_periods=4,
    )
    return {
        "retailer": retailer,
        "principal": principal,
        "item": item,
        "review": review,
        "presentation": presentation,
        "deal": deal,
    }


def counter_with_a_smaller_forecast(api, scope):
    return fixtures.counter(
        api,
        scope["deal"]["id"],
        scope["retailer"]["id"],
        COUNTER_FEE_PER_STORE_CENTS,
        counter_forecast_annual_units=FINAL_FORECAST_UNITS,
    )


def re_propose(api, scope):
    return fixtures.propose(api, scope["deal"]["id"], FINAL_FEE_PER_STORE_CENTS)


def award_and_accept(api, scope):
    fixtures.lock_and_decide(
        api, scope["review"]["id"], scope["retailer"]["id"], [scope["item"]["id"]]
    )
    return fixtures.accept_as_buyer(
        api, scope["deal"]["id"], scope["retailer"]["id"], scope["principal"]["id"]
    )


class TestQuoteLadderCreditCapAndTierBoundary:
    def test_the_volume_credit_is_capped_against_the_gross_fee(
        self, api, negotiation_at_the_opening_ask
    ):
        """A 2,000,000 case forecast earns 6,000,000 of raw credit but only 2,000,000 is allowed.

        PRD: "The cap is 4,000 basis points of the gross fee — forty percent of `gross_fee_cents`,
        floored to whole cents."

        Design: Corner/calculations/slotting_quote_volume_credit_cap_and_admin_tier_boundary
        """
        deal = negotiation_at_the_opening_ask["deal"]
        raw_credit = OPENING_FORECAST_UNITS * CREDIT_PER_FORECAST_UNIT_CENTS

        assert deal["gross_fee_cents"] == 5000000
        assert raw_credit == 6000000
        assert deal["volume_credit_cents"] == 5000000 * VOLUME_CREDIT_CAP_BPS // 10000
        assert deal["volume_credit_cents"] == 2000000
        assert deal["net_before_admin_cents"] == 3000000
        assert deal["admin_fee_cents"] == 75000
        assert deal["quoted_fee_cents"] == 3075000

    def test_the_admin_tier_ceiling_is_inclusive_on_the_net_figure(
        self, api, negotiation_at_the_opening_ask
    ):
        """The counter lands the net on exactly 5,000,000, which is still the 250 bps tier.

        PRD: "The administration rate is tiered on `net_before_admin_cents` and on nothing else:
        250 basis points when `net_before_admin_cents` is at or below 5,000,000 cents (the
        fifty-thousand-dollar tier-1 ceiling, inclusive), and 150 basis points above it."

        PRD: "The tier is keyed on the net figure *before* the administration fee is added — never
        on `quoted_fee_cents` and never on `accepted_fee_cents` — even though the administration
        fee is itself part of the quoted figure."

        Design: Corner/calculations/slotting_quote_volume_credit_cap_and_admin_tier_boundary
        """
        countered = counter_with_a_smaller_forecast(api, negotiation_at_the_opening_ask)

        assert countered["gross_fee_cents"] == 5600000
        assert countered["volume_credit_cents"] == 600000
        assert countered["net_before_admin_cents"] == ADMIN_TIER_1_MAX_CENTS
        # 5,000,000 * 250 / 10,000. Keying the tier on the quoted figure (5,125,000, above
        # the ceiling) would charge 150 bps and yield 76,875 / 5,076,875 instead.
        assert countered["admin_fee_cents"] == ADMIN_TIER_1_MAX_CENTS * ADMIN_BPS_TIER_1 // 10000
        assert countered["admin_fee_cents"] == 125000
        assert countered["quoted_fee_cents"] == 5125000

    def test_the_smaller_forecast_survives_the_re_proposal(
        self, api, negotiation_at_the_opening_ask
    ):
        """The broker comes back down to 13,000 while the countered forecast stays in force.

        PRD: "`net_before_admin_cents` is `gross_fee_cents` less `volume_credit_cents`."

        PRD: "`quoted_fee_cents` is `net_before_admin_cents` plus `admin_fee_cents`."

        Design: Corner/calculations/slotting_quote_volume_credit_cap_and_admin_tier_boundary
        """
        scope = negotiation_at_the_opening_ask
        counter_with_a_smaller_forecast(api, scope)

        reproposed = re_propose(api, scope)

        assert reproposed["current_fee_per_store_cents"] == FINAL_FEE_PER_STORE_CENTS
        assert reproposed["last_offer_side"] == OfferSide.BROKER
        assert_quote_ladder(
            reproposed,
            FINAL_FEE_PER_STORE_CENTS,
            STORE_COUNT,
            ITEM_COUNT,
            FINAL_FORECAST_UNITS,
        )
        assert reproposed["gross_fee_cents"] == 5200000
        assert reproposed["net_before_admin_cents"] == 4600000
        assert reproposed["admin_fee_cents"] == 115000
        assert reproposed["quoted_fee_cents"] == 4715000

    def test_acceptance_freezes_the_standing_quote_and_derives_the_unit_cost(
        self, api, negotiation_at_the_opening_ask
    ):
        """4,715,000 over 200,000 forecast cases is 23.575, which rounds half up to 23.58.

        PRD: "Acceptance freezes `accepted_fee_cents` at the standing `quoted_fee_cents`, sets
        `unamortized_balance_cents` to that same figure, and computes
        `cost_per_forecast_unit_cents` as `accepted_fee_cents` divided by `forecast_annual_units`,
        rounded half up to two decimal places — null when `forecast_annual_units` is zero."

        Design: Corner/calculations/slotting_quote_volume_credit_cap_and_admin_tier_boundary
        """
        scope = negotiation_at_the_opening_ask
        counter_with_a_smaller_forecast(api, scope)
        re_propose(api, scope)

        accepted = award_and_accept(api, scope)

        assert accepted["accepted_fee_cents"] == 4715000
        assert accepted["unamortized_balance_cents"] == 4715000
        assert accepted["cost_per_forecast_unit_cents"] == pytest.approx(23.58)
        assert accepted["state"] == DealState.AMORTIZING

    def test_the_accepted_quote_lands_on_the_principal_ledger(
        self, api, negotiation_at_the_opening_ask
    ):
        """The committed and open liability figures both carry the final quote, not the opening one.

        PRD: "The third hop re-derives the principal: `slotting_committed_cents`,
        `open_slotting_liability_cents` and `liability_ratio_bps` are recomputed and
        `credit_posture` is re-derived, which may move the principal from `NORMAL` to `WATCH` or
        `RESTRICTED` in the very request that accepted the deal."

        Design: Corner/calculations/slotting_quote_volume_credit_cap_and_admin_tier_boundary
        """
        scope = negotiation_at_the_opening_ask
        counter_with_a_smaller_forecast(api, scope)
        re_propose(api, scope)
        award_and_accept(api, scope)

        principal = fixtures.get_principal(api, scope["principal"]["id"])

        assert principal["slotting_committed_cents"] == 4715000
        assert principal["open_slotting_liability_cents"] == 4715000
