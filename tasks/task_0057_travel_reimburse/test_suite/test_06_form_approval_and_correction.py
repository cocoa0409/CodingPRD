"""Reimbursement-form approval chain + reject-with-correction cycle.

Targets PRD §3.7 chain, §3.7 reject-with-correction (cyclic transition),
and the priority-15 ERR_GM_APPROVAL_REQUIRED rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    approval_payload,
    approved_application,
    attach_item,
    create_form,
    get_success_data,
    reject_form_payload,
    standard_test_environment,
    submit_form,
    upload_and_verify_invoice,
    validate_error,
    validate_success,
    walk_form_approval_chain,
)
from test_helpers.fixtures import (
    approved_form_with_one_lodging_item,
    approved_form_no_self_paid,
    book_segment,
)


# ---------------------------------------------------------------------------
# ERR_GM_APPROVAL_REQUIRED (PRD §3.7, priority 15)
# ---------------------------------------------------------------------------
class TestGmRequiredAtFinanceStep:

    def test_finance_cannot_approve_self_paid_form_to_approved(self, api):
        """PRD §3.7: "Any attempt by Finance to move a form whose
        requires_special_approval is true directly to APPROVED is
        rejected with ERR_GM_APPROVAL_REQUIRED."

        Claim: a form with total_self_paid>0 sitting at FINANCE_APPROVED
        — but the Finance officer issues a SECOND approve while
        requires_special_approval==true — receives ERR_GM_APPROVAL_REQUIRED.

        Implementation note: the PRD-faithful read is that FINANCE moves
        the form FROM DEPT_APPROVED → FINANCE_APPROVED (priority-15 fires
        only if Finance attempts to reach APPROVED on a special-approval
        form). We thus walk the form to FINANCE_APPROVED, then try a
        second Finance approve which would otherwise close out (Finance
        completes the chain for non-special forms): that call must be
        rejected with ERR_GM_APPROVAL_REQUIRED.
        """
        # Build a self-paid form and stop at FINANCE_APPROVED so we can
        # probe the ERR_GM_APPROVAL_REQUIRED guard.
        cast, _std = standard_test_environment(
            lodging_daily_cap=400.00,
        )
        from test_helpers.fixtures import (
            draft_application, walk_approval_chain, book_segment,
        )
        app = draft_application(cast, estimated_budget=2_000.00)
        walk_approval_chain(cast, app)
        seg = book_segment(
            cast, app["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-04T11:00:00.000Z",
            cost=1350.00,
        )
        invoice = upload_and_verify_invoice(
            cast, category="LODGING", amount=1350.00,
            invoice_date="2025-06-02T12:00:00.000Z",
        )
        form = create_form(cast, app["id"])
        attach_item(
            cast, form["id"], invoice_id=invoice["id"], category="LODGING",
            covered_days=3, claimed_amount=1350.00,
            matched_segment_id=seg["id"],
        )
        submitted = submit_form(cast, form["id"])
        assert submitted["requires_special_approval"] is True, (
            "PRD §3.8: total_self_paid > 0 ⇒ requires_special_approval=true"
        )
        # Walk to FINANCE_APPROVED only.
        partial = walk_form_approval_chain(
            cast, submitted, stop_at_state="FINANCE_APPROVED",
        )
        assert partial["status"] == "FINANCE_APPROVED"

        # Finance attempts to issue the terminal approval (the "shortcut")
        # on a special-approval form — must be rejected.
        res = api.approve_reimbursement_form(
            form["id"], cast.finance_headers, approval_payload(),
        )
        validate_error(res, ApiErrorId.ERR_GM_APPROVAL_REQUIRED.value)


# ---------------------------------------------------------------------------
# Two terminal paths to APPROVED (PRD §3.7)
# ---------------------------------------------------------------------------
class TestTwoTerminalPaths:

    def test_finance_approves_non_special_form_to_approved(self, api):
        """PRD §3.7: "If the form's requires_special_approval is false,
        Finance may directly transition the form to APPROVED; this is
        the simple finance-approves path."

        Claim: a form with no self-paid amount lands at APPROVED via the
        FINANCE_APPROVED → APPROVED transition (no GM step).
        """
        cast, _app, _seg, _inv, approved_form = approved_form_no_self_paid()
        assert approved_form["status"] == "APPROVED"
        # No GM step in the chain — re-fetch and check special_approval_granted
        # was never set true.
        form = validate_success(
            api.get_reimbursement_form(approved_form["id"],
                                       cast.applicant_headers),
        )
        assert form["special_approval_granted"] is False

    def test_gm_approval_lands_special_form_at_approved(self, api):
        """PRD §3.7: "If the form's requires_special_approval is true,
        Finance MUST advance the form to GM_APPROVED and a GeneralManager
        then issues the final approval, which sets special_approval_granted
        to true and, via a system auto-transition, lands the form in APPROVED."

        Claim: a self-paid form walks SUPERVISOR → DEPT_HEAD → FINANCE →
        GM → APPROVED, with special_approval_granted=true.
        """
        cast, _app, _seg, _inv, approved_form = approved_form_with_one_lodging_item(
            lodging_daily_cap=400.00, covered_days=3, claimed_amount=1350.00,
        )
        assert approved_form["status"] == "APPROVED"
        form = validate_success(
            api.get_reimbursement_form(approved_form["id"],
                                       cast.applicant_headers),
        )
        assert form["special_approval_granted"] is True


# ---------------------------------------------------------------------------
# Reject-with-correction cycle (PRD §3.7)
# ---------------------------------------------------------------------------
class TestRejectWithCorrectionCycle:

    def test_reject_with_correction_returns_to_draft_and_bumps_round(self, api):
        """PRD §3.7: "A reject with correction set to true returns the
        form from any of SUBMITTED, SUPERVISOR_APPROVED, DEPT_APPROVED,
        or FINANCE_APPROVED to DRAFT, increments correction_round by 1,
        reverts every attached Invoice from ATTACHED back to TAX_VERIFIED,
        and writes one ApprovalRecord whose action is REJECT and whose
        comment carries the supplied rejection_reason."

        Claim: after reject-with-correction from SUPERVISOR_APPROVED:
        form is DRAFT, correction_round=1, every attached invoice is back
        to TAX_VERIFIED.
        """
        cast, _std = standard_test_environment()
        from test_helpers.fixtures import draft_application, walk_approval_chain
        app = draft_application(cast, estimated_budget=2_000.00)
        walk_approval_chain(cast, app)
        seg = book_segment(
            cast, app["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-04T11:00:00.000Z",
            cost=600.00,
        )
        invoice = upload_and_verify_invoice(
            cast, category="LODGING", amount=600.00,
            invoice_date="2025-06-02T12:00:00.000Z",
        )
        form = create_form(cast, app["id"])
        attach_item(
            cast, form["id"], invoice_id=invoice["id"], category="LODGING",
            covered_days=3, claimed_amount=600.00,
            matched_segment_id=seg["id"],
        )
        submitted = submit_form(cast, form["id"])
        # SUPERVISOR approves → SUPERVISOR_APPROVED
        get_success_data(
            api.approve_reimbursement_form(
                form["id"], cast.supervisor_headers, approval_payload(),
            )
        )
        # DeptHead rejects with correction=true
        rejected = validate_success(
            api.reject_reimbursement_form(
                form["id"],
                reject_form_payload(
                    rejection_reason="Need updated receipts",
                    correction=True,
                ),
                cast.dept_head_headers,
            ),
        )
        assert rejected["status"] == "DRAFT", (
            "PRD §3.7: reject-with-correction returns form to DRAFT"
        )
        assert rejected["correction_round"] == 1, (
            "PRD §3.7: correction_round increments by 1"
        )
        # Invoice should be back to TAX_VERIFIED.
        inv_after = validate_success(
            api.get_invoice(invoice["id"], cast.applicant_headers),
        )
        assert inv_after["ocr_status"] == "TAX_VERIFIED", (
            "PRD §3.7: revert every attached Invoice from ATTACHED back to TAX_VERIFIED"
        )

    def test_reject_without_correction_terminates(self, api):
        """PRD §3.7: "A reject with correction set to false terminates
        the form: it transitions from SUBMITTED to REJECTED and writes
        the same ApprovalRecord, but does not revert invoices or
        increment the correction counter."

        Claim: reject-without-correction from SUBMITTED → REJECTED,
        no invoice revert, correction_round unchanged.
        """
        cast, _std = standard_test_environment()
        from test_helpers.fixtures import draft_application, walk_approval_chain
        app = draft_application(cast, estimated_budget=2_000.00)
        walk_approval_chain(cast, app)
        seg = book_segment(
            cast, app["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-04T11:00:00.000Z",
            cost=600.00,
        )
        invoice = upload_and_verify_invoice(
            cast, category="LODGING", amount=600.00,
            invoice_date="2025-06-02T12:00:00.000Z",
        )
        form = create_form(cast, app["id"])
        attach_item(
            cast, form["id"], invoice_id=invoice["id"], category="LODGING",
            covered_days=3, claimed_amount=600.00,
            matched_segment_id=seg["id"],
        )
        submit_form(cast, form["id"])
        # Supervisor rejects with correction=false
        rejected = validate_success(
            api.reject_reimbursement_form(
                form["id"],
                reject_form_payload(
                    rejection_reason="Out of policy", correction=False,
                ),
                cast.supervisor_headers,
            ),
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["correction_round"] == 0, (
            "PRD §3.7: reject-without-correction does not increment correction_round"
        )
        # Invoice stays ATTACHED because PRD §3.7 explicitly says
        # reject-without-correction does NOT revert invoices.
        inv_after = validate_success(
            api.get_invoice(invoice["id"], cast.applicant_headers),
        )
        assert inv_after["ocr_status"] == "ATTACHED"
