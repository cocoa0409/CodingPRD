"""Invoicing, payment, the dispute/refund backward cascade, callback-rate, and flag cascades."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_customer_headers, make_pro_headers, TEST_USERS,
    create_category, create_customer, create_cleared_pro, create_pro, create_window,
    create_job, accepted_instant_job, instant_quoted_job,
    in_progress_job, issued_invoice_for_in_progress_job, completed_paid_job,
    dispute_under_review,
    set_clock, clear_pro,
    create_background_check_payload, decide_background_check_payload,
    book_window_payload, create_visit_payload, pay_invoice_payload,
    create_dispute_payload, resolve_dispute_payload, accept_quote_payload,
    assert_invoice_balance_reconciled,
)

ADMIN = TEST_USERS["admin_headers"]


# Common FLAT category: flat 12000 + local trip 2500 = total 14500.
def _completed_paid_flat_job(code, email_c, email_p, win_day, callback_warranty_days=30,
                             reason=None, refund_destination=None):
    set_clock("2026-06-01T08:00:00.000Z")
    cat = create_category(code=code, name="Cat", pricing_model="FLAT", flat_task_fee_cents=12000,
                          instant_quote_eligible=True, instant_quote_flat_cents=15000,
                          callback_warranty_days=callback_warranty_days, skill_tags=["plumb"])
    cust = create_customer(email=email_c, full_name="C", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["plumb"], home_zip_code="30301",
                             email=email_p, full_name="P")
    job, window, invoice = completed_paid_job(
        cust["id"], cat["id"], pro,
        "2026-06-01T10:00:00.000Z", "2026-06-01T12:00:00.000Z", "2026-06-01T10:30:00.000Z",
        pay_amount=14500)
    return cust, pro, job, invoice


# =====================================================================
# Difficulty: dual_variant_calc / callback_rate_two_variants_diverge_on_pro
# =====================================================================

class TestCallbackRateTwoVariants:
    """completed_job_count grows the denominator; callback_job_count grows the numerator."""

    def test_callback_rate_after_one_completion_one_callback(self, api):
        """PRD §3.8: "The callback rate is zero whenever `completed_job_count` is zero; otherwise
        it is `callback_job_count` divided by `completed_job_count`, rounded half-up to four
        decimal places." PRD §3.8: "Opening a callback also increments the professional's
        `callback_job_count` by one and recomputes their `callback_rate`."

        Design: Difficulty/dual_variant_calc/callback_rate_two_variants_diverge_on_pro
        """
        cust, pro, job, invoice = _completed_paid_flat_job("PLUMB_FLAT", "c2@x.com", "p2@x.com", "06-01")
        # completed_job_count==1, callback_rate==0 before callback
        pro_after_complete = get_success_data(api.get_pro(pro["id"], ADMIN))
        assert pro_after_complete["completed_job_count"] == 1
        assert pro_after_complete["callback_rate"] == 0
        # open warranty callback -> callback_job_count 1, rate 1/1 = 1.0
        get_success_data(api.open_callback(job["id"], make_customer_headers(cust["id"])))
        pro_final = get_success_data(api.get_pro(pro["id"], ADMIN))
        assert pro_final["completed_job_count"] == 1
        assert pro_final["callback_job_count"] == 1
        assert pro_final["callback_rate"] == 1.0

    def test_base_completion_holds_callback_rate_at_zero(self, api):
        """PRD §3.8: "a non-callback completion increments the professional's
        `completed_job_count` by one ... In both cases the professional's `callback_rate` is
        recomputed afterward. The callback rate is zero whenever `completed_job_count` is zero;
        otherwise it is `callback_job_count` divided by `completed_job_count`".

        Design: Difficulty/dual_variant_calc/callback_rate_two_variants_diverge_on_pro
        """
        cust, pro, job, invoice = _completed_paid_flat_job("PLUMB_F2", "c2b@x.com", "p2b@x.com", "06-01")
        pro_after = get_success_data(api.get_pro(pro["id"], ADMIN))
        # one completion, zero callbacks -> 0/1 == 0
        assert pro_after["completed_job_count"] == 1
        assert pro_after["callback_job_count"] == 0
        assert pro_after["callback_rate"] == 0


# =====================================================================
# Difficulty: transitive_cascade / dispute_approve_work_incomplete_depth3_cascade
# =====================================================================

class TestDisputeApproveWorkIncompleteCascade:
    """resolve(APPROVE, WORK_INCOMPLETE, full) cascades 3 levels deep."""

    def _setup(self):
        cust, pro, job, invoice = _completed_paid_flat_job("FLAT_SVC", "c7@x.com", "p7@x.com", "06-01")
        cust_h = make_customer_headers(cust["id"])
        cb_job = get_success_data(api_client.open_callback(job["id"], cust_h))
        disp = dispute_under_review(cust["id"], invoice["id"], job["id"],
                                    "WORK_INCOMPLETE", 14500, refund_destination="WALLET")
        return cust, pro, job, invoice, cb_job, disp

    def test_full_refund_flips_invoice_to_refunded_and_credits_wallet(self, api):
        """PRD §3.10: "the invoice's `refunded_cents` is increased by that amount and its
        `balance_due_cents` recomputed. If the cumulative refund now equals the invoice's
        `amount_paid_cents` — a full refund — the invoice transitions `PAID → REFUNDED` ... If the
        dispute's `refund_destination` is `WALLET`, the approved amount is added to the customer's
        `wallet_credit_cents`."

        Design: Difficulty/transitive_cascade/dispute_approve_work_incomplete_depth3_cascade
        """
        cust, pro, job, invoice, cb_job, disp = self._setup()
        resolved = validate_success(
            api.resolve_dispute(disp["id"], resolve_dispute_payload("APPROVE", approved_refund_cents=14500), ADMIN), 200)
        assert resolved["status"] == "APPROVED"
        inv = get_success_data(api.get_invoice(invoice["id"], ADMIN))
        assert inv["refunded_cents"] == 14500
        assert inv["status"] == "REFUNDED"
        cust_after = get_success_data(api.get_customer(cust["id"], ADMIN))
        assert cust_after["wallet_credit_cents"] == 14500

    def test_work_incomplete_cancels_callback_and_decrements_counter(self, api):
        """PRD §3.10: "if the dispute's `reason` is `WORK_INCOMPLETE` and an open warranty callback
        exists for the job, that callback job is auto-cancelled, the professional's
        `callback_job_count` is decremented by one, and their `callback_rate` is recomputed."

        Design: Difficulty/transitive_cascade/dispute_approve_work_incomplete_depth3_cascade
        """
        cust, pro, job, invoice, cb_job, disp = self._setup()
        api.resolve_dispute(disp["id"], resolve_dispute_payload("APPROVE", approved_refund_cents=14500), ADMIN)
        cb_after = get_success_data(api.get_job(cb_job["id"], ADMIN))
        assert cb_after["status"] == "CANCELLED"
        pro_after = get_success_data(api.get_pro(pro["id"], ADMIN))
        assert pro_after["callback_job_count"] == 0
        assert pro_after["callback_rate"] == 0.0


# =====================================================================
# Difficulty: transitive_cascade / pro_flagged_cascade_cancels_scheduled_releases_window
# =====================================================================

class TestProFlaggedCascade:
    """A post-clearance FAIL flags the pro, cancels SCHEDULED jobs, releases their windows."""

    def _setup(self):
        set_clock("2026-06-01T08:00:00.000Z")
        cat = create_category(code="FLAG_SVC", name="Flag Service", pricing_model="HOURLY",
                              hourly_rate_cents=9000, instant_quote_eligible=True,
                              instant_quote_flat_cents=15000, skill_tags=["hvac"])
        cust = create_customer(email="c8@x.com", full_name="C Eight", zip_code="30301")
        pro = create_cleared_pro(skill_tags=["hvac"], home_zip_code="30301",
                                 email="p8@x.com", full_name="P Eight")
        window = create_window(pro["id"], "2026-06-04T10:00:00.000Z", "2026-06-04T12:00:00.000Z", "30301")
        job, quote = accepted_instant_job(cust["id"], cat["id"], "30301")
        cust_h = make_customer_headers(cust["id"])
        get_success_data(api_client.book_window(
            window["id"], book_window_payload(job["id"], window["version"]), cust_h))
        # submit a post-clearance CRIMINAL check, leave PENDING
        bc3 = get_success_data(api_client.create_background_check(
            pro["id"], create_background_check_payload(check_type="CRIMINAL"), ADMIN))
        return cust, pro, job, window, bc3

    def test_post_clearance_fail_flags_pro(self, api):
        """PRD §3.2: "A professional moves to `FLAGGED` — whether they were `PENDING` or already
        `CLEARED` — as soon as any check of `check_type` `CRIMINAL` or `IDENTITY` records a
        `decision` of `FAIL`."

        Design: Difficulty/transitive_cascade/pro_flagged_cascade_cancels_scheduled_releases_window
        """
        cust, pro, job, window, bc3 = self._setup()
        api.decide_background_check(bc3["id"], decide_background_check_payload(decision="FAIL"), ADMIN)
        pro_after = get_success_data(api.get_pro(pro["id"], ADMIN))
        assert pro_after["background_check_status"] == "FLAGGED"

    def test_flag_cancels_scheduled_job_and_releases_window(self, api):
        """PRD §3.2: "The `CLEARED → FLAGGED` transition is not merely a status change: it cancels
        every one of that professional's `SCHEDULED` jobs (moving each to `CANCELLED`) and releases
        the dispatch windows those jobs had booked."

        Design: Difficulty/transitive_cascade/pro_flagged_cascade_cancels_scheduled_releases_window
        """
        cust, pro, job, window, bc3 = self._setup()
        api.decide_background_check(bc3["id"], decide_background_check_payload(decision="FAIL"), ADMIN)
        job_after = get_success_data(api.get_job(job["id"], ADMIN))
        assert job_after["status"] == "CANCELLED"
        win_after = get_success_data(api.get_dispatch_window(window["id"], ADMIN))
        assert win_after["hold_state"] == "RELEASED"


# =====================================================================
# Difficulty: compensating_invariant / refund_to_wallet_conserves_money_cents
# =====================================================================

class TestRefundToWalletConservesMoney:
    """After pay 24000 then full WALLET refund 24000, money is conserved with no drift."""

    def _setup(self):
        set_clock("2026-06-01T08:00:00.000Z")
        cat = create_category(code="CONS_FLAT", name="Cons Flat", pricing_model="FLAT",
                              flat_task_fee_cents=12000, instant_quote_eligible=True,
                              instant_quote_flat_cents=15000, skill_tags=["plumb"])
        cust = create_customer(email="c17@x.com", full_name="C Seventeen", zip_code="30301")
        pro = create_cleared_pro(skill_tags=["plumb"], home_zip_code="30301",
                                 email="p17@x.com", full_name="P Seventeen")
        # one special-order part 9500 -> labor 12000 + parts 9500 + local trip 2500 = 24000
        job, window, invoice = completed_paid_job(
            cust["id"], cat["id"], pro,
            "2026-06-01T10:00:00.000Z", "2026-06-01T12:00:00.000Z", "2026-06-01T10:30:00.000Z",
            pay_amount=24000,
            parts=[{"description": "Special valve", "unit_cost_cents": 4000, "quantity": 2,
                    "from_truck_stock": False}])
        disp = dispute_under_review(cust["id"], invoice["id"], job["id"], "OVERCHARGED", 24000,
                                    refund_destination="WALLET")
        return cust, invoice, disp

    def test_full_wallet_refund_reaches_refunded_state(self, api):
        """PRD §3.10: "If the cumulative refund now equals the invoice's `amount_paid_cents` — a
        full refund — the invoice transitions `PAID → REFUNDED`".

        Design: Difficulty/compensating_invariant/refund_to_wallet_conserves_money_cents
        """
        cust, invoice, disp = self._setup()
        api.resolve_dispute(disp["id"], resolve_dispute_payload("APPROVE", approved_refund_cents=24000), ADMIN)
        inv = get_success_data(api.get_invoice(invoice["id"], ADMIN))
        assert inv["total_cents"] == 24000
        assert inv["amount_paid_cents"] == 24000
        assert inv["refunded_cents"] == 24000
        assert inv["status"] == "REFUNDED"

    def test_money_conserved_into_wallet_no_drift(self, api):
        """PRD §3.10: "If the dispute's `refund_destination` is `WALLET`, the approved amount is
        added to the customer's `wallet_credit_cents`."

        Design: Difficulty/compensating_invariant/refund_to_wallet_conserves_money_cents
        """
        cust, invoice, disp = self._setup()
        api.resolve_dispute(disp["id"], resolve_dispute_payload("APPROVE", approved_refund_cents=24000), ADMIN)
        cust_after = get_success_data(api.get_customer(cust["id"], ADMIN))
        inv = get_success_data(api.get_invoice(invoice["id"], ADMIN))
        # conserved: (paid - refunded) + wallet == paid
        retained = inv["amount_paid_cents"] - inv["refunded_cents"]
        assert retained + cust_after["wallet_credit_cents"] == 24000


# =====================================================================
# Difficulty: compensating_invariant / callback_open_then_dispute_cancel_conserves_callback_count
# =====================================================================

class TestCallbackCountConserved:
    """Opening a callback +1, the dispute-driven cancel -1, returning to the prior count."""

    def _setup(self):
        cust, pro, job, invoice = _completed_paid_flat_job("CONS_CB", "c18@x.com", "p18@x.com", "06-01")
        cust_h = make_customer_headers(cust["id"])
        cb_job = get_success_data(api_client.open_callback(job["id"], cust_h))
        disp = dispute_under_review(cust["id"], invoice["id"], job["id"], "WORK_INCOMPLETE", 14500,
                                    refund_destination="ORIGINAL")
        return cust, pro, job, invoice, cb_job, disp

    def test_callback_count_returns_to_zero_after_dispute_cancel(self, api):
        """PRD §3.10: "if the dispute's `reason` is `WORK_INCOMPLETE` and an open warranty callback
        exists for the job, that callback job is auto-cancelled, the professional's
        `callback_job_count` is decremented by one, and their `callback_rate` is recomputed."

        Design: Difficulty/compensating_invariant/callback_open_then_dispute_cancel_conserves_callback_count
        """
        cust, pro, job, invoice, cb_job, disp = self._setup()
        # before resolve: callback_job_count == 1
        pro_before = get_success_data(api.get_pro(pro["id"], ADMIN))
        assert pro_before["callback_job_count"] == 1
        api.resolve_dispute(disp["id"], resolve_dispute_payload("APPROVE", approved_refund_cents=14500), ADMIN)
        pro_after = get_success_data(api.get_pro(pro["id"], ADMIN))
        assert pro_after["callback_job_count"] == 0
        assert pro_after["completed_job_count"] == 1
        assert pro_after["callback_rate"] == 0.0

    def test_callback_job_auto_cancelled_by_dispute(self, api):
        """PRD §3.10: "if the dispute's `reason` is `WORK_INCOMPLETE` and an open warranty callback
        exists for the job, that callback job is auto-cancelled, the professional's
        `callback_job_count` is decremented by one, and their `callback_rate` is recomputed."

        Design: Difficulty/compensating_invariant/callback_open_then_dispute_cancel_conserves_callback_count
        """
        cust, pro, job, invoice, cb_job, disp = self._setup()
        api.resolve_dispute(disp["id"], resolve_dispute_payload("APPROVE", approved_refund_cents=14500), ADMIN)
        cb_after = get_success_data(api.get_job(cb_job["id"], ADMIN))
        assert cb_after["status"] == "CANCELLED"


# =====================================================================
# Corner: state_machines / partial_refund_keeps_invoice_paid_not_refunded
# =====================================================================

def test_partial_refund_keeps_invoice_paid(api):
    """PRD §3.10: "If the cumulative refund now equals the invoice's `amount_paid_cents` — a full
    refund — the invoice transitions `PAID → REFUNDED`; a partial refund leaves the invoice
    `PAID`."

    Design: Corner/state_machines/partial_refund_keeps_invoice_paid_not_refunded
    """
    cust, pro, job, invoice = _completed_paid_flat_job("SM_PART", "csm5@x.com", "psm5@x.com", "06-01")
    disp = dispute_under_review(cust["id"], invoice["id"], job["id"], "OVERCHARGED", 5000,
                                refund_destination="ORIGINAL")
    api.resolve_dispute(disp["id"], resolve_dispute_payload("APPROVE", approved_refund_cents=5000), ADMIN)
    inv = get_success_data(api.get_invoice(invoice["id"], ADMIN))
    assert inv["refunded_cents"] == 5000
    assert inv["status"] == "PAID"
    assert inv["balance_due_cents"] == 5000
    assert_invoice_balance_reconciled(inv)


# =====================================================================
# Corner: state_machines / dispute_resolve_from_open_without_review_returns_invalid_state
# =====================================================================

def test_resolve_dispute_still_open_rejected(api):
    """PRD §3.10: "From `UNDER_REVIEW` the administrator resolves the dispute by supplying a
    `decision`." PRD §2.9: "(7) state legality for the requested transition, surfacing
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/dispute_resolve_from_open_without_review_returns_invalid_state
    """
    cust, pro, job, invoice = _completed_paid_flat_job("SM_DISP", "csm4@x.com", "psm4@x.com", "06-01")
    cust_h = make_customer_headers(cust["id"])
    disp = get_success_data(api.create_dispute(
        create_dispute_payload(job["id"], invoice["id"], "OVERCHARGED", 5000), cust_h))
    # NOT reviewed: still OPEN
    res = api.resolve_dispute(disp["id"], resolve_dispute_payload("APPROVE", approved_refund_cents=5000), ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = get_success_data(api.get_dispute(disp["id"], ADMIN))
    assert after["status"] == "OPEN"


# =====================================================================
# Corner: cross_cutting / derived_balance_due_reconciled_after_pay
# =====================================================================

def test_balance_due_reconciled_to_zero_after_full_payment(api):
    """PRD §3.7: "The `balance_due_cents` is a derived figure kept continually reconciled as
    `total_cents` minus `amount_paid_cents` plus `refunded_cents`".

    Design: Corner/cross_cutting_complexity_layers/derived_balance_due_reconciled_after_pay
    """
    set_clock("2026-06-01T08:00:00.000Z")
    cat = create_category(code="CC_REC", name="CC Recon", pricing_model="FLAT",
                          flat_task_fee_cents=12000, instant_quote_eligible=True,
                          instant_quote_flat_cents=15000, skill_tags=["plumb"])
    cust = create_customer(email="ccc2@x.com", full_name="C CC2", zip_code="30301")
    pro = create_cleared_pro(skill_tags=["plumb"], home_zip_code="30301",
                             email="pcc2@x.com", full_name="P CC2")
    job, window, invoice = issued_invoice_for_in_progress_job(
        cust["id"], cat["id"], pro,
        "2026-06-25T10:00:00.000Z", "2026-06-25T12:00:00.000Z", "2026-06-25T10:30:00.000Z")
    assert invoice["total_cents"] == 14500
    paid = validate_success(
        api.pay_invoice(invoice["id"], pay_invoice_payload(14500), make_customer_headers(cust["id"])), 200)
    assert paid["balance_due_cents"] == 0
    assert paid["status"] == "PAID"
    assert_invoice_balance_reconciled(paid)
