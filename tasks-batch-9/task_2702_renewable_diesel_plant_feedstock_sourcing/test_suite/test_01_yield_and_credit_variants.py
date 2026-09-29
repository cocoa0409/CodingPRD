"""Provisional versus final yield, and provisional versus verified credits.

Both pairs are two variants of one formula family that must disagree even when
they are handed identical inputs, because each variant reads a different set of
multipliers.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_activity_index,
    assert_mass,
    assert_one_decimal,
)
from test_helpers.test_users import OFFICER_A_HEADERS, OPERATOR_HEADERS
from test_helpers.types import (
    CHARGE_ACTIVE,
    OUTCOME_VERIFIED,
    RUN_COMPLETED,
)


def test_provisional_plan_multiplies_blend_yield_by_catalyst_activity(api):
    """PRD §3.5: "Then `provisional_yield_pct` is that blend yield multiplied by the
    charge's `activity_index`, rounded half up to 3 decimal places."
    PRD §3.5: "`planned_saf_mt` is `planned_total_product_mt` multiplied by
    `target_saf_share_pct` as a fraction of 100, multiplied by an aviation-fuel
    conversion penalty of 0.94, rounded to 3 decimal places."

    Design: Difficulty/dual_variant_calc/run_yield_provisional_vs_final_on_same_charge
    """
    ctx = fx.baseline_campaign(api, target_saf_share_pct=10.00, alloc_mass_mt=400.000)
    run = ctx["run"]

    assert_mass(run["provisional_yield_pct"], 82.000, "provisional_yield_pct")
    assert_mass(run["planned_total_product_mt"], 328.000, "planned_total_product_mt")
    assert_mass(run["planned_saf_mt"], 30.832, "planned_saf_mt")
    assert_mass(run["planned_rd_mt"], 297.168, "planned_rd_mt")


def test_final_yield_divides_measured_product_by_consumed_mass(api):
    """PRD §3.6: "Where the provisional variant looked forward over `RESERVED` mass and
    multiplied by catalyst activity, the final variant ignores the `activity_index` and
    the aviation-fuel conversion penalty entirely and simply divides measured reality by
    consumed reality: `final_yield_pct` is the sum of `measured_rd_mt` and
    `measured_saf_mt`, divided by `consumed_mass_mt`, expressed as a percentage, rounded
    half up to 3 decimal places."

    Design: Difficulty/dual_variant_calc/run_yield_provisional_vs_final_on_same_charge
    """
    ctx = fx.completed_campaign(
        api, measured_rd_mt=290.000, measured_saf_mt=30.000, target_saf_share_pct=10.00
    )
    run = ctx["run"]

    assert run["status"] == RUN_COMPLETED, f"expected COMPLETED, got {run['status']}"
    assert_mass(run["consumed_mass_mt"], 400.000, "consumed_mass_mt")
    assert_mass(run["provisional_yield_pct"], 82.000, "provisional_yield_pct")
    assert_mass(run["final_yield_pct"], 80.000, "final_yield_pct")


def test_yield_variance_is_final_less_provisional_and_stays_inside_tolerance(api):
    """PRD §3.6: "`yield_variance_pct` is `final_yield_pct` less `provisional_yield_pct`,
    rounded to 3 decimal places, and `yield_variance_flag` is set when the absolute value
    of that variance is strictly greater than the 2.000 percentage-point tolerance."

    Design: Difficulty/dual_variant_calc/run_yield_provisional_vs_final_on_same_charge
    """
    ctx = fx.completed_campaign(
        api, measured_rd_mt=290.000, measured_saf_mt=30.000, target_saf_share_pct=10.00
    )
    run = ctx["run"]

    assert_mass(run["yield_variance_pct"], -2.000, "yield_variance_pct")
    assert run["yield_variance_flag"] is False, (
        "a variance of exactly -2.000 points is not strictly greater than the tolerance"
    )
    assert run["planned_rd_mt"] != run["measured_rd_mt"], (
        "the provisional plan and the measured reality must not coincide here"
    )


def test_completion_refreshes_catalyst_throughput_and_activity_index(api):
    """PRD §3.3: "Its `cumulative_throughput_mt` is the sum of `consumed_mass_mt` over
    every campaign on that charge whose status is `COMPLETED` or `RECONCILED`; campaigns
    still `PLANNED`, `HYDROGEN_SECURED` or `RUNNING`, and campaigns that were `ABORTED`,
    contribute nothing."
    PRD §3.3: "The `activity_index` is then 1.0000 reduced by 0.0125 for every thousand
    metric tonnes of cumulative throughput — that is, 1.0000 less the product of 0.0125
    and the cumulative throughput divided by 1000 — with the result held at a floor of
    0.6000 if the arithmetic would take it lower, and rounded half up to 4 decimal
    places."

    Design: Difficulty/dual_variant_calc/run_yield_provisional_vs_final_on_same_charge
    """
    ctx = fx.completed_campaign(
        api, measured_rd_mt=290.000, measured_saf_mt=30.000, target_saf_share_pct=10.00
    )

    charges = get_success_data(api.list_catalyst_charges(ctx["unit"]["id"], OPERATOR_HEADERS))
    charge = next(row for row in charges if row["id"] == ctx["charge"]["id"])

    assert charge["status"] == CHARGE_ACTIVE, f"expected ACTIVE, got {charge['status']}"
    assert_mass(charge["cumulative_throughput_mt"], 400.000, "cumulative_throughput_mt")
    assert_activity_index(charge["activity_index"], 0.9950)


def test_lcfs_provisional_credits_use_blend_ci_plus_process_adder(api):
    """PRD §3.8: "Its `provisional_ci_gco2e_per_mj` is frozen at creation as the producing
    campaign's `blend_ci_gco2e_per_mj` plus a process carbon adder of 8.75 grams of CO2
    equivalent per megajoule, rounded half up to 2 decimal places."
    PRD §3.8: "For an `LCFS` block, `provisional_credits_mtco2e` is formed by subtracting
    the block's `provisional_ci_gco2e_per_mj` from the program benchmark carbon intensity
    for the batch's product class — 88.50 for `RENEWABLE_DIESEL` and 89.37 for `SAF` —
    multiplying that difference by the energy economy ratio for the product class, which
    is 1.00 for both `RENEWABLE_DIESEL` and `SAF`, multiplying by the energy density in
    megajoules per gallon — 129.65 for `RENEWABLE_DIESEL` and 126.60 for `SAF` —
    multiplying by the batch's `volume_gal`, dividing by one million to express the result
    in metric tonnes of CO2 equivalent, and rounding half up to 3 decimal places."

    Design: Difficulty/dual_variant_calc/lcfs_credit_provisional_vs_verified_at_identical_ci
    """
    ctx = fx.credit_ready_campaign(api, target_saf_share_pct=10.00)
    block = fx.make_credit_block(api, ctx["batch"]["id"], ctx["pathway"]["id"])

    assert_one_decimal(ctx["batch"]["volume_gal"], 89320.0, "volume_gal")
    assert block["provisional_ci_gco2e_per_mj"] == 41.25, (
        f"expected 41.25, got {block['provisional_ci_gco2e_per_mj']}"
    )
    assert_mass(block["provisional_credits_mtco2e"], 547.171, "provisional_credits_mtco2e")
    assert block["provisional_rin_credits"] == 0, (
        "an LCFS block keeps the renewable-identification-number counts at zero"
    )


def test_verified_lcfs_credits_apply_the_discount_at_an_identical_carbon_intensity(api):
    """PRD §3.8: "For an `LCFS` block, `verified_credits_mtco2e` repeats the provisional
    arithmetic with two substitutions: the verifier's carbon intensity replaces the
    block's `provisional_ci_gco2e_per_mj`, and the whole quantity is additionally
    multiplied by a verification discount of 0.98 before the half-up rounding to 3 decimal
    places and the floor at 0.000."
    PRD §3.8: "When the relative divergence is within tolerance — that is, not greater
    than five hundredths — the block lands at `VERIFIED` with `verification_outcome` set
    to `VERIFIED`."

    Design: Difficulty/dual_variant_calc/lcfs_credit_provisional_vs_verified_at_identical_ci
    """
    ctx = fx.credit_ready_campaign(api, target_saf_share_pct=10.00)
    block = fx.verified_credit_block(
        api, ctx["batch"]["id"], ctx["pathway"]["id"], verified_ci=41.25
    )

    assert block["verified_ci_gco2e_per_mj"] == 41.25, (
        f"expected 41.25, got {block['verified_ci_gco2e_per_mj']}"
    )
    assert_mass(block["provisional_credits_mtco2e"], 547.171, "provisional_credits_mtco2e")
    assert_mass(block["verified_credits_mtco2e"], 536.228, "verified_credits_mtco2e")
    assert block["verified_rin_credits"] == 0, "an LCFS block mints no RIN credits"
    assert block["verification_outcome"] == OUTCOME_VERIFIED
    assert block["status"] == "VERIFIED", f"expected VERIFIED, got {block['status']}"


def test_pathway_outstanding_balance_counts_the_verified_quantity(api):
    """PRD §2.10: "For any pathway registration, `credits_outstanding_mtco2e` is the sum,
    over the credit blocks citing that pathway whose status is `VERIFIED`, `ADJUSTED` or
    `RETIRED`, of each block's `verified_credits_mtco2e` less its
    `retired_credits_mtco2e`, rounded to 3 decimal places."

    Design: Difficulty/dual_variant_calc/lcfs_credit_provisional_vs_verified_at_identical_ci
    """
    ctx = fx.credit_ready_campaign(api, target_saf_share_pct=10.00)
    fx.verified_credit_block(api, ctx["batch"]["id"], ctx["pathway"]["id"], verified_ci=41.25)

    pathway = validate_success(api.get_pathway(ctx["pathway"]["id"], OFFICER_A_HEADERS))

    assert_mass(pathway["credits_outstanding_mtco2e"], 536.228, "credits_outstanding_mtco2e")
    assert pathway["variance_strikes"] == 0, (
        "a divergence inside tolerance must not record a variance strike"
    )
