"""Batch indexability / delivery gating tests."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId,
    create_client_with_agreement, set_clock,
    batch_in_qa, batch_in_indexing, index_document,
    get_invoice_id_for_batch, get_invoice,
    scan_and_commit,
    make_intake_clerk_headers, make_scan_operator_headers,
    make_qa_reviewer_headers, make_indexer_headers, make_billing_clerk_headers,
    CLERK, SCAN, QA, IDX, BILL,
)


# ---------------------------------------------------------------------------
# Queue A — Difficulty / combinatorial_formula
# ---------------------------------------------------------------------------

class TestIndexabilityNestedAllowanceFloorModeA:
    """Two tests for Difficulty instance
    `indexability_nested_allowance_floor_mode_a`."""

    def _setup_10doc_batch_with_rejections(self, n_rejected: int):
        """Build an INDEXING batch with 10 one-page docs; the first
        (10 - n_rejected) are OCR-clean (95) and will be INDEXED, the last
        n_rejected have OCR 40 and will transition to REJECTED on submit."""
        client, _ = create_client_with_agreement(
            name="Bulk Forms Inc", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=20,
        )
        # Build doc specs: 10 1-page docs. Last n_rejected have ocr 40.
        doc_specs = []
        for i in range(10):
            ocr = 40 if i >= (10 - n_rejected) else 95
            doc_specs.append({"doc_type": "OTHER", "pages": 1, "ocr_confidence": ocr})
        ctx = batch_in_indexing(doc_specs, client_id=client["id"])
        # Submit index-records for all; the ocr-40 ones will reject.
        for i, d in enumerate(ctx["documents"]):
            get_success_data(index_document(
                d["id"], title="T", record_date="2026-01-01", subject="S",
                ocr_text_ref=f"ocr://{i+1}",
            ))
        return client, ctx

    def test_ten_docs_one_rejection_is_deliverable_and_partial(self, api):
        """PRD §3.6: "the number of `REJECTED` documents is at most the
        rejection allowance, defined as the larger of 1 and the floor of one
        tenth of the batch's total document count. The boundary is exact: a
        10-document batch tolerates exactly 1 rejection, a 20-document batch
        tolerates exactly 2, and 21 documents tolerate 2."

        Design: Difficulty/combinatorial_formula/indexability_nested_allowance_floor_mode_a
        """
        _client, ctx = self._setup_10doc_batch_with_rejections(n_rejected=1)
        # 1 rejection <= allowance max(1, floor(0.10*10)) = 1 -> deliver succeeds.
        resp = api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA))
        batch = validate_success(resp, expected_status=200)
        assert batch["status"] == "DELIVERED"
        assert batch["delivery_status"] == "PARTIAL"

        # Rejected doc stays REJECTED.
        d10 = get_success_data(api_client.get_document(ctx["documents"][9]["id"], make_qa_reviewer_headers(QA)))
        assert d10["status"] == "REJECTED"

    def test_final_invoice_subtotal_after_rejection(self, api):
        """PRD §3.6: "From delivery onward, the final variant's document set is
        `SCANNED`, `INDEXED`, and `DELIVERED` only; rejected documents are
        removed from the bill because undeliverable work is not charged at
        settlement."

        Design: Difficulty/combinatorial_formula/indexability_nested_allowance_floor_mode_a
        """
        _client, ctx = self._setup_10doc_batch_with_rejections(n_rejected=1)
        get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        inv_id = get_invoice_id_for_batch(ctx["batch"]["id"])
        inv = get_invoice(inv_id)
        # 9 delivered docs x 45c = 405c; rejected doc excluded.
        assert inv["page_subtotal_cents"] == 405, (
            f"final subtotal must exclude the rejected doc, got {inv['page_subtotal_cents']}"
        )


class TestPerDocumentRoundingBeforeSumModeB:
    """Two tests for Difficulty instance `per_document_rounding_before_sum_mode_b`."""

    def _setup_volume_rush_two_one_page_docs(self):
        """VOLUME agreement + RUSH batch + two 1-page docs, scanned/committed.
        Batch remains in SCANNING (provisional variant)."""
        client, _ = create_client_with_agreement(
            name="Rush Jobs LLC", hipaa_covered=False,
            price_tier="VOLUME", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        # batch_in_indexing advances to INDEXING; we want pre-delivery. Use batch_in_scanning.
        from test_helpers import batch_in_scanning
        ctx = batch_in_scanning(
            [
                {"doc_type": "OTHER", "pages": 1, "ocr_confidence": 95},
                {"doc_type": "OTHER", "pages": 1, "ocr_confidence": 95},
            ],
            client_id=client["id"], priority="RUSH",
        )
        specs = [(d["id"], d["pages"]) for d in ctx["documents"]]
        scan_and_commit(ctx, specs)
        return ctx

    def test_per_document_rounding_then_sum_yields_106(self, api):
        """PRD §2.6: "Per-page pricing is computed by rounding each document's
        charge to cents first — the document's page count multiplied by the
        applicable per-page dollar rate, multiplied by 100, rounded half-up
        to the nearest integer — and only then summing those rounded
        per-document amounts across the document set. Summing first and
        rounding once at the end yields different cents and is incorrect."

        Design: Difficulty/combinatorial_formula/per_document_rounding_before_sum_mode_b
        """
        ctx = self._setup_volume_rush_two_one_page_docs()
        inv_id = get_invoice_id_for_batch(ctx["batch"]["id"])
        inv = get_invoice(inv_id)
        # rate = 0.30 * 1.75 = 0.525 USD/page. round_half_up(1*52.5)=53 per doc.
        # 53 + 53 = 106 (not 105 from sum-then-round).
        assert inv["page_subtotal_cents"] == 106, (
            f"expected per-document rounding then sum = 106, got {inv['page_subtotal_cents']}"
        )

    def test_sum_then_round_would_produce_105_not_observed(self, api):
        """PRD §2.6: "Summing first and rounding once at the end yields
        different cents and is incorrect."

        Design: Difficulty/combinatorial_formula/per_document_rounding_before_sum_mode_b
        """
        ctx = self._setup_volume_rush_two_one_page_docs()
        inv_id = get_invoice_id_for_batch(ctx["batch"]["id"])
        inv = get_invoice(inv_id)
        # Disambiguation: the forbidden order would give 105. Assert != 105.
        assert inv["page_subtotal_cents"] != 105, (
            f"sum-then-round would give 105; observed {inv['page_subtotal_cents']}"
        )
        assert inv["page_subtotal_cents"] == 106


class TestIndexabilityAllowanceExceededBlocksDeliver:
    """Corner: indexability_allowance_exceeded_blocks_deliver."""

    def test_two_rejections_on_ten_docs_rejects_deliver(self, api):
        """PRD §3.6: "A batch failing any leg of that check is rejected with
        `ERR_BATCH_NOT_INDEXABLE` (HTTP 409)."

        Design: Corner/calculations/indexability_allowance_exceeded_blocks_deliver
        """
        client, _ = create_client_with_agreement(
            name="Idx Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=20,
        )
        doc_specs = []
        for i in range(10):
            ocr = 40 if i >= 8 else 95
            doc_specs.append({"doc_type": "OTHER", "pages": 1, "ocr_confidence": ocr})
        ctx = batch_in_indexing(doc_specs, client_id=client["id"])
        for i, d in enumerate(ctx["documents"]):
            get_success_data(index_document(
                d["id"], title="T", record_date="2026-01-01", subject="S",
                ocr_text_ref=f"ocr://{i+1}",
            ))
        # 2 rejections > allowance 1 -> deliver must be rejected.
        resp = api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA))
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_INDEXABLE, expected_status=409)
        # Status stays INDEXING; delivered_at stays null.
        batch = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_billing_clerk_headers(BILL)))
        assert batch["status"] == "INDEXING"
        assert batch.get("delivered_at") is None
