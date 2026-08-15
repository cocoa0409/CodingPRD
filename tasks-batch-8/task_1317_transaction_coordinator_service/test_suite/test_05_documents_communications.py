"""Document review cycle and communication-entry behaviors."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    make_active_listing_file, make_active_purchase_file,
    create_document_payload, accept_document, run_audit,
)


class TestDocumentReviewCycle:
    def test_document_reject_resubmit_review_round_cycle(self):
        """PRD §3.5: "A party agent submits it, moving `REQUESTED → RECEIVED` or, on
        resubmission, `REJECTED → RECEIVED`; the actor must be the file's buyer or
        seller agent (`ERR_AGENT_NOT_ON_FILE`), the document must be in `REQUESTED` or
        `REJECTED` (`ERR_DOCUMENT_INVALID_STATE`), the submit stamps
        `submitted_by_agent_id` with the acting agent, a resubmission increments
        `review_round` by 1, and every submission resets the file's
        `last_audit_status` to `NONE`."
        PRD §3.5: "The coordinator then accepts (`RECEIVED → ACCEPTED`) or rejects
        (`RECEIVED → REJECTED`) it; rejection requires a `reason` (otherwise
        `ERR_INVALID_REQUEST`) which is recorded as `reject_reason`, and both accept
        and reject also reset the file's `last_audit_status` to `NONE` — any document
        status mutation after an audit invalidates that audit."

        Design: Difficulty/non_linear_state_machine/document_reject_resubmit_review_round_cycle
        """
        scen = make_active_purchase_file(required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        doc = get_success_data(api_client.create_document(
            create_document_payload(file_id=file_id, doc_type="EXECUTED_CONTRACT"), coord_h
        ))
        assert doc["status"] == "REQUESTED"
        assert doc["review_round"] == 1
        submitted = validate_success(api_client.submit_document(doc["id"], scen["buyer_h"]))
        assert submitted["status"] == "RECEIVED"
        rejected = validate_success(
            api_client.reject_document(doc["id"], coord_h, payload={"reason": "illegible scan"})
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["reject_reason"] == "illegible scan"
        resubmitted = validate_success(api_client.submit_document(doc["id"], scen["buyer_h"]))
        assert resubmitted["status"] == "RECEIVED"
        accepted = validate_success(api_client.accept_document(doc["id"], coord_h))
        assert accepted["status"] == "ACCEPTED"

        final = validate_success(api_client.get_document(doc["id"], coord_h))
        assert final["status"] == "ACCEPTED"
        assert final["review_round"] == 2, (
            f"the REJECTED -> RECEIVED loop must increment review_round exactly once; "
            f"got {final['review_round']}"
        )
        assert final["reject_reason"] == "illegible scan", \
            "the recorded reject_reason survives the resubmission cycle"
        assert final["submitted_by_agent_id"] == scen["buyer"]["id"]

    def test_accept_requested_document_rejected(self):
        """PRD §3.5: "The coordinator then accepts (`RECEIVED → ACCEPTED`) or rejects
        (`RECEIVED → REJECTED`) it; rejection requires a `reason` (otherwise
        `ERR_INVALID_REQUEST`) which is recorded as `reject_reason`, and both accept
        and reject also reset the file's `last_audit_status` to `NONE` — any document
        status mutation after an audit invalidates that audit."
        PRD §3.5: "The document starts `REQUESTED` with `review_round` 1."

        Design: Corner/validations/accept_requested_document_rejected
        """
        scen = make_active_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        doc = get_success_data(api_client.create_document(
            create_document_payload(file_id=file_id, doc_type="T47_DISCLOSURE"), coord_h
        ))
        assert doc["status"] == "REQUESTED"
        resp = api_client.accept_document(doc["id"], coord_h)
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_INVALID_STATE)
        after = validate_success(api_client.get_document(doc["id"], coord_h))
        assert after["status"] == "REQUESTED", "a failed accept must leave the document REQUESTED"

    def test_document_accept_stales_prior_audit(self):
        """PRD §3.5: "The coordinator then accepts (`RECEIVED → ACCEPTED`) or rejects
        (`RECEIVED → REJECTED`) it; rejection requires a `reason` (otherwise
        `ERR_INVALID_REQUEST`) which is recorded as `reject_reason`, and both accept
        and reject also reset the file's `last_audit_status` to `NONE` — any document
        status mutation after an audit invalidates that audit."

        Design: Corner/state_machines/document_accept_stales_prior_audit
        """
        scen = make_active_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        accept_document(coord_h, scen["seller_h"], file_id, "T47_DISCLOSURE")
        audit = run_audit(coord_h, file_id)
        assert audit["result"] == "PASS", "pre-condition: first audit PASSes"
        mid = validate_success(api_client.get_file(file_id, coord_h))
        assert mid["last_audit_status"] == "PASS"
        # A second (optional) document is requested, submitted, and accepted.
        doc2 = get_success_data(api_client.create_document(
            create_document_payload(file_id=file_id, doc_type="HOA_ADDENDUM"), coord_h
        ))
        api_client.submit_document(doc2["id"], scen["seller_h"])
        validate_success(api_client.accept_document(doc2["id"], coord_h))
        after = validate_success(api_client.get_file(file_id, coord_h))
        assert after["last_audit_status"] == "NONE", \
            "a document status mutation after the audit must reset last_audit_status to NONE"


class TestCommunications:
    def test_communication_reply_marks_parent_answered(self):
        """PRD §3.5: "An optional `in_reply_to_id` references another entry on the
        file; when it references an `OPEN` entry, that referenced entry is marked
        `ANSWERED`."
        PRD §3.5: "Each entry records `author_role` from the caller's `X-User-Role`
        and starts `OPEN` with `entry_kind` `LOG` (other kinds being `ESCALATION` and
        `SYSTEM`)."

        Design: Corner/state_machines/communication_reply_marks_parent_answered
        """
        scen = make_active_listing_file(file_overrides={
            "inspection_offset_days": 14, "appraisal_offset_days": 21,
        })
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        entry_a = get_success_data(api_client.create_communication(
            {
                "file_id": file_id,
                "party": "SELLER_AGENT",
                "direction": "OUTBOUND",
                "body": "Need HOA resale certificate",
                "requires_response": True,
                "response_due_at": "2026-08-20T09:00:00Z",
            },
            coord_h,
        ))
        assert entry_a["status"] == "OPEN"
        entry_b = get_success_data(api_client.create_communication(
            {
                "file_id": file_id,
                "party": "SELLER_AGENT",
                "direction": "INBOUND",
                "body": "Certificate attached",
                "in_reply_to_id": entry_a["id"],
            },
            scen["seller_h"],
        ))
        assert entry_b["status"] == "OPEN", "the reply itself starts OPEN"
        assert entry_b["in_reply_to_id"] == entry_a["id"]
        parent = validate_success(api_client.get_communication(entry_a["id"], coord_h))
        assert parent["status"] == "ANSWERED", \
            "a reply referencing an OPEN entry must mark it ANSWERED"
        f_after = validate_success(api_client.get_file(file_id, coord_h))
        assert f_after["open_escalation_count"] == 0, \
            "answered before the due time; nothing escalated"

    def test_escalation_resolve_decrements_file_counter(self):
        """PRD §3.5: "When the clock advances past `response_due_at` on an `OPEN`
        entry flagged `requires_response`, the system moves it `OPEN → ESCALATED` and
        increments the file's `open_escalation_count` by 1. A coordinator resolves an
        entry in `OPEN` or `ESCALATED` (otherwise `ERR_COMMUNICATION_INVALID_STATE`);
        resolving an `ESCALATED` entry decrements the file's `open_escalation_count`
        by 1, while resolving an `OPEN` one leaves the counter untouched."

        Design: Corner/state_machines/escalation_resolve_decrements_file_counter
        """
        # Cash file with far-out contingency offsets; milestone due 2026-09-02, so the
        # sweep to 2026-08-04 escalates the entry and nothing else.
        scen = make_active_listing_file(
            template_overrides={
                "milestone_defs": [{"name": "Listing Paperwork", "offset_days": 30, "mandatory": False}],
            },
            file_overrides={"inspection_offset_days": 14, "appraisal_offset_days": 21},
        )
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        entry = get_success_data(api_client.create_communication(
            {
                "file_id": file_id,
                "party": "SELLER_AGENT",
                "direction": "OUTBOUND",
                "body": "Confirm possession date",
                "requires_response": True,
                "response_due_at": "2026-08-02T09:00:00Z",
            },
            coord_h,
        ))
        sweep = validate_success(api_client.set_clock({"to_iso8601": "2026-08-04T00:00:00Z"},
                                                      TEST_USERS["admin_headers"]))
        assert sweep["communications_escalated"] == 1
        mid = validate_success(api_client.get_communication(entry["id"], coord_h))
        assert mid["status"] == "ESCALATED", \
            "the clock passed response_due_at 2026-08-02T09:00:00Z"
        f_mid = validate_success(api_client.get_file(file_id, coord_h))
        assert f_mid["open_escalation_count"] == 1

        resolved = validate_success(api_client.resolve_communication(entry["id"], coord_h))
        assert resolved["status"] == "RESOLVED"
        f_after = validate_success(api_client.get_file(file_id, coord_h))
        assert f_after["open_escalation_count"] == 0, \
            "resolving an ESCALATED entry must decrement the file's counter"


class TestDocumentReviewCycleSecondForm:
    def test_document_two_reject_loops_reach_review_round_three(self):
        """PRD §3.5: "A party agent submits it, moving `REQUESTED → RECEIVED` or, on
        resubmission, `REJECTED → RECEIVED`; the actor must be the file's buyer or
        seller agent (`ERR_AGENT_NOT_ON_FILE`), the document must be in `REQUESTED` or
        `REJECTED` (`ERR_DOCUMENT_INVALID_STATE`), the submit stamps
        `submitted_by_agent_id` with the acting agent, a resubmission increments
        `review_round` by 1, and every submission resets the file's
        `last_audit_status` to `NONE`."

        Design: Difficulty/non_linear_state_machine/document_reject_resubmit_review_round_cycle
        """
        scen = make_active_purchase_file(required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        doc = get_success_data(api_client.create_document(
            create_document_payload(file_id=file_id, doc_type="EXECUTED_CONTRACT"), coord_h
        ))
        for round_no, reason in [(1, "illegible scan"), (2, "missing signature page")]:
            submitted = validate_success(api_client.submit_document(doc["id"], scen["buyer_h"]))
            assert submitted["status"] == "RECEIVED"
            rejected = validate_success(
                api_client.reject_document(doc["id"], coord_h, payload={"reason": reason})
            )
            assert rejected["status"] == "REJECTED"
            assert rejected["reject_reason"] == reason
        final_submit = validate_success(api_client.submit_document(doc["id"], scen["buyer_h"]))
        assert final_submit["status"] == "RECEIVED"
        assert final_submit["review_round"] == 3, (
            f"two REJECTED -> RECEIVED loops must increment review_round twice; "
            f"got {final_submit['review_round']}"
        )
