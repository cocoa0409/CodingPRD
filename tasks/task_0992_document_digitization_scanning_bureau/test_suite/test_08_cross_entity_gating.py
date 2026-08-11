"""Cross-entity state gating: scan sessions x batch, downloads x document."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_client_with_agreement, create_batch, create_box, create_document,
    create_scanner_unit, set_clock,
    batch_in_scanning, batch_in_qa, batch_in_indexing, index_document,
    scan_and_commit, open_session_with_logs,
    get_document, get_access_grant,
    make_platform_admin_headers, make_intake_clerk_headers,
    make_scan_operator_headers, make_qa_reviewer_headers,
    make_indexer_headers, make_client_user_headers,
    CLERK, SCAN, QA, IDX,
)


# ---------------------------------------------------------------------------
# Queue A — Difficulty / cross_entity_state_dependency
# ---------------------------------------------------------------------------

class TestScanSessionGatedByBatchState:
    """Two tests for Difficulty instance `scan_session_gated_by_batch_state`."""

    def _setup_qa_batch(self):
        client, _ = create_client_with_agreement(
            name="Gate Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_qa(
            [{"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        return client, ctx

    def test_open_session_rejected_when_batch_in_qa(self, api):
        """PRD §3.3: "A `ScanOperator` opens a scan session against a batch in
        `SCANNING` by naming a `scanner_id`."

        Design: Difficulty/cross_entity_state_dependency/scan_session_gated_by_batch_state
        """
        _client, ctx = self._setup_qa_batch()
        # Batch is now QA. Open a new session on the free scanner: rejected.
        resp = api_client.create_scan_session(
            ctx["batch"]["id"], {"scanner_id": ctx["scanner"]["id"]},
            make_scan_operator_headers(SCAN),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_no_new_session_persisted_on_rejection(self, api):
        """PRD §3.3: "A `ScanOperator` opens a scan session against a batch in
        `SCANNING` by naming a `scanner_id`."

        Design: Difficulty/cross_entity_state_dependency/scan_session_gated_by_batch_state
        """
        _client, ctx = self._setup_qa_batch()
        api_client.create_scan_session(
            ctx["batch"]["id"], {"scanner_id": ctx["scanner"]["id"]},
            make_scan_operator_headers(SCAN),
        )
        sessions, meta = validate_paginated(api_client.list_batch_scan_sessions(
            ctx["batch"]["id"], make_scan_operator_headers(SCAN),
        ))
        assert meta["total_count"] == 1, (
            f"exactly one (the original) session must exist; got {meta['total_count']}"
        )


class TestDownloadGatedByDocumentDelivery:
    """Two tests for Difficulty instance `download_gated_by_document_delivery`."""

    def _setup_indexed_batch_with_grant(self):
        client, _ = create_client_with_agreement(
            name="DL Gate", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_indexing(
            [{"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        get_success_data(index_document(ctx["documents"][0]["id"], title="T1", record_date="2026-01-01", subject="S1", ocr_text_ref="ocr://t1"))
        # Create the grant on the INDEXED batch (clock still at default).
        grant = get_success_data(api_client.create_access_grant(
            client["id"],
            {"batch_id": ctx["batch"]["id"], "scope": "FULL_IMAGE", "expires_at": "2027-01-01T00:00:00Z"},
            make_client_user_headers(client["id"]),
        ))
        return client, ctx, grant

    def test_download_rejected_while_document_indexed(self, api):
        """PRD §3.8: "the document itself in `DELIVERED` status (else
        `ERR_DOCUMENT_NOT_DELIVERED`, HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/download_gated_by_document_delivery
        """
        client, ctx, grant = self._setup_indexed_batch_with_grant()
        doc_id = ctx["documents"][0]["id"]
        resp = api_client.download_grant_document(
            grant["id"], doc_id, make_client_user_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_DELIVERED, expected_status=409)

    def test_download_succeeds_after_delivery(self, api):
        """PRD §3.8: "The download channel addresses a single document by its
        `docId` path parameter within the grant's context and returns that
        document's image as a payload of `document_id`, a `download_url`, and
        an `expires_in_seconds` lifetime."

        Design: Difficulty/cross_entity_state_dependency/download_gated_by_document_delivery
        """
        client, ctx, grant = self._setup_indexed_batch_with_grant()
        doc_id = ctx["documents"][0]["id"]
        # Deliver the batch
        get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        doc = get_document(doc_id)
        assert doc["status"] == "DELIVERED"
        resp = api_client.download_grant_document(
            grant["id"], doc_id, make_client_user_headers(client["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["download_url"]
        assert data["document_id"] == doc_id


# ---------------------------------------------------------------------------
# Queue B — Corner / endpoints
# ---------------------------------------------------------------------------

class TestDownloadScopeMetadataOnlyBlocked:
    """Corner: download_scope_metadata_only_blocked."""

    def test_metadata_only_grant_lists_but_cannot_download(self, api):
        """PRD §3.8: "the scope `FULL_IMAGE` — a `METADATA_ONLY` grant serves
        only the documents list, and attempting a download with one is
        rejected with `ERR_SCOPE_INSUFFICIENT` (HTTP 403)"

        Design: Corner/endpoints/download_scope_metadata_only_blocked
        """
        client, _ = create_client_with_agreement(
            name="ScopeDL Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_indexing(
            [{"doc_type": "OTHER", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        get_success_data(index_document(ctx["documents"][0]["id"], title="T1", record_date="2026-01-01", subject="S1", ocr_text_ref="ocr://t1"))
        get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        grant = get_success_data(api_client.create_access_grant(
            client["id"],
            {"batch_id": ctx["batch"]["id"], "scope": "METADATA_ONLY", "expires_at": "2027-01-01T00:00:00Z"},
            make_client_user_headers(client["id"]),
        ))
        # Metadata channel works
        docs, meta = validate_paginated(api_client.list_grant_documents(grant["id"], make_client_user_headers(client["id"])))
        assert docs[0]["id"] == ctx["documents"][0]["id"]
        # Download rejected
        resp = api_client.download_grant_document(
            grant["id"], ctx["documents"][0]["id"], make_client_user_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCOPE_INSUFFICIENT, expected_status=403)


class TestGrantExpiryLazyTransition:
    """Corner: grant_expiry_lazy_transition."""

    def test_expired_grant_rejected_and_status_flips(self, api):
        """PRD §3.8: "Grants are lazily time-aware: when the logical clock has
        passed a grant's `expires_at`, the next use transitions it to
        `EXPIRED`, and using an expired grant is rejected with
        `ERR_GRANT_EXPIRED` (HTTP 409)."

        Design: Corner/endpoints/grant_expiry_lazy_transition
        """
        client, _ = create_client_with_agreement(
            name="Exp Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_indexing(
            [{"doc_type": "OTHER", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        get_success_data(index_document(ctx["documents"][0]["id"], title="T1", record_date="2026-01-01", subject="S1", ocr_text_ref="ocr://t1"))
        get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        grant = get_success_data(api_client.create_access_grant(
            client["id"],
            {"batch_id": ctx["batch"]["id"], "scope": "FULL_IMAGE", "expires_at": "2026-05-10T00:00:00Z"},
            make_client_user_headers(client["id"]),
        ))
        # Advance clock past expires_at.
        set_clock("2026-05-11T00:00:00Z")
        resp = api_client.download_grant_document(
            grant["id"], ctx["documents"][0]["id"], make_client_user_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_GRANT_EXPIRED, expected_status=409)
        # Subsequent read shows status persisted to EXPIRED.
        g = get_access_grant(grant["id"], client["id"])
        assert g["status"] == "EXPIRED"


class TestGrantRevokeBlocksDownload:
    """Corner: grant_revoke_blocks_download."""

    def test_revoked_grant_rejected_with_invalid_state(self, api):
        """PRD §3.8: "The client may also revoke an `ACTIVE` grant outright,
        moving it to `REVOKED`." PRD §3.8: "Download requires the grant
        `ACTIVE` and unexpired"

        Design: Corner/endpoints/grant_revoke_blocks_download
        """
        client, _ = create_client_with_agreement(
            name="Rev Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_indexing(
            [{"doc_type": "OTHER", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        get_success_data(index_document(ctx["documents"][0]["id"], title="T1", record_date="2026-01-01", subject="S1", ocr_text_ref="ocr://t1"))
        get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        grant = get_success_data(api_client.create_access_grant(
            client["id"],
            {"batch_id": ctx["batch"]["id"], "scope": "FULL_IMAGE", "expires_at": "2027-01-01T00:00:00Z"},
            make_client_user_headers(client["id"]),
        ))
        get_success_data(api_client.revoke_access_grant(grant["id"], make_client_user_headers(client["id"])))
        resp = api_client.download_grant_document(
            grant["id"], ctx["documents"][0]["id"], make_client_user_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        g = get_access_grant(grant["id"], client["id"])
        assert g["status"] == "REVOKED"


class TestVaultOnlyGrantBlocksPublicDownload:
    """Corner: vault_only_grant_blocks_public_download."""

    def test_vault_only_grant_blocks_download_allows_metadata(self, api):
        """PRD §3.8: "the grant not `vault_only` (a vault-only grant used on
        the public download channel is rejected with `ERR_GRANT_VAULT_ONLY`,
        HTTP 422)" PRD §3.8: "its `vault_only` flag is computed server-side —
        true exactly when the client is `hipaa_covered` and any document in
        the referenced batch has `contains_phi` set."

        Design: Corner/endpoints/vault_only_grant_blocks_public_download
        """
        client, _ = create_client_with_agreement(
            name="Vault Health", hipaa_covered=True,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_indexing(
            [{"doc_type": "MEDICAL_RECORD", "pages": 100, "contains_phi": True, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        get_success_data(index_document(ctx["documents"][0]["id"], title="T1", record_date="2026-01-01", subject="S1", ocr_text_ref="ocr://t1"))
        get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        grant = get_success_data(api_client.create_access_grant(
            client["id"],
            {"batch_id": ctx["batch"]["id"], "scope": "FULL_IMAGE", "expires_at": "2027-01-01T00:00:00Z"},
            make_client_user_headers(client["id"]),
        ))
        assert grant["vault_only"] is True
        # Metadata channel still works
        docs, _ = validate_paginated(api_client.list_grant_documents(grant["id"], make_client_user_headers(client["id"])))
        assert docs[0]["id"] == ctx["documents"][0]["id"]
        # Download blocked
        resp = api_client.download_grant_document(
            grant["id"], ctx["documents"][0]["id"], make_client_user_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_GRANT_VAULT_ONLY, expected_status=422)
