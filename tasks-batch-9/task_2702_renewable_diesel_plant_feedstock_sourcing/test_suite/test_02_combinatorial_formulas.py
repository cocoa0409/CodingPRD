"""Formulas whose answer depends on how several inputs are combined.

Three separate arithmetic families: the pretreatment tier and fee collapsing four
laboratory metrics, the settlement bill whose rounding order is worth a cent, and
the hedge margin ladder whose tier is chosen from the base margin.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers.assertions import assert_mass, assert_money, assert_one_decimal
from test_helpers.test_users import ANALYST_HEADERS, OFFICER_A_HEADERS, TRADER_HEADERS
from test_helpers.types import (
    DISPOSITION_PRETREAT,
    FEEDSTOCK_TALLOW,
    HEDGE_OPEN,
    LOT_PRETREAT_REQUIRED,
    RUN_RECONCILED,
    TIER_HEAVY,
    TIER_T1,
)

SETTLEMENT_LINES = ((40.500, 905.55), (45.500, 920.25), (50.500, 925.35))


def test_worst_of_four_sub_tiers_governs_after_waste_phosphorus_escalation(api):
    """PRD §3.2: "Otherwise the worst of the four sub-tiers governs — the tier index is the
    largest of `ffa_tier_index`, `moisture_tier_index`, `insolubles_tier_index` and
    `phosphorus_tier_index`."
    PRD §3.2: "When the lot's `feedstock_type` is one of the three waste classes — `UCO`,
    `TALLOW` or `DCO` — and the test's `phosphorus_ppm` is at least 10, the governing tier
    index is raised by one, but never above 2."

    Design: Difficulty/combinatorial_formula/pretreatment_fee_four_metric_worst_tier_with_waste_escalation
    """
    supplier = fx.make_supplier(api, legal_name="Midwest Tallow Co", feedstock_types=[FEEDSTOCK_TALLOW])
    lot = fx.make_lot(
        api,
        supplier["id"],
        feedstock_type=FEEDSTOCK_TALLOW,
        mass_mt=300.000,
        attested_ci_gco2e_per_mj=41.00,
        purchase_price_usd_per_mt=780.00,
    )

    test_row = validate_success(
        api.create_quality_test(
            lot["id"],
            f.quality_test_payload(
                lot["version"],
                ffa_pct=5.00,
                moisture_pct=0.60,
                insolubles_ppm=400,
                phosphorus_ppm=12,
                sampled_at="2026-08-01T06:00:00Z",
            ),
            ANALYST_HEADERS,
        ),
        201,
    )

    assert test_row["ffa_tier_index"] == 2, f"ffa 5.00 is at least 5.00: {test_row}"
    assert test_row["moisture_tier_index"] == 1, "moisture 0.60 is at least 0.50 but under 1.00"
    assert test_row["insolubles_tier_index"] == 0, "insolubles 400 is under 500"
    assert test_row["phosphorus_tier_index"] == 1, "phosphorus 12 is at least 10 but under 20"
    assert test_row["tier"] == TIER_HEAVY, f"expected HEAVY, got {test_row['tier']}"
    assert test_row["disposition"] == DISPOSITION_PRETREAT


def test_pretreatment_fee_multiplies_tier_rate_by_mass_and_feedstock_multiplier(api):
    """PRD §3.2: "Otherwise the linear term is the per-tonne base rate for the governing
    tier — 18.50 US dollars per metric tonne for `LIGHT` and 42.75 for `HEAVY` — multiplied
    by the lot's `mass_mt`, multiplied by a feedstock-type multiplier of 1.20 for `UCO`,
    1.35 for `TALLOW`, 1.10 for `DCO`, and 1.00 for both `SOYBEAN_OIL` and `CANOLA_OIL`."
    PRD §3.2: "A `PRETREAT` moves the lot to `PRETREAT_REQUIRED`, sets `pretreatment_tier`
    to the test's `LIGHT` or `HEAVY`, and sets `pretreatment_fee_usd` to the quoted fee."

    Design: Difficulty/combinatorial_formula/pretreatment_fee_four_metric_worst_tier_with_waste_escalation
    """
    supplier = fx.make_supplier(api, legal_name="Midwest Tallow Co", feedstock_types=[FEEDSTOCK_TALLOW])
    lot = fx.make_lot(
        api,
        supplier["id"],
        feedstock_type=FEEDSTOCK_TALLOW,
        mass_mt=300.000,
        attested_ci_gco2e_per_mj=41.00,
        purchase_price_usd_per_mt=780.00,
    )
    fx.add_quality_test(
        api,
        lot["id"],
        lot["version"],
        ffa_pct=5.00,
        moisture_pct=0.60,
        insolubles_ppm=400,
        phosphorus_ppm=12,
        sampled_at="2026-08-01T06:00:00Z",
    )

    dispositioned = validate_success(api.get_feedstock_lot(lot["id"], TRADER_HEADERS))

    assert dispositioned["status"] == LOT_PRETREAT_REQUIRED
    assert dispositioned["pretreatment_tier"] == TIER_HEAVY
    assert_money(dispositioned["pretreatment_fee_usd"], 17313.75, "pretreatment_fee_usd")


def test_settlement_rounds_every_allocation_line_before_summing_them(api):
    """PRD §3.6: "for each of the campaign's allocations whose status is `CONSUMED`, taken
    in `created_at` ascending order, that line's `line_cost_usd` is its `mass_mt`
    multiplied by its lot's `purchase_price_usd_per_mt`, multiplied by one plus a freight
    loading of three and a half percent — that is, by 1.035 — and rounded half up to 2
    decimal places"
    PRD §3.6: "The campaign's `feedstock_cost_usd` is then the sum of those already-rounded
    line figures, rounded half up to 2 decimal places again."

    Design: Difficulty/combinatorial_formula/feedstock_settlement_round_per_line_then_sum
    """
    ctx = fx.reconciled_campaign_with_lot_lines(api, SETTLEMENT_LINES, measured_rd_mt=110.000)

    lines = sorted(ctx["allocations"], key=lambda row: row["created_at"])
    assert len(lines) == 3, f"expected three settled lines, got {len(lines)}"
    assert_money(lines[0]["line_cost_usd"], 37958.39, "line_cost_usd[0]")
    assert_money(lines[1]["line_cost_usd"], 43336.87, "line_cost_usd[1]")
    assert_money(lines[2]["line_cost_usd"], 48365.73, "line_cost_usd[2]")

    assert_money(ctx["run"]["feedstock_cost_usd"], 129660.99, "feedstock_cost_usd")
    assert round(float(ctx["run"]["feedstock_cost_usd"]), 2) != 129661.00, (
        "129661.00 is what summing the unrounded line products would produce"
    )


def test_reconciliation_freezes_consumed_mass_and_the_hydrogen_requirement(api):
    """PRD §3.6: "A `ComplianceOfficer` reconciles a `COMPLETED` campaign, moving it
    `COMPLETED → RECONCILED` — the terminal accounting state that freezes the campaign's
    yield and cost figures so credits can be claimed against them."
    PRD §3.5: "Second, a mass-weighted hydrogen intensity: for each counted line multiply
    its `mass_mt` by the hydrogen intensity of its lot's `feedstock_type` — 32.0 kilograms
    of hydrogen per metric tonne for `UCO`, 30.0 for `TALLOW`, 34.0 for `DCO`, 38.0 for
    `SOYBEAN_OIL` and 36.0 for `CANOLA_OIL` — sum those products, and divide by the total
    counted mass, keeping this quotient unrounded."

    Design: Difficulty/combinatorial_formula/feedstock_settlement_round_per_line_then_sum
    """
    ctx = fx.reconciled_campaign_with_lot_lines(api, SETTLEMENT_LINES, measured_rd_mt=110.000)
    run = validate_success(api.get_processing_run(ctx["run"]["id"], OFFICER_A_HEADERS))

    assert run["status"] == RUN_RECONCILED, f"expected RECONCILED, got {run['status']}"
    assert_mass(run["consumed_mass_mt"], 136.500, "consumed_mass_mt")
    assert_one_decimal(run["required_h2_kg_per_day"], 873.6, "required_h2_kg_per_day")


def test_hedge_volatility_tier_is_chosen_from_the_base_margin(api):
    """PRD §2.5: "The clearest case is hedge margin: the volatility tier is selected from
    the base margin, never from the total margin, so a position whose total margin crosses
    a tier floor while its base margin does not stays in the lower tier."
    PRD §3.9: "Step two: `base_margin_usd` is `gross_notional_usd` multiplied by the
    instrument's base margin rate — 8 percent for a `FEEDSTOCK_SWAP`, 12 percent for a
    `RIN_FORWARD`, 15 percent for an `LCFS_FORWARD` — rounded half up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/hedge_margin_tier_selected_from_base_not_total
    """
    position = fx.make_hedge(api, notional_units=62375, strike_price_usd=10.00)

    assert_money(position["gross_notional_usd"], 623750.00, "gross_notional_usd")
    assert_money(position["base_margin_usd"], 49900.00, "base_margin_usd")
    assert position["volatility_tier"] == TIER_T1, (
        f"a base margin of 49900.00 is under the 50000.00 floor: {position['volatility_tier']}"
    )
    assert position["status"] == HEDGE_OPEN


def test_hedge_total_margin_keeps_the_lower_tier_adder_it_was_derived_with(api):
    """PRD §3.9: "Step four: `volatility_adder_usd` is `base_margin_usd` multiplied by the
    tier's adder rate — 1.0 percent for `T1`, 2.5 percent for `T2`, 4.0 percent for `T3` —
    rounded half up to 2 decimal places."
    PRD §3.9: "Step five: `total_margin_usd` is `base_margin_usd` plus
    `volatility_adder_usd`, rounded half up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/hedge_margin_tier_selected_from_base_not_total
    """
    position = fx.make_hedge(api, notional_units=62375, strike_price_usd=10.00)

    assert_money(position["volatility_adder_usd"], 499.00, "volatility_adder_usd")
    assert_money(position["total_margin_usd"], 50399.00, "total_margin_usd")
    assert round(float(position["total_margin_usd"]), 2) != 51147.50, (
        "re-deriving the tier from the total margin is the forbidden evaluation order"
    )
