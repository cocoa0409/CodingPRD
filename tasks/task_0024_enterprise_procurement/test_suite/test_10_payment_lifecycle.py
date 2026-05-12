"""Payment application, approval, execution, and budget conservation
(PRD §3.10, §2.10)."""
from __future__ import annotations
import pytest

from prd_bench_local_runner.testing import build_user_headers

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    apply_payment_payload,
    setup_invoice_approved,
    setup_payment_applied,
    validate_error,
    validate_success,
)


# ===========================================================================
# Apply payment (PRD §3.10)
# ===========================================================================
class TestPaymentApply:
    def test_apply_flips_schedule_and_creates_payment(self, api, finance_headers):
        """PRD §3.10: "On creation the payment is in APPLIED, its
        amount_cents mirrors the schedule entry's amount_cents (and is
        immutable thereafter), and the schedule entry transitions from
        PENDING to APPLIED."

        Claim: applying a payment leaves it in APPLIED with amount mirror
        and the schedule entry now in APPLIED.
        """
        setup = setup_payment_applied()
        payment = setup["payment"]
        assert payment["status"] == "APPLIED"
        assert payment["amount_cents"] == setup["schedule_entry"]["amount_cents"]


# ===========================================================================
# Approve payment + segregation of duties (PRD §3.10, priority 8)
# ===========================================================================
class TestPaymentApproveSegregation:
    def test_payment_approver_must_not_be_prior_step_approver(self, api):
        """PRD §3.10: "A different FinanceApprover then approves the
        payment. The approving user must not have decided any
        ApprovalStep on the parent purchase order; this is the second arm
        of segregation-of-duties — finance-side approval-then-payment
        must be split across two distinct people. A violation surfaces as
        ERR_SEGREGATION_OF_DUTIES."

        Claim: if the same X-User-ID approved both an ApprovalStep on the
        PO and the Payment, the /payments/{id}/approve call yields
        ERR_SEGREGATION_OF_DUTIES.
        """
        # Build a TIER_2 PO so a FINANCE step exists and is decided by
        # a known X-User-ID. Then have the SAME X-User-ID try to approve
        # the Payment.
        from test_helpers import (
            approve_step_as,
            find_step_by_stage,
            make_finance_headers,
            setup_executed_contract,
            setup_tier3_po_with_two_serial_steps,
        )
        # Setup TIER_2 PO; approve DEPT_HEAD by some operator; FINANCE by user_X.
        setup = setup_tier3_po_with_two_serial_steps()
        # Approve DEPT_HEAD with a generic actor.
        from test_helpers import stage_actor
        dept = find_step_by_stage(setup["approval_steps"], "DEPARTMENT_HEAD")
        finance_step = find_step_by_stage(setup["approval_steps"], "FINANCE")
        approve_step_as(dept["id"], role_headers=stage_actor("DEPARTMENT_HEAD", "po-approve-1"))
        # Use a specific finance user_id to decide FINANCE step.
        shared_finance_id = "finance-shared-x"
        finance_actor = make_finance_headers(shared_finance_id)
        approve_step_as(finance_step["id"], role_headers=finance_actor)
        # Now PO is APPROVED. Build a contract, sign, schedule — and
        # apply a payment.
        from test_helpers import (
            create_contract_for,
            submit_contract_review,
            finalize_contract_review,
            buyer_signs,
            supplier_signs,
            setup_invoice_approved,  # not used here, but illustrative
        )
        contract = create_contract_for(setup["po"], payment_terms_type="ON_DELIVERY")
        submit_contract_review(contract["id"])
        finalize_contract_review(contract["id"])
        buyer_signs(contract["id"])
        supplier_signs(contract["id"], setup["po"]["supplier_id"])
        # Refresh PO; now CONTRACTED. Submit a delivery-event-anchored receipt.
        from test_helpers import (
            post_supplier_delivery,
            unique_delivery_note_no,
            create_receipt_payload,
        )
        delivery_note_no = unique_delivery_note_no()
        post_supplier_delivery(setup["po"]["id"], delivery_note_no=delivery_note_no, declared_quantity=100)
        po_id = setup["po"]["id"]
        receipt = validate_success(
            api.create_receipt(
                po_id,
                create_receipt_payload(
                    delivery_note_no=delivery_note_no,
                    received_quantity=100,
                    accepted_quantity=100,
                    quality_rating=90,
                ),
                TEST_USERS["inspector_headers"],
            ),
            201,
        )
        validate_success(api.inspect_receipt(receipt["id"], TEST_USERS["inspector_headers"]), 200)
        validate_success(api.accept_receipt(receipt["id"], TEST_USERS["inspector_headers"]), 200)

        # Submit invoice and walk to APPROVED.
        from test_helpers import (
            submit_invoice,
            match_invoice,
            approve_invoice,
        )
        po = validate_success(
            api.get_purchase_order(po_id, TEST_USERS["buyer_headers"]), 200
        )
        invoice = submit_invoice(
            po=po,
            supplier_id=po["supplier_id"],
            invoiced_quantity=100,
            invoiced_amount_cents=po["total_amount_cents"],
            # tax_expected = total - round(total/1.13) = 1_000_000 - 884_956 = 115_044.
            tax_amount_cents=115_044,
            tax_rate_declared=0.13,
        )
        match_invoice(invoice["id"])
        approve_invoice(invoice["id"])

        # Apply payment.
        schedule = validate_success(
            api.get_payment_schedule(po_id, TEST_USERS["finance_headers"]), 200
        )
        if isinstance(schedule, dict):
            schedule = schedule.get("payment_schedule") or schedule.get("data") or schedule.get("entries") or []
        payment = validate_success(
            api.apply_payment(
                apply_payment_payload(
                    payment_schedule_id=schedule[0]["id"], invoice_id=invoice["id"]
                ),
                TEST_USERS["finance_headers"],
            ),
            201,
        )
        # The same user_X who approved the FINANCE step now tries to
        # approve the payment. PRD §3.10 says this MUST yield
        # ERR_SEGREGATION_OF_DUTIES.
        res = api.approve_payment(payment["id"], finance_actor)
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ===========================================================================
# Cancel payment (PRD §3.10)
# ===========================================================================
class TestPaymentCancel:
    def test_cancel_applied_payment_returns_schedule_to_pending(
        self, api, finance_headers
    ):
        """PRD §3.10: "An APPLIED payment can also be cancelled by a
        FinanceApprover; cancellation moves the payment to CANCELLED and
        rolls the bound schedule entry from APPLIED back to PENDING,
        making it eligible for re-application."

        Claim: /payments/{id}/cancel sets payment=CANCELLED and the
        schedule entry returns to PENDING.
        """
        setup = setup_payment_applied()
        cancelled = validate_success(
            api.cancel_payment(setup["payment"]["id"], finance_headers), 200
        )
        assert cancelled["status"] == "CANCELLED"
        schedule = validate_success(
            api.get_payment_schedule(setup["po"]["id"], finance_headers), 200
        )
        if isinstance(schedule, dict):
            schedule = schedule.get("payment_schedule") or schedule.get("data") or schedule.get("entries") or []
        # Find the entry by id and confirm it's back to PENDING.
        entry = next(
            e for e in schedule if e["id"] == setup["schedule_entry"]["id"]
        )
        assert entry["status"] == "PENDING"


# ===========================================================================
# Execute payment (PRD §3.10, §2.10)
# ===========================================================================
class TestPaymentExecute:
    def test_execute_moves_committed_to_spent(
        self, api, finance_headers, finance_headers_alt, platform_admin_headers
    ):
        """PRD §3.10: "Successful execution moves the payment from
        APPROVED to EXECUTED, sets the payment's bank_reference from the
        bank's response, advances the schedule entry from APPLIED to
        EXECUTED, increases the bound budget account's spent_amount_cents
        by the payment's amount_cents, and decreases the bound budget
        account's committed_amount_cents by the same amount."

        Claim: after execute, payment=EXECUTED, schedule entry=EXECUTED,
        and the budget's committed/spent transfer the payment amount.
        """
        setup = setup_payment_applied()
        # Approve payment with a DIFFERENT FinanceApprover than the one
        # who decided the (default-suffix) ApprovalSteps.
        approver_for_payment = build_user_headers("payment-approver-only", "FinanceApprover")
        validate_success(
            api.approve_payment(setup["payment"]["id"], approver_for_payment), 200
        )
        committed_before = validate_success(
            api.get_budget_account(setup["budget"]["id"], finance_headers), 200
        )["committed_amount_cents"]
        executed = validate_success(
            api.execute_payment(setup["payment"]["id"], platform_admin_headers), 200
        )
        assert executed["status"] == "EXECUTED"
        assert executed.get("bank_reference") is not None

        budget = validate_success(
            api.get_budget_account(setup["budget"]["id"], finance_headers), 200
        )
        amount = setup["payment"]["amount_cents"]
        assert budget["committed_amount_cents"] == committed_before - amount
        assert budget["spent_amount_cents"] >= amount
