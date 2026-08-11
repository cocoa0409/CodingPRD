"""Scan-commit cascades, OCC on Batch.version, derived-field reconciliation."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId,
    create_client_with_agreement, create_batch, create_box, create_document,
    create_scanner_unit,
    batch_in_scanning, open_session_with_logs, scan_and_commit, commit_session,
    get_batch_version, get_invoice_id_for_batch, get_invoice,
    get_document, get_scan_session,
    make_intake_clerk_headers, make_scan_operator_headers,
    make_billing_clerk_headers,
    CLERK, SCAN, BILL,
)


# ---------------------------------------------------------------------------
# Queue A — Difficulty / transitive_cascade
# ---------------------------------------------------------------------------

class TestScanCommitBubbleupCascade:
    """Two tests for Difficulty instance
    `scan_commit_bubbleup_cascade_document_batch_invoice`."""

    def _setup(self):
        client, _ = create_client_with_agreement(
            name="Cascade Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_scanning(
            [{"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        session = open_session_with_logs(ctx, [(ctx["documents"][0]["id"], 100)])
        return client, ctx, session

    def test_commit_flips_document_and_updates_batch_ledgers(self, api):
        """PRD §3.3: "On commit the session moves to `COMMITTED` with
        `ended_at` stamped; every document whose cumulative committed-session
        pages now reach its declared `pages` transitions from `REGISTERED` —
        or, on the rework path, from `QA_FAILED` — to `SCANNED`; the batch's
        page ledgers are reconciled as described below."

        Design: Difficulty/transitive_cascade/scan_commit_bubbleup_cascade_document_batch_invoice
        """
        _client, ctx, session = self._setup()
        doc_id = ctx["documents"][0]["id"]
        commit_session(session["id"], ctx["batch"]["id"])

        doc = get_document(doc_id)
        assert doc["status"] == "SCANNED"
        batch = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_billing_clerk_headers(BILL)))
        assert batch["scanned_pages"] == 100
        assert batch["billable_scanned_pages"] == 100

    def test_commit_recomputes_draft_invoice_without_invoice_call(self, api):
        """PRD §3.6: "The provisional figure is recomputed on every
        scan-session commit and on every draft-invoice read."

        Design: Difficulty/transitive_cascade/scan_commit_bubbleup_cascade_document_batch_invoice
        """
        _client, ctx, session = self._setup()
        commit_session(session["id"], ctx["batch"]["id"])
        inv_id = get_invoice_id_for_batch(ctx["batch"]["id"])
        inv = get_invoice(inv_id)
        # 100 pages * 0.45 * 100 = 4500c recomputed on the DRAFT without any
        # invoice-direct mutation.
        assert inv["page_subtotal_cents"] == 4500
        assert inv["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue B — Corner / cross_cutting_layers
# ---------------------------------------------------------------------------

class TestOccStaleVersionCommitRejectedThenFreshSucceeds:
    """Corner: occ_stale_version_commit_rejected_then_fresh_succeeds."""

    def test_stale_version_rejected_then_fresh_commit_succeeds(self, api):
        """PRD §2.7: "If that value does not equal the batch's current
        `version` — because another writer has advanced the batch since the
        client read it — the commit is rejected with `ERR_STALE_VERSION`
        (HTTP 412) and nothing is persisted."

        Design: Corner/cross_cutting_layers/occ_stale_version_commit_rejected_then_fresh_succeeds
        """
        client, _ = create_client_with_agreement(
            name="OCC Co", hipaa_covered=False,
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
        scanner2 = create_scanner_unit(scanner_code="SCN-2", capacity=500)
        d1, d2 = ctx["documents"][0], ctx["documents"][1]
        ss1 = open_session_with_logs(ctx, [(d1["id"], 50)])
        ss2 = open_session_with_logs(ctx, [(d2["id"], 50)], scanner_id=scanner2["id"])

        # Observe the batch version BEFORE ss1 commits.
        observed = get_batch_version(ctx["batch"]["id"])
        # ss1 commits at the observed version: succeeds, advancing batch version.
        get_success_data(api_client.commit_scan_session(
            ss1["id"], {"expected_batch_version": observed},
            make_scan_operator_headers(SCAN),
        ))
        # ss2 tries to commit at the now-stale observed version: 412.
        resp = api_client.commit_scan_session(
            ss2["id"], {"expected_batch_version": observed},
            make_scan_operator_headers(SCAN),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        # Re-read fresh version and commit succeeds.
        fresh = get_batch_version(ctx["batch"]["id"])
        assert fresh == observed + 1
        ok = api_client.commit_scan_session(
            ss2["id"], {"expected_batch_version": fresh},
            make_scan_operator_headers(SCAN),
        )
        session_data = validate_success(ok, expected_status=200)
        assert session_data["status"] == "COMMITTED"


class TestDerivedFieldsReconciledImmediatelyOnCommit:
    """Corner: derived_fields_reconciled_immediately_on_commit."""

    def test_page_count_aggregation_and_immediate_batch_read(self, api):
        """PRD §3.3: "each log carries its owning `session_id`, a denormalized
        `batch_id` for reconciliation queries, a `document_id`, and a `pages`
        count of at least 1; the document must belong to the session's batch,
        and each accepted entry adds its `pages` to the session's `page_count`."

        Design: Corner/cross_cutting_layers/derived_fields_reconciled_immediately_on_commit
        """
        client, _ = create_client_with_agreement(
            name="Deriv Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_scanning(
            [{"doc_type": "OTHER", "pages": 80, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        doc = ctx["documents"][0]
        session = open_session_with_logs(ctx, [(doc["id"], 50), (doc["id"], 30)])
        s = get_scan_session(session["id"])
        assert s["page_count"] == 80

        commit_session(session["id"], ctx["batch"]["id"])
        batch = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
        assert batch["scanned_pages"] == 80
