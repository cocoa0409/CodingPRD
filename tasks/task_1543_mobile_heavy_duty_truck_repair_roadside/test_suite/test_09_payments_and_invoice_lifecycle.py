"""Invoice issue/payment parallel dimensions, payment post/void round trips,
invoice void segregation and payment blocking, and one-live-invoice rules."""
from test_helpers import (
    TEST_USERS,
    adjust_fleet_spend,
    assert_invoice,
    create_fleet,
    create_invoice_for_call,
    get_call,
    get_success_data,
    issue_invoice,
    make_billing_clerk_headers,
    make_ops_admin_headers,
    post_payment,
    setup_s1_completed_job,
    setup_s1_issued_invoice,
    validate_error,
    validate_success,
    void_payment,
)
from test_helpers import ApiErrorId

OPS = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


class TestParallelDimensions:
    def test_issue_moves_issue_dimension_only(self, api):
        """PRD: "a document's issuance lifecycle and its collection lifecycle
        evolve independently" — drafting begins at (`DRAFT`, `UNPAID`) and
        issuing moves only the issue dimension.

        Design: Difficulty/non_linear_state_machine/invoice_issue_and_payment_dimensions_evolve_independently
        """
        ctx = setup_s1_completed_job(fleet=create_fleet())
        invoice = create_invoice_for_call(ctx["call"]["id"])
        assert_invoice(invoice)
        assert (invoice["issue_status"], invoice["payment_status"]) == \
            ("DRAFT", "UNPAID")

        issued = issue_invoice(invoice["id"])
        assert (issued["issue_status"], issued["payment_status"]) == \
            ("ISSUED", "UNPAID"), "issue leaves the payment dimension untouched"

    def test_payment_and_void_move_payment_dimension_only(self, api):
        """PRD: "Posting recomputes the invoice's `amount_paid_cents` ... and
        `outstanding_cents` ..., moves `payment_status` from `UNPAID` to
        `PARTIALLY_PAID` while a balance remains" and voiding a payment
        "recomputes the amounts and the payment status (dropping back to
        `PARTIALLY_PAID` or `UNPAID` as the numbers dictate)" — the issue
        dimension never leaves ISSUED.

        Design: Difficulty/non_linear_state_machine/invoice_issue_and_payment_dimensions_evolve_independently
        """
        ctx = setup_s1_issued_invoice(fleet=create_fleet())
        inv_id = ctx["invoice"]["id"]
        assert ctx["invoice"]["total_cents"] == 136698

        payment = post_payment(inv_id, 50000, method="CHECK")
        mid = get_success_data(api.get_invoice(inv_id, BILLING))
        assert (mid["issue_status"], mid["payment_status"]) == \
            ("ISSUED", "PARTIALLY_PAID")
        assert mid["amount_paid_cents"] == 50000
        assert mid["outstanding_cents"] == 86698

        void_payment(payment["id"], reason="check bounced")
        after = get_success_data(api.get_invoice(inv_id, BILLING))
        assert (after["issue_status"], after["payment_status"]) == \
            ("ISSUED", "UNPAID")
        assert after["amount_paid_cents"] == 0
        assert after["outstanding_cents"] == 136698

        written = validate_success(api.writeoff_invoice(
            inv_id, {"reason": "uncollectible"}, OPS))
        assert (written["issue_status"], written["payment_status"]) == \
            ("ISSUED", "WRITTEN_OFF"), (
            "write-off lands on the payment dimension only")


class TestPaymentPostVoidInvariant:
    def test_payment_post_then_void_restores_invoice_outstanding(self, api):
        """PRD: voiding a payment "reverses its allocation, recomputes the
        amounts and the payment status (dropping back to `PARTIALLY_PAID` or
        `UNPAID` as the numbers dictate), moves the payment to `VOID`".

        Design: Difficulty/compensating_invariant/payment_post_then_void_restores_invoice_outstanding
        """
        ctx = setup_s1_issued_invoice(fleet=create_fleet())
        inv_id = ctx["invoice"]["id"]

        payment = post_payment(inv_id, 50000, method="ACH")
        mid = get_success_data(api.get_invoice(inv_id, BILLING))
        assert mid["outstanding_cents"] == 86698
        assert mid["payment_status"] == "PARTIALLY_PAID"

        voided = void_payment(payment["id"], reason="ACH returned")
        assert voided["status"] == "VOID"
        end = get_success_data(api.get_invoice(inv_id, BILLING))
        assert end["outstanding_cents"] == 136698
        assert end["amount_paid_cents"] == 0
        assert end["payment_status"] == "UNPAID", (
            "post + void conserves outstanding_cents with zero drift")

    def test_payment_void_leaves_issue_status_untouched(self, api):
        """PRD: the invoice's "issuance lifecycle and its collection
        lifecycle evolve independently" — voiding the only payment reverts
        payment_status to UNPAID while issue_status stays ISSUED.

        Design: Difficulty/compensating_invariant/payment_post_then_void_restores_invoice_outstanding
        """
        ctx = setup_s1_issued_invoice(fleet=create_fleet())
        inv_id = ctx["invoice"]["id"]
        payment = post_payment(inv_id, 50000, method="ACH")
        void_payment(payment["id"], reason="ACH returned")
        end = get_success_data(api.get_invoice(inv_id, BILLING))
        assert end["issue_status"] == "ISSUED"


class TestInvoiceVoidFleetInvariant:
    def _issued_invoice_with_credit_hold(self):
        """Fleet cap 140000 with +10000 adjustment; the S1 invoice (136698)
        pushes month spend to 146698 > cap -> SUSPENDED/CREDIT_HOLD."""
        # setup_s1_issued_invoice publishes the STD-2026 card itself; a second
        # identical-window publish would be rejected (PRD section 2.9).
        fleet = create_fleet(per_call_authorization_limit_cents=100000,
                             monthly_spend_cap_cents=140000)
        adjust_fleet_spend(fleet["id"], 10000, reason="prior correction")
        ctx = setup_s1_issued_invoice(
            fleet=fleet, issue_headers=make_billing_clerk_headers("bc-1"))
        return fleet, ctx

    def test_invoice_issue_then_void_restores_fleet_mtd(self, api):
        """PRD: "Voiding subtracts the invoice's `total_cents` back out of
        the fleet's `month_to_date_spend_cents`" — issue adds 136698
        (10000 -> 146698, crossing the 140000 cap), and a different operator's
        void returns the fleet to exactly 10000.

        Design: Difficulty/compensating_invariant/invoice_issue_then_void_restores_fleet_mtd_and_status
        """
        fleet, ctx = self._issued_invoice_with_credit_hold()
        mid = get_success_data(api.get_fleet_account(fleet["id"], OPS))
        assert mid["month_to_date_spend_cents"] == 146698
        assert mid["status"] == "SUSPENDED"
        assert mid["suspension_reason"] == "CREDIT_HOLD"

        voided = validate_success(api.void_invoice(
            ctx["invoice"]["id"], {"reason": "billing error"},
            make_ops_admin_headers("ops-2")))
        assert voided["issue_status"] == "VOID"
        end = get_success_data(api.get_fleet_account(fleet["id"], OPS))
        assert end["month_to_date_spend_cents"] == 10000, (
            "issue + void conserves month_to_date_spend_cents")

    def test_invoice_void_auto_reinstates_credit_hold_fleet(self, api):
        """PRD: voiding "automatically reinstates a `CREDIT_HOLD`-suspended
        fleet whose month total has returned to its cap or below, reverts the
        call from `INVOICED` to whatever `status_before_invoice` captured".

        Design: Difficulty/compensating_invariant/invoice_issue_then_void_restores_fleet_mtd_and_status
        """
        fleet, ctx = self._issued_invoice_with_credit_hold()
        validate_success(api.void_invoice(
            ctx["invoice"]["id"], {"reason": "billing error"},
            make_ops_admin_headers("ops-2")))
        end = get_success_data(api.get_fleet_account(fleet["id"], OPS))
        assert end["status"] == "ACTIVE"
        assert end["suspension_reason"] == "NONE"
        call = get_call(ctx["call"]["id"])
        assert call["status"] == "REPAIR_COMPLETED", (
            "the call reverts to its pre-issue status")


class TestPaymentAndInvoiceGuards:
    def test_payment_over_outstanding_rejected(self, api):
        """PRD: payments carry "an `amount_cents` of at least one and at most
        the invoice's current `outstanding_cents` (`ERR_PAYMENT_EXCEEDS_BALANCE`
        otherwise)" and "When a payment brings the outstanding balance to
        zero, `payment_status` becomes `PAID` and the call cascades from
        `INVOICED` to `CLOSED`".

        Design: Corner/errors/payment_over_outstanding_rejected
        """
        ctx = setup_s1_issued_invoice()
        inv_id = ctx["invoice"]["id"]
        resp = api.post_payment(
            inv_id, {"amount_cents": 136699, "method": "CARD"}, BILLING)
        assert resp.status_code == 422
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

        payment = post_payment(inv_id, 136698, method="CARD")
        assert payment["status"] == "POSTED"
        invoice = get_success_data(api.get_invoice(inv_id, BILLING))
        assert invoice["payment_status"] == "PAID"
        assert invoice["outstanding_cents"] == 0
        assert get_call(ctx["call"]["id"])["status"] == "CLOSED"

    def test_invoice_void_blocked_by_posted_payments(self, api):
        """PRD: an OpsAdmin may void an ISSUED invoice "only while no
        `POSTED` payments exist on it (else `ERR_INVOICE_HAS_PAYMENTS`)".

        Design: Corner/errors/error_invoice_void_blocked_by_posted_payments
        """
        ctx = setup_s1_issued_invoice(
            issue_headers=make_billing_clerk_headers("bc-1"))
        inv_id = ctx["invoice"]["id"]
        payment = post_payment(inv_id, 50000, method="ACH")

        resp = api.void_invoice(inv_id, {"reason": "billing error"}, OPS)
        validate_error(resp, ApiErrorId.ERR_INVOICE_HAS_PAYMENTS)

        void_payment(payment["id"], reason="returned")
        voided = validate_success(api.void_invoice(
            inv_id, {"reason": "billing error"}, OPS))
        assert voided["issue_status"] == "VOID", (
            "voiding the payment first releases the invoice void")

    def test_second_invoice_for_same_call_rejected(self, api):
        """PRD: "no invoice may be drafted while a claim of the call sits in
        `DRAFT`, `SUBMITTED`, or `APPEALED` (`ERR_WARRANTY_CLAIM_UNDECIDED`) —
        and the invoice side of that gate, or a second live invoice, is
        rejected with `ERR_INVOICE_EXISTS`."

        Design: Corner/errors/second_invoice_for_same_call_rejected
        """
        ctx = setup_s1_completed_job()
        create_invoice_for_call(ctx["call"]["id"])  # DRAFT invoice exists
        resp = api.create_invoice(ctx["call"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INVOICE_EXISTS)
