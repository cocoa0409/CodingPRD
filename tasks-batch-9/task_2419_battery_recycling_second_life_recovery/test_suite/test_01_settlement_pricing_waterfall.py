"""Provisional versus final feedstock pricing and the seven-step waterfall."""
from test_helpers import (
    assert_settlement,
    assert_settlement_line_breakdown,
    assert_settlement_waterfall,
    fixtures as fx,
    round_half_up_cents,
)
from test_helpers.constants import FOUR_METAL_QUOTES


# --------------------------------------------------------------------------
# Provisional pricing against the declared assay, final pricing against yields
# --------------------------------------------------------------------------

def test_provisional_settlement_prices_the_declared_assay_at_received_at(api):
    """The settlement cut at custody release prices the declared assay through the
    nominal recovery table at the shipment's received_at.

    PRD §3.5: "For each payable metal in turn under the `PROVISIONAL` variant, the
    contained mass is the shipment's `net_mass_kg` multiplied by that metal's
    declared percentage"; "The price date under this variant is the shipment's
    `received_at`."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_repricing_on_lot_finalize
    """
    ctx = fx.large_four_metal_world(api, stop_after="released")
    settlement = fx.read_settlement(api, ctx["settlement"]["id"])

    assert_settlement(settlement)
    assert settlement["variant"] == "PROVISIONAL"
    assert settlement["state"] == "DRAFT"
    assert settlement["price_basis_date"] == "2026-07-10T00:00:00.000Z"
    assert settlement["gross_cents"] == 260224
    assert settlement["net_payable_cents"] == 216493
    assert settlement["max_variance_pp"] is None, (
        "while a settlement is still PROVISIONAL, max_variance_pp is null"
    )


def test_lot_finalization_reprices_the_settlement_against_actual_yields(api):
    """Finalizing the lot flips the settlement to FINAL, re-prices it against the
    assay ledger at the lot's finalized_at, and computes the assay variance.

    PRD §3.7: "each contributing shipment's `DRAFT` settlement flips its `variant`
    `PROVISIONAL → FINAL`, is re-priced under the `FINAL` pricing rules and then
    through the seven-step waterfall of §3.5, has its `price_basis_date` reset to
    the lot's `finalized_at`, and has its `max_variance_pp` computed."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_repricing_on_lot_finalize
    """
    ctx = fx.large_four_metal_world(api)
    settlement = fx.read_settlement(api, ctx["settlement"]["id"])

    assert_settlement(settlement)
    assert settlement["variant"] == "FINAL"
    assert settlement["state"] == "DRAFT"
    assert settlement["price_basis_date"] == "2026-08-20T00:00:00.000Z"
    assert settlement["gross_cents"] == 257008
    assert settlement["processing_fee_cents"] == 30841
    assert settlement["quality_deduction_cents"] == 5140
    assert settlement["pre_surcharge_net_cents"] == 221027
    assert settlement["hazmat_surcharge_cents"] == 7300
    assert settlement["net_payable_cents"] == 213727
    assert float(settlement["max_variance_pp"]) == 3.50
    assert [line["line_cents"] for line in settlement["line_breakdown"]] == [
        83302,
        63006,
        89100,
        21600,
    ]


# --------------------------------------------------------------------------
# Per-line rounding order
# --------------------------------------------------------------------------

def test_final_gross_sums_lines_already_rounded_to_whole_cents(api):
    """Each payable line is rounded to whole cents before the gross is summed, so
    the gross lands one cent below the sum-then-round figure.

    PRD §2.9: "each metal's line amount is rounded to whole cents **first**, and the
    settlement's gross amount is the sum of those already-rounded lines. Summing
    unrounded line values and rounding once at the end is incorrect and can differ
    from the required result by one or more cents."

    Design: Difficulty/combinatorial_formula/final_gross_per_line_rounding_order_differs_from_sum_then_round
    """
    ctx = fx.large_four_metal_world(api)
    settlement = fx.read_settlement(api, ctx["settlement"]["id"])

    lines = settlement["line_breakdown"]
    assert [line["line_cents"] for line in lines] == [83302, 63006, 89100, 21600]
    assert settlement["gross_cents"] == 257008
    assert settlement["gross_cents"] != 257009, (
        "257009 is the incorrect sum-then-round result of the raw line values "
        "83302.45 + 63006.30 + 89100.00 + 21600.36"
    )
    assert_settlement_line_breakdown(settlement)


def test_line_rounding_order_carries_through_the_fee_and_the_net(api):
    """Because the gross is one cent lower, the processing fee and the net payable
    both differ from the sum-then-round arithmetic.

    PRD §3.5: "**Step three** computes `processing_fee_cents` as `gross_cents`
    multiplied by that rate, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/final_gross_per_line_rounding_order_differs_from_sum_then_round
    """
    ctx = fx.large_four_metal_world(api)
    settlement = fx.read_settlement(api, ctx["settlement"]["id"])

    assert settlement["gross_cents"] == 257008
    assert settlement["processing_fee_cents"] == 30841
    assert settlement["net_payable_cents"] == 213727
    assert settlement["net_payable_cents"] != 213728, (
        "the one-cent gross difference propagates all the way to the net payable"
    )
    assert_settlement_waterfall(settlement)


# --------------------------------------------------------------------------
# Quality deduction: three capped components, escalation, then a global cap
# --------------------------------------------------------------------------

_CONTAMINATED_INTAKE = {
    "declared_chemistry": "NCA",
    "gross_mass_kg": 1050.0,
    "packaging_tare_kg": 50.0,
    "declared_ni_pct": 10.0,
    "declared_co_pct": 5.0,
    "declared_li_pct": 3.0,
    "declared_cu_pct": 7.0,
    "moisture_pct": 12.0,
    "foreign_material_pct": 5.0,
}


def _two_counterparty_world(api):
    """One campus, one July price feed and two counterparties shipping identical
    contaminated, mislabelled feedstock — one with three logged quality incidents
    and one with none."""
    ctx = fx.bootstrap_network(
        api,
        quotes=FOUR_METAL_QUOTES,
        supplier={
            "legal_name": "Striker Dismantling",
            "channel": "DISMANTLER",
            "credit_limit_cents": 100_000_000,
        },
    )
    striker = ctx["supplier"]
    fx.log_quality_strikes(
        api,
        striker["id"],
        ("MOISTURE_EXCESS", "FOREIGN_MATERIAL", "MISLABELLED_CHEMISTRY"),
    )
    clean = fx.create_supplier(
        api,
        legal_name="Clean Automotive",
        channel="AUTOMAKER",
        credit_limit_cents=100_000_000,
    )

    chains = {}
    for label, supplier in (("striker", striker), ("clean", clean)):
        ctx["supplier"] = supplier
        chains[label] = fx.advance_intake(
            ctx,
            stop_after="released",
            intake=dict(_CONTAMINATED_INTAKE),
            modules=(),
            soc_pct=10.0,
        )
    ctx["chains"] = chains
    ctx["striker"] = striker
    ctx["clean"] = clean
    return ctx


def test_repeat_offender_escalation_pushes_the_deduction_onto_the_global_cap(api):
    """Mislabelling plus both individually capped contamination components escalate
    by half for a three-strike counterparty and are then held at the overall cap.

    PRD §3.5: "If the counterparty's `quality_strike_count` is at least 3, the
    accumulated total is then multiplied by 1.5 as a repeat-offender escalation.
    Finally the result is capped at twenty percent overall and rounded half up to
    four decimal places."

    Design: Difficulty/combinatorial_formula/quality_deduction_nested_caps_with_strike_escalation_and_global_cap
    """
    ctx = _two_counterparty_world(api)
    settlement = fx.read_settlement(api, ctx["chains"]["striker"]["settlement"]["id"])

    assert_settlement(settlement)
    assert settlement["gross_cents"] == 339820
    assert float(settlement["quality_deduction_pct"]) == 0.2000, (
        "0.04 mislabelling + 0.06 capped moisture + 0.05 capped foreign material "
        "escalates to 0.225 and is then held at the 0.20 overall cap"
    )
    assert settlement["quality_deduction_cents"] == 67964
    assert settlement["processing_fee_cents"] == 40778
    assert settlement["pre_surcharge_net_cents"] == 231078
    assert settlement["hazmat_surcharge_cents"] == 8500
    assert settlement["net_payable_cents"] == 222578


def test_counterparty_without_strikes_keeps_the_unescalated_deduction(api):
    """Identical feedstock from a counterparty with no logged incidents deducts the
    unescalated sum of the three capped components.

    PRD §3.5: "the excess moisture is the shipment's `moisture_pct` less a free
    allowance of 2.0 percentage points, floored at zero, and the component is that
    excess multiplied by one percent per percentage point, capped at six percent,
    and added."

    Design: Difficulty/combinatorial_formula/quality_deduction_nested_caps_with_strike_escalation_and_global_cap
    """
    ctx = _two_counterparty_world(api)
    clean = fx.read_settlement(api, ctx["chains"]["clean"]["settlement"]["id"])
    striker = fx.read_settlement(api, ctx["chains"]["striker"]["settlement"]["id"])

    assert clean["gross_cents"] == 339820 == striker["gross_cents"]
    assert float(clean["quality_deduction_pct"]) == 0.1500
    assert clean["quality_deduction_cents"] == 50973
    assert clean["pre_surcharge_net_cents"] == 248069
    assert clean["net_payable_cents"] == 239569
    assert clean["net_payable_cents"] > striker["net_payable_cents"], (
        "the escalated counterparty must be paid strictly less for identical material"
    )


# --------------------------------------------------------------------------
# Hazmat surcharge cap resolved against the pre-surcharge net
# --------------------------------------------------------------------------

_LFP_INTAKE = {
    "declared_chemistry": "LFP",
    "gross_mass_kg": 220.0,
    "packaging_tare_kg": 20.0,
    "declared_ni_pct": 5.0,
    "declared_co_pct": 3.0,
    "declared_li_pct": 2.0,
    "declared_cu_pct": 6.0,
}


def _light_lfp_settlement(api):
    ctx = fx.bootstrap_network(
        api,
        quotes=FOUR_METAL_QUOTES,
        supplier={
            "legal_name": "Basin LFP Collectors",
            "channel": "CONSUMER_COLLECTION",
            "credit_limit_cents": 100_000_000,
        },
    )
    fx.advance_intake(
        ctx,
        stop_after="released",
        intake=dict(_LFP_INTAKE),
        identified_chemistry="LFP",
        modules=(),
        soc_pct=8.0,
    )
    return fx.read_settlement(api, ctx["settlement"]["id"])


def test_hazmat_surcharge_takes_the_smaller_of_the_flat_and_the_capped_candidate(api):
    """A light, low-value shipment makes the percentage candidate the smaller one,
    so the surcharge is five percent of the pre-surcharge net.

    PRD §3.5: "**Step six** computes `hazmat_surcharge_cents` as the smaller of two
    candidates: a fixed 2,500 cents plus the shipment's `net_mass_kg` multiplied by
    6 cents per kilogram and rounded half up to a whole cent, or
    `pre_surcharge_net_cents` multiplied by 5 percent and rounded half up to a whole
    cent."

    Design: Difficulty/combinatorial_formula/hazmat_surcharge_cap_resolved_on_pre_surcharge_net_not_final_net
    """
    settlement = _light_lfp_settlement(api)

    assert_settlement(settlement)
    assert settlement["gross_cents"] == 16872
    assert float(settlement["processing_fee_pct"]) == 0.12
    assert settlement["processing_fee_cents"] == 2025
    assert float(settlement["quality_deduction_pct"]) == 0.0000
    assert settlement["quality_deduction_cents"] == 0
    assert settlement["pre_surcharge_net_cents"] == 14847
    assert settlement["hazmat_surcharge_cents"] == 742
    assert settlement["hazmat_surcharge_cents"] != 3700, (
        "3700 is the flat candidate, which is the larger of the two here"
    )
    assert settlement["net_payable_cents"] == 14105


def test_hazmat_cap_is_five_percent_of_the_pre_surcharge_net_not_of_the_final_net(api):
    """The percentage candidate is resolved against the pre-surcharge net, which is
    what stops the surcharge definition from being circular.

    PRD §3.5: "Taking the cap on the pre-surcharge figure rather than on the final
    net is what resolves what would otherwise be a circular definition."

    Design: Difficulty/combinatorial_formula/hazmat_surcharge_cap_resolved_on_pre_surcharge_net_not_final_net
    """
    settlement = _light_lfp_settlement(api)

    pre = settlement["pre_surcharge_net_cents"]
    net = settlement["net_payable_cents"]
    assert settlement["hazmat_surcharge_cents"] == round_half_up_cents(pre * 0.05) == 742
    assert settlement["hazmat_surcharge_cents"] != round_half_up_cents(net * 0.05), (
        "five percent of the final net would be 705, a different figure"
    )
    assert net == pre - settlement["hazmat_surcharge_cents"]
