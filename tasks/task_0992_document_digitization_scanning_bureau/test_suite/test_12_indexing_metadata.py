"""Indexing and metadata gating tests."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_client_with_agreement, create_batch, create_box, create_document,
    batch_in_indexing, index_document,
    get_document,
    make_intake_clerk_headers, make_indexer_headers, make_qa_reviewer_headers,
    CLERK, IDX, QA,
)


class TestIndexRecordsOnUnscannedDocumentReturnsInvalidState:
    """Corner: index_records_on_unscanned_document_returns_invalid_state."""

    def test_registered_document_in_intake_batch_rejected(self, api):
        """PRD §3.5: "Once the batch reaches `INDEXING`, an `Indexer` attaches
        metadata to each `SCANNED` document."

        Design: Corner/state_machines/index_records_on_unscanned_document_returns_invalid_state
        """
        client, _ = create_client_with_agreement(name="Pre Co", hipaa_covered=False)
        batch = create_batch(client["id"])
        box = create_box(batch["id"])
        doc = create_document(box["id"], doc_type="OTHER", pages=10, ocr_confidence=95)
        # Batch is INTAKE and document is REGISTERED — indexing must fail.
        resp = api_client.create_index_record(
            doc["id"],
            {"metadata_json": {"title": "T", "record_date": "2026-01-01", "subject": "S"},
             "ocr_text_ref": "ocr://x"},
            make_indexer_headers(IDX),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        d = get_document(doc["id"])
        assert d["status"] == "REGISTERED"
        # No IndexRecord exists for the document.
        records, _ = validate_paginated(api_client.get_document_index_records(doc["id"], make_indexer_headers(IDX)))
        assert records == []


class TestMetadataIncompleteRejected:
    """Corner: metadata_incomplete_rejected."""

    def test_missing_subject_key_rejected(self, api):
        """PRD §3.5: "The submission carries `metadata_json` — which must
        contain the keys `title`, `record_date`, and `subject`, with a missing
        key rejected as `ERR_METADATA_INCOMPLETE` (HTTP 422)."

        Design: Corner/validations/metadata_incomplete_rejected
        """
        client, _ = create_client_with_agreement(name="Meta Co", hipaa_covered=False)
        ctx = batch_in_indexing(
            [{"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        resp = api_client.create_index_record(
            ctx["documents"][0]["id"],
            {"metadata_json": {"title": "T", "record_date": "2026-01-01"},
             "ocr_text_ref": "ocr://x"},
            make_indexer_headers(IDX),
        )
        validate_error(resp, ApiErrorId.ERR_METADATA_INCOMPLETE, expected_status=422)
        d = get_document(ctx["documents"][0]["id"])
        assert d["status"] == "SCANNED"
        records, _ = validate_paginated(api_client.get_document_index_records(ctx["documents"][0]["id"], make_indexer_headers(IDX)))
        assert records == []
