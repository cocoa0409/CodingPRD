"""Two spare cents across three authorizations go to the lowest UPCs, not the first rows created."""

import pytest

from test_helpers import (
    AuthorizationState,
    CreditPosture,
    SettlementStateAuthorization,
    UPC_1,
    UPC_2,
    UPC_3,
    fixtures,
)
from test_helpers.assertions import (
    expected_liability_ratio_bps,
    expected_quote,
    round_half_up,
)

FEE_PER_STORE_CENTS = 12500
STORE_COUNT = 401
ITEM_COUNT = 3
GROSS_FEE_CENTS = 15037500
ADMIN_FEE_CENTS = 225563
ACCEPTED_FEE_CENTS = 15263063
BASE_SHARE_CENTS = 5087687
REMAINDER_CENTS = 2
SLOTTING_BUDGET_CENTS = 40000000


@pytest.fixture
def three_awarded_items(api):
    """Three items created in descending UPC order, all awarded by one decision."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(
        api,
        retailer["id"],
        principal_overrides={"slotting_budget_cents": SLOTTING_BUDGET_CENTS},
    )
    principal = bundle["principal"]
    # Deliberately non-UPC creation order: the highest UPC exists first.
    items = {
        upc: fixtures.validated_item(
            api, principal["id"], retailer["id"], upc=upc, description=f"Item {upc}"
        )
        for upc in (UPC_3, UPC_1, UPC_2)
    }
    review = fixtures.opened_review(api, retailer["id"], new_item_slots=3)
    item_ids = [items[UPC_3]["id"], items[UPC_1]["id"], items[UPC_2]["id"]]
    presentation = fixtures.submitted_presentation(
        api, review["id"], principal["id"], item_ids
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
        "items": items,
        "item_ids": item_ids,
        "review": review,
        "deal": deal,
    }


def award_and_accept(api, scope):
    fixtures.lock_and_decide(
        api, scope["review"]["id"], scope["retailer"]["id"], scope["item_ids"]
    )
    return fixtures.accept_as_buyer(
        api, scope["deal"]["id"], scope["retailer"]["id"], scope["principal"]["id"]
    )


def shares_by_upc(api, scope):
    """Map each awarded item's UPC to its authorization row."""
    authorizations = fixtures.authorizations_for_review(api, scope["review"]["id"])
    by_item = {row["item_id"]: row for row in authorizations}
    return {upc: by_item[item["id"]] for upc, item in scope["items"].items()}


class TestSlottingShareRemainderAllocation:
    def test_the_tier_two_rate_and_half_up_rounding_fix_the_accepted_fee(
        self, api, three_awarded_items
    ):
        """A net above five million takes 150 bps, and 225,562.5 rounds up to 225,563.

        PRD: "The administration rate is tiered on `net_before_admin_cents` and on nothing else:
        250 basis points when `net_before_admin_cents` is at or below 5,000,000 cents (the
        fifty-thousand-dollar tier-1 ceiling, inclusive), and 150 basis points above it."

        PRD: "`admin_fee_cents` is `net_before_admin_cents` multiplied by that tiered basis-point
        rate, divided by 10,000, rounded half up to whole cents."

        Design: Corner/calculations/slotting_share_remainder_goes_to_the_lowest_upcs
        """
        deal = three_awarded_items["deal"]

        assert deal["gross_fee_cents"] == GROSS_FEE_CENTS
        assert deal["volume_credit_cents"] == 0
        assert deal["net_before_admin_cents"] == GROSS_FEE_CENTS
        assert round_half_up(GROSS_FEE_CENTS * 150, 10000) == ADMIN_FEE_CENTS
        assert deal["admin_fee_cents"] == ADMIN_FEE_CENTS
        assert deal["quoted_fee_cents"] == ACCEPTED_FEE_CENTS
        assert (
            expected_quote(FEE_PER_STORE_CENTS, STORE_COUNT, ITEM_COUNT, 0)["quoted_fee_cents"]
            == ACCEPTED_FEE_CENTS
        )

    def test_the_base_share_is_floored_and_leaves_two_spare_cents(
        self, api, three_awarded_items
    ):
        """15,263,063 over three authorizations is 5,087,687 each with two cents left over.

        PRD: "The second hop allocates the money: `slotting_share_cents` distributes
        `accepted_fee_cents` across those authorizations by taking the base share as
        `accepted_fee_cents` divided by the number of linked authorizations, floored to whole
        cents, computing the remainder as `accepted_fee_cents` less the base share multiplied by
        that count, and giving one extra cent to each of the first *remainder* authorizations in an
        order defined by `created_at` ascending and then item `upc` ascending."

        Design: Corner/calculations/slotting_share_remainder_goes_to_the_lowest_upcs
        """
        accepted = award_and_accept(api, three_awarded_items)

        assert accepted["accepted_fee_cents"] == ACCEPTED_FEE_CENTS
        assert ACCEPTED_FEE_CENTS // ITEM_COUNT == BASE_SHARE_CENTS
        assert ACCEPTED_FEE_CENTS - BASE_SHARE_CENTS * ITEM_COUNT == REMAINDER_CENTS

    def test_the_two_lowest_upcs_absorb_the_spare_cents(self, api, three_awarded_items):
        """The item created first holds the highest UPC and gets the bare base share.

        PRD: "The ordering is deterministic and never depends on `id`, and the shares sum to
        `accepted_fee_cents` exactly."

        Design: Corner/calculations/slotting_share_remainder_goes_to_the_lowest_upcs
        """
        award_and_accept(api, three_awarded_items)

        shares = shares_by_upc(api, three_awarded_items)

        assert shares[UPC_1]["slotting_share_cents"] == BASE_SHARE_CENTS + 1
        assert shares[UPC_2]["slotting_share_cents"] == BASE_SHARE_CENTS + 1
        assert shares[UPC_3]["slotting_share_cents"] == BASE_SHARE_CENTS

    def test_the_shares_sum_to_the_accepted_fee_exactly(self, api, three_awarded_items):
        """No cent is minted and none is lost by the flooring.

        PRD: "Across a deal's authorizations, the sum of `slotting_share_cents` equals the deal's
        `accepted_fee_cents` exactly, with no cent lost or duplicated."

        Design: Corner/calculations/slotting_share_remainder_goes_to_the_lowest_upcs
        """
        award_and_accept(api, three_awarded_items)

        shares = shares_by_upc(api, three_awarded_items)

        assert sum(row["slotting_share_cents"] for row in shares.values()) == ACCEPTED_FEE_CENTS

    def test_trade_spend_equals_the_share_while_no_promotion_has_settled(
        self, api, three_awarded_items
    ):
        """Promotional funding contributes nothing yet, so trade spend is the slotting share alone.

        PRD: "Each authorization's `trade_spend_total_cents` is then recomputed as
        `slotting_share_cents` plus `promo_settled_funding_cents`."

        Design: Corner/calculations/slotting_share_remainder_goes_to_the_lowest_upcs
        """
        award_and_accept(api, three_awarded_items)

        shares = shares_by_upc(api, three_awarded_items)

        for row in shares.values():
            assert row["promo_settled_funding_cents"] == 0
            assert row["trade_spend_total_cents"] == row["slotting_share_cents"]
        assert shares[UPC_3]["trade_spend_total_cents"] == BASE_SHARE_CENTS

    def test_all_three_authorizations_go_live_and_leave_the_principal_normal(
        self, api, three_awarded_items
    ):
        """Every linked authorization moves on both dimensions and the ratio stays under half.

        PRD: "The first hop moves every authorization linked to that deal on both dimensions at
        once: `authorization_state` from `PENDING_SETUP` to `AUTHORIZED`, and `settlement_state`
        from `UNBILLED` to `SLOTTING_AMORTIZING`."

        Design: Corner/calculations/slotting_share_remainder_goes_to_the_lowest_upcs
        """
        scope = three_awarded_items
        award_and_accept(api, scope)

        shares = shares_by_upc(api, scope)
        for row in shares.values():
            assert row["authorization_state"] == AuthorizationState.AUTHORIZED
            assert row["settlement_state"] == SettlementStateAuthorization.SLOTTING_AMORTIZING
            assert row["authorized_store_count"] == STORE_COUNT

        principal = fixtures.get_principal(api, scope["principal"]["id"])
        assert principal["liability_ratio_bps"] == expected_liability_ratio_bps(
            ACCEPTED_FEE_CENTS, 0, SLOTTING_BUDGET_CENTS
        )
        assert principal["liability_ratio_bps"] == 3815
        assert principal["credit_posture"] == CreditPosture.NORMAL
