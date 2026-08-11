"""Batch state machine: initial state, invalid transitions, terminal lockdown."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_client_with_agreement, create_batch, create_box, create_document,
    create_shelf_slot, create_scanner_unit, shelve_box, set_clock,
    batch_in_scanning, scan_and_commit, index_document, destroy_box,
    make_intake_clerk_headers, make_scan_operator_headers,
    make_qa_reviewer_headers, make_indexer_headers,
    make_destruction_specialist_headers, make_compliance_officer_headers,
    make_platform_admin_headers,
    CLERK, SCAN, QA, IDX, DS, CO, WITNESS, ADMIN,
)


class TestBatchInitialStateAndInvalidTransitionFromIntake:
    """Corner: batch_initial_state_and_invalid_transition_from_intake."""

    def test_fresh_batch_is_intake_and_pass_qa_is_invalid(self, api):
        """PRD §3.2: "The batch is born in `INTAKE` status" PRD §3.4: "Passing
        QA, `QA → INDEXING`, requires that no document of the batch is
        `QA_FAILED` (else `ERR_DOCUMENTS_INCOMPLETE`)."

        Design: Corner/state_machines/batch_initial_state_and_invalid_transition_from_intake
        """
        client, _ = create_client_with_agreement(name="Init Co", hipaa_covered=False)
        batch = create_batch(client["id"])
        assert batch["status"] == "INTAKE"
        assert batch["version"] == 1

        resp = api_client.pass_qa(batch["id"], make_qa_reviewer_headers(QA))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = get_success_data(api_client.get_batch(batch["id"], make_intake_clerk_headers(CLERK)))
        assert after["status"] == "INTAKE"
        assert after["version"] == 1


class TestBatchTerminalLockdownClosedRejectsAllActions:
    """Corner: batch_terminal_lockdown_closed_rejects_all_actions."""

    def test_closed_batch_rejects_start_prep_and_deliver(self, api):
        """PRD §3.7: "a `ComplianceOfficer` closes the batch, moving it to
        `CLOSED`, the terminal pipeline state." PRD §2.8: "then state-machine
        legality (`ERR_INVALID_STATE`, or `ERR_DOCUMENT_NOT_DELIVERED` on the
        download path)"

        Design: Corner/state_machines/batch_terminal_lockdown_closed_rejects_all_actions
        """
        client, _ = create_client_with_agreement(
            name="Term Co", hipaa_covered=False, retention_days=5,
        )
        slot = create_shelf_slot(shelf_code="SH-T", zone="GENERAL", capacity_grams=2000)
        ctx = batch_in_scanning(
            [{"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        shelve_box(ctx["box"]["id"], slot["id"])
        scan_and_commit(ctx, [(ctx["documents"][0]["id"], 100)])
        get_success_data(api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
        get_success_data(api_client.pass_qa(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        get_success_data(index_document(ctx["documents"][0]["id"], title="T1", record_date="2026-01-01", subject="S1", ocr_text_ref="ocr://t1"))
        set_clock("2026-05-10T00:00:00Z")
        get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        set_clock("2026-05-15T00:00:00Z")
        destroy_box(ctx["box"]["id"], method="INCINERATE")
        get_success_data(api_client.close_batch(ctx["batch"]["id"], make_compliance_officer_headers(CO)))

        # CLOSED is terminal: every further action is rejected.
        resp1 = api_client.start_prep(ctx["batch"]["id"], make_intake_clerk_headers(CLERK))
        validate_error(resp1, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        resp2 = api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA))
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        final = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_compliance_officer_headers(CO)))
        assert final["status"] == "CLOSED"
