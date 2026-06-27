"""Refund amount divergence and compensating-action invariants (PRD §3.11)."""
from test_helpers import (
    validate_success, validate_paginated,
    setup_refund_approved, setup_financing_active,
    manufacture_and_ship_first_steps, open_refund,
    api_client, TEST_USERS,
)

BILLING = TEST_USERS["billing_headers"]
MFG = TEST_USERS["manufacturing_headers"]


def test_patient_cancel_refund_prorates_consumed_value_and_withholds_fee(api):
    """PRD §3.11 Refund amount: "When the reason is `PATIENT_CANCEL`, the refund
    is pro-rated: let the shipped fraction be the count of first-run steps (those
    with a null `supersedes_step_id`) currently `SHIPPED` divided by the count of
    non-`VOID` first-run steps ...; the consumed value is the case's
    `total_contracted_cents` multiplied by that shipped fraction, rounded half-up
    to whole cents; the `restocking_fee_cents` is a flat 7500 cents; and
    `computed_refund_cents` is the `amount_collected_cents` minus the consumed
    value minus the restocking fee, floored at 0".

    Collected 340000, total 340000, 20 first-run steps with 5 SHIPPED:
    consumed = round(340000 * 5/20) = 85000; refund = 340000-85000-7500 = 247500.

    Design: Difficulty/dual_variant_calc/refund_amount_eligibility_vs_patient_cancel_diverge
    """
    ctx = setup_refund_approved(
        reason="PATIENT_CANCEL", proposed_step_count=20, list_price_cents=400000,
        discount_code="WELCOME15", down_payment_cents=340000, shipped_steps=5,
    )
    assert ctx["case"]["total_contracted_cents"] == 340000
    assert ctx["case"]["amount_collected_cents"] == 340000
    refund = ctx["refund"]
    assert refund["status"] == "APPROVED"
    assert refund["computed_refund_cents"] == 247500, refund["computed_refund_cents"]
    assert refund["restocking_fee_cents"] == 7500, refund["restocking_fee_cents"]


def test_patient_cancel_refund_scales_with_shipped_fraction(api):
    """PRD §3.11 Refund amount: "the consumed value is the case's
    `total_contracted_cents` multiplied by that shipped fraction, rounded half-up
    to whole cents; the `restocking_fee_cents` is a flat 7500 cents; and
    `computed_refund_cents` is the `amount_collected_cents` minus the consumed
    value minus the restocking fee, floored at 0".

    Same collected 340000 / total 340000 / 20 first-run steps but with 10 SHIPPED:
    consumed = round(340000 * 10/20) = 170000; refund = 340000-170000-7500 =
    162500. More shipped value consumed yields a strictly smaller refund.

    Design: Difficulty/dual_variant_calc/refund_amount_eligibility_vs_patient_cancel_diverge
    """
    ctx = setup_refund_approved(
        reason="PATIENT_CANCEL", proposed_step_count=20, list_price_cents=400000,
        discount_code="WELCOME15", down_payment_cents=340000, shipped_steps=10,
    )
    refund = ctx["refund"]
    assert refund["computed_refund_cents"] == 162500, refund["computed_refund_cents"]
    assert refund["restocking_fee_cents"] == 7500, refund["restocking_fee_cents"]


def test_refund_settle_net_cash_position_equals_withheld_fee(api):
    """PRD §3.11 Settlement cascade: "The case's `refund_issued_cents` is set to
    the refund's `computed_refund_cents` and the case's `status` becomes
    `REFUNDED`."
    PRD §3.11 Refund amount: "`computed_refund_cents` is the
    `amount_collected_cents` minus the consumed value minus the restocking fee,
    floored at 0".

    Collected 300000, 0 first-run steps shipped (consumed 0), PATIENT_CANCEL:
    refund_issued = 300000-0-7500 = 292500, so the conserved net cash
    (amount_collected - refund_issued) lands at exactly the 7500 withheld fee.

    Design: Difficulty/compensating_invariant/refund_settle_conserves_net_cash_position
    """
    ctx = setup_refund_approved(
        reason="PATIENT_CANCEL", proposed_step_count=10, list_price_cents=375000,
        down_payment_cents=300000, shipped_steps=0,
    )
    # list 375000, 10 steps LIGHT 0.80 -> 300000 contracted; full down payment.
    assert ctx["case"]["amount_collected_cents"] == 300000
    validate_success(api.settle_refund(ctx["refund"]["id"], BILLING), 200)
    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    assert case["amount_collected_cents"] == 300000, case["amount_collected_cents"]
    assert case["refund_issued_cents"] == 292500, case["refund_issued_cents"]
    assert case["amount_collected_cents"] - case["refund_issued_cents"] == 7500


def test_refund_settle_drives_case_to_refunded(api):
    """PRD §3.11 Settlement cascade: "Settling an approved refund drives the case
    to `REFUNDED` and unwinds the case atomically within the settling request.
    The case's `refund_issued_cents` is set to the refund's
    `computed_refund_cents` and the case's `status` becomes `REFUNDED`."

    The compensating-settle moves the case to the terminal REFUNDED posture and
    writes refund_issued_cents equal to the computed refund (292500 here).

    Design: Difficulty/compensating_invariant/refund_settle_conserves_net_cash_position
    """
    ctx = setup_refund_approved(
        reason="PATIENT_CANCEL", proposed_step_count=10, list_price_cents=375000,
        down_payment_cents=300000, shipped_steps=0,
    )
    # list 375000, 10 steps LIGHT 0.80 -> 300000 contracted; full down payment.
    computed = ctx["refund"]["computed_refund_cents"]
    validate_success(api.settle_refund(ctx["refund"]["id"], BILLING), 200)
    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    assert case["status"] == "REFUNDED", case["status"]
    assert case["refund_issued_cents"] == computed, case["refund_issued_cents"]


def _setup_financing_active_with_posted_first_installment(api):
    """Financing ACTIVE (principal 240000, term 12, apr 0), installment 1 POSTED
    so outstanding is 220000, case then ACTIVE, a PATIENT_CANCEL refund APPROVED.
    """
    ctx = setup_financing_active(
        proposed_step_count=10, term_months=12, down_payment_cents=0, apr_bps=0,
        list_price_cents=300000,
    )
    # list 300000, 10 steps LIGHT 0.80 -> 240000 contracted.
    assert ctx["case"]["total_contracted_cents"] == 240000
    fin_id = ctx["financing"]["id"]
    validate_success(api.post_installment_payment(fin_id, 1, BILLING), 200)
    validate_success(api.activate_case(ctx["case"]["id"], MFG), 200)
    refund = open_refund(ctx["case"]["id"], reason="PATIENT_CANCEL")
    validate_success(api.approve_refund(refund["id"], BILLING), 200)
    ctx["refund"] = refund
    ctx["fin_id"] = fin_id
    return ctx


def test_financing_cancel_preserves_principal_split(api):
    """PRD §2.8: "The ledger fields on a case (`amount_collected_cents`,
    `outstanding_principal_cents` on the financing plan, ...) are maintained by
    these side effects rather than written directly by clients."
    PRD §3.11 Settlement cascade: "If a financing plan exists for the case, its
    `billing_state` is set to `CANCELLED` and all of its `SCHEDULED` (and `LATE`)
    installments are marked `WAIVED`."

    Before cancel: installment 1 POSTED (principal 20000), outstanding 220000,
    financed 240000. The cancel/waive compensation must not alter financed
    (240000) and must leave outstanding at 220000.

    Design: Difficulty/compensating_invariant/financing_cancel_conserves_principal_split
    """
    ctx = _setup_financing_active_with_posted_first_installment(api)
    validate_success(api.settle_refund(ctx["refund"]["id"], BILLING), 200)
    fin = validate_success(api.get_financing_plan(ctx["fin_id"], BILLING), 200)
    assert fin["financed_principal_cents"] == 240000, fin["financed_principal_cents"]
    assert fin["outstanding_principal_cents"] == 220000, fin["outstanding_principal_cents"]
    assert fin["billing_state"] == "CANCELLED", fin["billing_state"]


def test_financing_cancel_waives_unposted_installment(api):
    """PRD §3.11 Settlement cascade: "all of its `SCHEDULED` (and `LATE`)
    installments are marked `WAIVED`."

    With installment 1 already POSTED, the still-SCHEDULED installment 2 is
    waived by the cancel cascade (POSTED installments are not re-touched).

    Design: Difficulty/compensating_invariant/financing_cancel_conserves_principal_split
    """
    ctx = _setup_financing_active_with_posted_first_installment(api)
    validate_success(api.settle_refund(ctx["refund"]["id"], BILLING), 200)
    data, _meta = validate_paginated(api.list_installments(ctx["fin_id"], BILLING))
    by_seq = {i["sequence_no"]: i for i in data}
    assert by_seq[2]["status"] == "WAIVED", by_seq[2]["status"]
    assert by_seq[1]["status"] == "POSTED", by_seq[1]["status"]
