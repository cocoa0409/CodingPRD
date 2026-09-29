"""The nine pinned pricing steps: tiers, the discount ceiling, floors and add-on caps."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import ADMIN_REVIEW, assert_add_on_detail, assert_cents, assert_fraction
from test_helpers.constants import (
    PRIMER_QTY_FOR_5000000,
    PRIMER_QTY_FOR_20000000,
    SKU_CART,
    SKU_DISPENSER,
)
from test_helpers.factories import (
    ADJUSTMENT_LINE,
    CART_LINE,
    DISPENSER_LINE,
    OMIT,
    price_quote_params,
)
from test_helpers.fixtures import (
    prime_committed_spend,
    read_member,
    read_usage,
    record_usage,
    setup_active_contract,
    setup_authorised_member,
)


def _nonprofit_world(api):
    """A nonprofit member sitting exactly on the tier-2 threshold of 20000000 cents."""
    world = setup_active_contract(
        api, lines=(DISPENSER_LINE, CART_LINE, ADJUSTMENT_LINE)
    )
    member, analysis = setup_authorised_member(
        api,
        world,
        legal_name="Harbor Lights Foundation",
        state_code="TX",
        member_category="NONPROFIT_501C3",
        annual_spend_ceiling_cents=50000000,
        governing_body_resolution_number=OMIT,
        irs_determination_letter_number="IRS-DL-2019-88213",
    )
    world["member"] = member
    world["analysis"] = analysis
    world["primer"] = prime_committed_spend(
        api, world, member, analysis, PRIMER_QTY_FOR_20000000
    )
    return world


def _quote(api, world, sku, quantity, **extra):
    params = price_quote_params(
        world["lines"][sku]["id"], world["member"]["id"], quantity, **extra
    )
    return validate_success(
        api.get_price_quote(world["contract"]["id"], ADMIN_REVIEW, params=params)
    )


def _add_on_world(api):
    """One tier-0 member and one member primed exactly onto the tier-1 threshold."""
    world = setup_active_contract(api, lines=(DISPENSER_LINE, ADJUSTMENT_LINE))
    pine, pine_analysis = setup_authorised_member(
        api,
        world,
        legal_name="Pine Hollow",
        state_code="TX",
        member_category="CITY",
        governing_body_resolution_number="RES-PH-2026-002",
    )
    quarry, quarry_analysis = setup_authorised_member(
        api,
        world,
        legal_name="Quarry Ridge County",
        state_code="TX",
        member_category="COUNTY",
        governing_body_resolution_number="RES-QR-2026-007",
    )
    world["primer"] = prime_committed_spend(
        api, world, quarry, quarry_analysis, PRIMER_QTY_FOR_5000000
    )
    world["pine"] = (pine, pine_analysis)
    world["quarry"] = (quarry, quarry_analysis)
    return world


def _elect_all_add_ons(api, world, member, analysis, quantity):
    return record_usage(
        api,
        world["contract"]["id"],
        member["id"],
        world["lines"][SKU_DISPENSER]["id"],
        analysis["id"],
        quantity=quantity,
        add_on_codes=["TRAINING", "FREIGHT", "INSIDE_DELIVERY"],
    )


class TestDiscountCeilingAndPriceFloor:
    def test_01_the_nonprofit_bonus_is_added_then_capped_at_twenty_percent(self, api):
        """PRD §3.6: "A member whose `member_category` is `NONPROFIT_501C3` earns a
        bonus of three percentage points on top — the fraction 0.0300 — and every other
        category earns nothing extra. Add base and bonus, then cap the sum at a total
        discount of twenty percent (the fraction 0.2000); the result is
        `total_discount_pct`."

        Design: Difficulty/combinatorial_formula/net_unit_price_tier_plus_nonprofit_bonus_hits_discount_cap_then_floor
        """
        world = _nonprofit_world(api)
        assert_cents(world["primer"]["total_cents"], 20000000, "primer total_cents")

        quote = _quote(api, world, SKU_DISPENSER, 10)

        assert_cents(quote["spend_basis_cents"], 20000000, "spend_basis_cents")
        assert quote["discount_tier_index"] == 2
        assert_fraction(quote["total_discount_pct"], 0.2000, "total_discount_pct")
        assert_cents(quote["net_unit_price_cents"], 10000, "net_unit_price_cents")
        assert quote["floor_binding"] is False

    def test_02_a_capped_discount_can_still_be_absorbed_entirely_by_the_price_floor(self, api):
        """PRD §3.6: "`net_unit_price_cents` is the larger of that rounded figure and
        the line's `price_floor_cents` — the rounding happens *before* the floor
        comparison, so the stored net price is always a whole cent and never below the
        floor."

        Design: Difficulty/combinatorial_formula/net_unit_price_tier_plus_nonprofit_bonus_hits_discount_cap_then_floor
        """
        world = _nonprofit_world(api)

        quote = _quote(api, world, SKU_CART, 1)

        assert_fraction(quote["total_discount_pct"], 0.2000, "total_discount_pct")
        assert_cents(quote["net_unit_price_cents"], 9800, "net_unit_price_cents")
        assert quote["floor_binding"] is True
        assert_cents(quote["total_cents"], 9947, "total_cents")

    def test_03_the_quoted_waterfall_is_the_one_frozen_onto_the_recorded_order(self, api):
        """PRD §3.6: "That read-only computation takes a `line_item_id`, a
        `member_agency_id`, a `quantity` and optional `add_on_codes`, runs exactly the
        same steps one through eight against the member's *current*
        `committed_spend_cents`, creates no row and moves no counter, and returns
        `line_item_id`, `member_agency_id`, `spend_basis_cents`, `discount_tier_index`,
        `total_discount_pct`, `net_unit_price_cents`, `subtotal_cents`,
        `add_on_charges_cents`, `chargeable_base_cents`, `effective_fee_rate_bps`,
        `admin_fee_cents` and `total_cents`, plus two diagnostic booleans:
        `floor_binding`, true when the price floor rather than the discounted price
        determined `net_unit_price_cents`, and `aggregate_add_on_cap_binding`, true when
        the fifteen-percent aggregate ceiling rather than the per-code sum determined
        `add_on_charges_cents`."

        Design: Difficulty/combinatorial_formula/net_unit_price_tier_plus_nonprofit_bonus_hits_discount_cap_then_floor
        """
        world = _nonprofit_world(api)
        quote = _quote(api, world, SKU_DISPENSER, 10)

        assert_cents(quote["subtotal_cents"], 100000, "subtotal_cents")
        assert_cents(quote["add_on_charges_cents"], 0, "add_on_charges_cents")
        assert quote["effective_fee_rate_bps"] == 150
        assert_cents(quote["admin_fee_cents"], 1500, "admin_fee_cents")
        assert_cents(quote["total_cents"], 101500, "total_cents")

        usage = record_usage(
            api,
            world["contract"]["id"],
            world["member"]["id"],
            world["lines"][SKU_DISPENSER]["id"],
            world["analysis"]["id"],
            quantity=10,
        )
        assert_cents(usage["net_unit_price_cents"], 10000, "net_unit_price_cents")
        assert_cents(usage["total_cents"], 101500, "total_cents")

    def test_04_each_line_resolves_the_same_capped_discount_against_its_own_floor(self, api):
        """PRD §3.6: "The two bounds are independent: the twenty-percent ceiling caps
        the discount, the floor caps the resulting price, and either, both or neither
        may bind."

        Design: Difficulty/combinatorial_formula/net_unit_price_tier_plus_nonprofit_bonus_hits_discount_cap_then_floor
        """
        world = _nonprofit_world(api)
        dispenser = record_usage(
            api,
            world["contract"]["id"],
            world["member"]["id"],
            world["lines"][SKU_DISPENSER]["id"],
            world["analysis"]["id"],
            quantity=10,
        )
        cart = record_usage(
            api,
            world["contract"]["id"],
            world["member"]["id"],
            world["lines"][SKU_CART]["id"],
            world["analysis"]["id"],
            quantity=1,
        )

        assert_cents(dispenser["net_unit_price_cents"], 10000, "dispenser net_unit_price_cents")
        assert cart["discount_tier_index"] == 2
        assert_cents(cart["net_unit_price_cents"], 9800, "cart net_unit_price_cents")
        assert_cents(cart["admin_fee_cents"], 147, "cart admin_fee_cents")
        assert_cents(cart["total_cents"], 9947, "cart total_cents")
        member = read_member(api, world["member"]["id"])
        assert_cents(member["committed_spend_cents"], 20111447, "committed_spend_cents")


class TestAddOnCapsAndOrdering:
    def test_05_every_per_code_cap_binds_before_the_charges_are_summed(self, api):
        """PRD §3.6: "For each catalogue entry whose `code` the member elected, compute
        a `raw_cents` charge as `subtotal_cents` multiplied by that entry's `rate_pct`,
        rounded half up to a whole cent; compute `capped_cents` as the smaller of
        `raw_cents` and that entry's `cap_cents`; and append an object of `code`,
        `raw_cents` and `capped_cents` to `add_on_detail`."

        Design: Difficulty/combinatorial_formula/add_on_charges_per_code_caps_versus_aggregate_cap_with_pinned_order
        """
        world = _add_on_world(api)
        member, analysis = world["pine"]

        usage = _elect_all_add_ons(api, world, member, analysis, 160)

        assert usage["discount_tier_index"] == 0
        assert_cents(usage["net_unit_price_cents"], 12500, "net_unit_price_cents")
        assert_cents(usage["subtotal_cents"], 2000000, "subtotal_cents")
        assert_add_on_detail(
            usage["add_on_detail"],
            [
                ("FREIGHT", 120000, 50000),
                ("INSIDE_DELIVERY", 80000, 15000),
                ("TRAINING", 200000, 100000),
            ],
        )
        assert_cents(usage["add_on_charges_cents"], 165000, "add_on_charges_cents")

    def test_06_the_fee_is_assessed_on_the_subtotal_plus_the_capped_add_ons(self, api):
        """PRD §3.6: "`chargeable_base_cents` is `subtotal_cents` plus
        `add_on_charges_cents`. This is the base on which the administrative fee is
        assessed."

        Design: Difficulty/combinatorial_formula/add_on_charges_per_code_caps_versus_aggregate_cap_with_pinned_order
        """
        world = _add_on_world(api)
        member, analysis = world["pine"]

        usage = _elect_all_add_ons(api, world, member, analysis, 160)

        assert_cents(usage["chargeable_base_cents"], 2165000, "chargeable_base_cents")
        assert usage["effective_fee_rate_bps"] == 200
        assert_cents(usage["admin_fee_cents"], 43300, "admin_fee_cents")
        assert_cents(usage["total_cents"], 2208300, "total_cents")

    def test_07_the_aggregate_ceiling_is_rounded_half_up_before_it_is_compared(self, api):
        """PRD §3.6: "Separately compute an aggregate ceiling as `subtotal_cents`
        multiplied by fifteen percent (the fraction 0.1500), rounded half up to a whole
        cent. `add_on_charges_cents` is the smaller of the per-code sum and that
        aggregate ceiling."

        Design: Difficulty/combinatorial_formula/add_on_charges_per_code_caps_versus_aggregate_cap_with_pinned_order
        """
        world = _add_on_world(api)
        member, analysis = world["quarry"]

        usage = _elect_all_add_ons(api, world, member, analysis, 10)

        assert usage["discount_tier_index"] == 1
        assert_cents(usage["subtotal_cents"], 118750, "subtotal_cents")
        assert_add_on_detail(
            usage["add_on_detail"],
            [
                ("FREIGHT", 7125, 7125),
                ("INSIDE_DELIVERY", 4750, 4750),
                ("TRAINING", 11875, 11875),
            ],
        )
        assert_cents(usage["add_on_charges_cents"], 17813, "add_on_charges_cents")
        assert_cents(usage["chargeable_base_cents"], 136563, "chargeable_base_cents")
        assert usage["effective_fee_rate_bps"] == 180
        assert_cents(usage["admin_fee_cents"], 2458, "admin_fee_cents")
        assert_cents(usage["total_cents"], 139021, "total_cents")

    def test_08_the_detail_follows_the_catalogue_order_not_the_election_order(self, api):
        """PRD §3.6: "Walk the contract's `permitted_add_ons` array in **array order**,
        not in the order the member listed its codes, so that `add_on_detail` and every
        remainder behaviour are deterministic."

        Design: Difficulty/combinatorial_formula/add_on_charges_per_code_caps_versus_aggregate_cap_with_pinned_order
        """
        world = _add_on_world(api)
        member, analysis = world["quarry"]

        usage = _elect_all_add_ons(api, world, member, analysis, 10)

        assert [row["code"] for row in usage["add_on_detail"]] == [
            "FREIGHT",
            "INSIDE_DELIVERY",
            "TRAINING",
        ]
        stored = read_usage(api, usage["id"])
        assert [row["code"] for row in stored["add_on_detail"]] == [
            "FREIGHT",
            "INSIDE_DELIVERY",
            "TRAINING",
        ]

    def test_09_the_two_members_price_the_same_line_from_different_spend_snapshots(self, api):
        """PRD §3.6: "Read the member's `committed_spend_cents` as it stands **before**
        this order is added; that snapshot is the `spend_basis_cents`."

        Design: Difficulty/combinatorial_formula/add_on_charges_per_code_caps_versus_aggregate_cap_with_pinned_order
        """
        world = _add_on_world(api)
        pine, _ = world["pine"]
        quarry, _ = world["quarry"]
        assert_cents(world["primer"]["total_cents"], 5000000, "primer total_cents")
        assert_cents(
            read_member(api, quarry["id"])["committed_spend_cents"],
            5000000,
            "committed_spend_cents",
        )

        world["member"] = pine
        pine_quote = _quote(api, world, SKU_DISPENSER, 10)
        world["member"] = quarry
        quarry_quote = _quote(api, world, SKU_DISPENSER, 10)

        assert_cents(pine_quote["spend_basis_cents"], 0, "spend_basis_cents")
        assert pine_quote["discount_tier_index"] == 0
        assert_cents(quarry_quote["spend_basis_cents"], 5000000, "spend_basis_cents")
        assert quarry_quote["discount_tier_index"] == 1
        assert_cents(quarry_quote["net_unit_price_cents"], 11875, "net_unit_price_cents")
