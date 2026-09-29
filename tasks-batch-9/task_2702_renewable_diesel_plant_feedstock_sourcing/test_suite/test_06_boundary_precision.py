"""Inclusive thresholds probed at the last digit that can move them.

Each pair sits on either side of one boundary — a hundredth of a percentage
point, a thousandth of a tonne, a single notional unit — with everything else
held identical, so only the comparison operator can explain the divergence.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_MIN_CHARGE_NOT_MET, ERR_NO_FEEDSTOCK_ALLOCATED
from test_helpers.assertions import assert_mass, assert_money, assert_one_decimal
from test_helpers.test_users import OPERATOR_HEADERS
from test_helpers.types import (
    DISPOSITION_PRETREAT,
    LOT_PRETREAT_REQUIRED,
    RUN_HYDROGEN_SECURED,
    TIER_HEAVY,
    TIER_LIGHT,
    TIER_T1,
    TIER_T2,
)


def test_free_fatty_acid_exactly_at_the_heavy_floor_is_charged_the_heavy_rate(api):
    """PRD §3.2: "`ffa_tier_index` is 2 when `ffa_pct` is at least 5.00, otherwise 1 when it
    is at least 2.00, otherwise 0."
    PRD §3.2: "Otherwise the linear term is the per-tonne base rate for the governing tier —
    18.50 US dollars per metric tonne for `LIGHT` and 42.75 for `HEAVY` — multiplied by the
    lot's `mass_mt`, multiplied by a feedstock-type multiplier of 1.20 for `UCO`, 1.35 for
    `TALLOW`, 1.10 for `DCO`, and 1.00 for both `SOYBEAN_OIL` and `CANOLA_OIL`."

    Design: Difficulty/boundary_precision_check/ffa_exactly_at_heavy_threshold_versus_one_hundredth_below
    """
    ctx = fx.soybean_lot_with_test(api, ffa_pct=5.00)

    assert ctx["test"]["ffa_tier_index"] == 2, f"got {ctx['test']['ffa_tier_index']}"
    assert ctx["test"]["moisture_tier_index"] == 0
    assert ctx["test"]["insolubles_tier_index"] == 0
    assert ctx["test"]["phosphorus_tier_index"] == 0
    assert ctx["test"]["tier"] == TIER_HEAVY
    assert ctx["test"]["disposition"] == DISPOSITION_PRETREAT

    assert ctx["lot"]["status"] == LOT_PRETREAT_REQUIRED
    assert ctx["lot"]["pretreatment_tier"] == TIER_HEAVY
    assert_money(ctx["lot"]["pretreatment_fee_usd"], 4275.00, "pretreatment_fee_usd")


def test_one_hundredth_below_the_heavy_floor_stays_on_the_light_rate(api):
    """PRD §3.2: "`ffa_tier_index` is 2 when `ffa_pct` is at least 5.00, otherwise 1 when it
    is at least 2.00, otherwise 0."
    PRD §3.2: "A `PRETREAT` moves the lot to `PRETREAT_REQUIRED`, sets `pretreatment_tier`
    to the test's `LIGHT` or `HEAVY`, and sets `pretreatment_fee_usd` to the quoted fee."

    Design: Difficulty/boundary_precision_check/ffa_exactly_at_heavy_threshold_versus_one_hundredth_below
    """
    ctx = fx.soybean_lot_with_test(api, ffa_pct=4.99)

    assert ctx["test"]["ffa_tier_index"] == 1, f"got {ctx['test']['ffa_tier_index']}"
    assert ctx["test"]["tier"] == TIER_LIGHT
    assert ctx["test"]["disposition"] == DISPOSITION_PRETREAT

    assert ctx["lot"]["status"] == LOT_PRETREAT_REQUIRED
    assert ctx["lot"]["pretreatment_tier"] == TIER_LIGHT
    assert_money(ctx["lot"]["pretreatment_fee_usd"], 1850.00, "pretreatment_fee_usd")


def test_zero_allocations_is_a_cardinality_refusal_and_never_a_mass_refusal(api):
    """PRD §3.5: "the campaign must hold at least one allocation at `RESERVED`, a
    zero-cardinality guard checked ahead of any mass threshold and reported as
    `ERR_NO_FEEDSTOCK_ALLOCATED`"
    PRD §3.5: "Its `reserved_mass_mt` and `consumed_mass_mt` are 0.000;
    `blend_ci_gco2e_per_mj` and `required_h2_kg_per_day` are null, because a campaign with no
    counted allocation has no blend and is feeding nothing"

    Design: Difficulty/boundary_precision_check/zero_allocations_versus_one_thousandth_under_minimum_charge
    """
    ctx = fx.unallocated_run_ready_for_hydrogen(api)
    assert_mass(ctx["run"]["reserved_mass_mt"], 0.000, "reserved_mass_mt")

    validate_error(
        api.secure_hydrogen(ctx["run"]["id"], OPERATOR_HEADERS), ERR_NO_FEEDSTOCK_ALLOCATED
    )


def test_one_thousandth_under_the_minimum_charge_is_refused(api):
    """PRD §3.5: "the campaign's `reserved_mass_mt` must be at least the minimum charge of
    100.0 metric tonnes, so a single allocation of 99.999 metric tonnes fails with
    `ERR_MIN_CHARGE_NOT_MET`"

    Design: Difficulty/boundary_precision_check/zero_allocations_versus_one_thousandth_under_minimum_charge
    """
    ctx = fx.unallocated_run_ready_for_hydrogen(api)
    fx.allocate(api, ctx["run"]["id"], ctx["lot"]["id"], 99.999)

    validate_error(
        api.secure_hydrogen(ctx["run"]["id"], OPERATOR_HEADERS), ERR_MIN_CHARGE_NOT_MET
    )

    run = validate_success(api.get_processing_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert_mass(run["reserved_mass_mt"], 99.999, "reserved_mass_mt")


def test_exactly_the_minimum_charge_clears_the_securement_gate(api):
    """PRD §3.5: "the campaign's `reserved_mass_mt` must be at least the minimum charge of
    100.0 metric tonnes, so a single allocation of 99.999 metric tonnes fails with
    `ERR_MIN_CHARGE_NOT_MET`"
    PRD §3.5: "Third, the daily feed rate: the total counted mass divided by the campaign's
    `run_days`, and this one **is rounded half up to 3 decimal places before it is used**."

    Design: Difficulty/boundary_precision_check/zero_allocations_versus_one_thousandth_under_minimum_charge
    """
    ctx = fx.unallocated_run_ready_for_hydrogen(api)
    fx.allocate(api, ctx["run"]["id"], ctx["lot"]["id"], 99.999)
    fx.allocate(api, ctx["run"]["id"], ctx["lot"]["id"], 0.001)

    run = validate_success(api.secure_hydrogen(ctx["run"]["id"], OPERATOR_HEADERS))

    assert run["status"] == RUN_HYDROGEN_SECURED, f"expected HYDROGEN_SECURED, got {run['status']}"
    assert_mass(run["reserved_mass_mt"], 100.000, "reserved_mass_mt")
    assert_one_decimal(run["required_h2_kg_per_day"], 1066.7, "required_h2_kg_per_day")
    assert_mass(run["provisional_yield_pct"], 82.000, "provisional_yield_pct")
    assert_mass(run["planned_total_product_mt"], 82.000, "planned_total_product_mt")


def test_base_margin_of_exactly_fifty_thousand_lands_in_the_second_tier(api):
    """PRD §3.9: "Step three: `volatility_tier` is selected **from `base_margin_usd` and
    never from `total_margin_usd`** — it is `T3` when the base margin is at least 250000.00
    US dollars, otherwise `T2` when the base margin is at least 50000.00, otherwise `T1`."
    PRD §3.9: "Both boundaries are inclusive, so a base margin of exactly 50000.00 is `T2`
    and one of exactly 250000.00 is `T3`."

    Design: Difficulty/boundary_precision_check/hedge_tier_boundary_at_exactly_fifty_thousand_base_margin
    """
    position = fx.make_hedge(api, notional_units=62500, strike_price_usd=10.00)

    assert_money(position["gross_notional_usd"], 625000.00, "gross_notional_usd")
    assert_money(position["base_margin_usd"], 50000.00, "base_margin_usd")
    assert position["volatility_tier"] == TIER_T2, f"got {position['volatility_tier']}"
    assert_money(position["volatility_adder_usd"], 1250.00, "volatility_adder_usd")
    assert_money(position["total_margin_usd"], 51250.00, "total_margin_usd")


def test_one_notional_unit_fewer_keeps_the_position_in_the_first_tier(api):
    """PRD §3.9: "Step three: `volatility_tier` is selected **from `base_margin_usd` and
    never from `total_margin_usd`** — it is `T3` when the base margin is at least 250000.00
    US dollars, otherwise `T2` when the base margin is at least 50000.00, otherwise `T1`."
    PRD §3.9: "Step four: `volatility_adder_usd` is `base_margin_usd` multiplied by the
    tier's adder rate — 1.0 percent for `T1`, 2.5 percent for `T2`, 4.0 percent for `T3` —
    rounded half up to 2 decimal places."

    Design: Difficulty/boundary_precision_check/hedge_tier_boundary_at_exactly_fifty_thousand_base_margin
    """
    position = fx.make_hedge(api, notional_units=62499, strike_price_usd=10.00)

    assert_money(position["gross_notional_usd"], 624990.00, "gross_notional_usd")
    assert_money(position["base_margin_usd"], 49999.20, "base_margin_usd")
    assert position["volatility_tier"] == TIER_T1, f"got {position['volatility_tier']}"
    assert_money(position["volatility_adder_usd"], 499.99, "volatility_adder_usd")
    assert_money(position["total_margin_usd"], 50499.19, "total_margin_usd")
