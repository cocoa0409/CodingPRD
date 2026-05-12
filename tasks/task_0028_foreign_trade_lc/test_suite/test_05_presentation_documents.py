"""Presentation creation, document attachment, document-frozen, and
drawing-cap boundary (PRD §3.5)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_document,
    assert_presentation,
    attach_bill_of_lading,
    attach_certificate_of_origin,
    attach_commercial_invoice,
    bill_of_lading_payload,
    certificate_of_origin_payload,
    commercial_invoice_payload,
    create_presentation,
    create_presentation_payload,
    get_clock,
    get_lc,
    iso_z,
    parse_iso,
    setup_active_lc,
    setup_examined_clean_presentation,
    setup_party_bundle,
    setup_paid_sight_settlement,
    setup_presentation_with_clean_documents,
    start_examination,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.5 — Presentation creation
# ===========================================================================
class TestPresentationCreation:

    def test_create_presentation_starts_in_submitted(self, api):
        """PRD §3.5: 'The system mints a presentation_seq per LC starting
        at 1, sets presented_at to the server clock, and starts the row
        in status SUBMITTED.'"""
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        res = api.create_presentation(
            lc["id"],
            create_presentation_payload(
                shipment_date=ship_date,
                drawing_amount_minor_units=5_000,
            ),
            bundle["beneficiary_headers"],
        )
        presentation = validate_success(res, expected_status=201)
        assert_presentation(presentation)
        assert presentation["status"] == "SUBMITTED"
        assert presentation["presentation_seq"] == 1, (
            "PRD §3.5: 'a presentation_seq per LC starting at 1'"
        )

    def test_shipment_date_after_latest_shipment_rejected(self, api):
        """PRD §3.5: 'The shipment_date must be on or before the LC's
        latest_shipment_date and on or before the current server clock —
        if either condition fails the request is rejected with
        ERR_SHIPMENT_OUT_OF_WINDOW.'"""
        now = parse_iso(get_clock()["now"])
        lc, bundle = setup_active_lc(
            amount_minor_units=10_000,
            latest_shipment_date=iso_z(now + timedelta(days=10)),
            expiry_date=iso_z(now + timedelta(days=60)),
        )
        # Ship 30 days from now — past LC.latest_shipment_date.
        ship_date = iso_z(now + timedelta(days=30))
        res = api.create_presentation(
            lc["id"],
            create_presentation_payload(
                shipment_date=ship_date,
                drawing_amount_minor_units=5_000,
            ),
            bundle["beneficiary_headers"],
        )
        validate_error(res, "ERR_SHIPMENT_OUT_OF_WINDOW")

    def test_shipment_date_in_future_rejected(self, api):
        """PRD §3.5: 'The shipment_date must be ... on or before the
        current server clock — if either condition fails the request
        is rejected with ERR_SHIPMENT_OUT_OF_WINDOW.'"""
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        now = parse_iso(get_clock()["now"])
        future = iso_z(now + timedelta(days=2))
        res = api.create_presentation(
            lc["id"],
            create_presentation_payload(
                shipment_date=future,
                drawing_amount_minor_units=5_000,
            ),
            bundle["beneficiary_headers"],
        )
        validate_error(res, "ERR_SHIPMENT_OUT_OF_WINDOW")

    def test_drawing_above_available_rejected(self, api):
        """PRD §3.5: 'The drawing_amount_minor_units must be strictly
        positive and must not exceed available_amount_minor_units; an
        over-draw raises ERR_LC_INSUFFICIENT_AVAILABLE.'"""
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        res = api.create_presentation(
            lc["id"],
            create_presentation_payload(
                shipment_date=ship_date,
                drawing_amount_minor_units=10_001,   # > 10000 cap
            ),
            bundle["beneficiary_headers"],
        )
        validate_error(res, "ERR_LC_INSUFFICIENT_AVAILABLE")

    def test_drawing_at_inclusive_upper_boundary_accepted(self, api):
        """PRD §3.5: 'The drawing_amount_minor_units must be strictly
        positive and must not exceed available_amount_minor_units'.

        Boundary: drawing == available is allowed (not exceed = '<=').
        """
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        res = api.create_presentation(
            lc["id"],
            create_presentation_payload(
                shipment_date=ship_date,
                drawing_amount_minor_units=10_000,
            ),
            bundle["beneficiary_headers"],
        )
        presentation = validate_success(res, expected_status=201)
        assert presentation["drawing_amount_minor_units"] == 10_000


# ===========================================================================
# §3.5 — Document attachment
# ===========================================================================
class TestDocumentAttachment:

    def test_attach_required_document_succeeds(self, api):
        """PRD §3.5: 'Once the presentation row exists, the beneficiary
        attaches each Document referenced by required_documents.'"""
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        presentation = create_presentation(
            lc_id=lc["id"], beneficiary_headers=bundle["beneficiary_headers"],
            drawing_amount_minor_units=5_000, shipment_date=ship_date,
        )
        res = api.attach_document(
            presentation["id"],
            commercial_invoice_payload(stated_amount_minor_units=5_000),
            bundle["beneficiary_headers"],
        )
        doc = validate_success(res, expected_status=201)
        assert_document(doc)
        assert doc["document_type"] == "COMMERCIAL_INVOICE"

    def test_attach_unrequired_document_rejected(self, api):
        """PRD §3.5: 'The document is rejected with
        ERR_DOCUMENT_NOT_REQUIRED_OR_DUPLICATE when its document_type
        does not appear in the LC's required_documents list ...'."""
        lc, bundle = setup_active_lc(
            amount_minor_units=10_000,
            required_documents=["COMMERCIAL_INVOICE", "BILL_OF_LADING"],
        )
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        presentation = create_presentation(
            lc_id=lc["id"], beneficiary_headers=bundle["beneficiary_headers"],
            drawing_amount_minor_units=5_000, shipment_date=ship_date,
        )
        # PACKING_LIST not in required_documents.
        res = api.attach_document(
            presentation["id"],
            {
                "document_type": "PACKING_LIST",
                "issuer": "Test Packer",
                "document_date": ship_date,
                "stated_amount_minor_units": 0,
                "stated_currency": "USD",
                "payload": {},
            },
            bundle["beneficiary_headers"],
        )
        validate_error(res, "ERR_DOCUMENT_NOT_REQUIRED_OR_DUPLICATE")

    def test_duplicate_non_invoice_document_rejected(self, api):
        """PRD §3.5: '... or when it duplicates an existing document of
        the same type for the same presentation; the only document_type
        that may legitimately duplicate per presentation is
        COMMERCIAL_INVOICE.'"""
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        presentation = create_presentation(
            lc_id=lc["id"], beneficiary_headers=bundle["beneficiary_headers"],
            drawing_amount_minor_units=5_000, shipment_date=ship_date,
        )
        # Two BILL_OF_LADING attachments — second must be rejected.
        attach_bill_of_lading(
            presentation["id"], bundle["beneficiary_headers"],
            shipped_on_board_date=ship_date,
        )
        res = api.attach_document(
            presentation["id"],
            bill_of_lading_payload(shipped_on_board_date=ship_date),
            bundle["beneficiary_headers"],
        )
        validate_error(res, "ERR_DOCUMENT_NOT_REQUIRED_OR_DUPLICATE")

    def test_duplicate_commercial_invoice_allowed(self, api):
        """PRD §3.5: 'the only document_type that may legitimately
        duplicate per presentation is COMMERCIAL_INVOICE.'"""
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        presentation = create_presentation(
            lc_id=lc["id"], beneficiary_headers=bundle["beneficiary_headers"],
            drawing_amount_minor_units=5_000, shipment_date=ship_date,
        )
        attach_commercial_invoice(
            presentation["id"], bundle["beneficiary_headers"],
            stated_amount_minor_units=2_500,
        )
        res = api.attach_document(
            presentation["id"],
            commercial_invoice_payload(stated_amount_minor_units=2_500),
            bundle["beneficiary_headers"],
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# §3.5 — Documents frozen on examination start
# ===========================================================================
class TestDocumentsFrozen:

    def test_attach_after_examination_start_rejected(self, api):
        """PRD §3.5: 'from this moment the document set is FROZEN — any
        subsequent attempt to attach or mutate a document on this
        presentation is rejected with ERR_DOCUMENTS_FROZEN until either
        examination is FINALIZED or the report is RESET after a CONFLICT.'"""
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        presentation = setup_presentation_with_clean_documents(
            lc=lc, bundle=bundle, drawing_amount_minor_units=5_000,
        )
        # Start examination — documents are now frozen.
        start_examination(presentation["id"], bundle["issuing_bank_headers"])
        # Try to attach another invoice.
        res = api.attach_document(
            presentation["id"],
            commercial_invoice_payload(stated_amount_minor_units=2_500),
            bundle["beneficiary_headers"],
        )
        validate_error(res, "ERR_DOCUMENTS_FROZEN")


# ===========================================================================
# §3.5 — Aggregate-capacity overlap on /presentations
# ===========================================================================
class TestAggregateCapacity:

    def test_second_presentation_after_settle_overdraws(self, api):
        """PRD §3.5: 'The drawn portion is the sum, across all
        PaymentSettlement rows whose lc_id matches and whose status is
        in the set ACCEPTED or PAID ... of each settlement's
        principal_minor_units. The available amount is then the cap
        minus the drawn portion, with the result clamped to be no less
        than zero.'

        After P1 drawing 7000 settles, available drops to 3000. A second
        presentation drawing 4000 must fail with
        ERR_LC_INSUFFICIENT_AVAILABLE.
        """
        lc_after, bundle, _, _ = setup_paid_sight_settlement(
            amount_minor_units=10_000,
            drawing_amount_minor_units=7_000,
        )
        # available is now 3000.
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        res = api.create_presentation(
            lc_after["id"],
            create_presentation_payload(
                shipment_date=ship_date,
                drawing_amount_minor_units=4_000,
            ),
            bundle["beneficiary_headers"],
        )
        validate_error(res, "ERR_LC_INSUFFICIENT_AVAILABLE")
