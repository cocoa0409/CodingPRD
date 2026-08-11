"""Scan session lifecycle and precondition errors."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_client_with_agreement, create_scanner_unit,
    batch_in_scanning, open_session_with_logs, scan_and_commit,
    get_batch_version, get_document, get_scan_session,
    make_platform_admin_headers, make_intake_clerk_headers,
    make_scan_operator_headers, make_qa_reviewer_headers,
    CLERK, SCAN, QA, ADMIN,
)


class TestSessionVoidThenCommitReturnsInvalidState:
    """Corner: session_void_then_commit_returns_invalid_state."""

    def test_voided_session_cannot_commit(self, api):
        """PRD §3.3: "An operator may instead void an open session, moving it
        to `VOIDED` with `ended_at` stamped; a voided session's page logs are
        retained for audit but excluded from every aggregate."

        Design: Corner/state_machines/session_void_then_commit_returns_invalid_state
        """
        client, _ = create_client_with_agreement(name="Void Co", hipaa_covered=False)
        ctx = batch_in_scanning(
            [{"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        session = open_session_with_logs(ctx, [])  # no page logs needed
        get_success_data(api_client.void_scan_session(session["id"], make_scan_operator_headers(SCAN)))
        bv = get_batch_version(ctx["batch"]["id"])
        resp = api_client.commit_scan_session(
            session["id"], {"expected_batch_version": bv},
            make_scan_operator_headers(SCAN),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        s = get_scan_session(session["id"])
        assert s["status"] == "VOIDED"
        b = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
        assert b["scanned_pages"] == 0


class TestErrorScannerOverCapacityAtCommit:
    """Corner: error_scanner_over_capacity_at_commit."""

    def test_over_capacity_commit_rejected(self, api):
        """PRD §3.3: "no greater than the scanner's
        `capacity_pages_per_session` (else `ERR_SCANNER_OVER_CAPACITY`,
        HTTP 409)"

        Design: Corner/errors/error_scanner_over_capacity_at_commit
        """
        client, _ = create_client_with_agreement(name="Cap Co", hipaa_covered=False)
        ctx = batch_in_scanning(
            [{"doc_type": "OTHER", "pages": 60, "ocr_confidence": 95}],
            client_id=client["id"],
            scanner_capacity=50,
        )
        session = open_session_with_logs(ctx, [(ctx["documents"][0]["id"], 60)])
        bv = get_batch_version(ctx["batch"]["id"])
        resp = api_client.commit_scan_session(
            session["id"], {"expected_batch_version": bv},
            make_scan_operator_headers(SCAN),
        )
        validate_error(resp, ApiErrorId.ERR_SCANNER_OVER_CAPACITY, expected_status=409)
        s = get_scan_session(session["id"])
        assert s["status"] == "OPEN"
        d = get_document(ctx["documents"][0]["id"])
        assert d["status"] == "REGISTERED"


class TestErrorEmptyScanSessionCommit:
    """Corner: error_empty_scan_session_commit."""

    def test_empty_session_commit_rejected(self, api):
        """PRD §3.3: "requires `page_count` strictly greater than 0 (else
        `ERR_EMPTY_SCAN_SESSION`, HTTP 409)"

        Design: Corner/errors/error_empty_scan_session_commit
        """
        client, _ = create_client_with_agreement(name="Empty Co", hipaa_covered=False)
        ctx = batch_in_scanning(
            [{"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        session = open_session_with_logs(ctx, [])
        bv = get_batch_version(ctx["batch"]["id"])
        resp = api_client.commit_scan_session(
            session["id"], {"expected_batch_version": bv},
            make_scan_operator_headers(SCAN),
        )
        validate_error(resp, ApiErrorId.ERR_EMPTY_SCAN_SESSION, expected_status=409)


class TestErrorOpenSessionBlocksSubmitQa:
    """Corner: error_open_session_blocks_submit_qa."""

    def test_open_session_blocks_submit_qa_then_void_unblocks(self, api):
        """PRD §3.4: "Submitting for QA, `SCANNING → QA`, requires that no
        scan session of the batch is still `OPEN` (else
        `ERR_OPEN_SCAN_SESSION_EXISTS`, HTTP 409)"

        Design: Corner/errors/error_open_session_blocks_submit_qa
        """
        client, _ = create_client_with_agreement(name="OpenS Co", hipaa_covered=False)
        ctx = batch_in_scanning(
            [{"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        scanner2 = create_scanner_unit(scanner_code="SCN-2", capacity=500)
        # Scan and commit the first session so document is SCANNED
        scan_and_commit(ctx, [(ctx["documents"][0]["id"], 50)])
        # Open a second session on a different scanner — leaves it OPEN
        open_session_with_logs(ctx, [], scanner_id=scanner2["id"])
        # submit-qa must be rejected
        resp = api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN))
        validate_error(resp, ApiErrorId.ERR_OPEN_SCAN_SESSION_EXISTS, expected_status=409)
        # Void the dangling session and retry — succeeds
        sessions = api_client.list_batch_scan_sessions(ctx["batch"]["id"], make_scan_operator_headers(SCAN))
        from test_helpers import validate_paginated
        data, _ = validate_paginated(sessions)
        open_session = next(s for s in data if s["status"] == "OPEN")
        get_success_data(api_client.void_scan_session(open_session["id"], make_scan_operator_headers(SCAN)))
        ok = api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN))
        batch = validate_success(ok, expected_status=200)
        assert batch["status"] == "QA"


class TestErrorScannerUnavailableMaintenance:
    """Corner: error_scanner_unavailable_maintenance."""

    def test_maintenance_scanner_rejects_open_until_available(self, api):
        """PRD §3.3: "the scanner unit must exist and be `AVAILABLE` (a unit
        in `MAINTENANCE` rejects both session open and commit with
        `ERR_SCANNER_UNAVAILABLE`, HTTP 409)"

        Design: Corner/errors/error_scanner_unavailable_maintenance
        """
        client, _ = create_client_with_agreement(name="Maint Co", hipaa_covered=False)
        ctx = batch_in_scanning(
            [{"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        scanner_id = ctx["scanner"]["id"]
        # Toggle scanner to MAINTENANCE
        get_success_data(api_client.set_scanner_maintenance(
            scanner_id, {"status": "MAINTENANCE"}, make_platform_admin_headers(ADMIN),
        ))
        resp = api_client.create_scan_session(
            ctx["batch"]["id"], {"scanner_id": scanner_id},
            make_scan_operator_headers(SCAN),
        )
        validate_error(resp, ApiErrorId.ERR_SCANNER_UNAVAILABLE, expected_status=409)
        # Toggle back to AVAILABLE — open succeeds.
        get_success_data(api_client.set_scanner_maintenance(
            scanner_id, {"status": "AVAILABLE"}, make_platform_admin_headers(ADMIN),
        ))
        ok = api_client.create_scan_session(
            ctx["batch"]["id"], {"scanner_id": scanner_id},
            make_scan_operator_headers(SCAN),
        )
        session = validate_success(ok, expected_status=201)
        assert session["status"] == "OPEN"


class TestErrorDocumentsIncompleteBlocksSubmitQa:
    """Corner: error_documents_incomplete_blocks_submit_qa_and_pass_qa."""

    def test_submit_qa_with_unscanned_document_rejected(self, api):
        """PRD §3.4: "Submitting for QA, `SCANNING → QA`, requires that no
        scan session of the batch is still `OPEN` (else
        `ERR_OPEN_SCAN_SESSION_EXISTS`, HTTP 409) and that every document of
        the batch sits in `SCANNED`, `QA_FAILED`, or `REJECTED` (else
        `ERR_DOCUMENTS_INCOMPLETE`, HTTP 409)."

        Design: Corner/errors/error_documents_incomplete_blocks_submit_qa_and_pass_qa
        """
        client, _ = create_client_with_agreement(name="Inc Co", hipaa_covered=False)
        ctx = batch_in_scanning(
            [
                {"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95},
                {"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95},
            ],
            client_id=client["id"],
        )
        # Only scan d1; d2 remains REGISTERED.
        scan_and_commit(ctx, [(ctx["documents"][0]["id"], 50)])
        resp = api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN))
        validate_error(resp, ApiErrorId.ERR_DOCUMENTS_INCOMPLETE, expected_status=409)
        batch = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
        assert batch["status"] == "SCANNING"


class TestErrorFailQaNotReworkable:
    """Corner: error_fail_qa_not_reworkable."""

    def test_fail_qa_without_qa_failed_document_rejected(self, api):
        """PRD §3.4: "Failing QA, `QA → SCANNING`, requires that at least one
        document is `QA_FAILED` (else `ERR_BATCH_NOT_REWORKABLE`, HTTP 409)"

        Design: Corner/errors/error_fail_qa_not_reworkable
        """
        client, _ = create_client_with_agreement(name="NR Co", hipaa_covered=False)
        ctx = batch_in_scanning(
            [{"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        scan_and_commit(ctx, [(ctx["documents"][0]["id"], 50)])
        get_success_data(api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
        # No document is QA_FAILED — fail-qa must reject.
        resp = api_client.fail_qa(ctx["batch"]["id"], make_qa_reviewer_headers(QA))
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_REWORKABLE, expected_status=409)
        batch = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        assert batch["status"] == "QA"
        assert batch["rework_cycle_count"] == 0
