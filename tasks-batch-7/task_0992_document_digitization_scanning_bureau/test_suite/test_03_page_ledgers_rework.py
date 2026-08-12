"""Page ledgers (scanned_pages / billable_scanned_pages) and rework loop."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_client_with_agreement, create_scanner_unit,
    batch_in_scanning, batch_in_qa, batch_in_indexing,
    scan_and_commit, open_session_with_logs, commit_session, get_batch_version,
    index_document, get_invoice_id_for_batch, get_invoice,
    make_intake_clerk_headers, make_scan_operator_headers,
    make_qa_reviewer_headers, make_indexer_headers, make_billing_clerk_headers,
    CLERK, SCAN, QA, IDX, BILL,
)


# ---------------------------------------------------------------------------
# Queue A — Difficulty / non_linear_state_machine + compensating_invariant
# ---------------------------------------------------------------------------

class TestBatchQAReworkCycleLoop:
    """Two tests for Difficulty instance `batch_qa_rework_cycle_loop`."""

    def _setup_reworked_batch(self):
        """Single 100-page doc; scan, QA-fail, fail-qa (rework), rescan,
        submit-qa, pass-qa. Returns (client, ctx, doc_id)."""
        client, _ = create_client_with_agreement(
            name="Cycle Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_scanning(
            [{"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        doc = ctx["documents"][0]
        # First scan: 100 pages -> SCANNED
        scan_and_commit(ctx, [(doc["id"], 100)])
        # Mark QA_FAILED
        get_success_data(api_client.create_qa_review(
            ctx["batch"]["id"], {"document_id": doc["id"]}, make_qa_reviewer_headers(QA),
        ))
        # Submit then fail QA -> rework
        get_success_data(api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
        get_success_data(api_client.fail_qa(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        # Rework: scan the doc again in a new session
        scan_and_commit(ctx, [(doc["id"], 100)])
        get_success_data(api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
        get_success_data(api_client.pass_qa(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        return client, ctx, doc["id"]

    def test_rework_cycle_traverses_qa_scanning_qa_indexing(self, api):
        """PRD §3.4: "Failing QA, `QA → SCANNING`, requires that at least one
        document is `QA_FAILED` (else `ERR_BATCH_NOT_REWORKABLE`, HTTP 409); it
        bumps the batch's `rework_cycle_count` by 1, leaves both page ledgers
        untouched, and leaves the `QA_FAILED` documents in `QA_FAILED` — they
        become `SCANNED` again only through a rework scan-session commit whose
        logs, accumulated after the document entered `QA_FAILED`, once again
        cover its declared page count."

        Design: Difficulty/non_linear_state_machine/batch_qa_rework_cycle_loop
        """
        _client, ctx, doc_id = self._setup_reworked_batch()
        batch = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        assert batch["status"] == "INDEXING"
        assert batch["rework_cycle_count"] == 1
        doc = get_success_data(api_client.get_document(doc_id, make_qa_reviewer_headers(QA)))
        assert doc["status"] == "SCANNED"

    def test_scanned_pages_accumulates_billable_stays_count_once(self, api):
        """PRD §3.3: "`scanned_pages` tracks produced material: it grows by a
        document's `pages` on every transition of that document into `SCANNED`,
        including each rework rescan. `billable_scanned_pages` is a count-once
        ledger: it grows by the document's `pages` only on that document's
        first transition into `SCANNED`, and rework rescans never double-count."

        Design: Difficulty/non_linear_state_machine/batch_qa_rework_cycle_loop
        """
        _client, ctx, _doc_id = self._setup_reworked_batch()
        batch = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        assert batch["scanned_pages"] == 200, (
            f"produced material must accumulate (100 + 100), got {batch['scanned_pages']}"
        )
        assert batch["billable_scanned_pages"] == 100, (
            f"billable count-once ledger must stay at 100, got {batch['billable_scanned_pages']}"
        )


class TestBillablePagesCountOnceAcrossRework:
    """Two tests for Difficulty instance `billable_pages_count_once_across_rework`."""

    def _setup(self):
        client, _ = create_client_with_agreement(
            name="Ledger Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_scanning(
            [{"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        doc = ctx["documents"][0]
        # First scan/commit
        scan_and_commit(ctx, [(doc["id"], 100)])
        inv_id = get_invoice_id_for_batch(ctx["batch"]["id"])
        sub_after_scan = get_invoice(inv_id)["page_subtotal_cents"]
        # QA-fail, submit, fail-qa (rework), rescan
        get_success_data(api_client.create_qa_review(
            ctx["batch"]["id"], {"document_id": doc["id"]}, make_qa_reviewer_headers(QA),
        ))
        get_success_data(api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
        get_success_data(api_client.fail_qa(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        scan_and_commit(ctx, [(doc["id"], 100)])
        return ctx, inv_id, sub_after_scan, doc["id"]

    def test_invoice_subtotal_unchanged_across_rework(self, api):
        """PRD §3.4: "both page ledgers stay unchanged — the pages remain
        billed, because rework is free for the client."

        Design: Difficulty/compensating_invariant/billable_pages_count_once_across_rework
        """
        _ctx, inv_id, sub_after_scan, _doc_id = self._setup()
        assert sub_after_scan == 4500
        sub_after_rework = get_invoice(inv_id)["page_subtotal_cents"]
        assert sub_after_rework == 4500, (
            f"rework must never double-bill; got {sub_after_rework}"
        )

    def test_billable_pages_conserved_produced_diverges(self, api):
        """PRD §3.3: "`scanned_pages` tracks produced material: it grows by a
        document's `pages` on every transition of that document into `SCANNED`,
        including each rework rescan. `billable_scanned_pages` is a count-once
        ledger: it grows by the document's `pages` only on that document's
        first transition into `SCANNED`, and rework rescans never double-count."

        Design: Difficulty/compensating_invariant/billable_pages_count_once_across_rework
        """
        ctx, _inv_id, _sub, _doc_id = self._setup()
        batch = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_billing_clerk_headers(BILL)))
        assert batch["billable_scanned_pages"] == 100
        assert batch["scanned_pages"] == 200


# ---------------------------------------------------------------------------
# Queue B — Corner / state_machines
# ---------------------------------------------------------------------------

class TestQaReviewFlipsOnlyTargetDocument:
    """Corner: qa_review_side_effect_flips_only_target_document."""

    def test_qa_review_targets_one_doc_and_preserves_ledgers(self, api):
        """PRD §3.4: "While the batch is in `SCANNING` or `QA`, a `QAReviewer`
        may flag an individual `SCANNED` document as `QA_FAILED`; both page
        ledgers stay unchanged — the pages remain billed, because rework is
        free for the client."

        Design: Corner/state_machines/qa_review_side_effect_flips_only_target_document
        """
        client, _ = create_client_with_agreement(
            name="SideFx Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_scanning(
            [
                {"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95},
                {"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95},
            ],
            client_id=client["id"],
        )
        d1, d2 = ctx["documents"][0], ctx["documents"][1]
        scan_and_commit(ctx, [(d1["id"], 50), (d2["id"], 50)])

        get_success_data(api_client.create_qa_review(
            ctx["batch"]["id"], {"document_id": d1["id"]}, make_qa_reviewer_headers(QA),
        ))
        d1_after = get_success_data(api_client.get_document(d1["id"], make_qa_reviewer_headers(QA)))
        d2_after = get_success_data(api_client.get_document(d2["id"], make_qa_reviewer_headers(QA)))
        assert d1_after["status"] == "QA_FAILED"
        assert d2_after["status"] == "SCANNED"
        batch = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        assert batch["scanned_pages"] == 100
        assert batch["billable_scanned_pages"] == 100
