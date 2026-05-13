"""Concurrency + audit + end-to-end integration.

Race tests cover only the scenarios PRD explicitly pins (PRD §3.6
"duplicate-attach hazard", PRD §3.2 "simultaneity hazard", PRD §3.9
"Two Finance officers clicking execute"). The integration test walks
the full happy-path lifecycle through to PAID.
"""
from __future__ import annotations
import uuid

import pytest

from test_helpers import (
    ApiErrorId,
    add_item_payload,
    api_client,
    approval_payload,
    approved_application,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    attach_item,
    book_segment_payload,
    create_form,
    create_payment_batch,
    execute_payment,
    get_success_data,
    payment_pending,
    post_payment_outcome,
    run_race,
    standard_test_environment,
    submit_application,
    submit_form,
    upload_and_verify_invoice,
    upload_invoice_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    walk_approval_chain,
    walk_form_approval_chain,
)
from test_helpers.fixtures import (
    ADMIN,
    book_segment,
    approved_form_no_self_paid,
    draft_application,
)


# ---------------------------------------------------------------------------
# Race: two simultaneous attaches of the same TAX_VERIFIED invoice (PRD §3.6)
# ---------------------------------------------------------------------------
class TestDuplicateAttachRace:

    def test_only_one_form_can_attach_a_tax_verified_invoice(self, api):
        """PRD §3.6: "The duplicate-attach hazard appears when two
        different ReimbursementForms race to attach the same
        TAX_VERIFIED invoice. At most one attach succeeds; the loser
        sees Invoice.ocr_status already at ATTACHED and receives
        ERR_INVOICE_ALREADY_ATTACHED (HTTP 409). The serialisation
        guarantee is first-writer-wins on the invoice's ocr_status."

        Claim: two simultaneous attach calls → exactly one succeeds,
        the loser sees ERR_INVOICE_ALREADY_ATTACHED.
        """
        cast, _std = standard_test_environment()
        # Two APPROVED applications under the same applicant, each with
        # a HOTEL segment whose window encloses the same invoice date.
        app_a = draft_application(cast, estimated_budget=2_000.00)
        walk_approval_chain(cast, app_a)
        seg_a = book_segment(
            cast, app_a["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-04T11:00:00.000Z",
            cost=400.00,
        )
        app_b = draft_application(cast, estimated_budget=2_000.00)
        walk_approval_chain(cast, app_b)
        seg_b = book_segment(
            cast, app_b["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-04T11:00:00.000Z",
            cost=400.00,
        )

        # One TAX_VERIFIED invoice — race for it across two forms.
        invoice = upload_and_verify_invoice(
            cast, category="LODGING", amount=400.00,
            invoice_date="2025-06-02T12:00:00.000Z",
        )
        form_a = create_form(cast, app_a["id"])
        form_b = create_form(cast, app_b["id"])

        def attach_via(form_id: str, seg_id: str):
            return api.add_reimbursement_item(
                form_id,
                add_item_payload(
                    invoice_id=invoice["id"], category="LODGING",
                    covered_days=1, claimed_amount=400.00,
                    matched_segment_id=seg_id,
                ),
                cast.applicant_headers,
            )

        results = run_race(
            lambda: attach_via(form_a["id"], seg_a["id"]),
            lambda: attach_via(form_b["id"], seg_b["id"]),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # The loser must carry ERR_INVOICE_ALREADY_ATTACHED.
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVOICE_ALREADY_ATTACHED.value)


# ---------------------------------------------------------------------------
# Race: two FINANCE officers /execute the same PENDING payment (PRD §3.9)
# ---------------------------------------------------------------------------
class TestPaymentExecuteRace:

    def test_simultaneous_execute_only_one_succeeds(self, api):
        """PRD §3.9: "Two Finance officers clicking execute on the same
        PENDING payment race: exactly one attempt_count increment
        succeeds, and the loser sees the payment already EXECUTING and
        receives ERR_INVALID_STATE (HTTP 409). The serialisation
        guarantee is first-writer-wins on the payment's status using
        the OCC version."

        Claim: two simultaneous /execute calls → exactly one succeeds,
        loser returns ERR_INVALID_STATE.
        """
        cast, _approved, _batch, pending = payment_pending(
            fixture_factory=approved_form_no_self_paid,
        )
        results = run_race(
            lambda: api.execute_payment(pending["id"], cast.finance_headers),
            lambda: api.execute_payment(pending["id"], cast.finance_headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Race: two simultaneous /approve calls on the same chain step (PRD §3.2)
# ---------------------------------------------------------------------------
class TestApprovalRace:

    def test_simultaneous_approve_at_supervisor_step_only_one_succeeds(self, api):
        """PRD §3.2: "A simultaneity hazard exists at every step: two
        approvers (or the same approver under retry) in the same chain
        step click approve on the same application at the same time.
        Exactly one transition succeeds; the loser sees the application
        already in the next status, and receives ERR_INVALID_STATE
        (HTTP 409). The serialisation guarantee is first-writer-wins on
        the application's status using the OCC version."

        Claim: two simultaneous SUPERVISOR-step approvals → exactly one
        succeeds; the loser returns ERR_INVALID_STATE.
        """
        cast, _std = standard_test_environment()
        app = draft_application(cast, estimated_budget=4_500.00)
        submit_application(cast, app)
        results = run_race(
            lambda: api.approve_travel_application(
                app["id"], cast.supervisor_headers, approval_payload(),
            ),
            lambda: api.approve_travel_application(
                app["id"], cast.supervisor_headers, approval_payload(),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Audit + ApprovalRecord stream (PRD §3.10)
# ---------------------------------------------------------------------------
class TestApprovalRecordStream:

    def test_approval_records_emitted_per_approve(self, api):
        """PRD §3.10: "The approval-records stream lists every
        ApprovalRecord row — that is, every approve and every reject
        ever issued against either a TRAVEL_APPLICATION or a
        REIMBURSEMENT_FORM — and supports filtering by subject_type,
        subject_id, and actor_id."

        Claim: filtering the approval-records stream by an APPROVED
        application's subject_id surfaces at least one ApprovalRecord
        per chain step taken.
        """
        cast, approved = approved_application(
            estimated_budget=4_500.00,
        )
        data, _meta = validate_paginated(
            api.list_approval_records(
                cast.finance_headers,
                params={
                    "subject_type": "TRAVEL_APPLICATION",
                    "subject_id": approved["id"],
                },
            )
        )
        # The chain was [SUPERVISOR, FINANCE]; there should be at least
        # two APPROVE rows.
        approve_rows = [r for r in data if r.get("action") == "APPROVE"]
        assert len(approve_rows) >= 2, (
            "PRD §3.10: every approve writes one ApprovalRecord; a "
            "two-step approval should surface at least two APPROVE rows"
        )


# ---------------------------------------------------------------------------
# Full happy-path integration: app submit → APPROVED → book → form → PAID
# ---------------------------------------------------------------------------
class TestFullLifecycleIntegration:

    def test_end_to_end_through_paid(self, api):
        """PRD §3.9: "A SUCCESS outcome transitions the payment from
        EXECUTING to SUCCESS, sets external_ref, and cascades two
        further state changes: the parent ReimbursementForm transitions
        from APPROVED to PAID, and every Invoice that any of the form's
        ReimbursementItems reference (via invoice_id) transitions from
        ATTACHED to CONSUMED."

        Claim: the complete lifecycle (employee bootstrap → standard
        publish → application submit → approval chain → booking →
        invoice upload + verify → form item attach → form submit →
        form approval chain → payment batch → execute → SUCCESS
        callback) ends with form in PAID and the attached invoice in
        CONSUMED.
        """
        from test_helpers.fixtures import approved_form_with_one_lodging_item
        cast, _app, _seg, invoice, approved_form = (
            approved_form_with_one_lodging_item(
                lodging_daily_cap=400.00, covered_days=3,
                claimed_amount=1350.00,
            )
        )
        assert approved_form["status"] == "APPROVED"

        # Finance creates the batch
        create_payment_batch(cast, [approved_form["id"]])
        data, _meta = validate_paginated(
            api.list_payments(
                cast.finance_headers,
                params={"form_id": approved_form["id"]},
            )
        )
        assert len(data) == 1
        payment = data[0]

        # Execute + SUCCESS callback
        execute_payment(cast, payment["id"])
        success = post_payment_outcome(
            cast, payment["id"], outcome="SUCCESS",
        )
        assert success["status"] == "SUCCESS"
        assert success["external_ref"] is not None

        # Form must now be PAID
        form_after = validate_success(
            api.get_reimbursement_form(
                approved_form["id"], cast.applicant_headers,
            ),
        )
        assert form_after["status"] == "PAID"

        # Invoice must now be CONSUMED
        invoice_after = validate_success(
            api.get_invoice(invoice["id"], cast.applicant_headers),
        )
        assert invoice_after["ocr_status"] == "CONSUMED"
