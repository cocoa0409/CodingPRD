"""Thresholds tested one cent either side of the line."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_cents,
    assert_fraction,
    make_member_headers,
)
from test_helpers.constants import (
    PRIMER_QTY_FOR_4999999,
    PRIMER_QTY_FOR_5000000,
    SKU_ADJUSTMENT,
    SKU_DISPENSER,
)
from test_helpers.factories import ADJUSTMENT_LINE, DISPENSER_LINE, contract_usage_payload
from test_helpers.fixtures import (
    prime_committed_spend,
    read_contract,
    read_member,
    read_usage,
    record_usage,
    setup_active_contract,
    setup_authorised_member,
)

LOWLINE = dict(
    legal_name="Lowline Municipal Utility District",
    state_code="TX",
    member_category="SPECIAL_DISTRICT",
    annual_spend_ceiling_cents=10000000,
    governing_body_resolution_number="RES-LO-2026-011",
)
HIGHLINE = dict(
    legal_name="Highline County Schools",
    state_code="TX",
    member_category="K12_DISTRICT",
    annual_spend_ceiling_cents=10000000,
    governing_body_resolution_number="RES-HI-2026-012",
)
EXACTLINE = dict(
    legal_name="Exactline State Purchasing Office",
    state_code="TX",
    member_category="STATE_AGENCY",
    annual_spend_ceiling_cents=1020000,
    governing_body_resolution_number="RES-EX-2026-014",
)


def _threshold_world(api):
    """Two members one cent apart, straddling the tier-1 threshold of 5000000 cents."""
    world = setup_active_contract(api, lines=(DISPENSER_LINE, ADJUSTMENT_LINE))
    low, low_analysis = setup_authorised_member(api, world, **LOWLINE)
    high, high_analysis = setup_authorised_member(api, world, **HIGHLINE)
    world["low"] = (low, low_analysis)
    world["high"] = (high, high_analysis)
    world["low_primer"] = prime_committed_spend(
        api, world, low, low_analysis, PRIMER_QTY_FOR_4999999
    )
    world["high_primer"] = prime_committed_spend(
        api, world, high, high_analysis, PRIMER_QTY_FOR_5000000
    )
    return world


def _dispenser_order(api, world, key, quantity=10):
    member, analysis = world[key]
    return record_usage(
        api,
        world["contract"]["id"],
        member["id"],
        world["lines"][SKU_DISPENSER]["id"],
        analysis["id"],
        quantity=quantity,
    )


def _ceiling_world(api):
    """A member whose ceiling is exactly reachable by one adjustment-line order."""
    world = setup_active_contract(api, lines=(ADJUSTMENT_LINE,))
    member, analysis = setup_authorised_member(api, world, **EXACTLINE)
    world["member"] = member
    world["analysis"] = analysis
    return world


def _adjustment_order(api, world, quantity):
    return api.create_contract_usage(
        contract_usage_payload(
            world["contract"]["id"],
            world["member"]["id"],
            world["lines"][SKU_ADJUSTMENT]["id"],
            world["analysis"]["id"],
            quantity=quantity,
        ),
        make_member_headers(world["member"]["id"]),
    )


class TestDiscountTierThreshold:
    def test_01_the_two_members_are_primed_exactly_one_cent_apart(self, api):
        """PRD §3.6: "Only now is `total_cents` added to the member's
        `committed_spend_cents`, and `chargeable_base_cents` added to the contract's
        `usage_chargeable_cents_total`."

        Design: Difficulty/boundary_precision_check/discount_tier_threshold_is_inclusive_at_exactly_one_cent_of_spend
        """
        world = _threshold_world(api)

        assert_cents(world["low_primer"]["total_cents"], 4999999, "primer total_cents")
        assert_cents(world["high_primer"]["total_cents"], 5000000, "primer total_cents")
        low, _ = world["low"]
        high, _ = world["high"]
        assert_cents(read_member(api, low["id"])["committed_spend_cents"], 4999999, "low spend")
        assert_cents(read_member(api, high["id"])["committed_spend_cents"], 5000000, "high spend")

    def test_02_one_cent_short_of_the_threshold_stays_in_tier_zero(self, api):
        """PRD §3.6: "Select the entry of the contract's `discount_tiers` with the largest
        `min_annual_spend_cents` that is less than or equal to the spend basis; since the
        ladder always contains a `tier_index` 0 entry whose threshold is 0 the candidate
        set is never empty, and a spend basis exactly equal to a tier's threshold selects
        that tier."

        Design: Difficulty/boundary_precision_check/discount_tier_threshold_is_inclusive_at_exactly_one_cent_of_spend
        """
        world = _threshold_world(api)

        order = _dispenser_order(api, world, "low")

        assert_cents(order["spend_basis_cents"], 4999999, "spend_basis_cents")
        assert order["discount_tier_index"] == 0
        assert_fraction(order["total_discount_pct"], 0.0000, "total_discount_pct")
        assert_cents(order["net_unit_price_cents"], 12500, "net_unit_price_cents")
        assert_cents(order["subtotal_cents"], 125000, "subtotal_cents")
        assert order["effective_fee_rate_bps"] == 200
        assert_cents(order["admin_fee_cents"], 2500, "admin_fee_cents")
        assert_cents(order["total_cents"], 127500, "total_cents")

    def test_03_a_spend_basis_exactly_on_the_threshold_selects_that_tier(self, api):
        """PRD §3.6: "Multiply the line's `base_unit_price_cents` by one minus
        `total_discount_pct` and round half up to a whole cent."

        Design: Difficulty/boundary_precision_check/discount_tier_threshold_is_inclusive_at_exactly_one_cent_of_spend
        """
        world = _threshold_world(api)

        order = _dispenser_order(api, world, "high")

        assert_cents(order["spend_basis_cents"], 5000000, "spend_basis_cents")
        assert order["discount_tier_index"] == 1
        assert_fraction(order["total_discount_pct"], 0.0500, "total_discount_pct")
        assert_cents(order["net_unit_price_cents"], 11875, "net_unit_price_cents")
        assert_cents(order["subtotal_cents"], 118750, "subtotal_cents")

    def test_04_the_tier_one_rebate_and_its_half_cent_fee_round_half_up(self, api):
        """PRD §3.6: "The rebate is keyed on the `discount_tier_index` chosen in step two:
        tier 0 earns no rebate, tier 1 earns a ten percent rebate (the fraction 0.1000),
        tier 2 earns a twenty-five percent rebate (the fraction 0.2500), and any tier index
        not in that map earns no rebate at all."

        Design: Difficulty/boundary_precision_check/discount_tier_threshold_is_inclusive_at_exactly_one_cent_of_spend
        """
        world = _threshold_world(api)

        order = _dispenser_order(api, world, "high")

        assert order["effective_fee_rate_bps"] == 180
        assert_cents(order["admin_fee_cents"], 2138, "admin_fee_cents")
        assert_cents(order["total_cents"], 120888, "total_cents")
        assert_cents(read_usage(api, order["id"])["total_cents"], 120888, "stored total_cents")


class TestMemberSpendCeiling:
    def test_05_landing_exactly_on_the_ceiling_is_permitted(self, api):
        """PRD §3.6: "Finally the member's `committed_spend_cents` plus this order's own
        `total_cents` must not exceed its `annual_spend_ceiling_cents`; landing exactly on
        the ceiling is permitted, and exceeding it is `ERR_MEMBER_CEILING_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/member_ceiling_admits_the_exact_limit_and_refuses_it_by_one_cent
        """
        world = _ceiling_world(api)

        order = validate_success(_adjustment_order(api, world, 1000000), 201)

        assert_cents(order["subtotal_cents"], 1000000, "subtotal_cents")
        assert_cents(order["admin_fee_cents"], 20000, "admin_fee_cents")
        assert_cents(order["total_cents"], 1020000, "total_cents")
        assert order["status"] == "RECORDED"
        assert_cents(
            read_member(api, world["member"]["id"])["committed_spend_cents"],
            1020000,
            "committed_spend_cents",
        )

    def test_06_one_further_cent_is_refused_and_debits_nothing(self, api):
        """PRD §2.9: "A member's spend ceiling is respected —
        `ERR_MEMBER_CEILING_EXCEEDED`, 422, on `POST /coop/contract-usages`."

        Design: Difficulty/boundary_precision_check/member_ceiling_admits_the_exact_limit_and_refuses_it_by_one_cent
        """
        world = _ceiling_world(api)
        validate_success(_adjustment_order(api, world, 1000000), 201)

        response = _adjustment_order(api, world, 1)

        validate_error(response, ApiErrorId.ERR_MEMBER_CEILING_EXCEEDED, 422)
        assert_cents(
            read_member(api, world["member"]["id"])["committed_spend_cents"],
            1020000,
            "committed_spend_cents",
        )
        assert_cents(
            read_contract(api, world["contract"]["id"])["usage_chargeable_cents_total"],
            1000000,
            "usage_chargeable_cents_total",
        )
