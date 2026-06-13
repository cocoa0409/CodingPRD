"""Payment capture, job closure, and warranty refunds: the money conservation
invariant (capture then warranty refund), the state-before-fiscal validation order on
payment, the overpay / over-refund / expired-warranty guards, and the closure
preconditions.

Difficulty queue: compensating_invariant (money), priority_pair_validation_conflict
(state beats fiscal on payment).
Corner queue: state_machines (close not paid, complete-work no approved quote, cancel
terminal, warranty expired), validations (payment exceeds due, refund exceeds paid).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_technician_headers,
    setup_submitted_quote,
    setup_approved_quote,
    setup_drafted_quote,
    setup_filed_warranty_claim,
    create_job,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_agent_headers"]


# ─── compensating_invariant / money_conserved_on_capture_then_warranty_refund ──
def test_capture_then_warranty_refund_recomputes_net_paid(api):
    """PRD §3.14: "that payment moves from CAPTURED to REFUNDED with its
    refunded_amount_cents set to its full captured_amount_cents; the job's
    net_paid_cents is recomputed; and the job's payment_status moves to the terminal
    REFUNDED."
    PRD §3.12: "the job's net_paid_cents is recomputed: it is the sum of
    captured_amount_cents across the job's payments in CAPTURED status, minus the sum
    of refunded_amount_cents across the job's payments in REFUNDED status (a payment's
    refunded_amount_cents is 0 until it is refunded, at which point it equals that
    payment's captured_amount_cents)."

    Design: Difficulty/compensating_invariant/money_conserved_on_capture_then_warranty_refund
    """
    job, tech, quote, payment, claim = setup_filed_warranty_claim(
        customer_user_id="cust-mon", refund_amount_cents=8000, days_since_close=3
    )
    approved = validate_success(api.approve_warranty_claim(claim["id"], DISPATCHER), 200)
    assert approved["status"] == "APPROVED"
    job_after = validate_success(api.get_service_job(job["id"], DISPATCHER), 200)
    assert job_after["payment_status"] == "REFUNDED"
    # Apply the PRD §3.12 formula literally to the post-refund state: the only payment
    # is now REFUNDED, so the CAPTURED sum is 0 and the REFUNDED sum is 8000, giving
    # net_paid_cents = 0 - 8000 = -8000. The PRD formula restricts the captured sum to
    # CAPTURED-status payments, so a fully refunded payment yields a negative net.
    assert job_after["net_paid_cents"] == -8000, "0 (CAPTURED) - 8000 (REFUNDED) = -8000"


def test_warranty_refund_sets_payment_refunded_amount(api):
    """PRD §3.12: "a payment's refunded_amount_cents is 0 until it is refunded, at which
    point it equals that payment's captured_amount_cents"

    Design: Difficulty/compensating_invariant/money_conserved_on_capture_then_warranty_refund
    """
    job, tech, quote, payment, claim = setup_filed_warranty_claim(
        customer_user_id="cust-mon2", refund_amount_cents=8000, days_since_close=3
    )
    assert payment["refunded_amount_cents"] == 0
    get_success_data(api.approve_warranty_claim(claim["id"], DISPATCHER))
    payments = get_success_data(api.list_payments(job["id"], DISPATCHER))
    refunded = [p for p in payments if p["id"] == payment["id"]][0]
    assert refunded["status"] == "REFUNDED"
    assert refunded["refunded_amount_cents"] == 8000


# ─── priority_pair_validation_conflict / state_beats_fiscal_on_payment ─────────
def test_payment_no_approved_quote_beats_fiscal(api):
    """PRD §2.6: "Fifth, the target resource's state must permit the requested
    transition, else the relevant state-conflict error."
    PRD §3.12: "A capture requires the job to have an APPROVED quote — without one the
    capture is rejected with ERR_NO_APPROVED_QUOTE."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_payment
    """
    # SUBMITTED (not approved) quote -> amount_due 0; capture 5000 would also overpay,
    # but the no-approved-quote state gate outranks the fiscal over-due check.
    job, tech, quote = setup_submitted_quote(customer_user_id="cust-sbf")
    res = api.capture_payment(job["id"], {"captured_amount_cents": 5000}, BILLING)
    validate_error(res, "ERR_NO_APPROVED_QUOTE", expected_status=409)


def test_payment_no_approved_quote_when_only_drafted(api):
    """PRD §3.12: "A capture requires the job to have an APPROVED quote — without one
    the capture is rejected with ERR_NO_APPROVED_QUOTE."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_payment
    """
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-sbf2")
    res = api.capture_payment(job["id"], {"captured_amount_cents": 5000}, BILLING)
    validate_error(res, "ERR_NO_APPROVED_QUOTE", expected_status=409)


# ─── Corner: validations / payment_exceeds_due_rejected ────────────────────────
def test_payment_exceeds_due_rejected(api):
    """PRD §3.12: "A capture must not push net_paid_cents above the job's
    amount_due_cents; an overpayment is rejected with ERR_PAYMENT_EXCEEDS_DUE."

    Design: Corner/validations/payment_exceeds_due_rejected
    """
    job, tech, quote = setup_approved_quote(customer_user_id="cust-ovd", labor_hours=1.0)
    # final 8000; capture 9000 overpays
    res = api.capture_payment(job["id"], {"captured_amount_cents": 9000}, BILLING)
    validate_error(res, "ERR_PAYMENT_EXCEEDS_DUE", expected_status=409)


# ─── Corner: validations / refund_exceeds_paid_rejected ────────────────────────
def test_warranty_refund_exceeds_paid_rejected(api):
    """PRD §3.14: "The requested refund_amount_cents must not exceed the job's current
    net_paid_cents, else the approval is rejected with ERR_REFUND_EXCEEDS_PAID."

    Design: Corner/validations/refund_exceeds_paid_rejected
    """
    job, tech, quote, payment, claim = setup_filed_warranty_claim(
        customer_user_id="cust-rfx", refund_amount_cents=9000, days_since_close=3
    )
    res = api.approve_warranty_claim(claim["id"], DISPATCHER)
    validate_error(res, "ERR_REFUND_EXCEEDS_PAID", expected_status=409)


# ─── Corner: state_machines / warranty_approve_expired_window ──────────────────
def test_warranty_approve_expired_window_rejected(api):
    """PRD §3.14: "The warranty is valid only when days_since_close is at most 90 days;
    a claim at exactly 90 days is still covered, but 91 days or more is expired and is
    rejected with ERR_WARRANTY_EXPIRED."

    Design: Corner/state_machines/warranty_approve_expired_window
    """
    job, tech, quote, payment, claim = setup_filed_warranty_claim(
        customer_user_id="cust-exp", refund_amount_cents=8000, days_since_close=400
    )
    res = api.approve_warranty_claim(claim["id"], DISPATCHER)
    validate_error(res, "ERR_WARRANTY_EXPIRED", expected_status=409)
    refreshed = validate_success(api.get_warranty_claim(claim["id"], DISPATCHER), 200)
    assert refreshed["status"] == "FILED"


# ─── Corner: state_machines / close_job_not_fully_paid_invalid_state ───────────
def test_close_job_not_fully_paid_rejected(api):
    """PRD §3.12: "A job moves from WORK_COMPLETE to the terminal CLOSED only when its
    payment_status is PAID; an attempt to close a job that is not fully paid is rejected
    with ERR_JOB_NOT_FULLY_PAID."

    Design: Corner/state_machines/close_job_not_fully_paid_invalid_state
    """
    job, tech, quote = setup_approved_quote(customer_user_id="cust-nfp", labor_hours=1.0)
    tech_h = make_technician_headers(tech["id"])
    # complete-work without any payment -> WORK_COMPLETE & UNPAID
    get_success_data(api.complete_work(job["id"], tech_h))
    res = api.close_service_job(job["id"], DISPATCHER)
    validate_error(res, "ERR_JOB_NOT_FULLY_PAID", expected_status=409)


# ─── Corner: state_machines / complete_work_without_approved_quote ─────────────
def test_complete_work_without_approved_quote_rejected(api):
    """PRD §3.10: "This requires the job to have an APPROVED quote; with no approved
    quote on the job the request is rejected with ERR_NO_APPROVED_QUOTE."

    Design: Corner/state_machines/complete_work_without_approved_quote
    """
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-naq")
    res = api.complete_work(job["id"], make_technician_headers(tech["id"]))
    validate_error(res, "ERR_NO_APPROVED_QUOTE", expected_status=409)


# ─── Corner: state_machines / cancel_already_cancelled_job_invalid_state ───────
def test_cancel_already_cancelled_job_rejected(api):
    """PRD §3.13: "a job in WORK_COMPLETE, CLOSED, or already CANCELLED cannot be
    cancelled and yields ERR_JOB_NOT_CANCELLABLE."

    Design: Corner/state_machines/cancel_already_cancelled_job_invalid_state
    """
    job = create_job(customer_user_id="cust-cc", service_type="SAFE", requested_at_minute=600)
    get_success_data(api.cancel_service_job(job["id"], DISPATCHER))
    res = api.cancel_service_job(job["id"], DISPATCHER)
    validate_error(res, "ERR_JOB_NOT_CANCELLABLE", expected_status=409)
