"""Appeals resolution and refund claims: the dual-variant refund interest anchor,
the reduced-decision cycle, abatement ledger reversal, and the overpayment guard."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_refund_claim, assert_appeal,
    TEST_USERS, make_operator_headers,
    single_line, setup_operator_with_property,
    create_and_file_return, create_cleared_remittance, amend_return, set_clock,
    create_refund_claim, get_operator,
    setup_issued_assessment, submit_appeal, begin_review, request_info,
    provide_info, decide_appeal, create_active_operator,
)

ADMIN = TEST_USERS["taxadmin_headers"]


# ============================================================
# Difficulty: dual_variant_calc/refund_interest_statutory_vs_audit
# ============================================================
def _setup_two_approved_refunds(api):
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    ret = create_and_file_return(api, op["id"], single_line(prop["id"], 1000000))  # tax 120000
    create_cleared_remittance(api, ret["id"], 120000)  # balance 0
    amend_return(api, ret["id"], op["id"], single_line(prop["id"], 500000))  # tax 60000 -> balance -60000
    set_clock(api, "2026-06-01T00:00:00Z")
    rc_over = create_refund_claim(api, op["id"], "OVERPAYMENT", 50000, "2026-02-01T00:00:00Z")
    rc_audit = create_refund_claim(api, op["id"], "AUDIT_ADJUSTMENT", 50000, "2026-06-01T00:00:00Z")
    set_clock(api, "2026-08-01T00:00:00Z")
    rc_over = validate_success(api.approve_refund(rc_over["id"], ADMIN), 200)
    rc_audit = validate_success(api.approve_refund(rc_audit["id"], ADMIN), 200)
    return rc_over, rc_audit


def test_overpayment_variant_anchors_at_overpayment_date(api):
    """PRD 3.9: "The anchor depends on the reason: for a statutory `OVERPAYMENT` the
    anchor is the earlier `overpayment_date`, yielding more months and more interest".
    PRD 3.9: "The interest is `principal_cents` multiplied by the jurisdiction's
    monthly refund rate (`refund_interest_monthly_bps` divided by 10,000) and by that
    month count, rounded half-up to whole cents, and `total_refund_cents` is
    `principal_cents` plus that `interest_cents`."

    Design: Difficulty/dual_variant_calc/refund_interest_statutory_vs_audit
    """
    rc_over, _ = _setup_two_approved_refunds(api)
    assert_refund_claim(rc_over)
    # anchor 2026-02-01 -> 6 months; 50000 * 0.005 * 6 = 1500.
    assert rc_over["interest_cents"] == 1500
    assert rc_over["total_refund_cents"] == 51500


def test_audit_adjustment_variant_anchors_at_created_at(api):
    """PRD 3.9: "for an `AUDIT_ADJUSTMENT` overpayment arising from an abated or
    reduced assessment the anchor is the claim's own `created_at`, which is later and
    yields fewer months and less interest."

    Design: Difficulty/dual_variant_calc/refund_interest_statutory_vs_audit
    """
    _, rc_audit = _setup_two_approved_refunds(api)
    assert_refund_claim(rc_audit)
    # anchor created_at 2026-06-01 -> 2 months; 50000 * 0.005 * 2 = 500.
    assert rc_audit["interest_cents"] == 500
    assert rc_audit["total_refund_cents"] == 50500


# ---- Corner: state_machines/appeal_full_cycle_reduced_decision ----
def test_appeal_cycle_then_reduced_decision(api):
    """PRD 3.9: "The operator provides the requested information, moving the appeal
    back to `UNDER_REVIEW` and incrementing its `round_count` by one — this is the
    cyclic negotiation loop, and `round_count` records how many information cycles
    have completed."
    PRD 3.9: "A `REDUCED` decision drives the assessment to `FINAL` at the reduced
    figure and posts an `ADJUSTMENT` ledger entry for the negative of the difference
    between `total_assessed_cents` and `reduced_total_cents`, crediting back only the
    reduced portion."

    Design: Corner/state_machines/appeal_full_cycle_reduced_decision
    """
    bundle = setup_issued_assessment(api, gross=1000000, audited_taxable_cents=6000000,
                                     classification="NEGLIGENCE", pay_full=True)
    op, asmt = bundle["operator"], bundle["assessment"]
    ap = submit_appeal(api, asmt["id"], op["id"], grounds="overstated")
    begin_review(api, ap["id"])
    request_info(api, ap["id"])
    provide_info(api, ap["id"], op["id"])
    decided = decide_appeal(api, ap["id"], "REDUCED", reduced_total_cents=400000)
    assert_appeal(decided)
    assert decided["status"] == "DECIDED"
    assert decided["round_count"] == 1
    assert validate_success(api.get_assessment(asmt["id"], ADMIN), 200)["status"] == "FINAL"


# ---- Corner: cross_cutting_complexity_layers/assessment_abated_reverses_ledger_on_appeal ----
def test_appeal_abated_reverses_ledger_and_restores_active(api):
    """PRD 3.9: "An `ABATED` decision drives the assessment to `ABATED` and posts an
    `ABATEMENT` ledger entry for the negative of `total_assessed_cents`, reversing the
    original assessment debit and conserving the ledger."
    PRD 2.7: "A `DELINQUENT` operator whose balance returns to zero or below (after a
    cleared remittance, a paid refund, or an abatement) moves back to `ACTIVE`".

    Design: Corner/cross_cutting_complexity_layers/assessment_abated_reverses_ledger_on_appeal
    """
    bundle = setup_issued_assessment(api, gross=1000000, audited_taxable_cents=6000000,
                                     classification="NEGLIGENCE", pay_full=True)
    op, asmt = bundle["operator"], bundle["assessment"]
    ap = submit_appeal(api, asmt["id"], op["id"], grounds="not liable")
    begin_review(api, ap["id"])
    decide_appeal(api, ap["id"], "ABATED")
    assert validate_success(api.get_assessment(asmt["id"], ADMIN), 200)["status"] == "ABATED"
    after_op = get_operator(api, op["id"])
    assert after_op["account_balance_cents"] == 0
    assert after_op["status"] == "ACTIVE"


# ---- Corner: validations/refund_exceeds_overpayment_rejected ----
def test_refund_exceeding_credit_rejected(api):
    """PRD 3.9: "the principal must not exceed the magnitude of the operator's
    negative (credit) balance; a principal larger than the held overpayment credit is
    rejected with `ERR_REFUND_EXCEEDS_OVERPAYMENT`."

    Design: Corner/validations/refund_exceeds_overpayment_rejected
    """
    op = create_active_operator(api)  # balance 0, no credit
    rc = create_refund_claim(api, op["id"], "OVERPAYMENT", 100000, "2026-04-01T00:00:00Z")
    resp = api.approve_refund(rc["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_OVERPAYMENT.value)
    assert validate_success(api.get_refund_claim(rc["id"], ADMIN), 200)["status"] == "REQUESTED"
