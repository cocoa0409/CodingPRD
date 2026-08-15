"""Programs and funders: creation defaults, system-field handling, error
envelope shape, listing pagination, and code uniqueness."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_program,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import create_funder, create_program
from test_helpers.test_users import DIRECTOR


class TestProgramCreation:
    def test_program_create_defaults_and_retrieval(self, api):
        """PRD section 3.1: "A new program begins in `DRAFT` status, with
        `current_logic_model_id` unset - no measurement framework is attached
        until a logic model wins approval - and with
        `current_consent_form_version` set to 1, the first edition of the
        program's consent form."
        PRD section 2.4: "`id` (string): a unique, server-generated identifier
        formatted as a UUID, with no type prefix."

        Design: Corner/entities/program_create_defaults_and_retrieval
        """
        resp = api.create_program({"name": "Afterschool", "code": "AFS"}, DIRECTOR)
        data = validate_success(resp, expected_status=201)
        assert_program(data)
        assert data["status"] == "DRAFT"
        assert data["current_consent_form_version"] == 1
        assert data["current_logic_model_id"] is None
        assert is_valid_uuid(data["id"])

        get_resp = api.get_program(data["id"], DIRECTOR)
        got = validate_success(get_resp)
        assert got["id"] == data["id"]
        assert got["status"] == "DRAFT"
        assert got["current_consent_form_version"] == 1
        assert got["current_logic_model_id"] is None

    def test_program_system_fields_input_ignored(self, api):
        """PRD section 2.9: "Unknown fields and system-managed fields supplied
        in a request body are ignored, not rejected."
        PRD section 3.1: "A new program begins in `DRAFT` status, with
        `current_logic_model_id` unset - no measurement framework is attached
        until a logic model wins approval - and with
        `current_consent_form_version` set to 1, the first edition of the
        program's consent form."

        Design: Corner/entities/program_system_fields_input_ignored
        """
        forged_id = "00000000-0000-0000-0000-000000000000"
        resp = api.create_program(
            {
                "name": "Rigged",
                "code": "RIG",
                "id": forged_id,
                "status": "ACTIVE",
                "version": 99,
                "current_consent_form_version": 42,
            },
            DIRECTOR,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT", "server must ignore client-supplied status"
        assert data["current_consent_form_version"] == 1, (
            "server must ignore client-supplied current_consent_form_version"
        )
        assert data["id"] != forged_id, "server must mint its own id"
        assert isinstance(data["version"], int) and data["version"] >= 1


class TestProgramRead:
    def test_program_not_found_returns_404(self, api):
        """PRD section 2.10: "The server resolves each identifier in order and
        responds with `ERR_NOT_FOUND` (HTTP 404) for the *first* identifier
        that does not resolve to an existing resource, without consulting
        later identifiers."

        Design: Corner/entities/program_not_found_returns_404
        """
        resp = api.get_program("11111111-2222-3333-4444-555555555555", DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_program_missing_required_code_returns_invalid_request(self, api):
        """PRD section 2.9: "request-body well-formedness - required fields
        present, types correct, enum values within their declared sets
        (`ERR_INVALID_REQUEST`)".
        PRD section 3.1: "A `ProgramDirector` creates one by supplying a
        human-readable `name` and a `code`".

        Design: Corner/entities/program_missing_required_code_returns_invalid_request
        """
        resp = api.create_program({"name": "NoCode"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestProgramListing:
    def test_program_list_pagination_defaults_and_offsets(self, api):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned: it defaults to 10 when omitted, and accepts values from a
        minimum of 1 to a maximum of 100. The `offset` parameter specifies
        how many items to skip and defaults to 0."
        PRD section 2.3: "The `meta` object of a list response always carries
        four pagination fields: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/program_list_pagination_defaults_and_offsets
        """
        for i in range(1, 12):
            create_program(name=f"P{i:02d}", code=f"P{i:02d}")

        default_page, default_meta = validate_paginated(api.list_programs(DIRECTOR))
        assert len(default_page) == 10
        assert default_meta["total_count"] == 11
        assert default_meta["has_more"] is True
        assert default_meta["limit"] == 10
        assert default_meta["offset"] == 0

        full_page, full_meta = validate_paginated(
            api.list_programs(DIRECTOR, params={"limit": 11, "offset": 0}))
        assert len(full_page) == 11
        assert full_meta["total_count"] == 11
        assert full_meta["has_more"] is False

        tail_page, tail_meta = validate_paginated(
            api.list_programs(DIRECTOR, params={"limit": 5, "offset": 10}))
        assert len(tail_page) == 1
        assert tail_meta["total_count"] == 11
        assert tail_meta["has_more"] is False


class TestProgramCodeUniqueness:
    def test_program_code_uniqueness_error_envelope(self, api):
        """PRD section 3.1: "the code must be unique across all programs, and
        a duplicate is rejected with `ERR_DUPLICATE_CODE` (HTTP 409)".
        PRD section 2.2: "All error API responses (4xx status codes) follow
        this standard envelope format" with `response_type: "error"` and
        `data.error_id` / `data.message`.

        Design: Corner/errors/error_envelope_shape_on_business_rejection
        """
        create_program(name="First", code="DUP-CODE")
        resp = api.create_program({"name": "Second", "code": "DUP-CODE"}, DIRECTOR)
        error_data = validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)
        assert isinstance(error_data.get("message"), str) and error_data["message"], (
            "error envelope must carry a non-empty message"
        )
