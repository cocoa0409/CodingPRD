"""Lease pricing by product type: residual, buyout, tax, and rounding variants.

Difficulty queue: dual_variant_calc, combinatorial_formula.
Corner queue: calculations (dollar_out residual), consistency_model (immediate
visibility of book results).
"""
import pytest
from test_helpers import (
    validate_success,
    get_success_data,
    setup_active_lease,
    setup_end_of_term_lease,
    create_lessor,
    create_approved_vendor,
    create_approved_lessee,
    create_lease,
    attach_equipment,
    set_clock,
    elect,
    bill_line,
    list_scheduled_lines,
    TEST_USERS,
)

OFFICER = TEST_USERS["funding_officer_headers"]
SERVICER = TEST_USERS["servicer_headers"]


# ─── dual_variant_calc / residual_buyout_differs_by_lease_type ─────────
def test_fmv_buyout_quote_equals_residual_plus_remaining_rent(api):
    """PRD §3.11: "an `FMV` buyout is the lease's `residual_value_cents` plus the
    remaining rent (the lessee buys at fair value)".
    PRD §3.6: "a term of 24 months or fewer uses a band of 2000 basis points (20%)".

    An FMV term-1 lease (cost 500000, rate 2000) books with monthly_payment 100000
    and residual 100000 (20% band). After paying the single installment there are
    zero remaining installments, so the BUYOUT quote = residual 100000 + 0 = 100000.

    Design: Difficulty/dual_variant_calc/residual_buyout_differs_by_lease_type
    """
    ctx = setup_end_of_term_lease(
        equipment_cost_cents=500_000, term_months=1, monthly_rate_factor_bps=2000,
        serial_number="FMV-SN-1")
    election = elect(ctx["lessor_id"], ctx["lease"]["id"], "BUYOUT")
    assert election["quoted_amount_cents"] == 100_000, (
        f"FMV buyout should be residual 100000 + 0 remaining rent, "
        f"got {election['quoted_amount_cents']}"
    )


def test_trac_buyout_quote_equals_stipulated_residual_only(api):
    """PRD §3.11: "a `TRAC` buyout is the `residual_value_cents` alone, since a
    TRAC lease adjusts at sale rather than at buyout".
    PRD §3.6: "For a `TRAC` lease the residual is the client-stipulated
    `trac_residual_pct_bps` multiplied by the equipment cost, divided by 10,000,
    rounded half up".

    A TRAC term-1 lease (cost 600000, trac_residual 1500 bps) books with residual
    90000; after the single installment is paid the BUYOUT quote = residual alone
    = 90000, distinct from the FMV buyout above.

    Design: Difficulty/dual_variant_calc/residual_buyout_differs_by_lease_type
    """
    ctx = setup_end_of_term_lease(
        lease_type="TRAC", equipment_cost_cents=600_000, term_months=1,
        monthly_rate_factor_bps=2000, trac_residual_pct_bps=1500,
        original_cost_cents=600_000, serial_number="TRAC-SN-1")
    election = elect(ctx["lessor_id"], ctx["lease"]["id"], "BUYOUT")
    assert election["quoted_amount_cents"] == 90_000, (
        f"TRAC buyout should equal stipulated residual 90000, "
        f"got {election['quoted_amount_cents']}"
    )


# ─── dual_variant_calc / tax_amount_differs_sales_use_vs_property ───────
def test_sales_use_tax_amount_on_equipment_cost(api):
    """PRD §3.8: "For a `SALES_USE` assessment, the taxable base is the lease's
    `equipment_cost_cents`, and the tax amount is that base multiplied by the
    lessor's `sales_tax_rate_bps`, divided by 10,000, rounded half up".

    Funding auto-generates the SALES_USE assessment: base 500000 at 825 bps =
    41250 cents, base = 500000.

    Design: Difficulty/dual_variant_calc/tax_amount_differs_sales_use_vs_property
    """
    ctx = setup_active_lease(
        equipment_cost_cents=500_000, term_months=12, monthly_rate_factor_bps=2000,
        serial_number="SN-100", clock_iso=None)
    assessments = get_success_data(api.list_lease_tax_assessments(
        ctx["lessor_id"], ctx["lease"]["id"], SERVICER, params={"tax_type": "SALES_USE"}))
    assert len(assessments) >= 1, "funding must auto-generate a SALES_USE assessment"
    sales = assessments[0]
    assert sales["tax_amount_cents"] == 41250, (
        f"SALES_USE tax should be 500000*825/10000=41250, got {sales['tax_amount_cents']}"
    )
    assert sales["taxable_base_cents"] == 500_000


def test_property_tax_amount_on_assessed_value_year_zero(api):
    """PRD §3.8: "For a `PROPERTY` assessment, the taxable base is the sum of
    `assessed_value_cents` over the lease's units whose status is not `DISPOSED`,
    and the tax amount is that base multiplied by the lessor's
    `property_tax_rate_bps`, divided by 10,000, rounded half up".

    At year 0 (just booked, no clock advance) the 500000-cost unit assesses at
    500000; PROPERTY tax at 120 bps = 6000 cents, base = 500000 — different base
    AND rate from the SALES_USE assessment above.

    Design: Difficulty/dual_variant_calc/tax_amount_differs_sales_use_vs_property
    """
    lessor_id = create_lessor()["id"]
    set_clock(lessor_id, "2026-01-01T00:00:00.000Z")
    ctx = setup_active_lease(
        lessor_id=lessor_id, equipment_cost_cents=500_000, term_months=12,
        monthly_rate_factor_bps=2000, serial_number="SN-101", original_cost_cents=500_000)
    res = api.create_tax_assessment(
        lessor_id, ctx["lease"]["id"], {"tax_type": "PROPERTY"}, SERVICER)
    prop = validate_success(res, 201)
    assert prop["tax_amount_cents"] == 6000, (
        f"PROPERTY tax should be 500000*120/10000=6000, got {prop['tax_amount_cents']}"
    )
    assert prop["taxable_base_cents"] == 500_000


# NOTE — SKIPPED instance:
#   Difficulty/combinatorial_formula/buyout_quote_multibranch_three_inputs
# The instance asserts an FMV BUYOUT quote with a NON-ZERO remaining-rent term
# (residual + remaining_installments * monthly_payment). Per PRD §3.11 an
# End-Of-Term Election is recorded only "within end-of-term", reachable only once
# "`paid_installment_count` must be at least `term_months` minus
# `advance_payment_count`". At that point remaining = term - paid - advance is
# floored at zero, so the remaining-rent term is structurally always 0 for any
# legitimately-reached BUYOUT election — a faithful PRD-only implementer would
# compute residual-alone via the API and never the multibranch value the instance
# pins. The asserted outcome is not uniquely-derivable through any valid API state,
# so the instance is skipped (no weakened/substitute test emitted). The reachable
# combinatorial instance (invoice_sales_tax_round_per_line_order) is covered below.


# ─── combinatorial_formula / invoice_sales_tax_round_per_line_order ────
def test_invoice_sales_tax_rounded_per_line(api):
    """PRD §3.9: "This rounding happens per invoice — each invoice's tax is rounded
    on its own base rent and never by summing several base rents and taxing the
    total, so two equal rents of $33.33 at 8.25% each round to 275 cents
    independently."
    PRD §3.9: "The per-invoice sales tax is the invoice's own base rent multiplied
    by the lessor's `sales_tax_rate_bps`, divided by 10,000, rounded half up; the
    total due is the base rent plus that tax."

    A lease with monthly_payment 1000 (cost 400000, rate 25) under an 825-bps
    lessor: each of two invoices rounds tax to 83 cents on its own base rent
    (166 total), not 165 from summing-then-taxing; total_due 1083.

    Design: Difficulty/combinatorial_formula/invoice_sales_tax_round_per_line_order
    """
    ctx = setup_active_lease(
        equipment_cost_cents=400_000, term_months=2, monthly_rate_factor_bps=25,
        serial_number="SN-300")
    lessor_id, lease_id = ctx["lessor_id"], ctx["lease"]["id"]
    lines = list_scheduled_lines(lessor_id, lease_id)
    assert len(lines) >= 2, "term 2 should leave 2 SCHEDULED lines"
    inv0 = bill_line(lessor_id, lease_id, lines[0]["id"])
    inv1 = bill_line(lessor_id, lease_id, lines[1]["id"])
    assert inv0["sales_tax_cents"] == 83, f"got {inv0['sales_tax_cents']}"
    assert inv1["sales_tax_cents"] == 83, f"got {inv1['sales_tax_cents']}"
    assert inv0["total_due_cents"] == 1083, f"got {inv0['total_due_cents']}"
    assert inv0["base_rent_cents"] == 1000, f"got {inv0['base_rent_cents']}"


def test_invoice_sales_tax_rounds_half_up_per_invoice(api):
    """PRD §3.9: "The per-invoice sales tax is the invoice's own base rent multiplied
    by the lessor's `sales_tax_rate_bps`, divided by 10,000, rounded half up; the
    total due is the base rent plus that tax."
    PRD §2.7: "the system divides the product by 10,000 and rounds the result to the
    nearest whole cent using the **round half up** convention — a result whose
    fractional part is exactly one-half rounds up."

    A single invoice with base rent 1000 at 825 bps computes its own tax as
    round_half_up(1000*825/10000) = round_half_up(82.5) = 83, total_due 1083 — the
    rounding is performed on this one invoice's base rent.

    Design: Difficulty/combinatorial_formula/invoice_sales_tax_round_per_line_order
    """
    ctx = setup_active_lease(
        equipment_cost_cents=400_000, term_months=1, monthly_rate_factor_bps=25,
        serial_number="SN-301")
    lessor_id, lease_id = ctx["lessor_id"], ctx["lease"]["id"]
    line = list_scheduled_lines(lessor_id, lease_id)[0]
    inv = bill_line(lessor_id, lease_id, line["id"])
    assert inv["base_rent_cents"] == 1000, f"got {inv['base_rent_cents']}"
    assert inv["sales_tax_cents"] == 83, f"got {inv['sales_tax_cents']}"
    assert inv["total_due_cents"] == 1083, f"got {inv['total_due_cents']}"


# ─── Corner: calculations / dollar_out_residual_nominal_one_dollar ─────
def test_dollar_out_residual_is_nominal_one_dollar(api):
    """PRD §3.6: "For a `DOLLAR_OUT` lease the residual is a fixed nominal $1, that
    is, exactly 100 cents, regardless of term or cost."
    PRD §3.4: "`monthly_payment_cents` is set to the equipment cost multiplied by
    the monthly rate factor in basis points, divided by 10,000, rounded half up".

    A DOLLAR_OUT lease (cost 900000, term 24, rate 300) books with residual 100
    and monthly_payment 27000.

    Design: Corner/calculations/dollar_out_residual_nominal_one_dollar
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(
        lessor_id, lessee_id, vendor_id,
        lease_type="DOLLAR_OUT", equipment_cost_cents=900_000, term_months=24,
        monthly_rate_factor_bps=300)
    attach_equipment(lessor_id, lease["id"], "J-SN-1", original_cost_cents=900_000)
    booked = get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER))
    assert booked["residual_value_cents"] == 100, f"got {booked['residual_value_cents']}"
    assert booked["monthly_payment_cents"] == 27_000, f"got {booked['monthly_payment_cents']}"


# ─── Corner: consistency_model / immediate_visibility_of_book_results ──
def test_book_response_carries_computed_pricing_immediately(api):
    """PRD §3.6: "a term greater than 24 but no more than 48 months uses 1500 basis
    points (15%)".
    PRD §3.4: "`monthly_payment_cents` is set to the equipment cost multiplied by
    the monthly rate factor in basis points, divided by 10,000, rounded half up".

    The book response itself carries the freshly-computed monthly_payment_cents
    (100000) and residual_value_cents (75000 for an FMV term-36 lease at 1500 bps
    on cost 500000), with no re-read required.

    Design: Corner/consistency_model/immediate_visibility_of_book_results
    """
    lessor_id = create_lessor()["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(
        lessor_id, lessee_id, vendor_id,
        lease_type="FMV", equipment_cost_cents=500_000, term_months=36,
        monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "Z-SN-1", original_cost_cents=500_000)
    booked = get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER))
    assert booked["monthly_payment_cents"] == 100_000, f"got {booked['monthly_payment_cents']}"
    assert booked["residual_value_cents"] == 75_000, f"got {booked['residual_value_cents']}"
