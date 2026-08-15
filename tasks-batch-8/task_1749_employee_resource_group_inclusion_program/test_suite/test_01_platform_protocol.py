"""Platform-wide protocol: auth gate, envelopes, 404s, pagination, filtered
listings, and immediate read-after-write."""
import pytest

from test_helpers import (
    NO_AUTH_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_group_draft,
    create_group_payload,
    create_open_program,
    create_venue,
    create_venue_payload,
    is_valid_uuid,
    make_employee_headers,
    make_group_leader_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import DEI_HEADERS, add_members


class TestAuthenticationGate:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role value outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.create_program(
            {"fiscal_year": 2027, "pool_total_cents": 100000}, NO_AUTH_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, 400)


class TestErrorEnvelope:
    def test_error_response_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

        Design: Corner/endpoints/error_response_envelope_shape
        """
        resp = api.get_venue(NON_EXISTENT_UUID, DEI_HEADERS)
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)
        body = resp.json()
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
        assert isinstance(meta.get("api_request_timestamp"), str)
        assert body["response_type"] == "error"
        assert isinstance(error_data["message"], str) and error_data["message"].strip()


class TestNotFound:
    def test_get_group_not_found_returns_404(self, api):
        """PRD §2.6: "4. **Existence** — path and body-referenced resource ids exist, validated left-to-right (`ERR_NOT_FOUND`, 404)."

        Design: Corner/entities/get_group_not_found_returns_404
        """
        resp = api.get_group("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", DEI_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


class TestServerMintedFields:
    def test_create_group_ignores_client_supplied_id(self, api):
        """PRD §2.4: "Every persisted entity carries a server-minted `id` formatted as a bare UUID with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities except `SurveyResponse` additionally carry `updated_at` (same timestamp format, refreshed on every mutation) and `version` (an integer that starts at 1 and increments by 1 on every mutation of that entity)."

        Design: Corner/entities/create_group_id_input_ignored
        """
        program = create_open_program(100000)
        payload = create_group_payload(program["id"], "Id Ignore", "m", "AFFINITY")
        payload["id"] = "11111111-1111-1111-1111-111111111111"
        resp = api.create_group(payload, make_group_leader_headers("emp_l21"))
        data = validate_success(resp, 201)
        assert is_valid_uuid(data["id"]), "group id must be a server-minted UUID"
        assert data["id"] != "11111111-1111-1111-1111-111111111111", (
            "client-supplied id must be ignored"
        )
        assert data["version"] == 1
        assert data.get("created_at") and data.get("updated_at")


class TestListEndpoints:
    def test_list_groups_pagination_envelope(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0, minimum 0). Results are sorted by `created_at` ascending. List responses include `limit`, `offset`, `total_count`, and `has_more` in `meta`."

        Design: Corner/entities/list_groups_pagination_envelope
        """
        program = create_open_program(100000)
        create_group_draft(program["id"], "Page One", "AFFINITY", "emp_l23")
        create_group_draft(program["id"], "Page Two", "PROFESSIONAL", "emp_l24")

        resp1 = api.list_groups(
            DEI_HEADERS, params={"program_id": program["id"], "limit": 1, "offset": 0}
        )
        data1, meta1 = validate_paginated(resp1)
        assert len(data1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        resp2 = api.list_groups(
            DEI_HEADERS, params={"program_id": program["id"], "limit": 1, "offset": 1}
        )
        data2, meta2 = validate_paginated(resp2)
        assert len(data2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False

    def test_filtered_lists_reach_foreign_keys(self, api):
        """PRD §4: "List endpoints accept optional filter query parameters as described in §3: groups by `program_id`, `sponsor_id`, `status`; memberships by `group_id`, `employee_id`, `status`; leadership terms by `group_id`, `employee_id`, `predecessor_term_id`, `status`; funding requests by `group_id`, `status`; events by `group_id`, `venue_id`, `funding_request_id`, `status`; RSVPs by `event_id`, `employee_id`, `status`; climate surveys by `program_id`, `status`; survey responses by `survey_id`, `employee_id`; mentoring engagements by `program_id`, `sponsor_id`, `mentee_employee_id`, `status`."

        Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
        """
        program = create_open_program(100000)
        group = create_group_draft(program["id"], "FK Walk", "AFFINITY", "emp_l58")
        add_members(group["id"], ["emp_k1", "emp_k2"])
        venue = create_venue("FK Hall", 20)

        data, meta = validate_paginated(
            api.list_memberships(DEI_HEADERS, params={"group_id": group["id"]})
        )
        assert meta["total_count"] == 2
        assert len(data) == 2

        data, meta = validate_paginated(
            api.list_events(DEI_HEADERS, params={"venue_id": venue["id"]})
        )
        assert meta["total_count"] == 0
        assert data == []

        data, meta = validate_paginated(
            api.list_groups(DEI_HEADERS, params={"program_id": program["id"]})
        )
        assert meta["total_count"] == 1


class TestImmediateConsistency:
    def test_read_your_writes_on_venue(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_read_your_writes
        """
        venue = create_venue("RYW Hall", 42)
        # GET is a shared read operation available to every role.
        resp = api.get_venue(venue["id"], make_employee_headers("emp_any"))
        data = validate_success(resp, 200)
        assert data["name"] == "RYW Hall"
        assert data["capacity"] == 42
        assert data["version"] == 1
