"""Entity creation / read shape, default fields, append-only invariants."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, is_valid_uuid,
    ApiErrorId,
    create_client, create_client_with_agreement, create_batch, create_box,
    create_document, create_scanner_unit,
    batch_in_scanning, open_session_with_logs,
    make_platform_admin_headers, make_intake_clerk_headers,
    make_scan_operator_headers,
    ADMIN, CLERK, SCAN, NON_EXISTENT_UUID,
)


class TestClientCreationDefaultsAndSystemFields:
    """Corner: client_creation_defaults_and_system_fields."""

    def test_new_client_active_version_one_clock_default(self, api):
        """PRD §3.1: "A new client starts in `ACTIVE` status" PRD §2.4:
        "`version`, an integer that increments by exactly 1 on every mutation
        of the resource." PRD §2.5: "The clock's startup default, before
        anyone has set it, is exactly `2026-05-01T00:00:00Z`, and the server
        must not silently fall back to the host's wall clock."

        Design: Corner/entities/client_creation_defaults_and_system_fields
        """
        client = create_client(name="Acme", hipaa_covered=True)
        assert client["status"] == "ACTIVE"
        assert client["version"] == 1
        # PRD §2.5 clock default 2026-05-01T00:00:00Z serialized per PRD §2.4
        # with three fractional digits.
        assert client["created_at"] == "2026-05-01T00:00:00.000Z", (
            f"created_at must follow the logical clock default, got {client['created_at']}"
        )
        assert is_valid_uuid(client["id"])


class TestGetNonexistentBatchReturnsNotFound:
    """Corner: get_nonexistent_batch_returns_not_found."""

    def test_get_missing_batch_returns_404(self, api):
        """PRD §2.9: "Where a URL nests a resource under a parent, path
        parameters are validated left to right: each id must exist, and each
        child must actually belong to the named parent. A wrong-parent id is
        reported as `ERR_NOT_FOUND` (HTTP 404), never as a malformed-request
        400."

        Design: Corner/entities/get_nonexistent_batch_returns_not_found
        """
        resp = api_client.get_batch(NON_EXISTENT_UUID, make_intake_clerk_headers(CLERK))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestCreateDocumentMissingRequiredPages:
    """Corner: create_document_missing_required_pages_returns_invalid_request."""

    def test_missing_pages_field_rejected_400(self, api):
        """PRD §2.8: "then request-body well-formedness — required fields
        present, types correct, enums within their declared sets, numeric
        ranges honored, and no unknown or server-computed keys in the payload
        (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/create_document_missing_required_pages_returns_invalid_request
        """
        client, _ = create_client_with_agreement(name="Req Co", hipaa_covered=False)
        batch = create_batch(client["id"])
        box = create_box(batch["id"])
        resp = api_client.create_document(
            box["id"],
            {"doc_type": "OTHER", "contains_phi": False, "ocr_confidence": 95},
            make_intake_clerk_headers(CLERK),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        docs, meta = validate_paginated(api_client.list_box_documents(box["id"], make_intake_clerk_headers(CLERK)))
        assert meta["total_count"] == 0


class TestCreateBatchWithComputedFieldExtraFieldRejected:
    """Corner: create_batch_with_computed_field_extra_field_rejected."""

    def test_scanned_pages_in_create_payload_rejected(self, api):
        """PRD §2.8: "then request-body well-formedness — required fields
        present, types correct, enums within their declared sets, numeric
        ranges honored, and no unknown or server-computed keys in the payload
        (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/create_batch_with_computed_field_extra_field_rejected
        """
        client, _ = create_client_with_agreement(name="Xtra Co", hipaa_covered=False)
        resp = api_client.create_batch(
            {"client_id": client["id"], "priority": "STANDARD", "scanned_pages": 999},
            make_intake_clerk_headers(CLERK),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestPageLogAppendOnlyImmutability:
    """Corner: page_log_append_only_immutability."""

    def test_page_log_carries_no_version_or_updated_at(self, api):
        """PRD §2.4: "Two resource kinds are deliberately append-only event
        logs and carry only `id` and `created_at`: a `PageLog` row and a
        `CustodyEvent` row have neither `updated_at` nor `version`."

        Design: Corner/entities/page_log_append_only_immutability
        """
        client, _ = create_client_with_agreement(name="PL Co", hipaa_covered=False)
        ctx = batch_in_scanning(
            [{"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        session = open_session_with_logs(ctx, [(ctx["documents"][0]["id"], 50)])
        # List page logs of the session
        logs, _ = validate_paginated(api_client.list_session_page_logs(session["id"], make_scan_operator_headers(SCAN)))
        assert len(logs) == 1
        log = logs[0]
        assert "version" not in log, "PageLog must not expose version"
        assert "updated_at" not in log, "PageLog must not expose updated_at"
        assert log["pages"] == 50
        assert log["document_id"] == ctx["documents"][0]["id"]
        # GET the page log by id and re-assert shape
        single = get_success_data(api_client.get_page_log(log["id"], make_scan_operator_headers(SCAN)))
        assert "version" not in single
        assert "updated_at" not in single


class TestDocumentEnumTypeConstraintRejected:
    """Corner: document_enum_type_constraint_rejected."""

    def test_doc_type_outside_enum_rejected(self, api):
        """PRD §3.3: "an `IntakeClerk` or `PrepTechnician` registers each
        document into its box with a `doc_type` of `MEDICAL_RECORD`,
        `INVOICE`, `CONTRACT`, `CORRESPONDENCE`, or `OTHER`" PRD §2.8: "then
        request-body well-formedness — required fields present, types correct,
        enums within their declared sets, numeric ranges honored, and no
        unknown or server-computed keys in the payload
        (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/document_enum_type_constraint_rejected
        """
        client, _ = create_client_with_agreement(name="Enum Co", hipaa_covered=False)
        batch = create_batch(client["id"])
        box = create_box(batch["id"])
        resp = api_client.create_document(
            box["id"],
            {"doc_type": "BLUEPRINT", "pages": 10, "contains_phi": False, "ocr_confidence": 95},
            make_intake_clerk_headers(CLERK),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
