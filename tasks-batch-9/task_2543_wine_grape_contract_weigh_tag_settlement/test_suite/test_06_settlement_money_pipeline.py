"""Closing the vintage: line finalisation under both settlement bases, the nested
per-ton rounding, and the sequential net-payable pipeline."""
from test_helpers import (
    assert_installments_sum_to_net_payable,
    assert_settlement_line,
    close_settlement,
    list_installments,
    list_settlement_lines,
    move_clock,
    read_settlement_summary,
    record_grading,
    setup_settlement_basis_pair,
    setup_single_load_on_pad,
    single_installment_plan,
)

SETTLEMENT_CLOSE_AT = "2026-08-28T09:00:00Z"


def _line_for_tag(contract_id: str, tag_id: str) -> dict:
    lines = list_settlement_lines(contract_id=contract_id, weigh_tag_id=tag_id)
    assert len(lines) == 1, f"expected exactly one settlement line for tag {tag_id}, got {len(lines)}"
    return lines[0]


def test_settlement_basis_variants_diverge_on_byte_identical_loads():
    """Two contracts differing only in `settlement_basis` receive the same two loads
    — 22.000 tons graded at Brix 28.0 and 18.000 tons graded at Brix 21.5.

    PRD: "Which arithmetic runs is decided by the contract's `settlement_basis`, and
    the two variants return genuinely different totals for byte-identical load data."

    Design: Difficulty/dual_variant_calc/settlement_basis_load_by_load_versus_weighted_blend_divergence
    """
    ctx = setup_settlement_basis_pair()
    move_clock(SETTLEMENT_CLOSE_AT)

    contract_a = close_settlement(ctx["contract_a"]["id"])
    contract_b = close_settlement(ctx["contract_b"]["id"])

    assert contract_a["final_settlement_cents"] == 18630000, (
        "load-by-load keeps each load's own clamped price: 10692000 + 7938000"
    )
    assert contract_b["final_settlement_cents"] == 19026000, (
        "the weighted blend re-prices the contract bucket at one blended adjustment"
    )
    assert contract_b["final_settlement_cents"] - contract_a["final_settlement_cents"] == 396000


def test_load_by_load_final_amounts_keep_each_loads_struck_price():
    """The high-Brix load was clamped to +8.0 percent at grading time and the
    low-Brix load carries a 2.0 point penalty; neither is re-priced on close.

    PRD: "Under `LOAD_BY_LOAD`, every line keeps the price it was struck at: each
    line's `final_amount_cents` becomes its own `gross_amount_cents`, and the
    settlement total is the sum of those amounts."

    Design: Difficulty/dual_variant_calc/settlement_basis_load_by_load_versus_weighted_blend_divergence
    """
    ctx = setup_settlement_basis_pair()
    move_clock(SETTLEMENT_CLOSE_AT)
    contract_a = close_settlement(ctx["contract_a"]["id"])

    high_line = _line_for_tag(contract_a["id"], ctx["tags_a"][0]["id"])
    low_line = _line_for_tag(contract_a["id"], ctx["tags_a"][1]["id"])

    assert_settlement_line(high_line)
    assert_settlement_line(low_line)
    assert high_line["price_per_ton_cents"] == 486000
    assert high_line["final_amount_cents"] == 10692000
    assert high_line["final_amount_cents"] == high_line["gross_amount_cents"]
    assert low_line["price_per_ton_cents"] == 441000
    assert low_line["final_amount_cents"] == 7938000
    assert low_line["final_amount_cents"] == low_line["gross_amount_cents"]
    for line in (high_line, low_line):
        assert line["status"] == "FINAL"
        assert line["voided_at"] is None


def test_weighted_blend_reprices_both_lines_at_one_pre_clamp_blend():
    """The blend runs on the pre-clamp raw adjustments — +12.0 and -2.0 percent
    weighted by 22.000 and 18.000 tons — so the clipped bonus pulls the blend up.

    PRD: "The blended raw adjustment is the sum, over those lines, of each line's
    `tons` multiplied by the `raw_adjustment_pct` of that line's grading, divided by
    the blend tonnage, rounded half up to 2 decimals."

    Design: Difficulty/dual_variant_calc/settlement_basis_load_by_load_versus_weighted_blend_divergence
    """
    ctx = setup_settlement_basis_pair()
    move_clock(SETTLEMENT_CLOSE_AT)
    contract_b = close_settlement(ctx["contract_b"]["id"])

    high_line = _line_for_tag(contract_b["id"], ctx["tags_b"][0]["id"])
    low_line = _line_for_tag(contract_b["id"], ctx["tags_b"][1]["id"])

    # Blend = (22.000 * 12.0 + 18.000 * -2.0) / 40.000 = 5.7 percent, inside the clamp.
    assert high_line["final_amount_cents"] == 10464300
    assert low_line["final_amount_cents"] == 8561700
    assert high_line["final_amount_cents"] + low_line["final_amount_cents"] == 19026000
    for line in (high_line, low_line):
        assert line["status"] == "FINAL"
        assert line["voided_at"] is None


def test_settlement_basis_divergence_carries_through_to_net_payable():
    """Both totals sit in the top prompt-payment tier, so the divergence survives the
    credit, the holdback and the installment distribution.

    PRD: "Step five computes `net_payable_cents` as the settlement total plus
    `prompt_pay_credit_cents` less `lien_holdback_cents`."

    Design: Difficulty/dual_variant_calc/settlement_basis_load_by_load_versus_weighted_blend_divergence
    """
    ctx = setup_settlement_basis_pair()
    move_clock(SETTLEMENT_CLOSE_AT)
    contract_a = close_settlement(ctx["contract_a"]["id"])
    contract_b = close_settlement(ctx["contract_b"]["id"])

    assert contract_a["prompt_pay_credit_cents"] == 279450
    assert contract_a["lien_holdback_cents"] == 931500
    assert contract_a["net_payable_cents"] == 17977950
    assert contract_b["prompt_pay_credit_cents"] == 285390
    assert contract_b["lien_holdback_cents"] == 951300
    assert contract_b["net_payable_cents"] == 18360090

    for contract in (contract_a, contract_b):
        assert_installments_sum_to_net_payable(
            list_installments(contract_id=contract["id"]), contract["net_payable_cents"]
        )


def _odd_price_load() -> dict:
    """One 22.000-ton load on a contract whose base price is an odd 450001 cents."""
    return setup_single_load_on_pad(
        contract_overrides={
            "base_price_per_ton_cents": 450001,
            "committed_tons": 22.000,
            "over_delivery_policy": "REJECT",
            "settlement_basis": "LOAD_BY_LOAD",
            "installment_plan": single_installment_plan(),
        },
        net_tons=22.000,
        tare_weight_lbs=17240,
    )


def test_weight_conversion_and_single_clamp_feed_the_pricing_pipeline():
    """A 61240 lb gross against a 17240 lb tare converts to exactly 22.000 tons, and
    a Brix 28.0 reading earns +12.0 percent raw, clipped once to the +8.0 ceiling.

    PRD: "`net_tons` is `net_weight_lbs` divided by 2000 pounds per ton, rounded half
    up to 3 decimals."

    Design: Difficulty/combinatorial_formula/settlement_line_nested_rounding_per_ton_then_tons
    """
    ctx = _odd_price_load()
    grading = record_grading(ctx["tag"]["id"], brix=28.0, ta_gl=6.5, ph=3.60, rot_pct=1.0, mog_pct=0.5)

    tag = ctx["tag"]
    assert tag["net_weight_lbs"] == 44000
    assert float(tag["net_tons"]) == 22.000
    assert float(grading["raw_adjustment_pct"]) == 12.0
    assert float(grading["adjustment_pct"]) == 8.0

    line = _line_for_tag(ctx["contract"]["id"], tag["id"])
    assert line["provisional_amount_cents"] == 6415213, (
        "the provisional payment is 60 percent of the rounded gross amount"
    )


def test_per_ton_price_is_rounded_to_whole_cents_before_multiplying_tons():
    """450001 cents lifted by 8.0 percent is 486001.08 cents per ton, which becomes
    486001 whole cents and only then multiplies 22.000 tons.

    PRD: "Collapsing the second and third steps into a single rounding of base times
    adjustment times tons produces a different figure whenever the adjusted per-ton
    price is not already a whole cent, and is wrong."

    Design: Difficulty/combinatorial_formula/settlement_line_nested_rounding_per_ton_then_tons
    """
    ctx = _odd_price_load()
    record_grading(ctx["tag"]["id"], brix=28.0, ta_gl=6.5, ph=3.60, rot_pct=1.0, mog_pct=0.5)

    line = _line_for_tag(ctx["contract"]["id"], ctx["tag"]["id"])
    assert line["price_per_ton_cents"] == 486001, (
        "the inner rounding lands on whole cents per ton, never on 486001.08 or 486002"
    )
    assert line["gross_amount_cents"] == 10692022, (
        "the outer rounding multiplies the whole-cent price by the tons: 486001 * 22"
    )


def test_nested_rounding_survives_line_finalisation():
    """Closing the vintage on a LOAD_BY_LOAD contract copies the nested-rounding gross
    onto the line and onto the contract, so the lost cents never reappear.

    PRD: "each line's `final_amount_cents` becomes its own `gross_amount_cents`, and
    the settlement total is the sum of those amounts."

    Design: Difficulty/combinatorial_formula/settlement_line_nested_rounding_per_ton_then_tons
    """
    ctx = _odd_price_load()
    record_grading(ctx["tag"]["id"], brix=28.0, ta_gl=6.5, ph=3.60, rot_pct=1.0, mog_pct=0.5)
    move_clock(SETTLEMENT_CLOSE_AT)
    contract = close_settlement(ctx["contract"]["id"])

    line = _line_for_tag(contract["id"], ctx["tag"]["id"])
    assert line["final_amount_cents"] == 10692022, "not 10692024, which is what one collapsed rounding yields"
    assert contract["final_settlement_cents"] == 10692022


def _tier_edge_load() -> dict:
    """One 25.000-ton load priced at 598000 cents a ton, so the settled gross lands at
    14,950,000 cents — just under the top prompt-payment tier."""
    return setup_single_load_on_pad(
        contract_overrides={
            "base_price_per_ton_cents": 598000,
            "committed_tons": 25.000,
            "over_delivery_policy": "REJECT",
            "settlement_basis": "LOAD_BY_LOAD",
            "lien_holdback_pct": 5.0,
            "installment_plan": single_installment_plan(),
        },
        net_tons=25.000,
        tare_weight_lbs=17000,
    )


def test_readings_on_every_dead_band_boundary_leave_the_base_price_intact():
    """Brix exactly at `brix_bonus_start`, acidity inside the flat band, rot exactly at
    `rot_free_pct` and MOG exactly at `max_mog_pct` all contribute nothing.

    PRD: "`price_per_ton_cents` is the base multiplied by one plus
    `adjustment_pct_applied` divided by 100, rounded half up to a whole number of cents."

    Design: Difficulty/combinatorial_formula/net_payable_sequential_tier_then_credit_then_holdback
    """
    ctx = _tier_edge_load()
    grading = record_grading(ctx["tag"]["id"], brix=24.0, ta_gl=6.5, ph=3.50, rot_pct=2.0, mog_pct=1.0)

    assert float(grading["adjustment_pct"]) == 0.0
    line = _line_for_tag(ctx["contract"]["id"], ctx["tag"]["id"])
    assert line["price_per_ton_cents"] == 598000
    assert line["gross_amount_cents"] == 14950000


def test_prompt_pay_tier_is_looked_up_on_the_pre_credit_total():
    """A settled gross of 14,950,000 cents sits in the 1.0 percent tier; reading the
    tier off the credited or held-back subtotal would move it.

    PRD: "Step two looks up a prompt-payment tier **on that pre-credit total**: below
    5,000,000 cents the rate is 0.0 percent; from 5,000,000 up to but not including
    10,000,000 cents it is 0.5 percent; from 10,000,000 up to but not including
    15,000,000 cents it is 1.0 percent; and at or above 15,000,000 cents it is 1.5
    percent."

    Design: Difficulty/combinatorial_formula/net_payable_sequential_tier_then_credit_then_holdback
    """
    ctx = _tier_edge_load()
    record_grading(ctx["tag"]["id"], brix=24.0, ta_gl=6.5, ph=3.50, rot_pct=2.0, mog_pct=1.0)
    move_clock(SETTLEMENT_CLOSE_AT)
    contract = close_settlement(ctx["contract"]["id"])

    assert contract["final_settlement_cents"] == 14950000
    assert contract["prompt_pay_credit_cents"] == 149500, (
        "1.0 percent of 14,950,000 — not 224,250, which is the 1.5 percent tier"
    )


def test_lien_holdback_is_keyed_on_the_pre_credit_total_not_the_credited_subtotal():
    """The 5.0 percent holdback is taken on the settled gross, and the net payable is
    the gross plus the credit less that holdback.

    PRD: "Step four computes the statutory producer-lien holdback,
    `lien_holdback_cents`, **also keyed on the pre-credit total**: the settlement total
    multiplied by the contract's `lien_holdback_pct` divided by 100, rounded half up to
    whole cents."

    Design: Difficulty/combinatorial_formula/net_payable_sequential_tier_then_credit_then_holdback
    """
    ctx = _tier_edge_load()
    record_grading(ctx["tag"]["id"], brix=24.0, ta_gl=6.5, ph=3.50, rot_pct=2.0, mog_pct=1.0)
    move_clock(SETTLEMENT_CLOSE_AT)
    contract = close_settlement(ctx["contract"]["id"])

    assert contract["lien_holdback_cents"] == 747500, "5 percent of the pre-credit 14,950,000, not of 15,099,500"
    assert contract["net_payable_cents"] == 14352000, (
        "14,950,000 + 149,500 - 747,500 — not 14,426,750 and not 14,344,525"
    )

    summary = read_settlement_summary(contract["id"])
    assert summary["net_payable_cents"] == 14352000
    assert summary["installment_planned_total_cents"] == 14352000


def test_single_installment_absorbs_the_whole_net_payable_on_close():
    """A 100 percent installment plan schedules exactly the net payable.

    PRD: "Each receives a `planned_amount_cents` of `net_payable_cents` multiplied by
    its own `pct_of_settlement` divided by 100, rounded half up to whole cents"

    Design: Difficulty/combinatorial_formula/net_payable_sequential_tier_then_credit_then_holdback
    """
    ctx = _tier_edge_load()
    record_grading(ctx["tag"]["id"], brix=24.0, ta_gl=6.5, ph=3.50, rot_pct=2.0, mog_pct=1.0)
    move_clock(SETTLEMENT_CLOSE_AT)
    contract = close_settlement(ctx["contract"]["id"])

    installments = list_installments(contract_id=contract["id"])
    assert len(installments) == 1
    assert installments[0]["installment_no"] == 1
    assert installments[0]["planned_amount_cents"] == 14352000
    assert installments[0]["status"] == "SCHEDULED"
