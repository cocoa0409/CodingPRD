"""Reimbursement form: item attach, segment-category matching, submit
gating, final-settlement calculation (chronological-final, PRD §3.8).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_item_payload,
    api_client,
    approved_application,
    assert_form_totals_consistent,
    assert_reimbursement_form,
    assert_reimbursement_item,
    attach_item,
    book_segment_payload,
    create_form,
    create_form_payload,
    get_success_data,
    standard_test_environment,
    submit_form,
    upload_and_verify_invoice,
    upload_invoice_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import book_segment


# ---------------------------------------------------------------------------
# Form create (PRD §3.7)
# ---------------------------------------------------------------------------
class TestFormCreate:

    def test_create_form_initialises_totals_to_zero(self, api):
        """PRD §3.7: "Creating the form requires only the parent
        application_id; the form is created in DRAFT with applicant_id
        mirrored from the application, correction_round initialised to
        zero, and all four computed totals (total_claimed,
        total_reimbursable, total_self_paid) initialised to zero."

        Claim: form created in DRAFT with totals==0, correction_round=0,
        applicant_id mirrored from the application.
        """
        from test_helpers.fixtures import book_segment
        cast, approved = approved_application(estimated_budget=4_500.00)
        # Need at least one ACTIVE segment for application to be in BOOKING_LOCKED
        book_segment(
            cast, approved["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-02T11:00:00.000Z",
            cost=400.00,
        )
        form = validate_success(
            api.create_reimbursement_form(
                create_form_payload(approved["id"]),
                cast.applicant_headers,
            ),
            expected_status=201,
        )
        assert_reimbursement_form(form)
        assert form["status"] == "DRAFT"
        assert form["correction_round"] == 0
        assert form["total_claimed"] == pytest.approx(0.0)
        assert form["total_reimbursable"] == pytest.approx(0.0)
        assert form["total_self_paid"] == pytest.approx(0.0)
        assert form["applicant_id"] == cast.applicant["id"]


# ---------------------------------------------------------------------------
# Item attach: invoice state guard (PRD §3.7, priority 13)
# ---------------------------------------------------------------------------
class TestItemAttachInvoiceStateGuard:

    def test_attach_invoice_not_tax_verified_rejected(self, api):
        """PRD §3.7: "Each ReimbursementItem carries the parent form_id,
        an invoice_id referencing an Invoice whose ocr_status is
        currently TAX_VERIFIED... The error code for an attached invoice
        that is not currently in TAX_VERIFIED is ERR_INVOICE_NOT_VERIFIED."

        Claim: invoice in OCR_RECOGNIZED (not TAX_VERIFIED) → ERR_INVOICE_NOT_VERIFIED.
        """
        from test_helpers.fixtures import book_segment
        cast, approved = approved_application(estimated_budget=4_500.00)
        seg = book_segment(
            cast, approved["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-02T11:00:00.000Z",
            cost=400.00,
        )
        # Upload + OCR but do NOT tax-verify.
        inv = get_success_data(
            api.upload_invoice(
                upload_invoice_payload(
                    applicant_id=cast.applicant["id"],
                    category="LODGING", amount=400.00,
                    invoice_date="2025-06-01T20:00:00.000Z",
                ),
                cast.applicant_headers,
            )
        )
        get_success_data(api.ocr_invoice(inv["id"], cast.applicant_headers))
        # Now invoice is OCR_RECOGNIZED — attach must reject.
        form = create_form(cast, approved["id"])
        res = api.add_reimbursement_item(
            form["id"],
            add_item_payload(
                invoice_id=inv["id"], category="LODGING",
                covered_days=1, claimed_amount=400.00,
                matched_segment_id=seg["id"],
            ),
            cast.applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVOICE_NOT_VERIFIED.value)


# ---------------------------------------------------------------------------
# Item attach: segment-category matching (PRD §3.7, priority 12)
# ---------------------------------------------------------------------------
class TestItemSegmentMatching:

    def test_lodging_item_without_matched_segment_rejected(self, api):
        """PRD §3.7: "A matched_segment_id is required for LODGING and
        TRANSPORTATION items and is nullable for PER_DIEM and OTHER. The
        error code for any failure of segment matching or
        category–segment-type compatibility is ERR_INVOICE_NOT_MATCHED."

        Claim: LODGING item without matched_segment_id → ERR_INVOICE_NOT_MATCHED.
        """
        from test_helpers.fixtures import book_segment
        cast, approved = approved_application(estimated_budget=4_500.00)
        # Book HOTEL segment so the application is in BOOKING_LOCKED.
        book_segment(
            cast, approved["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-02T11:00:00.000Z",
            cost=400.00,
        )
        invoice = upload_and_verify_invoice(
            cast, category="LODGING", amount=400.00,
            invoice_date="2025-06-01T20:00:00.000Z",
        )
        form = create_form(cast, approved["id"])
        # LODGING with no matched_segment_id — must be rejected.
        res = api.add_reimbursement_item(
            form["id"],
            add_item_payload(
                invoice_id=invoice["id"], category="LODGING",
                covered_days=1, claimed_amount=400.00,
                matched_segment_id=None,
            ),
            cast.applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVOICE_NOT_MATCHED.value)

    def test_lodging_item_matched_to_flight_segment_rejected(self, api):
        """PRD §3.7: "an invoice attached as LODGING must match a HOTEL
        segment; an invoice attached as TRANSPORTATION must match a
        FLIGHT, TRAIN, or CAR segment... The error code for any failure
        of segment matching or category–segment-type compatibility is
        ERR_INVOICE_NOT_MATCHED."

        Claim: LODGING item matched to a FLIGHT segment → ERR_INVOICE_NOT_MATCHED.
        """
        from test_helpers.fixtures import book_segment
        cast, approved = approved_application(estimated_budget=4_500.00)
        flight = book_segment(
            cast, approved["id"], segment_type="FLIGHT",
            start_at="2025-06-01T10:00:00.000Z",
            end_at="2025-06-01T13:00:00.000Z",
            cost=400.00,
        )
        invoice = upload_and_verify_invoice(
            cast, category="LODGING", amount=400.00,
            invoice_date="2025-06-01T12:00:00.000Z",
        )
        form = create_form(cast, approved["id"])
        res = api.add_reimbursement_item(
            form["id"],
            add_item_payload(
                invoice_id=invoice["id"], category="LODGING",
                covered_days=1, claimed_amount=400.00,
                matched_segment_id=flight["id"],
            ),
            cast.applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVOICE_NOT_MATCHED.value)


# ---------------------------------------------------------------------------
# Item attach side-effect: Invoice TAX_VERIFIED → ATTACHED (PRD §3.7)
# ---------------------------------------------------------------------------
class TestAttachInvoiceTransitions:

    def test_attach_transitions_invoice_to_attached(self, api):
        """PRD §3.7: "Successfully attaching an item moves the underlying
        Invoice from TAX_VERIFIED to ATTACHED."

        Claim: invoice.ocr_status is ATTACHED after successful item attach.
        """
        from test_helpers.fixtures import book_segment
        cast, approved = approved_application(estimated_budget=4_500.00)
        seg = book_segment(
            cast, approved["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-02T11:00:00.000Z",
            cost=400.00,
        )
        invoice = upload_and_verify_invoice(
            cast, category="LODGING", amount=400.00,
            invoice_date="2025-06-01T20:00:00.000Z",
        )
        assert invoice["ocr_status"] == "TAX_VERIFIED"
        form = create_form(cast, approved["id"])
        attach_item(
            cast, form["id"], invoice_id=invoice["id"],
            category="LODGING", covered_days=1, claimed_amount=400.00,
            matched_segment_id=seg["id"],
        )
        after = validate_success(
            api.get_invoice(invoice["id"], cast.applicant_headers),
        )
        assert after["ocr_status"] == "ATTACHED"

    def test_delete_item_reverts_invoice_to_tax_verified(self, api):
        """PRD §3.7: "Removing an item from a draft form moves the
        underlying Invoice from ATTACHED back to TAX_VERIFIED."

        Claim: DELETE /reimbursement-forms/{id}/items/{itemId} reverts
        the invoice to TAX_VERIFIED.
        """
        from test_helpers.fixtures import book_segment
        cast, approved = approved_application(estimated_budget=4_500.00)
        seg = book_segment(
            cast, approved["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-02T11:00:00.000Z",
            cost=400.00,
        )
        invoice = upload_and_verify_invoice(
            cast, category="LODGING", amount=400.00,
            invoice_date="2025-06-01T20:00:00.000Z",
        )
        form = create_form(cast, approved["id"])
        item = attach_item(
            cast, form["id"], invoice_id=invoice["id"],
            category="LODGING", covered_days=1, claimed_amount=400.00,
            matched_segment_id=seg["id"],
        )
        # DELETE returns 204 with empty body per PRD §4.
        del_res = api.delete_reimbursement_item(
            form["id"], item["id"], cast.applicant_headers,
        )
        assert del_res.status_code == 204, (
            "PRD §4: DELETE /reimbursement-forms/{id}/items/{itemId} "
            "returns 204 with empty body"
        )
        after = validate_success(
            api.get_invoice(invoice["id"], cast.applicant_headers),
        )
        assert after["ocr_status"] == "TAX_VERIFIED"


# ---------------------------------------------------------------------------
# Submit gating (PRD §3.7)
# ---------------------------------------------------------------------------
class TestFormSubmitGating:

    def test_submit_form_with_no_items_rejected(self, api):
        """PRD §3.7: "Submission is admissible only when the parent
        application's status is BOOKING_LOCKED or COMPLETED, at least
        one ReimbursementItem exists, and every attached Invoice has
        ocr_status equal to ATTACHED."

        Claim: form with zero items → submit returns ERR_INVALID_STATE.
        """
        from test_helpers.fixtures import book_segment
        cast, approved = approved_application(estimated_budget=4_500.00)
        book_segment(
            cast, approved["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-02T11:00:00.000Z",
            cost=400.00,
        )
        form = create_form(cast, approved["id"])
        res = api.submit_reimbursement_form(
            form["id"], cast.applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Final-settlement calculation (PRD §3.8)
# ---------------------------------------------------------------------------
class TestFinalSettlementCalculation:

    def test_self_paid_equals_excess_above_cap(self, api):
        """PRD §3.8: "Each item's standard_cap_applied is then set to
        the per-unit cap multiplied by the item's covered_days, rounded
        to two decimal places using round-half-up. The item's
        reimbursable_amount is the lesser of claimed_amount and
        standard_cap_applied. The item's self_paid_amount is the greater
        of zero and (claimed_amount minus standard_cap_applied)."

        Claim: lodging_daily_cap=400, covered_days=3, claimed=1350 ⇒
        standard_cap_applied=1200, reimbursable=1200, self_paid=150 ⇒
        total_self_paid=150 on the form.
        """
        from test_helpers.fixtures import approved_form_with_one_lodging_item
        cast, _app, _seg, _inv, approved_form = approved_form_with_one_lodging_item(
            lodging_daily_cap=400.00, covered_days=3, claimed_amount=1350.00,
        )
        assert approved_form["status"] == "APPROVED"
        # Re-fetch to be defensive — totals were computed at submit.
        form = validate_success(
            api.get_reimbursement_form(approved_form["id"],
                                       cast.applicant_headers),
        )
        assert form["total_claimed"] == pytest.approx(1350.00, abs=0.01)
        assert form["total_reimbursable"] == pytest.approx(1200.00, abs=0.01)
        assert form["total_self_paid"] == pytest.approx(150.00, abs=0.01)
        assert_form_totals_consistent(form)

    def test_form_under_cap_has_no_self_paid(self, api):
        """PRD §3.8: "The item's self_paid_amount is the greater of zero
        and (claimed_amount minus standard_cap_applied); a non-negative
        quantity by construction."

        Claim: claimed (600) < cap (1200) ⇒ self_paid=0,
        reimbursable=600, requires_special_approval=false on submit.
        """
        from test_helpers.fixtures import approved_form_no_self_paid
        cast, _app, _seg, _inv, approved_form = approved_form_no_self_paid()
        assert approved_form["status"] == "APPROVED"
        form = validate_success(
            api.get_reimbursement_form(approved_form["id"],
                                       cast.applicant_headers),
        )
        assert form["total_self_paid"] == pytest.approx(0.0, abs=0.01)
        assert form["total_reimbursable"] == pytest.approx(600.00, abs=0.01)
