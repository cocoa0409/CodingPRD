"""Estimate-vs-adjudication divergence and the nested benefit formula.

Difficulty queue A: dual_variant_calc, combinatorial_formula instances.
"""
from test_helpers import (
    setup_practice,
    create_plan_with_items,
    propose_plan,
    accept_plan,
    complete_item_via_visit,
    create_claim,
    attach_and_submit,
    adjudicate_claim,
    create_payment_plan,
    setup_adjudicated_claim,
    setup_completed_item_claim,
    get_success_data,
    validate_success,
    TEST_USERS,
)
from test_helpers import api_client

BILL = TEST_USERS["billing_headers"]


# ─── dual_variant_calc / estimate_vs_adjudication_diverge_on_major_crown ───────

def test_crown_estimate_is_best_case_forward_view():
    """PRD §3.8: "The item's `estimated_insurance_cents` is the smaller of the
    gross benefit and that remaining annual maximum, and its
    `estimated_patient_portion_cents` is the item's `fee_cents` minus
    `estimated_insurance_cents`."
    PRD §3.8: "Because this estimate reads the accumulator as it stands now and
    ignores other in-flight planned items, it is a best-case forward view."

    A fresh MAJOR crown (fee 120000, MAJOR 50%, deductible 5000) estimates
    floor((120000-5000)*50/100)=57500 carrier, leaving 62500 patient portion.

    Design: Difficulty/dual_variant_calc/estimate_vs_adjudication_diverge_on_major_crown
    """
    ctx = setup_practice()
    patient, provider = ctx["patient"], ctx["provider"]
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D2740", "category": "MAJOR", "fee_cents": 120_000,
          "phase_number": 1, "tooth_number": 8},
         {"cdt_code": "D2391", "category": "BASIC", "fee_cents": 100_000,
          "phase_number": 1, "tooth_number": 3}],
    )
    crown = items[0]
    propose_plan(plan["id"], provider["id"])
    crown_after = validate_success(
        api_client.get_treatment_plan_item(crown["id"], ctx["clinician_headers"])
    )
    assert crown_after["estimated_insurance_cents"] == 57500
    assert crown_after["estimated_patient_portion_cents"] == 62500


def test_crown_adjudicates_lower_than_estimate_once_pool_consumed():
    """PRD §3.8: "The remaining annual maximum is the plan's `annual_maximum_cents`
    minus the coverage's live `annual_benefit_used_cents`, floored at zero, and
    `carrier_paid_cents` is the smaller of the gross benefit and that remaining
    annual maximum."
    PRD §3.6: "when the carrier payment is less than the gross benefit — because
    the live remaining annual maximum clamped it — the claim becomes
    `PARTIALLY_PAID`."

    After a BASIC claim consumes 76000 of the 100000 max, the identical crown
    (gross 60000, deductible already met) is clamped to remaining 24000 and
    becomes PARTIALLY_PAID; patient owes 120000-24000=96000.

    Design: Difficulty/dual_variant_calc/estimate_vs_adjudication_diverge_on_major_crown
    """
    ctx = setup_practice()
    patient, provider, operatory, coverage = (
        ctx["patient"], ctx["provider"], ctx["operatory"], ctx["coverage"]
    )
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D2740", "category": "MAJOR", "fee_cents": 120_000,
          "phase_number": 1, "tooth_number": 8},
         {"cdt_code": "D2391", "category": "BASIC", "fee_cents": 100_000,
          "phase_number": 1, "tooth_number": 3}],
    )
    crown, basic = items[0], items[1]
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])

    # BASIC claim first: fresh accumulator => paid 76000.
    complete_item_via_visit(patient["id"], provider["id"], operatory["id"], basic["id"],
                            start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T10:00:00Z")
    basic_claim = create_claim(patient["id"], basic["id"], coverage["id"])
    attach_and_submit(basic_claim["id"], attachment_type="XRAY", document_ref="ref://x1")
    basic_adj = adjudicate_claim(basic_claim["id"])
    assert basic_adj["carrier_paid_cents"] == 76000

    # Crown claim next: deductible met, remaining max 24000 clamps the 60000 gross.
    complete_item_via_visit(patient["id"], provider["id"], operatory["id"], crown["id"],
                            start_at="2026-03-02T09:00:00Z", end_at="2026-03-02T10:00:00Z")
    crown_claim = create_claim(patient["id"], crown["id"], coverage["id"])
    attach_and_submit(crown_claim["id"], attachment_type="XRAY", document_ref="ref://x2")
    crown_adj = adjudicate_claim(crown_claim["id"])

    assert crown_adj["carrier_paid_cents"] == 24000
    assert crown_adj["patient_responsibility_cents"] == 96000
    assert crown_adj["adjudication_status"] == "PARTIALLY_PAID"


# ─── dual_variant_calc / payment_plan_projected_vs_actual_payoff_diverge ───────

def test_payment_plan_projected_schedule_on_create():
    """PRD §3.7: "The base per-installment amount is the principal divided by the
    installment count, floored to whole cents; `installment_amount_cents` is that
    base and applies to the first `installment_count` minus one installments. The
    `final_installment_cents` is whatever remains — the principal minus the base
    multiplied by one less than the installment count."

    A fresh MAJOR crown adjudicates to patient_responsibility 62500; financed over
    7 installments => base floor(62500/7)=8928, final 62500-8928*6=8932.

    Design: Difficulty/dual_variant_calc/payment_plan_projected_vs_actual_payoff_diverge
    """
    ctx = setup_practice()
    _, claim = setup_adjudicated_claim(ctx, 120_000, category="MAJOR", cdt_code="D2750",
                                       tooth_number=9, document_ref="ref://n1",
                                       attachment_type="NARRATIVE")
    assert claim["patient_responsibility_cents"] == 62500
    pp = create_payment_plan(ctx["patient"]["id"], claim["id"], claim["version"],
                             installment_count=7)
    assert pp["principal_cents"] == 62500
    assert pp["installment_amount_cents"] == 8928
    assert pp["final_installment_cents"] == 8932


def test_payment_plan_actual_payoff_precedes_scheduled_count():
    """PRD §3.7: "the moment `amount_posted_cents` reaches or exceeds
    `principal_cents`, the plan flips to `PAID_OFF` with `remaining_balance_cents`
    of zero — this can happen before all installments are posted."

    A single lump 62500 post on a 7-installment plan drives remaining to 0 and
    flips PAID_OFF before the projected 7 installments.

    Design: Difficulty/dual_variant_calc/payment_plan_projected_vs_actual_payoff_diverge
    """
    ctx = setup_practice()
    _, claim = setup_adjudicated_claim(ctx, 120_000, category="MAJOR", cdt_code="D2750",
                                       tooth_number=9, document_ref="ref://n2",
                                       attachment_type="NARRATIVE")
    pp = create_payment_plan(ctx["patient"]["id"], claim["id"], claim["version"],
                             installment_count=7)
    after = get_success_data(api_client.post_installment(pp["id"], {"amount_cents": 62500}, BILL))
    assert after["remaining_balance_cents"] == 0
    assert after["status"] == "PAID_OFF"


# ─── combinatorial_formula / adjudicated_benefit_nested_min_max_three_inputs ───

def test_adjudicated_benefit_clamped_at_annual_max_is_paid():
    """PRD §3.8: "the gross benefit is the amount after deductible multiplied by
    the chosen coinsurance percentage divided by 100, with the fraction dropped.
    The remaining annual maximum is the plan's `annual_maximum_cents` minus the
    coverage's live `annual_benefit_used_cents`, floored at zero, and
    `carrier_paid_cents` is the smaller of the gross benefit and that remaining
    annual maximum."
    PRD §3.6: "when the carrier payment equals the gross benefit the claim becomes
    `PAID`".

    A fresh BASIC claim fee=130000, ded=5000, BASIC=80%: gross=floor(125000*80/100)
    =100000, remaining max=100000, carrier_paid=min(100000,100000)=100000 (PAID,
    no shortfall); patient owes 30000.

    Design: Difficulty/combinatorial_formula/adjudicated_benefit_nested_min_max_three_inputs
    """
    ctx = setup_practice()
    _, claim = setup_adjudicated_claim(ctx, 130_000, category="BASIC", cdt_code="D2392",
                                       tooth_number=14, document_ref="ref://x3",
                                       attachment_type="XRAY")
    assert claim["carrier_paid_cents"] == 100000
    assert claim["patient_responsibility_cents"] == 30000
    assert claim["adjudication_status"] == "PAID"


def test_adjudicated_benefit_floors_coinsurance_product():
    """PRD §3.8: "the gross benefit is the amount after deductible multiplied by
    the chosen coinsurance percentage divided by 100, with the fraction dropped."

    A second pinned point on the nested formula: a fresh BASIC claim fee=130000
    yields a floored coinsurance product that equals the annual-max clamp (100000),
    so the floor + min composition lands on exactly 100000 carrier-paid.

    Design: Difficulty/combinatorial_formula/adjudicated_benefit_nested_min_max_three_inputs
    """
    ctx = setup_practice()
    item, claim = setup_completed_item_claim(ctx, 130_000, category="BASIC",
                                             cdt_code="D2392", tooth_number=15)
    attach_and_submit(claim["id"], attachment_type="XRAY", document_ref="ref://x3b")
    adjudicated = adjudicate_claim(claim["id"])
    # gross = floor((130000-5000)*80/100) = 100000; clamp = 100000.
    assert adjudicated["carrier_paid_cents"] == 100000


# ─── combinatorial_formula / payment_plan_round_per_installment_then_reconcile ─

def test_payment_plan_remainder_reconciled_into_final_installment():
    """PRD §3.7: "the final installment absorbs the rounding remainder, and the
    base multiplied by one-less-than-the-count plus the final installment equals
    the principal exactly."

    principal=62500, n=7 => base=floor(62500/7)=8928, final=62500-8928*6=8932, and
    8928*6+8932 == 62500 exactly.

    Design: Difficulty/combinatorial_formula/payment_plan_round_per_installment_then_reconcile_remainder
    """
    ctx = setup_practice()
    _, claim = setup_adjudicated_claim(ctx, 120_000, category="MAJOR", cdt_code="D2740",
                                       tooth_number=8, document_ref="ref://p1",
                                       attachment_type="PHOTO")
    pp = create_payment_plan(ctx["patient"]["id"], claim["id"], claim["version"],
                             installment_count=7)
    assert pp["principal_cents"] == 62500
    assert pp["installment_amount_cents"] == 8928
    assert pp["final_installment_cents"] == 8932


def test_payment_plan_schedule_sums_to_principal_exactly():
    """PRD §3.7: "the base multiplied by one-less-than-the-count plus the final
    installment equals the principal exactly."

    The pinned invariant base*(count-1) + final == principal holds for the 7-way
    split of 62500.

    Design: Difficulty/combinatorial_formula/payment_plan_round_per_installment_then_reconcile_remainder
    """
    ctx = setup_practice()
    _, claim = setup_adjudicated_claim(ctx, 120_000, category="MAJOR", cdt_code="D2740",
                                       tooth_number=8, document_ref="ref://p1b",
                                       attachment_type="PHOTO")
    pp = create_payment_plan(ctx["patient"]["id"], claim["id"], claim["version"],
                             installment_count=7)
    assert (pp["installment_amount_cents"] * (pp["installment_count"] - 1)
            + pp["final_installment_cents"]) == pp["principal_cents"]
