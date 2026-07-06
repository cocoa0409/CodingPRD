"""Dual-variant and combinatorial calculation tests: estimate bands, invoice
per-line tax, and payment-plan eval order.

Difficulty queue: dual_variant_calc, combinatorial_formula.
"""
from test_helpers import (
    validate_success,
    make_finance_coordinator_headers,
    register_and_triage,
    create_draft_estimate,
    setup_visit_with_performed_charges,
    setup_finalized_invoice,
    get_invoice,
    api_client,
)


def test_estimate_low_and_high_bands_diverge_on_uplift(api):
    """PRD §3.4: "The low subtotal is exactly this raw subtotal."
    PRD §3.4: "The high subtotal takes the raw subtotal, adds a twenty percent
    clinical-variance uplift (that is, multiplies it by 1.20), and rounds the
    result up to the next whole cent."
    PRD §3.4: "For the high band, `high_cents` is the high subtotal plus the high
    tax, where the high tax is the single uplifted high subtotal multiplied by
    the tax rate of 0.0725, rounded half-up to a whole cent"
    PRD §3.4: "The `deposit_pct` is 0.80 for a `RED` case, 0.60 for `ORANGE`,
    0.50 for `YELLOW`, and 0.30 for `GREEN`."

    Design: Difficulty/dual_variant_calc/dvc_estimate_low_vs_high_band
    """
    finance = make_finance_coordinator_headers()
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-1")
    resp = api.create_estimate(visit["id"], {
        "line_items": [{"code": "TX", "description": "treatment", "qty": 1,
                        "unit_price_cents": 200000}]
    }, finance)
    est = validate_success(resp, expected_status=201)
    assert est["low_cents"] == 214500, f"expected low_cents 214500, got {est['low_cents']}"
    assert est["high_cents"] == 257400, f"expected high_cents 257400, got {est['high_cents']}"
    assert est["deposit_pct"] == 0.5, f"expected deposit_pct 0.5, got {est['deposit_pct']}"
    assert est["deposit_cents"] == 128700, f"expected deposit_cents 128700, got {est['deposit_cents']}"


def test_estimate_deposit_pct_from_yellow_tier(api):
    """PRD §3.4: "The deposit is a fraction of the high band determined by the
    Visit's triage level at the time the estimate is issued."
    PRD §3.4: "The `deposit_cents` is `high_cents` multiplied by `deposit_pct`,
    rounded up to the next whole cent."

    Design: Difficulty/dual_variant_calc/dvc_estimate_low_vs_high_band
    """
    _, visit = register_and_triage(triage_level="YELLOW", owner_user_id="owner-1")
    est = create_draft_estimate(visit["id"], unit_price_cents=200000)
    assert est["deposit_pct"] == 0.5
    assert est["deposit_cents"] == 128700


def test_invoice_tax_per_line_not_sum_then_tax(api):
    """PRD §3.9: "for each charge line, take its `qty` multiplied by its
    `unit_price_cents` multiplied by the tax rate of 0.0725, round that half-up
    to a whole cent, and add these rounded per-line taxes together."
    PRD §3.9: "This per-line ordering is authoritative; the alternative of
    summing the subtotal first and taxing once must not be used, as it can
    differ by a cent."

    Design: Difficulty/dual_variant_calc/dvc_invoice_per_line_vs_sum_then_tax
    """
    _, visit, _, _, _ = setup_visit_with_performed_charges(
        prices=[4599, 12750, 8899], triage_level="GREEN",
        approved_ceiling_cents=30000, owner_user_id="owner-2")
    invoice = get_invoice(visit["id"])
    assert invoice["subtotal_cents"] == 26248, f"expected subtotal 26248, got {invoice['subtotal_cents']}"
    assert invoice["tax_cents"] == 1902, f"expected per-line tax 1902, got {invoice['tax_cents']}"


def test_invoice_subtotal_sums_charge_lines(api):
    """PRD §3.9: "The `subtotal_cents` is the sum, over all charge lines, of each
    line's `qty` multiplied by its `unit_price_cents`."

    Design: Difficulty/dual_variant_calc/dvc_invoice_per_line_vs_sum_then_tax
    """
    _, visit, _, _, _ = setup_visit_with_performed_charges(
        prices=[4599, 12750, 8899], triage_level="GREEN",
        approved_ceiling_cents=30000, owner_user_id="owner-2")
    invoice = get_invoice(visit["id"])
    assert invoice["subtotal_cents"] == 26248


def test_invoice_rounding_order_pinned_per_line(api):
    """PRD §3.9: "for each charge line, take its `qty` multiplied by its
    `unit_price_cents` multiplied by the tax rate of 0.0725, round that half-up
    to a whole cent, and add these rounded per-line taxes together."
    PRD §3.9: "This per-line ordering is authoritative; the alternative of
    summing the subtotal first and taxing once must not be used, as it can
    differ by a cent."

    Design: Difficulty/combinatorial_formula/cf_rounding_order_invoice_per_line
    """
    _, visit, _, _, _ = setup_visit_with_performed_charges(
        prices=[4599, 12750, 8899], triage_level="GREEN",
        approved_ceiling_cents=30000, owner_user_id="owner-2")
    invoice = get_invoice(visit["id"])
    # sum-then-tax would give 1903; the pinned per-line order gives 1902.
    assert invoice["tax_cents"] == 1902, f"expected 1902 (per-line), got {invoice['tax_cents']}"
    assert invoice["subtotal_cents"] == 26248


def test_invoice_per_line_tax_distinct_from_forbidden_variant(api):
    """PRD §3.9: "This per-line ordering is authoritative; the alternative of
    summing the subtotal first and taxing once must not be used, as it can
    differ by a cent."

    Design: Difficulty/combinatorial_formula/cf_rounding_order_invoice_per_line
    """
    _, visit, _, _, _ = setup_visit_with_performed_charges(
        prices=[4599, 12750, 8899], triage_level="GREEN",
        approved_ceiling_cents=30000, owner_user_id="owner-2")
    invoice = get_invoice(visit["id"])
    assert invoice["tax_cents"] != 1903, "must not use sum-then-tax variant"
    assert invoice["tax_cents"] == 1902


def test_payment_plan_promo_eval_order_carecredit_6mo(api):
    """PRD §3.10: "`promo_applied` is true if and only if the provider is
    `CARECREDIT` and the `principal_cents` is at least 100,000 cents and the
    `term_months` is at most 6"
    PRD §3.10: "when the promotion applies, the `financing_fee_cents` is zero"
    PRD §3.10: "the `installment_cents` charged for each of the first
    `term_months` minus one installments is the total divided by `term_months`,
    rounded up to the next whole cent, and the `final_installment_cents` is the
    remainder"

    Design: Difficulty/combinatorial_formula/cf_payment_plan_eval_order_promo
    """
    finance = make_finance_coordinator_headers()
    _, visit, _, _, _, invoice = setup_finalized_invoice(
        surgery_price=300000, triage_level="YELLOW",
        approved_ceiling_cents=386100, owner_user_id="owner-3")
    resp = api.create_payment_plan(visit["id"], {
        "invoice_id": invoice["id"], "provider": "CARECREDIT", "term_months": 6,
    }, finance)
    plan = validate_success(resp, expected_status=201)
    assert plan["principal_cents"] == 128700, f"expected principal 128700, got {plan['principal_cents']}"
    assert plan["promo_applied"] is True
    assert plan["financing_fee_cents"] == 0
    assert plan["installment_cents"] == 21450
    assert plan["final_installment_cents"] == 21450


def test_payment_plan_promo_zeroes_financing_fee(api):
    """PRD §3.10: "the financing fee is set from that eligibility: when the
    promotion applies, the `financing_fee_cents` is zero"

    Design: Difficulty/combinatorial_formula/cf_payment_plan_eval_order_promo
    """
    finance = make_finance_coordinator_headers()
    _, visit, _, _, _, invoice = setup_finalized_invoice(
        surgery_price=300000, triage_level="YELLOW",
        approved_ceiling_cents=386100, owner_user_id="owner-3")
    resp = api.create_payment_plan(visit["id"], {
        "invoice_id": invoice["id"], "provider": "CARECREDIT", "term_months": 6,
    }, finance)
    plan = validate_success(resp, expected_status=201)
    assert plan["promo_applied"] is True
    assert plan["financing_fee_cents"] == 0
