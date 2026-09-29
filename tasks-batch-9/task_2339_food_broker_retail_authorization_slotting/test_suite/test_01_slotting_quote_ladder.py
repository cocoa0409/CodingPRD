"""The six-step slotting quote ladder and where its administration tier is keyed."""

import pytest

from test_helpers import UPC_1, UPC_2, DealState, fixtures
from test_helpers.assertions import assert_deal, assert_quote_ladder, expected_admin_fee


@pytest.fixture
def negotiation_scope(api):
    """A chain, an active principal, two items, a scheduled review and a draft deck.

    Opening a negotiation needs only a presentation, so the items here are left
    unvalidated on purpose.
    """
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(api, retailer["id"])
    principal = bundle["principal"]
    item_one = fixtures.create_item(api, principal["id"], upc=UPC_1)
    item_two = fixtures.create_item(api, principal["id"], upc=UPC_2, description="Mini Pizzas 8ct")
    review = fixtures.create_review(api, retailer["id"])
    presentation = fixtures.create_presentation(
        api, review["id"], principal["id"], [item_one["id"], item_two["id"]]
    )
    return {
        "retailer": retailer,
        "principal": principal,
        "items": [item_one, item_two],
        "review": review,
        "presentation": presentation,
    }


class TestQuoteLadderAdministrationTier:
    def test_quote_ladder_intermediates_are_persisted_step_by_step(self, api, negotiation_scope):
        """Each ladder step is stored, so a quote is auditable end to end.

        PRD: "Every time the fee on the table changes, the quote ladder is re-evaluated
        in strict order, and every intermediate is persisted so the quote is auditable
        and no step can be back-derived from a later one."

        Design: Difficulty/combinatorial_formula/slotting_admin_tier_keyed_on_pre_admin_net_not_quoted_fee
        """
        deal = fixtures.create_deal(
            api,
            negotiation_scope["presentation"]["id"],
            requested_fee_per_store_cents=28000,
            store_count_in_scope=100,
            item_count_in_scope=2,
            forecast_annual_units=200000,
            amortization_periods=6,
        )

        assert_deal(deal)
        assert deal["gross_fee_cents"] == 5600000
        assert deal["volume_credit_cents"] == 600000
        assert deal["net_before_admin_cents"] == 5000000
        assert deal["admin_fee_cents"] == 125000
        assert deal["quoted_fee_cents"] == 5125000
        assert_quote_ladder(deal, 28000, 100, 2, 200000)

    def test_volume_credit_is_capped_at_forty_percent_of_the_gross_fee(self, api, negotiation_scope):
        """A 200,000 case forecast asks for 600,000 cents of credit and gets all of it.

        PRD: "`volume_credit_cents` is the smaller of the raw credit and the cap, so once
        the forecast reaches the capped credit divided by the 3-cent rate the credit stops
        growing entirely and further forecast volume buys no further discount."

        Design: Difficulty/combinatorial_formula/slotting_admin_tier_keyed_on_pre_admin_net_not_quoted_fee
        """
        deal = fixtures.create_deal(
            api,
            negotiation_scope["presentation"]["id"],
            requested_fee_per_store_cents=28000,
            store_count_in_scope=100,
            item_count_in_scope=2,
            forecast_annual_units=200000,
            amortization_periods=6,
        )

        raw_credit = 200000 * 3
        cap = 5600000 * 4000 // 10000
        assert raw_credit == 600000
        assert cap == 2240000
        assert deal["volume_credit_cents"] == min(raw_credit, cap)
        assert deal["net_before_admin_cents"] == deal["gross_fee_cents"] - deal["volume_credit_cents"]

    def test_administration_tier_reads_the_net_and_not_the_quoted_figure(self, api, negotiation_scope):
        """Net lands exactly on the inclusive tier-1 ceiling, so 250 basis points apply.

        PRD: "The tier is keyed on the net figure *before* the administration fee is added
        — never on `quoted_fee_cents` and never on `accepted_fee_cents` — even though the
        administration fee is itself part of the quoted figure."

        Design: Difficulty/combinatorial_formula/slotting_admin_tier_keyed_on_pre_admin_net_not_quoted_fee
        """
        deal = fixtures.create_deal(
            api,
            negotiation_scope["presentation"]["id"],
            requested_fee_per_store_cents=28000,
            store_count_in_scope=100,
            item_count_in_scope=2,
            forecast_annual_units=200000,
            amortization_periods=6,
        )

        # 250 bps of the net, because 5,000,000 cents is the inclusive tier-1 ceiling.
        assert deal["admin_fee_cents"] == expected_admin_fee(5000000) == 125000
        assert deal["quoted_fee_cents"] == 5125000
        # Keying the tier on the quoted figure would have charged 150 bps instead.
        assert deal["quoted_fee_cents"] != 5076875
        assert deal["admin_fee_cents"] != 76875

    def test_a_freshly_opened_negotiation_carries_no_accepted_fee(self, api, negotiation_scope):
        """The ladder produces a quote; only acceptance freezes a fee.

        PRD: "A new deal begins with `state` at `DRAFT`, `round_index` at 0,
        `last_offer_side` null, `accepted_fee_cents`, `recovered_cents`,
        `written_off_cents`, `unamortized_balance_cents` and `periods_posted` all at 0,
        `reject_reason` null, and `current_fee_per_store_cents` seeded from
        `requested_fee_per_store_cents`."

        Design: Difficulty/combinatorial_formula/slotting_admin_tier_keyed_on_pre_admin_net_not_quoted_fee
        """
        deal = fixtures.create_deal(
            api,
            negotiation_scope["presentation"]["id"],
            requested_fee_per_store_cents=28000,
            store_count_in_scope=100,
            item_count_in_scope=2,
            forecast_annual_units=200000,
            amortization_periods=6,
        )

        assert deal["state"] == DealState.DRAFT
        # No fee is frozen before acceptance; the unset value is not a positive amount.
        assert not deal["accepted_fee_cents"]
        assert deal["round_index"] == 0
        assert deal["last_offer_side"] is None
        assert deal["current_fee_per_store_cents"] == 28000
        assert deal["recovered_cents"] == 0
        assert deal["unamortized_balance_cents"] == 0
        assert deal["periods_posted"] == 0
