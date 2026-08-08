"""Construction-permit fee calculations, payment, and refund conservation.

Covers the permit-fee dual variant, the non-linear combinatorial fee, the
sample panel fee, immediate pay visibility, and the pay/deny money-conservation
invariant.
"""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, factories as f, fixtures as fx,
)

OFFICER = TEST_USERS["health_officer_headers"]
LAB = TEST_USERS["lab_analyst_headers"]


# --------------------------------------------------------------------------
# dual_variant_calc / permit_fee_estimate_vs_final_reconcile
# --------------------------------------------------------------------------
def test_permit_fee_estimate_and_final_diverge_and_reconcile(api):
    """PRD §3.3: "The system recomputes the permit fee final variant from the
    actual drilled depth — the identical tiered formula from §3.2, but now keyed
    on total_depth_ft rather than the proposed depth — and stores it in
    fee_final_cents".
    PRD §3.3: "The paying applicant's net_fees_paid_cents is reconciled by the
    delta between final and estimate so the ledger reflects the true charge."

    Design: Difficulty/dual_variant_calc/permit_fee_estimate_vs_final_reconcile
    """
    ctx = fx.setup_active_well(
        api, aquifer_sensitivity="HIGH", intended_use="DOMESTIC",
        proposed_depth_ft=250, total_depth_ft=320)
    assert ctx.permit["fee_estimate_cents"] == 35000
    assert ctx.permit["fee_final_cents"] == 50000
    applicant = get_success_data(api.get_applicant(ctx.applicant_id, OFFICER))
    assert applicant["net_fees_paid_cents"] == 50000


def test_permit_final_fee_replaces_charged_estimate(api):
    """PRD §3.3: "it then sets fee_charged_cents to that final amount, replacing
    the previously charged estimate."

    Design: Difficulty/dual_variant_calc/permit_fee_estimate_vs_final_reconcile
    """
    ctx = fx.setup_active_well(
        api, aquifer_sensitivity="HIGH", intended_use="DOMESTIC",
        proposed_depth_ft=250, total_depth_ft=320)
    assert ctx.permit["fee_estimate_cents"] == 35000
    assert ctx.permit["fee_charged_cents"] == 50000


# --------------------------------------------------------------------------
# combinatorial_formula / permit_fee_nonlinear_multi_input_mode_a
# --------------------------------------------------------------------------
def test_permit_fee_irrigation_moderate_expedite_composition(api):
    """PRD §3.2: "this depth base is multiplied by an intended-use multiplier
    drawn from the well: 1.0 for DOMESTIC, 1.2 for IRRIGATION, and 1.5 for
    LIVESTOCK; this product is rounded half-up to a whole number of cents."
    PRD §3.2: "the system adds an aquifer sensitivity surcharge — 10000 cents
    for a HIGH aquifer, 5000 cents for a MODERATE aquifer, and nothing for a LOW
    aquifer — and then, only if the permit is expedited, a further 20000-cent
    expedite fee."

    Design: Difficulty/combinatorial_formula/permit_fee_nonlinear_multi_input_mode_a
    """
    ctx = fx.setup_submitted_permit(
        api, aquifer_sensitivity="MODERATE", intended_use="IRRIGATION",
        proposed_depth_ft=250, expedite=True)
    # depth tier2 25000 * IRRIGATION 1.2 = 30000; + MODERATE 5000 + expedite 20000 = 55000
    assert ctx.permit["fee_estimate_cents"] == 55000


def test_permit_fee_domestic_high_no_expedite_composition(api):
    """PRD §3.2: "a depth of at most 100 feet yields a base of 15000 cents; a
    depth greater than 100 but at most 300 feet yields 25000 cents; a depth
    greater than 300 feet yields 40000 cents."
    PRD §3.2: "the system adds an aquifer sensitivity surcharge — 10000 cents
    for a HIGH aquifer, 5000 cents for a MODERATE aquifer, and nothing for a LOW
    aquifer".

    Design: Difficulty/combinatorial_formula/permit_fee_nonlinear_multi_input_mode_a
    """
    ctx = fx.setup_submitted_permit(
        api, aquifer_sensitivity="HIGH", intended_use="DOMESTIC",
        proposed_depth_ft=250, expedite=False)
    # depth tier2 25000 * DOMESTIC 1.0 = 25000; + HIGH 10000 + no expedite = 35000
    assert ctx.permit["fee_estimate_cents"] == 35000


# --------------------------------------------------------------------------
# combinatorial_formula / panel_fee_round_per_analyte_then_sum_mode_b
# --------------------------------------------------------------------------
def test_panel_fee_rounds_each_analyte_line_then_sums(api):
    """PRD §3.4: "the system multiplies each requested analyte's base by 1.075,
    rounds that single line half-up to a whole cent, and only after every line
    is individually rounded does it sum the rounded lines into panel_fee_cents."

    Design: Difficulty/combinatorial_formula/panel_fee_round_per_analyte_then_sum_mode_b
    """
    ctx = fx.setup_active_well(api)
    sample = fx.submit_sample(
        api, ctx.well_id, ctx.applicant_id,
        requested_analytes=["BACTERIA", "NITRATE", "LEAD"])
    # 3225 + 2688 + 4838 = 10751 (round-per-line), NOT 10750 (sum-then-round)
    assert sample["panel_fee_cents"] == 10751


def test_panel_fee_single_analyte_line_rounds_half_up(api):
    """PRD §3.4: "Each requested analyte has a base price — 3000 cents for
    BACTERIA, 2500 cents for NITRATE, and 4500 cents for LEAD — and each base
    price is multiplied by a regional factor of 1.075."

    Design: Difficulty/combinatorial_formula/panel_fee_round_per_analyte_then_sum_mode_b
    """
    ctx = fx.setup_active_well(api)
    sample = fx.submit_sample(
        api, ctx.well_id, ctx.applicant_id, requested_analytes=["NITRATE"])
    # 2500 * 1.075 = 2687.5 -> round half up -> 2688
    assert sample["panel_fee_cents"] == 2688


# --------------------------------------------------------------------------
# consistency / pay_effect_immediately_visible
# --------------------------------------------------------------------------
def test_pay_permit_returns_paid_and_charged_immediately(api):
    """PRD §3.2: "Paying a permit is an applicant action available on a submitted
    permit: it sets fee_paid to true, copies fee_estimate_cents into
    fee_charged_cents, and triggers a recomputation of the paying applicant's
    net_fees_paid_cents."

    Design: Corner/consistency/pay_effect_immediately_visible
    """
    ctx = fx.setup_submitted_permit(
        api, aquifer_sensitivity="HIGH", intended_use="DOMESTIC", proposed_depth_ft=250)
    resp = api.pay_permit(ctx.permit_id, ctx.applicant_headers)
    data = validate_success(resp, 200)
    assert data["fee_paid"] is True
    assert data["fee_charged_cents"] == 35000


# --------------------------------------------------------------------------
# compensating_invariant / pay_then_deny_conserves_net_fees_paid
# --------------------------------------------------------------------------
def test_pay_then_deny_refunds_and_conserves_net_fees(api):
    """PRD §3.2: "Denial moves it from SUBMITTED to DENIED and, if the fee had
    been paid, issues a compensating refund: fee_refunded_cents is set to the
    current fee_charged_cents, and the applicant's net_fees_paid_cents is
    recomputed so the refund is reflected."

    Design: Difficulty/compensating_invariant/pay_then_deny_conserves_net_fees_paid
    """
    ctx = fx.setup_submitted_permit(
        api, aquifer_sensitivity="HIGH", intended_use="DOMESTIC", proposed_depth_ft=250)
    fx.pay_permit(api, ctx.permit_id, ctx.applicant_id)
    resp = api.deny_permit(ctx.permit_id, OFFICER)
    permit = validate_success(resp, 200)
    assert permit["status"] == "DENIED"
    assert permit["fee_refunded_cents"] == 35000
    applicant = get_success_data(api.get_applicant(ctx.applicant_id, OFFICER))
    assert applicant["net_fees_paid_cents"] == 0


def test_deny_unpaid_permit_refunds_nothing(api):
    """PRD §3.2: "the applicant's net_fees_paid_cents is recomputed so the
    refund is reflected. Denying an unpaid permit refunds nothing."

    Design: Difficulty/compensating_invariant/pay_then_deny_conserves_net_fees_paid
    """
    ctx = fx.setup_submitted_permit(
        api, aquifer_sensitivity="HIGH", intended_use="DOMESTIC", proposed_depth_ft=250)
    resp = api.deny_permit(ctx.permit_id, OFFICER)
    permit = validate_success(resp, 200)
    assert permit["status"] == "DENIED"
    assert permit["fee_refunded_cents"] == 0
    applicant = get_success_data(api.get_applicant(ctx.applicant_id, OFFICER))
    assert applicant["net_fees_paid_cents"] == 0
