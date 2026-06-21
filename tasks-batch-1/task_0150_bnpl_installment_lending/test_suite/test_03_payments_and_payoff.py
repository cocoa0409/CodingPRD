"""Payment allocation (oldest-due-first), pay-off cascades, autopay disable on
payoff, and borrower-credit conservation.

Covers queue A transitive_cascade (payment + return cascades) and
compensating_invariant (borrower credit), plus queue B corner instances on
overpayment, partial allocation, and the autopay sweep.
"""
from test_helpers import (
    validate_success,
    setup_activated_loan,
    setup_autopay_loan,
    get_loan,
    get_borrower,
    list_installments,
    installments_by_sequence,
    find_installment,
    make_payment,
    make_servicer_headers,
    make_borrower_headers,
    make_merchant_headers,
    create_payment_payload,
    create_return_payload,
    create_autopay_mandate_payload,
    assert_borrower_credit_conserved,
)

SERVICER = make_servicer_headers()


def test_payment_cascades_installments_paid_then_loan_paid_off(api):
    """PRD §3.5: "once an installment's amount_paid_cents reaches its amount_due_cents
    the installment transitions to PAID."
    PRD §3.5: "If a payment drives remaining_principal_cents to zero and leaves no
    installment in SCHEDULED or LATE, the loan bubbles up from ACTIVE to PAID_OFF".

    Design: Difficulty/transitive_cascade/payment_cascades_installment_paid_then_payoff_depth2
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4")
    payment = make_payment(ctx["loan"]["id"], ctx["borrower"]["id"], 100_000)
    assert payment["unapplied_cents"] == 0

    loan = get_loan(ctx["loan"]["id"])
    assert loan["remaining_principal_cents"] == 0
    assert loan["status"] == "PAID_OFF"

    installments = list_installments(loan["id"])
    assert all(i["status"] == "PAID" for i in installments), "all 4 installments PAID"


def test_payment_payoff_forces_delinquency_current(api):
    """PRD §3.5: "If a payment drives remaining_principal_cents to zero and leaves no
    installment in SCHEDULED or LATE, the loan bubbles up from ACTIVE to PAID_OFF; on
    pay-off the delinquency_status is forced to CURRENT".

    Design: Difficulty/transitive_cascade/payment_cascades_installment_paid_then_payoff_depth2
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    make_payment(ctx["loan"]["id"], ctx["borrower"]["id"], 100_000)
    loan = get_loan(ctx["loan"]["id"])
    assert loan["status"] == "PAID_OFF"
    assert loan["delinquency_status"] == "CURRENT"


def test_return_cascade_payoff_disables_autopay_depth3(api):
    """PRD §3.9: "if the reallocation drives remaining_principal_cents to zero and
    leaves no installment in SCHEDULED or LATE, the loan bubbles up to PAID_OFF."
    PRD §3.5: "on pay-off the delinquency_status is forced to CURRENT, any ENABLED
    autopay mandate on the loan is moved to DISABLED".

    Design: Difficulty/transitive_cascade/return_cascades_installment_payoff_autopay_disable_depth3
    """
    ctx = setup_autopay_loan(cart_amount_cents=100_000)
    mandate = ctx["mandate"]
    assert mandate["status"] == "ENABLED"

    # Full 100000 return drives remaining principal to 0 and cancels all installments.
    resp = api.create_return(
        create_return_payload(ctx["loan"]["id"], 100_000),
        make_merchant_headers(ctx["merchant"]["id"]),
    )
    validate_success(resp, 201)

    loan = get_loan(ctx["loan"]["id"])
    assert loan["remaining_principal_cents"] == 0
    assert loan["status"] == "PAID_OFF"

    mandate_after = validate_success(
        api.get_autopay_mandate(mandate["id"], SERVICER), 200
    )
    assert mandate_after["status"] == "DISABLED", "payoff disables the ENABLED mandate"


def test_return_cascade_cancels_all_installments(api):
    """PRD §3.9: "an installment whose outstanding is fully covered is moved to
    CANCELLED." PRD §3.9: "if the reallocation drives remaining_principal_cents to zero
    and leaves no installment in SCHEDULED or LATE, the loan bubbles up to PAID_OFF."

    Design: Difficulty/transitive_cascade/return_cascades_installment_payoff_autopay_disable_depth3
    """
    ctx = setup_autopay_loan(cart_amount_cents=100_000)
    resp = api.create_return(
        create_return_payload(ctx["loan"]["id"], 100_000),
        make_merchant_headers(ctx["merchant"]["id"]),
    )
    validate_success(resp, 201)
    installments = list_installments(ctx["loan"]["id"])
    assert all(i["status"] == "CANCELLED" for i in installments), (
        "full return cancels every unpaid installment"
    )
    assert get_loan(ctx["loan"]["id"])["status"] == "PAID_OFF"


def test_borrower_credit_conserved_across_activate_and_payoff(api):
    """PRD §2.5: "A borrower's outstanding_principal_cents is the sum of
    remaining_principal_cents over that borrower's loans whose status is ACTIVE or
    DELINQUENT, and its available_credit_cents is eligible_credit_limit_cents minus
    outstanding_principal_cents, never allowed below zero."

    Design: Difficulty/compensating_invariant/borrower_credit_conserved_across_activate_and_payoff
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4")
    borrower_id = ctx["borrower"]["id"]

    after_activate = get_borrower(borrower_id)
    assert after_activate["available_credit_cents"] == 400_000
    assert after_activate["outstanding_principal_cents"] == 100_000
    assert_borrower_credit_conserved(after_activate)

    make_payment(ctx["loan"]["id"], borrower_id, 100_000)

    after_payoff = get_borrower(borrower_id)
    assert after_payoff["available_credit_cents"] == 500_000
    assert after_payoff["outstanding_principal_cents"] == 0
    assert_borrower_credit_conserved(after_payoff)


def test_borrower_credit_never_below_zero_and_sum_holds_after_activate(api):
    """PRD §2.5: "its available_credit_cents is eligible_credit_limit_cents minus
    outstanding_principal_cents, never allowed below zero."

    Design: Difficulty/compensating_invariant/borrower_credit_conserved_across_activate_and_payoff
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4")
    after = get_borrower(ctx["borrower"]["id"])
    # eligible 500000; outstanding 100000 -> available 400000; sum conserved.
    assert after["eligible_credit_limit_cents"] == 500_000
    assert (after["available_credit_cents"] + after["outstanding_principal_cents"]
            == after["eligible_credit_limit_cents"])
    assert after["available_credit_cents"] >= 0


def test_overpayment_reports_unapplied_cents(api):
    """PRD §3.5: "Any payment money left after every open installment is exhausted is
    recorded as the payment's unapplied_cents — an overpayment that no open installment
    could absorb, refunded to the borrower's balance."

    Design: Corner/calculations/payment_overpayment_reports_unapplied
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4")
    resp = api.create_payment(
        create_payment_payload(ctx["loan"]["id"], 130_000, source="MANUAL"),
        make_borrower_headers(ctx["borrower"]["id"]),
    )
    payment = validate_success(resp, 201)
    assert payment["unapplied_cents"] == 30_000

    loan = get_loan(ctx["loan"]["id"])
    assert loan["status"] == "PAID_OFF"


def test_partial_payment_oldest_first_allocation(api):
    """PRD §3.5: "The payment is allocated oldest-due-first: the loan's installments
    whose status is SCHEDULED or LATE are ordered by ascending sequence_no".
    PRD §3.5: "the amount applied is the lesser of the payment money remaining and
    that need".

    Design: Corner/calculations/partial_payment_oldest_first_marks_first_installment_paid
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4")
    make_payment(ctx["loan"]["id"], ctx["borrower"]["id"], 30_000)

    installments = installments_by_sequence(list_installments(ctx["loan"]["id"]))
    inst1 = find_installment(installments, 1)
    inst2 = find_installment(installments, 2)
    assert inst1["status"] == "PAID" and inst1["amount_paid_cents"] == 25_000
    assert inst2["status"] == "SCHEDULED" and inst2["amount_paid_cents"] == 5_000

    loan = get_loan(ctx["loan"]["id"])
    assert loan["remaining_principal_cents"] == 75_000


def test_autopay_sweep_charges_due_installment(api):
    """PRD §3.7: "A Servicer runs the autopay sweep, an operator capability that charges
    every ENABLED autopay mandate whose loan has an installment due on or before now,
    oldest-due-first, for the amount of the next due installment. The sweep returns the
    count of mandates charged as charged_count".

    Design: Corner/endpoints/autopay_sweep_charges_due_installment
    """
    ctx = setup_autopay_loan(cart_amount_cents=100_000, clock_iso="2026-01-01T00:00:00Z")
    # Advance to 2026-01-02 so inst#1 (due 2026-01-01) is due on or before now.
    validate_success(api.set_clock({"to_iso8601": "2026-01-02T00:00:00Z"}, SERVICER), 200)

    sweep = validate_success(api.run_autopay_sweep(SERVICER), 200)
    assert sweep["charged_count"] == 1

    installments = installments_by_sequence(list_installments(ctx["loan"]["id"]))
    inst1 = find_installment(installments, 1)
    assert inst1["status"] == "PAID" and inst1["amount_paid_cents"] == 25_000

    loan = get_loan(ctx["loan"]["id"])
    assert loan["remaining_principal_cents"] == 75_000
