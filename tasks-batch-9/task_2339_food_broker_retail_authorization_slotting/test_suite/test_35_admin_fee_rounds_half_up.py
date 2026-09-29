"""A net that lands the administration fee on an exact half cent must round up, not to even."""

import pytest

from test_helpers import (
    ADMIN_BPS_TIER_1,
    DealState,
    fixtures,
)
from test_helpers.assertions import (
    assert_slotting_money_conserved,
    expected_admin_fee,
    round_half_up,
)

FEE_PER_STORE_CENTS = 50001
STORE_COUNT = 20
ITEM_COUNT = 1
GROSS_FEE_CENTS = 1000020
ADMIN_FEE_CENTS = 25001
QUOTED_FEE_CENTS = 1025021


@pytest.fixture
def deal_on_the_half_cent(api):
    """50,001 per store over 20 stores gives a net of 1,000,020 and a raw admin fee of 25,000.5."""
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
        fee_per_store_cents=FEE_PER_STORE_CENTS,
        store_count_in_scope=STORE_COUNT,
        item_count_in_scope=ITEM_COUNT,
        forecast_annual_units=0,
        amortization_periods=4,
    )
    return {
        "retailer": retailer,
        "principal": principal,
        "item": item,
        "review": review,
        "deal": deal,
    }


def award_and_accept(api, scope):
    fixtures.lock_and_decide(
        api, scope["review"]["id"], scope["retailer"]["id"], [scope["item"]["id"]]
    )
    return fixtures.accept_as_buyer(
        api, scope["deal"]["id"], scope["retailer"]["id"], scope["principal"]["id"]
    )


class TestAdminFeeRoundsHalfUp:
    def test_a_zero_forecast_earns_no_credit_so_the_net_is_the_gross(
        self, api, deal_on_the_half_cent
    ):
        """Twenty stores at 50,001 for one item is 1,000,020 with nothing to discount.

        PRD: "`gross_fee_cents` is `current_fee_per_store_cents` multiplied by
        `store_count_in_scope` and then by `item_count_in_scope`."

        Design: Corner/calculations/slotting_quote_admin_fee_rounds_half_up_not_bankers
        """
        deal = deal_on_the_half_cent["deal"]

        assert deal["gross_fee_cents"] == FEE_PER_STORE_CENTS * STORE_COUNT * ITEM_COUNT
        assert deal["gross_fee_cents"] == GROSS_FEE_CENTS
        assert deal["volume_credit_cents"] == 0
        assert deal["net_before_admin_cents"] == GROSS_FEE_CENTS

    def test_the_exact_half_cent_rounds_up_and_not_to_even(self, api, deal_on_the_half_cent):
        """1,000,020 times 250 bps is 25,000.5, which is 25,001 — banker's rounding gives 25,000.

        PRD: "`admin_fee_cents` is `net_before_admin_cents` multiplied by that tiered basis-point
        rate, divided by 10,000, rounded half up to whole cents."

        Design: Corner/calculations/slotting_quote_admin_fee_rounds_half_up_not_bankers
        """
        deal = deal_on_the_half_cent["deal"]
        raw_numerator = GROSS_FEE_CENTS * ADMIN_BPS_TIER_1

        assert raw_numerator == 250005000
        assert round_half_up(raw_numerator, 10000) == ADMIN_FEE_CENTS
        assert expected_admin_fee(GROSS_FEE_CENTS) == ADMIN_FEE_CENTS
        assert deal["admin_fee_cents"] == ADMIN_FEE_CENTS
        assert deal["admin_fee_cents"] != 25000

    def test_the_rounded_up_cent_reaches_the_quoted_and_accepted_figures(
        self, api, deal_on_the_half_cent
    ):
        """The extra cent is not swallowed anywhere downstream of the administration fee.

        PRD: "`quoted_fee_cents` is `net_before_admin_cents` plus `admin_fee_cents`."

        Design: Corner/calculations/slotting_quote_admin_fee_rounds_half_up_not_bankers
        """
        scope = deal_on_the_half_cent
        assert scope["deal"]["quoted_fee_cents"] == QUOTED_FEE_CENTS

        accepted = award_and_accept(api, scope)

        assert accepted["state"] == DealState.AMORTIZING
        assert accepted["accepted_fee_cents"] == QUOTED_FEE_CENTS
        assert accepted["unamortized_balance_cents"] == QUOTED_FEE_CENTS
        assert_slotting_money_conserved(accepted)

    def test_a_zero_forecast_leaves_the_unit_cost_undefined(self, api, deal_on_the_half_cent):
        """With no forecast cases there is no per-case figure, and the field is null rather than 0.

        PRD: "Acceptance freezes `accepted_fee_cents` at the standing `quoted_fee_cents`, sets
        `unamortized_balance_cents` to that same figure, and computes
        `cost_per_forecast_unit_cents` as `accepted_fee_cents` divided by `forecast_annual_units`,
        rounded half up to two decimal places — null when `forecast_annual_units` is zero."

        Design: Corner/calculations/slotting_quote_admin_fee_rounds_half_up_not_bankers
        """
        accepted = award_and_accept(api, deal_on_the_half_cent)

        assert accepted["forecast_annual_units"] == 0
        assert accepted["cost_per_forecast_unit_cents"] is None

    def test_the_single_authorization_carries_the_whole_odd_cent_fee(
        self, api, deal_on_the_half_cent
    ):
        """One linked authorization means a base share of the whole fee and no remainder.

        PRD: "The second hop allocates the money: `slotting_share_cents` distributes
        `accepted_fee_cents` across those authorizations by taking the base share as
        `accepted_fee_cents` divided by the number of linked authorizations, floored to whole
        cents, computing the remainder as `accepted_fee_cents` less the base share multiplied by
        that count, and giving one extra cent to each of the first *remainder* authorizations in an
        order defined by `created_at` ascending and then item `upc` ascending."

        Design: Corner/calculations/slotting_quote_admin_fee_rounds_half_up_not_bankers
        """
        scope = deal_on_the_half_cent
        award_and_accept(api, scope)

        authorization = fixtures.authorization_for_deal(api, scope["deal"]["id"])

        assert authorization["slotting_share_cents"] == QUOTED_FEE_CENTS
        assert authorization["authorized_store_count"] == STORE_COUNT
