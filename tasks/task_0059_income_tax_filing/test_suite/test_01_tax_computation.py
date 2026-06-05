"""Tax computation: deductions, bracket tax, credits, capital gains, boundaries.

Translates difficulty queue A rules dual_variant_calc, combinatorial_formula,
boundary_precision_check and corner queue B calculation instances.
"""
from test_helpers import (
    validate_success,
    make_taxpayer_headers,
    create_taxpayer_payload, create_tax_return_payload,
    create_income_document_payload, create_dependent_payload,
    create_credit_claim_payload, create_schedule_payload,
)


def _new_taxpayer(api, **tp_overrides):
    resp = api.create_taxpayer(create_taxpayer_payload(**tp_overrides),
                               make_taxpayer_headers("bootstrap"))
    return validate_success(resp, 201)


def _open_return(api, tp_id, **ret_overrides):
    h = make_taxpayer_headers(tp_id)
    resp = api.create_tax_return(create_tax_return_payload(tp_id, **ret_overrides), h)
    return validate_success(resp, 201)


# =====================================================================
# dual_variant_calc / deduction_standard_vs_itemized_diverges_on_taxreturn
# =====================================================================

def test_standard_deduction_single_balance_due(api):
    """PRD §3.5: "the deduction is the standard-deduction figure for the return's
    `filing_status`: fifteen hundred thousand cents ($15,000.00) for `SINGLE`, three
    million cents ($30,000.00) for `MARRIED_JOINT`, fifteen hundred thousand cents
    ($15,000.00) for `MARRIED_SEPARATE`, and two million two hundred fifty thousand
    cents ($22,500.00) for `HEAD_OF_HOUSEHOLD`; under the standard method, Schedule A
    is ignored even if present."
    PRD §3.5: "`balance_due_cents` is `tax_after_credits_cents` minus
    `total_payments_cents`: a positive figure is owed by the filer, a negative figure
    is a refund owed to the filer."

    Design: Difficulty/dual_variant_calc/deduction_standard_vs_itemized_diverges_on_taxreturn
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"],
        create_income_document_payload(box_amount_cents=8_000_000,
                                       federal_withholding_cents=900_000), h), 201)
    computed = validate_success(api.compute_tax_return(ret["id"], h), 200)
    assert computed["taxable_income_cents"] == 6_500_000
    assert computed["tax_before_credits_cents"] == 935_300
    assert computed["balance_due_cents"] == 35_300


def test_itemized_deduction_diverges_from_standard(api):
    """PRD §3.5: "When `deduction_method` is `ITEMIZED`, the deduction is Schedule A's
    `gross_amount_cents` (equivalently its net)."
    PRD §3.5: "The same income data therefore yields a different taxable income, and
    hence a different balance, depending on which deduction method is elected."

    Design: Difficulty/dual_variant_calc/deduction_standard_vs_itemized_diverges_on_taxreturn
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="ITEMIZED")
    validate_success(api.create_income_document(
        ret["id"],
        create_income_document_payload(box_amount_cents=8_000_000,
                                       federal_withholding_cents=900_000), h), 201)
    validate_success(api.create_schedule(
        ret["id"], create_schedule_payload("A", gross_amount_cents=2_500_000), h), 201)
    computed = validate_success(api.compute_tax_return(ret["id"], h), 200)
    # agi 8,000,000 - itemized 2,500,000 = taxable 5,500,000
    assert computed["taxable_income_cents"] == 5_500_000
    # balance differs from the STANDARD case (35,300)
    assert computed["balance_due_cents"] == -184_700


# =====================================================================
# combinatorial_formula / bracket_tax_three_tier_nonlinear_mode_a
# =====================================================================

def test_bracket_tax_crosses_three_tiers_single(api):
    """PRD §3.5: "For `SINGLE` and `MARRIED_SEPARATE`, the first tier is 10% on taxable
    income up to 1,160,000 cents, the second tier is 12% on the portion above 1,160,000
    and up to 4,715,000 cents, and the third tier is 22% on any portion above 4,715,000
    cents."
    PRD §3.5: "The rounding order here is pinned: the tax for each tier is computed and
    **rounded down to the nearest whole cent before the tiers are summed** — round per
    tier first, then add — and the sum is `tax_before_credits_cents`."

    Design: Difficulty/combinatorial_formula/bracket_tax_three_tier_nonlinear_mode_a
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=8_000_000,
                                                  federal_withholding_cents=0), h), 201)
    computed = validate_success(api.compute_tax_return(ret["id"], h), 200)
    assert computed["taxable_income_cents"] == 6_500_000
    # 116,000 + 426,600 + 392,700 = 935,300
    assert computed["tax_before_credits_cents"] == 935_300


def test_bracket_tax_married_joint_two_tiers(api):
    """PRD §3.5: "For `MARRIED_JOINT`, the first tier is 10% up to 2,320,000 cents, the
    second tier is 12% on the portion above 2,320,000 and up to 9,430,000 cents, and
    the third tier is 22% above 9,430,000 cents."
    PRD §3.5: "the deduction is the standard-deduction figure for the return's
    `filing_status`: fifteen hundred thousand cents ($15,000.00) for `SINGLE`, three
    million cents ($30,000.00) for `MARRIED_JOINT`, fifteen hundred thousand cents
    ($15,000.00) for `MARRIED_SEPARATE`, and two million two hundred fifty thousand
    cents ($22,500.00) for `HEAD_OF_HOUSEHOLD`; under the standard method, Schedule A is
    ignored even if present."

    Design: Difficulty/combinatorial_formula/bracket_tax_three_tier_nonlinear_mode_a
    """
    tp = _new_taxpayer(api, filing_status="MARRIED_JOINT")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="MARRIED_JOINT",
                       deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=8_000_000), h), 201)
    computed = validate_success(api.compute_tax_return(ret["id"], h), 200)
    assert computed["taxable_income_cents"] == 5_000_000
    # 232,000 (10% of 2,320,000) + 321,600 (12% of 2,680,000) = 553,600
    assert computed["tax_before_credits_cents"] == 553_600


# =====================================================================
# combinatorial_formula / aotc_two_step_floor_rounding_order_mode_b
# =====================================================================

def test_aotc_floor_then_percent_rounding_order(api):
    """PRD §3.5: "otherwise the allowed amount is the base multiplied by the quantity
    (nine million cents minus `agi_cents`) divided by (nine million cents minus eight
    million cents), with the result rounded down to the nearest cent."
    PRD §3.5: "The AOTC's refundable portion is then forty percent of that
    already-floored allowed amount, again rounded down to the nearest cent — the
    rounding order is pinned so that the refundable portion is computed from the floored
    allowed amount, not from the unfloored base."

    Design: Difficulty/combinatorial_formula/aotc_two_step_floor_rounding_order_mode_b
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=8_000_010,
                                                  federal_withholding_cents=1_000_000), h), 201)
    validate_success(api.create_dependent(
        ret["id"], create_dependent_payload(full_name="Kid", age_years=19,
                                            is_student=True), h), 201)
    validate_success(api.create_credit_claim(
        ret["id"], create_credit_claim_payload("AOTC", claimed_amount_cents=250_000), h), 201)
    validate_success(api.compute_tax_return(ret["id"], h), 200)
    claims = validate_success(api.list_credit_claims(ret["id"], h), 200)
    aotc = next(c for c in claims if c["credit_type"] == "AOTC")
    # floor(250000 * 999990 / 1000000) = 249997; floor(249997 * 40/100) = 99998
    assert aotc["allowed_amount_cents"] == 249_997
    assert aotc["refundable_cents"] == 99_998


def test_aotc_rounding_order_balance_due(api):
    """PRD §3.5: "The bracket tax is first reduced by the nonrefundable total but not
    below 0, and then the refundable total is subtracted from that floored result."
    PRD §3.5: "`balance_due_cents` is `tax_after_credits_cents` minus
    `total_payments_cents`: a positive figure is owed by the filer, a negative figure
    is a refund owed to the filer."

    Design: Difficulty/combinatorial_formula/aotc_two_step_floor_rounding_order_mode_b
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=8_000_010,
                                                  federal_withholding_cents=1_000_000), h), 201)
    validate_success(api.create_dependent(
        ret["id"], create_dependent_payload(full_name="Kid", age_years=19,
                                            is_student=True), h), 201)
    validate_success(api.create_credit_claim(
        ret["id"], create_credit_claim_payload("AOTC", claimed_amount_cents=250_000), h), 201)
    computed = validate_success(api.compute_tax_return(ret["id"], h), 200)
    assert computed["balance_due_cents"] == -314_695


# =====================================================================
# boundary_precision_check / aotc_phaseout_start_inclusive_boundary
# =====================================================================

def test_aotc_at_phaseout_start_full_allowed(api):
    """PRD §3.5: "if `agi_cents` is at most eight million cents ($80,000.00), the
    allowed amount is the full base with no proration; if `agi_cents` is at least nine
    million cents ($90,000.00), the allowed amount is 0; otherwise the allowed amount is
    the base multiplied by the quantity (nine million cents minus `agi_cents`) divided
    by (nine million cents minus eight million cents), with the result rounded down to
    the nearest cent."
    PRD §3.5: "The AOTC's refundable portion is then forty percent of that
    already-floored allowed amount, again rounded down to the nearest cent — the
    rounding order is pinned so that the refundable portion is computed from the floored
    allowed amount, not from the unfloored base."

    Design: Difficulty/boundary_precision_check/aotc_phaseout_start_inclusive_boundary
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=8_000_000,
                                                  federal_withholding_cents=0), h), 201)
    validate_success(api.create_dependent(
        ret["id"], create_dependent_payload(full_name="Kid", age_years=19,
                                            is_student=True), h), 201)
    validate_success(api.create_credit_claim(
        ret["id"], create_credit_claim_payload("AOTC", claimed_amount_cents=250_000), h), 201)
    validate_success(api.compute_tax_return(ret["id"], h), 200)
    claims = validate_success(api.list_credit_claims(ret["id"], h), 200)
    aotc = next(c for c in claims if c["credit_type"] == "AOTC")
    # agi == phaseout start (8,000,000) uses the no-proration branch
    assert aotc["allowed_amount_cents"] == 250_000
    assert aotc["refundable_cents"] == 100_000


def test_aotc_one_cent_past_phaseout_start_prorates(api):
    """PRD §3.5: "otherwise the allowed amount is the base multiplied by the quantity
    (nine million cents minus `agi_cents`) divided by (nine million cents minus eight
    million cents), with the result rounded down to the nearest cent."

    Design: Difficulty/boundary_precision_check/aotc_phaseout_start_inclusive_boundary
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=8_000_001,
                                                  federal_withholding_cents=0), h), 201)
    validate_success(api.create_dependent(
        ret["id"], create_dependent_payload(full_name="Kid", age_years=19,
                                            is_student=True), h), 201)
    validate_success(api.create_credit_claim(
        ret["id"], create_credit_claim_payload("AOTC", claimed_amount_cents=250_000), h), 201)
    validate_success(api.compute_tax_return(ret["id"], h), 200)
    claims = validate_success(api.list_credit_claims(ret["id"], h), 200)
    aotc = next(c for c in claims if c["credit_type"] == "AOTC")
    # floor(250000 * (9,000,000 - 8,000,001) / 1,000,000) = floor(249999.75) = 249999
    assert aotc["allowed_amount_cents"] == 249_999


# =====================================================================
# boundary_precision_check / capital_loss_limit_exact_boundary
# =====================================================================

def test_capital_loss_at_limit_preserved(api):
    """PRD §3.5: "If it is negative, the net loss is limited so it is no more negative
    than negative three hundred thousand cents — that is, a net loss is capped at a
    deductible maximum of three thousand dollars, and any loss beyond that is not
    deducted."

    Design: Difficulty/boundary_precision_check/capital_loss_limit_exact_boundary
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=5_000_000,
                                                  federal_withholding_cents=0), h), 201)
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(
            doc_type="1099_B", payer_name="Broker", box_amount_cents=0,
            proceeds_cents=0, cost_basis_cents=300_000, holding_long_term=True), h), 201)
    computed = validate_success(api.compute_tax_return(ret["id"], h), 200)
    scheds = validate_success(api.list_schedules(ret["id"], h), 200)
    sched_d = next(s for s in scheds if s["schedule_type"] == "D")
    # raw net -300,000 == limit -> preserved exactly
    assert sched_d["net_amount_cents"] == -300_000
    # total income = wages 5,000,000 + sched D -300,000 = 4,700,000
    assert computed["total_income_cents"] == 4_700_000


def test_capital_loss_one_cent_past_limit_capped(api):
    """PRD §3.5: "If it is negative, the net loss is limited so it is no more negative
    than negative three hundred thousand cents — that is, a net loss is capped at a
    deductible maximum of three thousand dollars, and any loss beyond that is not
    deducted."

    Design: Difficulty/boundary_precision_check/capital_loss_limit_exact_boundary
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=5_000_000,
                                                  federal_withholding_cents=0), h), 201)
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(
            doc_type="1099_B", payer_name="Broker", box_amount_cents=0,
            proceeds_cents=0, cost_basis_cents=300_001, holding_long_term=True), h), 201)
    computed = validate_success(api.compute_tax_return(ret["id"], h), 200)
    scheds = validate_success(api.list_schedules(ret["id"], h), 200)
    sched_d = next(s for s in scheds if s["schedule_type"] == "D")
    # raw net -300,001 capped at -300,000
    assert sched_d["net_amount_cents"] == -300_000
    assert computed["total_income_cents"] == 4_700_000


# =====================================================================
# Corner B / calculations
# =====================================================================

def test_standard_deduction_married_joint_correct(api):
    """PRD §3.5: "the deduction is the standard-deduction figure for the return's
    `filing_status`: fifteen hundred thousand cents ($15,000.00) for `SINGLE`, three
    million cents ($30,000.00) for `MARRIED_JOINT`, fifteen hundred thousand cents
    ($15,000.00) for `MARRIED_SEPARATE`, and two million two hundred fifty thousand
    cents ($22,500.00) for `HEAD_OF_HOUSEHOLD`; under the standard method, Schedule A is
    ignored even if present."
    PRD §3.5: "For `MARRIED_JOINT`, the first tier is 10% up to 2,320,000 cents, the
    second tier is 12% on the portion above 2,320,000 and up to 9,430,000 cents, and the
    third tier is 22% above 9,430,000 cents."

    Design: Corner/calculations/standard_deduction_married_joint_correct
    """
    tp = _new_taxpayer(api, filing_status="MARRIED_JOINT")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="MARRIED_JOINT",
                       deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=8_000_000), h), 201)
    computed = validate_success(api.compute_tax_return(ret["id"], h), 200)
    assert computed["taxable_income_cents"] == 5_000_000
    assert computed["tax_before_credits_cents"] == 553_600


def test_capital_gain_positive_added_to_income(api):
    """PRD §3.5: "the raw net is the sum of each document's `proceeds_cents` minus its
    `cost_basis_cents`, combining short-term and long-term lots together. If that raw
    net is zero or positive, Schedule D's `net_amount_cents` is that raw net."
    PRD §3.5: "To these are added the net of Schedule C, the net of Schedule E, and the
    net of Schedule D, each taken as 0 if that schedule does not exist."

    Design: Corner/calculations/capital_gain_positive_added_to_income
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=4_000_000), h), 201)
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(
            doc_type="1099_B", payer_name="Broker", box_amount_cents=0,
            proceeds_cents=5_000_000, cost_basis_cents=2_000_000,
            holding_long_term=True), h), 201)
    computed = validate_success(api.compute_tax_return(ret["id"], h), 200)
    scheds = validate_success(api.list_schedules(ret["id"], h), 200)
    sched_d = next(s for s in scheds if s["schedule_type"] == "D")
    assert sched_d["net_amount_cents"] == 3_000_000
    assert computed["total_income_cents"] == 7_000_000


def test_ctc_capped_by_qualifying_children(api):
    """PRD §3.5: "count the dependents whose `age_years` is less than 17 (their
    `qualifies_ctc` is true); the allowed amount is the smaller of the CTC claim's
    `claimed_amount_cents` and that child count multiplied by two hundred thousand cents
    ($2,000.00 per qualifying child). The CTC is treated as nonrefundable, so its
    `refundable_cents` is 0."

    Design: Corner/calculations/ctc_capped_by_qualifying_children
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=9_000_000,
                                                  federal_withholding_cents=1_000_000), h), 201)
    validate_success(api.create_dependent(
        ret["id"], create_dependent_payload(full_name="K1", age_years=10), h), 201)
    validate_success(api.create_dependent(
        ret["id"], create_dependent_payload(full_name="K2", age_years=12), h), 201)
    validate_success(api.create_credit_claim(
        ret["id"], create_credit_claim_payload("CTC", claimed_amount_cents=700_000), h), 201)
    validate_success(api.compute_tax_return(ret["id"], h), 200)
    claims = validate_success(api.list_credit_claims(ret["id"], h), 200)
    ctc = next(c for c in claims if c["credit_type"] == "CTC")
    assert ctc["allowed_amount_cents"] == 400_000
    assert ctc["refundable_cents"] == 0


def test_eitc_phaseout_reduces_allowed(api):
    """PRD §3.5: "the EITC maximum is 60,000 cents for zero such children, 396,000 cents
    for one, and 655,000 cents for two or more. The capped figure is the smaller of the
    EITC claim's `claimed_amount_cents` and that band maximum. Then compute the excess
    of `agi_cents` over two million cents ($20,000.00), taking 0 if AGI is at or below
    that threshold; reduce the capped figure by twenty-one percent of that excess
    rounded down to the nearest cent, and floor the result at 0. The EITC allowed amount
    is fully refundable, so its `refundable_cents` equals its `allowed_amount_cents`."

    Design: Corner/calculations/eitc_phaseout_reduces_allowed
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=3_000_000,
                                                  federal_withholding_cents=100_000), h), 201)
    validate_success(api.create_dependent(
        ret["id"], create_dependent_payload(full_name="K", age_years=10), h), 201)
    validate_success(api.create_credit_claim(
        ret["id"], create_credit_claim_payload("EITC", claimed_amount_cents=500_000), h), 201)
    validate_success(api.create_credit_claim(
        ret["id"], create_credit_claim_payload("CTC", claimed_amount_cents=200_000), h), 201)
    computed = validate_success(api.compute_tax_return(ret["id"], h), 200)
    claims = validate_success(api.list_credit_claims(ret["id"], h), 200)
    eitc = next(c for c in claims if c["credit_type"] == "EITC")
    # 396,000 - floor(1,000,000*21/100)=210,000 -> 186,000 fully refundable
    assert eitc["allowed_amount_cents"] == 186_000
    assert eitc["refundable_cents"] == 186_000
    assert computed["balance_due_cents"] == -286_000


def test_aotc_above_phaseout_end_zero(api):
    """PRD §3.5: "if `agi_cents` is at most eight million cents ($80,000.00), the
    allowed amount is the full base with no proration; if `agi_cents` is at least nine
    million cents ($90,000.00), the allowed amount is 0; otherwise the allowed amount is
    the base multiplied by the quantity (nine million cents minus `agi_cents`) divided
    by (nine million cents minus eight million cents), with the result rounded down to
    the nearest cent."

    Design: Corner/calculations/aotc_above_phaseout_end_zero
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=9_000_000), h), 201)
    validate_success(api.create_dependent(
        ret["id"], create_dependent_payload(full_name="Stu", age_years=19,
                                            is_student=True), h), 201)
    validate_success(api.create_credit_claim(
        ret["id"], create_credit_claim_payload("AOTC", claimed_amount_cents=250_000), h), 201)
    validate_success(api.compute_tax_return(ret["id"], h), 200)
    claims = validate_success(api.list_credit_claims(ret["id"], h), 200)
    aotc = next(c for c in claims if c["credit_type"] == "AOTC")
    assert aotc["allowed_amount_cents"] == 0
    assert aotc["refundable_cents"] == 0
