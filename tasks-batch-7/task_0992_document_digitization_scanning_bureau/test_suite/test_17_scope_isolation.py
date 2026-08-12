"""Scope / nesting isolation tests."""
import pytest

from test_helpers import (
    api_client, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_client_with_agreement, create_batch, create_box, create_document,
    create_scanner_unit,
    batch_in_scanning, open_session_with_logs, get_scan_session,
    make_scan_operator_headers, make_intake_clerk_headers,
    SCAN, CLERK,
)


class TestPageLogDocumentFromOtherBatchReturnsNotFound:
    """Corner: page_log_document_from_other_batch_returns_not_found."""

    def test_document_outside_session_batch_scope_is_404(self, api):
        """PRD §2.9: "The same `ERR_NOT_FOUND` treatment applies to ids
        referenced in request bodies — `scanner_id`, `shelf_slot_id`,
        `document_id`, and `batch_id` must exist and belong to the operation's
        scope."

        Design: Corner/validations/page_log_document_from_other_batch_returns_not_found
        """
        client, _ = create_client_with_agreement(name="Scope Co", hipaa_covered=False)
        # Two batches both in SCANNING; d2 lives in B2; session OPEN on B1.
        ctx1 = batch_in_scanning(
            [{"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        ctx2 = batch_in_scanning(
            [{"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        d2 = ctx2["documents"][0]
        session1 = open_session_with_logs(ctx1, [])
        resp = api_client.create_page_log(
            session1["id"], {"document_id": d2["id"], "pages": 10},
            make_scan_operator_headers(SCAN),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        s = get_scan_session(session1["id"])
        assert s["page_count"] == 0
