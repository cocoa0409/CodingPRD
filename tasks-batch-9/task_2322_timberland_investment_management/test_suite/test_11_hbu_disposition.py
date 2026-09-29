"""Higher-and-better-use closing: the money waterfall, the acreage split and the tonnage claw-back."""

from test_helpers import (
    assert_acres,
    assert_fund_cash,
    assert_money,
    assert_property_dimensions,
    assert_stand_partition,
    assert_tons,
    validate_paginated,
)
from test_helpers.fixtures import (
    close_parcel,
    contracted_parcel,
    owned_tract,
    read_block,
    read_fund,
    read_property,
    read_stand,
    reserve_block,
)
from test_helpers.test_users import make_forest_manager_headers

CONTRACT_PRICE_USD = 285000.00
CLOSING_COSTS_USD = 4200.00


def _tract_with_a_contracted_parcel(api):
    """An owned tract whose 110.00-acre carve-out is under contract at 285000.00."""
    ctx = owned_tract(api)
    block = reserve_block(api, ctx.stand_id, planned_tons=1000.00)
    assert_stand_partition(read_stand(api, ctx.stand_id), available_tons=3647.12)
    parcel = contracted_parcel(
        api, ctx.stand_id, contract_price_usd=CONTRACT_PRICE_USD, acres=110.00
    )
    assert_property_dimensions(
        read_property(api, ctx.property_id), status="HBU_MARKETED"
    )
    return ctx, block, parcel


class TestHbuClosingSplitsTheStandAndPaysTheFund:
    """One closing settles cash, mints a derived stand and trims the harvest plan."""

    def test_closing_settles_the_commission_and_the_net_proceeds(self, api):
        """A 285000.00 contract yields 9975.00 of commission and 270825.00 of proceeds.

        PRD: "Money settles first: `net_proceeds_usd` is `contract_price_usd` less `commission_usd` less `closing_costs_usd`, rounded half-up to two decimals, and is credited to both the fund's `cash_balance_usd` and its `net_operating_cash_usd`."

        Design: Difficulty/transitive_cascade/hbu_close_cascades_split_waterfall_and_fund_proceeds
        """
        ctx, _, parcel = _tract_with_a_contracted_parcel(api)
        assert_money(parcel["commission_usd"], 9975.00, "commission_usd")

        closed = close_parcel(api, parcel["id"], closing_costs_usd=CLOSING_COSTS_USD)

        assert closed["status"] == "CLOSED"
        assert_money(closed["net_proceeds_usd"], 270825.00, "net_proceeds_usd")
        assert_fund_cash(
            read_fund(api, ctx.fund_id),
            cash_balance_usd=570825.00,
            net_operating_cash_usd=270825.00,
        )

    def test_the_withdrawn_tonnage_is_a_pro_rata_share_of_the_pre_split_acreage(self, api):
        """One hundred ten of one hundred twenty acres carries 4259.86 of the 4647.12 tons.

        PRD: "`withdrawn_tons` is the parent stand's `net_merch_tons` multiplied by the parcel's `acres` and divided by the parent stand's `acres` — a pro-rata share of standing wood measured against the pre-split acreage — rounded half-up to two decimals."

        Design: Difficulty/transitive_cascade/hbu_close_cascades_split_waterfall_and_fund_proceeds
        """
        ctx, _, parcel = _tract_with_a_contracted_parcel(api)

        closed = close_parcel(api, parcel["id"], closing_costs_usd=CLOSING_COSTS_USD)

        assert_tons(closed["withdrawn_tons"], 4259.86, "withdrawn_tons")

    def test_the_split_conserves_the_original_acreage_exactly(self, api):
        """Ten acres stay behind and one hundred ten leave on a disposed derived stand.

        PRD: "and the parent stand's `acres` is reduced by the parcel's `acres`, rounded half-up to two decimals, so that parent and derived together equal the original"

        Design: Difficulty/transitive_cascade/hbu_close_cascades_split_waterfall_and_fund_proceeds
        """
        ctx, _, parcel = _tract_with_a_contracted_parcel(api)

        closed = close_parcel(api, parcel["id"], closing_costs_usd=CLOSING_COSTS_USD)

        parent = read_stand(api, ctx.stand_id)
        assert_acres(parent["acres"], 10.00, "parent acres")

        derived, _meta = validate_paginated(
            api.list_stand_derived_stands(ctx.stand_id, make_forest_manager_headers())
        )
        assert len(derived) == 1, "one closing mints exactly one derived stand"
        assert derived[0]["id"] == closed["derived_stand_id"]
        assert_acres(derived[0]["acres"], 110.00, "derived acres")
        assert_acres(
            float(derived[0]["acres"]) + float(parent["acres"]),
            120.00,
            "conserved acreage",
        )

    def test_the_derived_stand_carries_the_withdrawn_wood_and_is_disposed(self, api):
        """The minted stand inherits the cruise and lands in its terminal state.

        PRD: "The derived stand references its origin through `split_from_stand_id`, inherits the parent's descriptive attributes, carries `net_merch_tons` equal to `withdrawn_tons`, is created directly in `INVENTORIED` because it inherits a completed cruise, and is then moved in the same chain of effects to the terminal `DISPOSED`; no client-facing operation reaches `DISPOSED` by any other route."

        Design: Difficulty/transitive_cascade/hbu_close_cascades_split_waterfall_and_fund_proceeds
        """
        ctx, _, parcel = _tract_with_a_contracted_parcel(api)

        close_parcel(api, parcel["id"], closing_costs_usd=CLOSING_COSTS_USD)

        derived, _meta = validate_paginated(
            api.list_stand_derived_stands(ctx.stand_id, make_forest_manager_headers())
        )
        assert derived[0]["status"] == "DISPOSED"
        assert derived[0]["split_from_stand_id"] == ctx.stand_id
        assert_tons(derived[0]["net_merch_tons"], 4259.86, "derived net_merch_tons")

    def test_the_parent_pool_stays_whole_while_the_claim_moves_buckets(self, api):
        """The pool is unchanged and the withdrawal is parked in its own bucket.

        PRD: "Instead the tonnage is parked in the `hbu_withdrawn_tons` bucket, which rises by `withdrawn_tons`."

        Design: Difficulty/transitive_cascade/hbu_close_cascades_split_waterfall_and_fund_proceeds
        """
        ctx, _, parcel = _tract_with_a_contracted_parcel(api)

        close_parcel(api, parcel["id"], closing_costs_usd=CLOSING_COSTS_USD)

        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            net_merch_tons=4647.12,
            hbu_withdrawn_tons=4259.86,
            reserved_tons=387.26,
            committed_tons=0.00,
            dedicated_tons=0.00,
            available_tons=0.00,
        )

    def test_the_waterfall_trims_the_reserved_block_without_voiding_it(self, api):
        """A 612.74-ton shortfall leaves 387.26 planned tons on a still-reserved block.

        PRD: "against a shortfall computed as the greater of zero and the sum of `reserved_tons`, `committed_tons`, `dedicated_tons` and `hbu_withdrawn_tons` less the stand's `net_merch_tons`, rounded half-up to two decimals"

        Design: Difficulty/transitive_cascade/hbu_close_cascades_split_waterfall_and_fund_proceeds
        """
        ctx, block, parcel = _tract_with_a_contracted_parcel(api)

        close_parcel(api, parcel["id"], closing_costs_usd=CLOSING_COSTS_USD)

        trimmed = read_block(api, block["id"])
        assert_tons(trimmed["planned_tons"], 387.26, "planned_tons")
        assert trimmed["status"] == "RESERVED"
        assert trimmed["voided_reason"] is None

    def test_the_closing_flags_replanning_and_returns_the_tract_to_owned(self, api):
        """With the pipeline empty the tract comes off the market carrying a replan flag.

        PRD: "Finally, closing returns the property's `status` from `HBU_MARKETED` to `OWNED` when no parcel of the property remains in `LISTED` or `UNDER_CONTRACT`, and increments the stand's `version`."

        Design: Difficulty/transitive_cascade/hbu_close_cascades_split_waterfall_and_fund_proceeds
        """
        ctx, _, parcel = _tract_with_a_contracted_parcel(api)

        close_parcel(api, parcel["id"], closing_costs_usd=CLOSING_COSTS_USD)

        assert_property_dimensions(
            read_property(api, ctx.property_id),
            status="OWNED",
            harvest_plan_status="REPLAN_REQUIRED",
        )
        assert read_fund(api, ctx.fund_id)["replan_property_count"] == 1
