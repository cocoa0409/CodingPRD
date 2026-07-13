"""Certificate fee calculation: PROVISIONAL vs FINAL divergence, per-line rounding,
MAWP tiers, the validity window, and the conserved fee ledger.

Difficulty queue A: dual_variant_calc, combinatorial_formula, compensating_invariant.
Corner queue B: calculations section.
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_registered_vessel, new_inspection, raise_deficiency, record_result,
    new_fee_invoice, pay_invoice, vessel_version, issue_certificate,
    set_clock, new_jurisdiction, new_owner, new_inspector, commission,
    new_vessel, register_vessel, assert_same_instant, TEST_USERS,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / fee_provisional_vs_final_diverge_on_certificate_domain
# ---------------------------------------------------------------------------
def _fee_divergence_ctx():
    ctx = setup_registered_vessel(clock="2026-06-01T00:00:00Z", vessel_class="POWER_BOILER", mawp_psig=120)
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"])
    d1 = raise_deficiency(insp1["id"], ctx["insp_a_id"], severity="NON_CRITICAL", description="sight glass corrosion")
    record_result(insp1["id"], ctx["insp_a_id"], "PASS_WITH_DEFICIENCIES")
    fee1 = new_fee_invoice(ctx["vessel_id"], insp1["id"])
    return ctx, insp1, fee1


def test_provisional_fee_excludes_deficiency_surcharge(api):
    """PRD §3.4: "This is an early estimate taken before any findings exist: it includes
    only the base class line and the pressure-tier line, with zero for the deficiency
    surcharge and zero for the incident surcharge."

    Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_diverge_on_certificate_domain
    """
    ctx, insp1, _fee1 = _fee_divergence_ctx()
    data = validate_success(api.get_inspection(insp1["id"], ADMIN))
    assert data["provisional_fee_cents"] == 26338


def test_final_fee_adds_deficiency_surcharge_and_diverges(api):
    """PRD §3.7: "the FINAL variant, computed at invoice creation using the actual
    non-withdrawn `NON_CRITICAL` deficiency count and the recorded `is_special` flag,
    adds the third and fourth lines, so the two variants diverge exactly when
    deficiencies were found or the inspection is special."

    Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_diverge_on_certificate_domain
    """
    ctx, insp1, fee1 = _fee_divergence_ctx()
    fee_data = validate_success(api.get_fee_invoice(fee1["id"], ADMIN))
    insp_data = validate_success(api.get_inspection(insp1["id"], ADMIN))
    assert fee_data["amount_cents"] == 29026
    assert fee_data["amount_cents"] != insp_data["provisional_fee_cents"]


# ---------------------------------------------------------------------------
# combinatorial_formula / fee_round_per_line_then_sum_mode_b
# ---------------------------------------------------------------------------
def _round_per_line_fee():
    ctx = setup_registered_vessel(clock="2026-06-01T00:00:00Z", vessel_class="POWER_BOILER", mawp_psig=120)
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"])
    raise_deficiency(insp1["id"], ctx["insp_a_id"], severity="NON_CRITICAL", description="loose fitting")
    record_result(insp1["id"], ctx["insp_a_id"], "PASS_WITH_DEFICIENCIES")
    return new_fee_invoice(ctx["vessel_id"], insp1["id"])


def test_fee_rounds_per_line_then_sums(api):
    """PRD §3.7: "Each non-zero line is first multiplied by one plus the jurisdiction's
    `admin_fee_pct` (which defaults to 0.075) and rounded to whole cents using
    round-half-up; the rounded lines are then summed to produce the fee."

    Design: Difficulty/combinatorial_formula/fee_round_per_line_then_sum_mode_b
    """
    fee1 = _round_per_line_fee()
    data = validate_success(api.get_fee_invoice(fee1["id"], ADMIN))
    assert data["amount_cents"] == 29026


def test_fee_not_computed_by_sum_then_round(api):
    """PRD §3.7: "Rounding is per line, then summed — never sum-then-round."

    Design: Difficulty/combinatorial_formula/fee_round_per_line_then_sum_mode_b
    """
    fee1 = _round_per_line_fee()
    data = validate_success(api.get_fee_invoice(fee1["id"], ADMIN))
    # Per-line rounding gives 21500+4838+2688 = 29026; sum-then-round would give 29025.
    assert data["amount_cents"] == 29026
    assert data["amount_cents"] != 29025


# ---------------------------------------------------------------------------
# Corner / calculations / fee_mawp_high_tier_boundary_151_psig
# ---------------------------------------------------------------------------
def test_fee_mawp_high_tier_at_151_psig(api):
    """PRD §3.7: "The second line is the pressure-tier fee determined by the vessel's
    `mawp_psig`: zero when the pressure is at most 15 psig; 4500 cents when the pressure
    is above 15 and at most 150; 12000 cents when above 150 and at most 600; and 25000
    cents when above 600."

    Design: Corner/calculations/fee_mawp_high_tier_boundary_151_psig
    """
    ctx = setup_registered_vessel(clock="2026-06-01T00:00:00Z", vessel_class="POWER_BOILER", mawp_psig=151)
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"])
    record_result(insp1["id"], ctx["insp_a_id"], "PASS")
    fee1 = new_fee_invoice(ctx["vessel_id"], insp1["id"])
    data = validate_success(api.get_fee_invoice(fee1["id"], ADMIN))
    assert data["amount_cents"] == 34400


# ---------------------------------------------------------------------------
# Corner / calculations / certificate_validity_window_pressure_vessel_24_months
# ---------------------------------------------------------------------------
def test_pressure_vessel_certificate_valid_until_24_months(api):
    """PRD §3.7: "The interval in months is the jurisdiction's `interval_months_override`
    when that override is not null; otherwise it is the class default — 12 months for a
    `POWER_BOILER`, 12 months for a `HEATING_BOILER`, and 24 months for a `PRESSURE_VESSEL`.
    Then `valid_until` is `valid_from` advanced by that many calendar months, keeping the
    same day-of-month."

    Design: Corner/calculations/certificate_validity_window_pressure_vessel_24_months
    """
    ctx = setup_registered_vessel(clock="2026-06-01T00:00:00Z", vessel_class="PRESSURE_VESSEL", mawp_psig=300)
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"])
    record_result(insp1["id"], ctx["insp_a_id"], "PASS")
    fee1 = new_fee_invoice(ctx["vessel_id"], insp1["id"])
    fee_data = validate_success(api.get_fee_invoice(fee1["id"], ADMIN))
    assert fee_data["amount_cents"] == 29025
    pay_invoice(fee1["id"], ctx["owner_id"])
    ver = vessel_version(ctx["vessel_id"])
    cert1 = issue_certificate(ctx["vessel_id"], insp1["id"], fee1["id"], ver)
    assert_same_instant(cert1["valid_until"], "2028-06-01T00:00:00Z")


# ---------------------------------------------------------------------------
# compensating_invariant / fee_ledger_conserved_on_pay_then_refund_money
# ---------------------------------------------------------------------------
def _pay_then_refund_ctx():
    ctx = setup_registered_vessel(clock="2026-06-01T00:00:00Z", vessel_class="POWER_BOILER", mawp_psig=120)
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"])
    record_result(insp1["id"], ctx["insp_a_id"], "PASS")
    fee1 = new_fee_invoice(ctx["vessel_id"], insp1["id"])
    pay_invoice(fee1["id"], ctx["owner_id"])
    get_success_data(api_client.refund_fee_invoice(fee1["id"], ADMIN))
    return ctx, fee1


def test_ledger_nets_to_zero_after_pay_then_refund(api):
    """PRD §2.8: "This ledger is credited the instant an invoice is paid and debited the
    instant it is refunded, so that a pay followed by a refund nets to zero."

    Design: Difficulty/compensating_invariant/fee_ledger_conserved_on_pay_then_refund_money
    """
    ctx, _fee1 = _pay_then_refund_ctx()
    jur = validate_success(api.get_jurisdiction(ctx["jur_id"], ADMIN))
    assert jur["collected_fees_cents"] == 0


def test_refund_sets_invoice_refunded_and_amount(api):
    """PRD §3.7: "refunding advances the invoice `PAID → REFUNDED` (terminal), sets
    `refunded_cents` equal to `amount_cents`, and debits the jurisdiction's
    `collected_fees_cents` by `amount_cents`, so the pay-then-refund pair nets to zero."

    Design: Difficulty/compensating_invariant/fee_ledger_conserved_on_pay_then_refund_money
    """
    ctx, fee1 = _pay_then_refund_ctx()
    data = validate_success(api.get_fee_invoice(fee1["id"], ADMIN))
    assert data["amount_cents"] == 26338
    assert data["status"] == "REFUNDED"
