"""Carrier invoices: tiered admin fee with pinned evaluation order, claim-credit
conservation across approve/void, payment/reconcile fiscal gates, dispute cycle,
and creation gating (PRD §2.7, §2.8, §3.8).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, assert_invoice_invariants,
    create_job, create_statement, get_statement, set_clock, run_billing,
    setup_draft_invoice, setup_submitted_invoice,
    setup_finalized_storage_scenario,
    create_invoice, get_invoice, transition_invoice,
    setup_job_with_room, register_item,
    file_claim, submit_claim_for_review, approve_claim, transition_claim,
    get_job,
)

PM1 = TEST_USERS["pm1_headers"]
ADJ1 = TEST_USERS["adj1_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]
CARRIER = TEST_USERS["carrier_representative_headers"]


class TestTieredAdminFee:
    def _setup_tier_boundary_invoice(self):
        """One FINALIZED statement (final 4137: vol 40 @ 150/cu ft, placed
        2026-08-10, released 2026-08-31, 21 days x 197); invoice adjustment 95863
        so the pre-fee subtotal hits the 100000 tier boundary exactly."""
        ctx = setup_finalized_storage_scenario(
            job_overrides={"claim_number": "CLM-CF2"},
            item_overrides={"barcode": "BC-CF2", "description": "Sofa",
                            "item_category": "GENERAL", "declared_value_cents": 1000,
                            "volume_cu_ft": 40},
            vault_overrides={"code": "V-CF2", "climate_class": "CLIMATE_CONTROLLED",
                             "capacity_cu_ft": 10000,
                             "monthly_rate_cents_per_cu_ft": 150})
        assert ctx["statement"]["final_total_cents"] == 4137, (
            f"precondition: swept storage 4137, got {ctx['statement']['final_total_cents']}")
        return ctx

    def test_invoice_admin_fee_tier_keyed_on_subtotal(self, api):
        """PRD §3.8: "Then the fee percentage is selected by that pre-fee subtotal
        — never by the post-fee total: 5 percent when the subtotal is below 100000
        cents, 7 percent when it is at least 100000 and below 500000 cents, and 9
        percent when it is at least 500000 cents."
        PRD §3.8: "First the subtotal is formed as `storage_cents` plus
        `adjustment_cents`." and "The `total_cents` is the subtotal plus the fee —
        equivalently, `storage_cents` plus `adjustment_cents` plus
        `admin_fee_cents`."

        Design: Difficulty/combinatorial_formula/invoice_admin_fee_tier_keyed_on_subtotal
        """
        ctx = self._setup_tier_boundary_invoice()
        invoice = create_invoice(ctx["job"]["id"], adjustment_cents=95863)

        # subtotal = 4137 + 95863 = 100000 exactly -> 7% tier (boundary inclusive).
        assert invoice["admin_fee_cents"] == 7000, (
            f"subtotal 100000 lands in the 7% tier keyed BEFORE the fee, "
            f"got {invoice['admin_fee_cents']}")
        assert invoice["total_cents"] == 107000, (
            f"100000 + 7000, got {invoice['total_cents']}")
        assert_invoice_invariants(invoice)

    def test_invoice_sweeps_storage_and_initializes_balance(self, api):
        """PRD §3.8: "At creation, every `FINALIZED` statement of the job is
        swept: each becomes `INVOICED`, and the invoice's `storage_cents` is set to
        the sum of their `final_total_cents` values."
        PRD §3.8: "A new invoice starts `DRAFT` with `claim_credit_cents` zero and
        `amount_paid_cents` zero, and its `balance_cents` is always the total minus
        the claim credit minus the amount paid."

        Design: Difficulty/combinatorial_formula/invoice_admin_fee_tier_keyed_on_subtotal
        """
        ctx = self._setup_tier_boundary_invoice()
        invoice = create_invoice(ctx["job"]["id"], adjustment_cents=95863)

        assert invoice["storage_cents"] == 4137, (
            f"swept final statement total, got {invoice['storage_cents']}")
        assert invoice["status"] == "DRAFT"
        assert invoice["claim_credit_cents"] == 0
        assert invoice["amount_paid_cents"] == 0
        assert invoice["balance_cents"] == 107000

        stmt_after = get_statement(ctx["statement"]["id"])
        assert stmt_after["status"] == "INVOICED", (
            f"the swept statement becomes INVOICED, got {stmt_after['status']}")


class TestStateErrorBeatsFiscalError:
    def test_payment_on_draft_invoice_reports_state_error(self, api):
        """PRD §2.7: "When a single request would fail more than one rule, the
        failure reported is the one with the highest priority in the following
        fixed order." — "Seventh, state-legality checks — invalid-from transitions,
        terminal lockdown, duplicate actions, item terminal lockdown, the
        salvageability gate on cleaning and placement, and the job-close
        terminal-items gate — yield `ERR_INVALID_TRANSITION`, `ERR_ITEM_TERMINAL`,
        `ERR_ITEM_NOT_SALVAGEABLE`, or `ERR_JOB_ITEMS_NOT_TERMINAL` as applicable."
        — "Twelfth and last, fiscal gates yield `ERR_PAYMENT_EXCEEDS_BALANCE` or
        `ERR_INVOICE_BALANCE_OUTSTANDING`."
        PRD §3.8: "A `BillingClerk` records payments against a `SUBMITTED` or
        `DISPUTED` invoice"

        Design: Difficulty/priority_pair_validation_conflict/payment_state_error_beats_fiscal_error
        """
        _job, invoice = setup_draft_invoice(
            adjustment_cents=1000,
            job_overrides={"claim_number": "CLM-PP1"})
        assert invoice["balance_cents"] == 1050, (
            f"precondition: balance 1050, got {invoice['balance_cents']}")

        res = transition_invoice(invoice["id"], "RECORD_PAYMENT", amount_cents=999999)
        validate_error(res, ApiErrorId.ERR_INVALID_TRANSITION, expected_status=409)

    def test_rejected_payment_on_draft_leaves_invoice_unchanged(self, api):
        """PRD §3.8: "each `amount_cents` must be at least 1 — a smaller amount is
        rejected with `ERR_VALIDATION` — and no more than the current
        `balance_cents`, an excess rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`; the
        payment adds to `amount_paid_cents`, recomputes `balance_cents`, and leaves
        the invoice's status unchanged."

        Design: Difficulty/priority_pair_validation_conflict/payment_state_error_beats_fiscal_error
        """
        _job, invoice = setup_draft_invoice(
            adjustment_cents=1000,
            job_overrides={"claim_number": "CLM-PP1"})

        res = transition_invoice(invoice["id"], "RECORD_PAYMENT", amount_cents=999999)
        validate_error(res, ApiErrorId.ERR_INVALID_TRANSITION, expected_status=409)

        after = get_invoice(invoice["id"])
        assert after["status"] == "DRAFT", (
            f"a rejected payment is no transition, got {after['status']}")
        assert after["amount_paid_cents"] == 0
        assert after["balance_cents"] == 1050


class TestClaimCreditConservation:
    def _setup_approve_then_void(self):
        """ACV job; one REGISTERED item; LOSS claim (replacement 80000, age 1)
        approved at 72000 by adj-1 (filer pm-1), then voided; a FINALIZED empty
        statement exists so an invoice can be created with adjustment 2000."""
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-CI2", "property_address": "36 Chestnut Blvd",
                           "policy_coverage_type": "ACV"},
            room_overrides={"name": "Study", "room_type": "OTHER"})
        item = register_item(room["id"], barcode="BC-CI2", description="Camera",
                             item_category="ELECTRONICS", declared_value_cents=80000,
                             volume_cu_ft=1)
        claim = file_claim(item["id"], filer_headers=PM1,
                           claim_type="LOSS", description="Misplaced during transport",
                           replacement_cost_cents=80000, item_age_years=1)
        submit_claim_for_review(claim["id"], headers=ADJ1)
        approved = approve_claim(claim["id"], headers=ADJ1)
        # depreciation min(1*10, 70) = 10 -> 80000 * 90/100 = 72000; floor 24000.
        assert approved["settlement_amount_cents"] == 72000, (
            f"precondition: approved at 72000, got {approved['settlement_amount_cents']}")
        voided = get_success_data(transition_claim(claim["id"], "VOID", headers=ADJ1))
        create_statement(job["id"], "2026-08-01", "2026-09-01")
        set_clock("2026-09-01T00:00:00Z")
        run_billing()
        return job, approved, voided

    def test_approve_then_void_settles_at_zero_drift(self, api):
        """PRD §2.8: "Claim credit is conserved across approval and void: voiding
        an approved claim that has not yet been swept into an invoice returns the
        pending settlement liability and any not-yet-submitted invoice credit basis
        to their pre-approval values; an invoice's `balance_cents` may go negative
        only through a post-submission claim void, never otherwise."
        PRD §3.6: "an approved claim that has not been swept may be voided —
        voiding requires `credited_invoice_id` still null, else
        `ERR_INVALID_TRANSITION` — moving it to the terminal `VOIDED` and undoing
        the approval under the claim-credit conservation invariant of §2.8."

        Design: Difficulty/compensating_invariant/claim_credit_approve_void_compensation
        """
        _job, approved, voided = self._setup_approve_then_void()
        assert approved["status"] == "APPROVED"
        assert voided["status"] == "VOIDED", (
            f"the compensating VOID moves the claim to terminal VOIDED, got {voided['status']}")

    def test_invoice_after_void_carries_no_claim_credit(self, api):
        """PRD §3.8: "Submitting an invoice — a `BillingClerk` action — does the
        claim sweep. Every `APPROVED` handling claim of the job becomes `SETTLED`
        with its `credited_invoice_id` set to this invoice, the item-level
        claim-settlement cascade of §3.6 fires for each, and the invoice's
        `claim_credit_cents` is pinned to the sum of those claims'
        `settlement_amount_cents` values."

        Design: Difficulty/compensating_invariant/claim_credit_approve_void_compensation
        """
        job, _approved, voided = self._setup_approve_then_void()
        assert voided["status"] == "VOIDED"

        invoice = create_invoice(job["id"], adjustment_cents=2000)
        submitted = get_success_data(transition_invoice(invoice["id"], "SUBMIT"))

        assert submitted["claim_credit_cents"] == 0, (
            f"the voided approval contributes nothing to the sweep, "
            f"got {submitted['claim_credit_cents']}")
        # storage 0 + adjustment 2000 -> 5% fee 100 -> total 2100.
        assert submitted["total_cents"] == 2100
        assert submitted["balance_cents"] == 2100, (
            f"the approve/void pair left zero monetary drift, got {submitted['balance_cents']}")
        assert_invoice_invariants(submitted)


class TestInvoiceLifecycle:
    def test_invoice_dispute_resubmit_cycle(self, api):
        """PRD §3.8: "A `CarrierRepresentative` may dispute it — a `dispute_reason`
        is required, its absence rejected with `ERR_VALIDATION` — moving it to
        `DISPUTED` and setting the job's `billing_status` to `DISPUTED`."
        PRD §3.8: "A disputed invoice may be resubmitted through the same action;
        resubmission re-sweeps any newly approved claims into the credit,
        accumulating onto the pinned figure, and moves the invoice back to
        `SUBMITTED`."
        PRD §3.8: "it reads `DISPUTED` if any of the job's invoices is `DISPUTED`;
        otherwise `RECONCILED` if the job has at least one invoice and every
        invoice is `RECONCILED`; otherwise `INVOICED` if any invoice is `SUBMITTED`
        or `RECONCILED`; otherwise `ACCUMULATING`"

        Design: Corner/state_machines/invoice_dispute_resubmit_cycle
        """
        job, invoice = setup_submitted_invoice(
            adjustment_cents=500, job_overrides={"claim_number": "CLM-SM8"})
        assert invoice["status"] == "SUBMITTED" and invoice["total_cents"] == 525

        disputed = get_success_data(transition_invoice(
            invoice["id"], "DISPUTE", headers=CARRIER,
            dispute_reason="storage line mismatch"))
        assert disputed["status"] == "DISPUTED"
        assert get_job(job["id"])["billing_status"] == "DISPUTED", (
            "the job rollup reads DISPUTED while any invoice is DISPUTED")

        resubmitted = get_success_data(transition_invoice(invoice["id"], "SUBMIT"))
        assert resubmitted["status"] == "SUBMITTED", (
            f"DISPUTED -> SUBMITTED resubmission cycle, got {resubmitted['status']}")
        assert get_job(job["id"])["billing_status"] == "INVOICED", (
            "with the dispute resolved the job rollup returns to INVOICED")

    def test_reconcile_requires_exactly_zero_balance(self, api):
        """PRD §3.8: "When the balance reaches exactly zero cents, a
        `CarrierRepresentative` reconciles the invoice to its terminal `RECONCILED`
        state; reconciliation with any nonzero balance is rejected with
        `ERR_INVOICE_BALANCE_OUTSTANDING`."

        Design: Corner/validations/reconcile_requires_exactly_zero_balance
        """
        _job, invoice = setup_submitted_invoice(
            adjustment_cents=1000, job_overrides={"claim_number": "CLM-V6"})
        assert invoice["balance_cents"] == 1050

        res = transition_invoice(invoice["id"], "RECONCILE", headers=CARRIER)
        validate_error(res, ApiErrorId.ERR_INVOICE_BALANCE_OUTSTANDING, expected_status=422)

        paid = get_success_data(transition_invoice(
            invoice["id"], "RECORD_PAYMENT", amount_cents=1050))
        assert paid["balance_cents"] == 0, (
            f"paying exactly the balance zeroes it, got {paid['balance_cents']}")

        reconciled = get_success_data(transition_invoice(
            invoice["id"], "RECONCILE", headers=CARRIER))
        assert reconciled["status"] == "RECONCILED", (
            f"the == 0 boundary is inclusive, got {reconciled['status']}")

    def test_payment_exceeds_balance_returns_error(self, api):
        """PRD §3.8: "each `amount_cents` must be at least 1 — a smaller amount is
        rejected with `ERR_VALIDATION` — and no more than the current
        `balance_cents`, an excess rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`; the
        payment adds to `amount_paid_cents`, recomputes `balance_cents`, and leaves
        the invoice's status unchanged."

        Design: Corner/endpoints/payment_exceeds_balance_returns_error
        """
        _job, invoice = setup_submitted_invoice(
            adjustment_cents=1000, job_overrides={"claim_number": "CLM-EP2"})
        assert invoice["balance_cents"] == 1050

        res = transition_invoice(invoice["id"], "RECORD_PAYMENT", amount_cents=1051)
        validate_error(res, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE, expected_status=422)

        after = get_invoice(invoice["id"])
        assert after["amount_paid_cents"] == 0, (
            f"the excess payment must not be recorded, got {after['amount_paid_cents']}")
        assert after["balance_cents"] == 1050

    def test_invoice_create_blocked_by_provisional_statement(self, api):
        """PRD §3.8: "Creation is blocked while any statement of the job remains
        `PROVISIONAL`, and it requires at least one `FINALIZED` statement to sweep;
        violation is rejected with `ERR_STATEMENT_PERIOD_OPEN`."

        Design: Corner/validations/invoice_create_blocked_by_provisional_statement
        """
        job = create_job(claim_number="CLM-V5", property_address="74 Ash St")
        stmt = create_statement(job["id"], "2026-08-01", "2026-09-01")
        assert stmt["status"] == "PROVISIONAL", "precondition: statement still open"

        res = api.create_carrier_invoice(job["id"], {}, CLERK)
        validate_error(res, ApiErrorId.ERR_STATEMENT_PERIOD_OPEN, expected_status=409)

        invoices = get_success_data(api.list_carrier_invoices(job["id"], CLERK))
        assert invoices == [], f"no invoice may be persisted, got {invoices}"
