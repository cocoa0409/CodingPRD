"""Invoicing: BEAR/SPI method variants, creation gates, review-cycle loop,
ledger conservation, audit hold vs fiscal priority, deadlines (PRD §2.8, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_line_ledger_conserved,
    begin_review,
    create_invoice_submission_payload,
    decide_request,
    get_line,
    invoice_begin_review,
    new_bear_invoice,
    new_provider_with_headers,
    new_spi_invoice,
    invoice_approve,
    invoice_pay,
    invoice_reject,
    invoice_resubmit_by_coordinator,
    make_invoice_processor_headers,
    set_audit_hold,
    set_clock,
    setup_certified_contract,
    setup_committed_scenario,
    setup_request_with_lines,
    start_services,
    validate_error,
    validate_success,
)


class TestBearVsSpiDivergence:
    """Queue A: dual_variant_calc/invoice_bear_vs_spi_divergence."""

    def _two_committed_lines_started(self):
        # C1 rate 50%: L1 share 25000, L2 share 20000.
        return setup_committed_scenario(
            line_amounts=(50000, 40000), bid_price=90000, contract_total=90000,
            service_start=True,
        )

    def test_bear_reimbursement_capped_by_applicant_paid(self, api):
        """PRD §3.6: "the base is the smaller of `applicant_paid_cents` and
        `gross_invoiced_cents` for a BEAR invoice — the applicant-fronted amount
        drives the claim — or the full `gross_invoiced_cents` for an SPI invoice,
        where the vendor already discounted the bills. The tentative amount is the
        base multiplied by the request's pinned discount rate for the line's
        category, divided by 100, and rounded half up to integer cents."

        Design: Difficulty/dual_variant_calc/invoice_bear_vs_spi_divergence
        """
        ctx = self._two_committed_lines_started()
        l1, _ = ctx["lines"]
        inv = new_bear_invoice(ctx, l1, gross_invoiced_cents=40000,
                               applicant_paid_cents=30000)
        invoice_begin_review(inv)
        approved = invoice_approve(inv)
        # min(30000 paid, 40000 gross) * 50% = 15000
        assert approved["approved_reimbursement_cents"] == 15000, (
            f"BEAR reimbursement must be 15000, got "
            f"{approved['approved_reimbursement_cents']}"
        )

    def test_spi_reimbursement_uses_full_gross_and_diverges(self, api):
        """PRD §3.6: "Identical inputs therefore produce different results under
        the two variants: a 40,000-cent bill at a 50 percent rate reimburses
        15,000 cents under BEAR when the applicant paid 30,000 of it, but 20,000
        cents under SPI."

        Design: Difficulty/dual_variant_calc/invoice_bear_vs_spi_divergence
        """
        ctx = self._two_committed_lines_started()
        l1, l2 = ctx["lines"]

        bear = new_bear_invoice(ctx, l1, gross_invoiced_cents=40000,
                                applicant_paid_cents=30000)
        invoice_begin_review(bear)
        bear_approved = invoice_approve(bear)["approved_reimbursement_cents"]

        spi = new_spi_invoice(ctx, l2, gross_invoiced_cents=40000)
        invoice_begin_review(spi)
        spi_approved = invoice_approve(spi)["approved_reimbursement_cents"]

        assert bear_approved == 15000
        assert spi_approved == 20000, (
            f"SPI reimbursement must be 20000 (full gross base), got {spi_approved}"
        )
        assert bear_approved != spi_approved, (
            "identical gross and rate must diverge across the two method variants"
        )


class TestInvoiceCreationGates:
    """Queue A: cross_entity_state_dependency/invoice_requires_line_committed_and_services_started."""

    def test_invoice_rejected_while_line_pending(self, api):
        """PRD §3.6: "Three further gates apply at creation, in their validation
        tiers: the line must be `COMMITTED` (otherwise `ERR_LINE_NOT_COMMITTED`);
        the line's request must have recorded service start (otherwise
        `ERR_SERVICES_NOT_STARTED`); and the clock's date must be on or before the
        line's `invoice_deadline_date` — the deadline date itself is allowed —
        otherwise `ERR_INVOICE_DEADLINE_PASSED`."

        Design: Difficulty/cross_entity_state_dependency/invoice_requires_line_committed_and_services_started
        """
        ctx = setup_certified_contract()
        setup_request_with_lines(ctx, line_amounts=(50000,))  # FILED, line PENDING
        resp = api.create_invoice_submission(
            create_invoice_submission_payload(
                frn_line_id=ctx["lines"][0]["id"], method="BEAR",
                gross_invoiced_cents=10000, applicant_paid_cents=10000),
            ctx["coord_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_COMMITTED)

    def test_committed_line_still_requires_service_start(self, api):
        """PRD §3.6: "the line must be `COMMITTED` (otherwise
        `ERR_LINE_NOT_COMMITTED`); the line's request must have recorded service
        start (otherwise `ERR_SERVICES_NOT_STARTED`)".
        PRD §3.5: "Recording service start — the Form 486 equivalent — is a
        coordinator action and a deliberate self-loop: the request remains
        `COMMITTED`, `services_started` flips to true, `service_start_date` is
        set to the clock's date, and the request's `version` increments."
        PRD §3.5: "This flag gates invoice creation in §3.6."

        Design: Difficulty/cross_entity_state_dependency/invoice_requires_line_committed_and_services_started
        """
        ctx = setup_certified_contract()
        setup_request_with_lines(ctx, line_amounts=(50000,))
        begin_review(ctx, ctx["request"])
        decide_request(ctx, ctx["request"], outcome="COMMITTED")
        line = get_line(ctx["lines"][0]["id"])
        assert line["status"] == "COMMITTED"

        # Line committed, but services_started is still false.
        resp = api.create_invoice_submission(
            create_invoice_submission_payload(
                frn_line_id=line["id"], method="BEAR",
                gross_invoiced_cents=10000, applicant_paid_cents=10000),
            ctx["coord_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SERVICES_NOT_STARTED)

        # The identical call succeeds after service start is recorded.
        start_services(ctx, ctx["request"])
        data = validate_success(
            api.create_invoice_submission(
                create_invoice_submission_payload(
                    frn_line_id=line["id"], method="BEAR",
                    gross_invoiced_cents=10000, applicant_paid_cents=10000),
                ctx["coord_headers"],
            ),
            201,
        )
        assert data["status"] == "SUBMITTED"


class TestRejectResubmitCycle:
    """Queue A: non_linear_state_machine/invoice_reject_resubmit_cycle."""

    def _invoice_under_review(self):
        ctx = setup_committed_scenario(line_amounts=(50000,), service_start=True)
        inv = new_bear_invoice(ctx, ctx["lines"][0], 10000, 10000)
        return ctx, invoice_begin_review(inv)

    def test_reject_resubmit_cycle_leaves_no_financial_trace(self, api):
        """PRD §3.6: "From `UNDER_REVIEW`, rejection moves the invoice to
        `REJECTED` and stores the reason; no money fields ever changed, so nothing
        is unwound."
        PRD §3.6: "Resubmission then returns a `REJECTED` invoice to
        `UNDER_REVIEW`, clearing `rejection_reason`".

        Design: Difficulty/non_linear_state_machine/invoice_reject_resubmit_cycle
        """
        ctx, inv = self._invoice_under_review()
        rejected = invoice_reject(inv, "Missing proof of payment page 2")
        assert rejected["status"] == "REJECTED"

        resubmitted = invoice_resubmit_by_coordinator(ctx, rejected)
        assert resubmitted["status"] == "UNDER_REVIEW"
        assert resubmitted["rejection_reason"] is None, (
            "resubmission must clear the stored rejection_reason"
        )
        # The ledger is untouched by the loop: approval computes only now.
        line = get_line(ctx["lines"][0]["id"])
        assert line["reimbursed_cents"] == 0
        assert line["remaining_reimbursable_cents"] == 25000
        approved = invoice_approve(resubmitted)
        assert approved["approved_reimbursement_cents"] == 5000

    def test_cycle_then_pay_moves_ledger_exactly_once(self, api):
        """PRD §3.6: "Disbursement moves an `APPROVED` invoice to the terminal
        `PAID` state and syncs the line's reimbursement ledger in the same
        request: the approved amount is added to the line's `reimbursed_cents` and
        subtracted from its `remaining_reimbursable_cents`, so the line's
        committed share is exactly conserved between paid and remaining portions."

        Design: Difficulty/non_linear_state_machine/invoice_reject_resubmit_cycle
        """
        ctx, inv = self._invoice_under_review()
        rejected = invoice_reject(inv, "Missing proof of payment page 2")
        resubmitted = invoice_resubmit_by_coordinator(ctx, rejected)
        approved = invoice_approve(resubmitted)
        paid = invoice_pay(approved)
        assert paid["status"] == "PAID"

        line = get_line(ctx["lines"][0]["id"])
        assert line["reimbursed_cents"] == 5000, (
            f"exactly one ledger move despite the loop, got {line['reimbursed_cents']}"
        )
        assert line["remaining_reimbursable_cents"] == 20000
        assert_line_ledger_conserved(line)


class TestApproveValidationOrder:
    """Queue A: priority_pair_validation_conflict/approve_safety_beats_fiscal."""

    def test_audit_hold_blocks_before_fiscal_check(self, api):
        """PRD §2.8: "While an applicant's hold is active, approval of any invoice
        against that applicant's funding lines is blocked with
        `ERR_AUDIT_HOLD_ACTIVE` (HTTP 409) — and this compliance check is evaluated
        before any fiscal comparison, so a held applicant never reaches the
        reimbursement-arithmetic stage."
        PRD §3.6: "the approval-time checks run compliance before fiscal, per
        §2.10: if the applicant's `audit_hold_active` is true, approval is blocked
        with `ERR_AUDIT_HOLD_ACTIVE` before any amount is examined."

        Design: Difficulty/priority_pair_validation_conflict/approve_safety_beats_fiscal
        """
        ctx = setup_committed_scenario(line_amounts=(50000,), service_start=True)
        # Tentative 30000 exceeds the line's remaining 25000 AND the applicant
        # is held — the compliance error must surface.
        inv = new_bear_invoice(ctx, ctx["lines"][0], 60000, 60000)
        invoice_begin_review(inv)
        set_audit_hold(ctx, True)
        resp = api.approve_invoice(
            inv["id"], make_invoice_processor_headers("usac-inv-1")
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_HOLD_ACTIVE)

    def test_reimbursement_ceiling_enforced_without_hold(self, api):
        """PRD §3.6: "If the tentative amount exceeds the line's
        `remaining_reimbursable_cents`, approval is rejected with
        `ERR_REIMBURSEMENT_EXCEEDS_REMAINING`; equality is allowed and drains the
        remaining balance to exactly 0."

        Design: Difficulty/priority_pair_validation_conflict/approve_safety_beats_fiscal
        """
        ctx = setup_committed_scenario(line_amounts=(50000,), service_start=True)
        # Same overshoot (tentative 30000 > remaining 25000), no audit hold.
        inv = new_bear_invoice(ctx, ctx["lines"][0], 60000, 60000)
        invoice_begin_review(inv)
        resp = api.approve_invoice(
            inv["id"], make_invoice_processor_headers("usac-inv-1")
        )
        validate_error(resp, ApiErrorId.ERR_REIMBURSEMENT_EXCEEDS_REMAINING)


class TestLedgerConservation:
    """Queue A: compensating_invariant/line_ledger_conserved_across_pay_and_reject."""

    def _line_with_approved_and_pending_invoice(self):
        ctx = setup_committed_scenario(line_amounts=(50000,), service_start=True)
        line = ctx["lines"][0]  # committed share 25000
        inv1 = new_bear_invoice(ctx, line, 40000, 40000)   # tentative 20000
        invoice_begin_review(inv1)
        inv1 = invoice_approve(inv1)
        inv2 = new_bear_invoice(ctx, line, 10000, 10000)   # tentative 5000
        invoice_begin_review(inv2)
        return ctx, line, inv1, inv2

    def test_pay_moves_money_between_buckets_conserving_total(self, api):
        """PRD §3.6: "Disbursement moves an `APPROVED` invoice to the terminal
        `PAID` state and syncs the line's reimbursement ledger in the same
        request: the approved amount is added to the line's `reimbursed_cents`
        and subtracted from its `remaining_reimbursable_cents`, so the line's
        committed share is exactly conserved between paid and remaining portions."

        Design: Difficulty/compensating_invariant/line_ledger_conserved_across_pay_and_reject
        """
        ctx, line, inv1, _ = self._line_with_approved_and_pending_invoice()
        assert inv1["approved_reimbursement_cents"] == 20000

        paid = invoice_pay(inv1)
        assert paid["status"] == "PAID"
        line = get_line(line["id"])
        assert line["reimbursed_cents"] == 20000
        assert line["remaining_reimbursable_cents"] == 5000, (
            "25000 == 20000 + 5000 must be conserved after the disbursement"
        )
        assert line["committed_share_cents"] == 25000
        assert_line_ledger_conserved(line)

    def test_reject_from_approved_revokes_without_ledger_drift(self, api):
        """PRD §3.6: "If the tentative amount exceeds the line's
        `remaining_reimbursable_cents`, approval is rejected with
        `ERR_REIMBURSEMENT_EXCEEDS_REMAINING`; equality is allowed and drains the
        remaining balance to exactly 0."
        PRD §3.6: "From `APPROVED`, rejection is a compensating action that
        revokes the approval before any disbursement:
        `approved_reimbursement_cents` is cleared back to null, while the line's
        `reimbursed_cents` and `remaining_reimbursable_cents` remain untouched."

        Design: Difficulty/compensating_invariant/line_ledger_conserved_across_pay_and_reject
        """
        ctx, line, inv1, inv2 = self._line_with_approved_and_pending_invoice()
        invoice_pay(inv1)  # reimbursed 20000, remaining 5000

        # Approval at exact equality with the remaining balance is allowed.
        approved2 = invoice_approve(inv2)
        assert approved2["approved_reimbursement_cents"] == 5000

        rejected = invoice_reject(
            approved2, "Approval issued in error; corrected claim to follow"
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["approved_reimbursement_cents"] is None, (
            "the compensating revocation must clear approved_reimbursement_cents"
        )

        line = get_line(line["id"])
        assert line["reimbursed_cents"] == 20000
        assert line["remaining_reimbursable_cents"] == 5000
        assert line["committed_share_cents"] == 25000
        assert_line_ledger_conserved(line)


class TestInvoiceStateGatesAndDeadlines:
    def test_pay_from_under_review_rejected(self, api):
        """PRD §3.6: "Disbursement moves an `APPROVED` invoice to the terminal
        `PAID` state and syncs the line's reimbursement ledger in the same
        request" — an `UNDER_REVIEW` invoice is not in a from-state of that
        transition.
        PRD §2.10: "**State gates** — the target resource must be in a from-state
        of the invoked transition, or satisfy the state gate of a state-gated
        create" and "Violations yield `ERR_INVALID_STATE_TRANSITION`, or the more
        specific `ERR_CONTRACT_NOT_CERTIFIED`, `ERR_LINE_NOT_COMMITTED`, or
        `ERR_SERVICES_NOT_STARTED` where those named gates apply."

        Design: Corner/state_machines/pay_from_under_review_rejected
        """
        ctx = setup_committed_scenario(line_amounts=(50000,), service_start=True)
        inv = new_bear_invoice(ctx, ctx["lines"][0], 10000, 10000)
        invoice_begin_review(inv)

        resp = api.pay_invoice(inv["id"], make_invoice_processor_headers("usac-inv-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        line = get_line(ctx["lines"][0]["id"])
        assert line["reimbursed_cents"] == 0
        assert line["remaining_reimbursable_cents"] == 25000, (
            "the failed disbursement must not move the line's ledger"
        )

    def test_invoice_deadline_on_date_allowed_after_rejected(self, api):
        """PRD §2.4: "The **invoice deadline** is closed: an invoice may be
        submitted on or before its line's `invoice_deadline_date`, which is set at
        commitment to 120 days after the cycle's `service_delivery_deadline`.
        A later submission is `ERR_INVOICE_DEADLINE_PASSED`."

        Design: Corner/cross_cutting_complexity_layers/invoice_deadline_on_date_allowed_after_rejected
        """
        ctx = setup_committed_scenario(line_amounts=(50000,), service_start=True)
        line = get_line(ctx["lines"][0]["id"])
        # 2027-06-30 + 120 calendar days = 2027-10-28.
        assert line["invoice_deadline_date"] == "2027-10-28", (
            f"deadline must be 2027-10-28, got {line['invoice_deadline_date']}"
        )

        set_clock("2027-10-28T00:00:00Z")  # the deadline date itself
        data = validate_success(
            api.create_invoice_submission(
                create_invoice_submission_payload(
                    frn_line_id=line["id"], method="BEAR",
                    gross_invoiced_cents=10000, applicant_paid_cents=10000),
                ctx["coord_headers"],
            ),
            201,
        )
        assert data["status"] == "SUBMITTED"

        set_clock("2027-10-29T00:00:00Z")  # one day past
        resp = api.create_invoice_submission(
            create_invoice_submission_payload(
                frn_line_id=line["id"], method="BEAR",
                gross_invoiced_cents=5000, applicant_paid_cents=5000),
            ctx["coord_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_DEADLINE_PASSED)

    def test_spi_by_wrong_provider_denied(self, api):
        """PRD §3.6: "An SPI invoice is filed by the representative of the
        provider on the line's contract, with the invoice's
        `submitted_by_provider_id` taken from the caller's identity (it stays null
        on BEAR invoices); a representative of any other provider is refused with
        `ERR_PROVIDER_ACCESS_DENIED`."

        Design: Corner/rbac/spi_by_wrong_provider_denied
        """
        ctx = setup_committed_scenario(line_amounts=(50000,), service_start=True)
        _, vendor2_headers = new_provider_with_headers("VendorTwo", "SPIN-002")
        resp = api.create_invoice_submission(
            create_invoice_submission_payload(
                frn_line_id=ctx["lines"][0]["id"], method="SPI",
                gross_invoiced_cents=10000),
            vendor2_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PROVIDER_ACCESS_DENIED)
