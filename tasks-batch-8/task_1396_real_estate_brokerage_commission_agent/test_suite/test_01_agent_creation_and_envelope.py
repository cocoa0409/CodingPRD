"""Agent creation defaults, response envelope, pagination (PRD §2.2, §2.3, §2.5, §3.1)."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, validate_paginated,
    get_success_data, is_valid_uuid, is_iso8601_timestamp,
    ApiErrorId, assert_agent, create_agent_payload, NON_EXISTENT_UUID,
)


class TestAgentCreateDefaults:
    def test_agent_create_applies_defaults_and_initial_state(self, api):
        """PRD §3.1: "A newly created agent starts in `ONBOARDING` status with
        `debit_balance_cents` at 0 and `settled_deal_count` at 0."
        PRD §3.1: "Both `mentor_agent_id` and `team_lead_agent_id` default to
        null"; the `team_override_pct` "defaults to 0".

        Design: Corner/entities/agent_create_applies_defaults_and_initial_state
        """
        resp = api.create_agent(
            create_agent_payload(full_name="Default Dana", email="dd@x.com",
                                 license_number="LIC-E1", joined_at="2025-09-01"),
            TEST_USERS["broker_admin_headers"],
        )
        assert resp.status_code == 201
        data = validate_success(resp, expected_status=201)
        assert_agent(data)
        assert data["status"] == "ONBOARDING"
        assert data["debit_balance_cents"] == 0
        assert data["settled_deal_count"] == 0
        assert data["team_override_pct"] == 0
        assert data["version"] == 1
        assert data["mentor_agent_id"] is None
        assert data["team_lead_agent_id"] is None
        assert is_iso8601_timestamp(data["created_at"])

    def test_agent_create_response_is_object_envelope_with_meta(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format" with response_type "object" for a
        single resource and meta.api_request_id / meta.api_request_timestamp.

        Design: Corner/entities/agent_create_applies_defaults_and_initial_state
        """
        resp = api.create_agent(
            create_agent_payload(full_name="Default Dana", email="dd@x.com",
                                 license_number="LIC-E1", joined_at="2025-09-01"),
            TEST_USERS["broker_admin_headers"],
        )
        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"]
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert is_valid_uuid(body["data"]["id"])


class TestAgentCreateSystemFieldsIgnored:
    def test_client_supplied_id_ignored(self, api):
        """PRD §2.5: "id (string): a unique, server-generated identifier formatted
        as a UUID" — the server mints it; a client-supplied id never wins.
        PRD §3.1: "A newly created agent starts in ONBOARDING status with
        debit_balance_cents at 0".

        Design: Corner/entities/agent_create_system_fields_input_ignored
        """
        resp = api.create_agent(
            {
                "full_name": "Sneaky Sam", "email": "ss@x.com",
                "license_number": "LIC-E2", "joined_at": "2025-09-01",
                "id": "11111111-1111-1111-1111-111111111111",
                "status": "ACTIVE", "debit_balance_cents": 999,
            },
            TEST_USERS["broker_admin_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["id"] != "11111111-1111-1111-1111-111111111111"
        assert data["status"] == "ONBOARDING"
        assert data["debit_balance_cents"] == 0

    def test_server_minted_id_is_uuid(self, api):
        """PRD §2.5: "id (string): a unique, server-generated identifier formatted
        as a UUID, with no type prefix."

        Design: Corner/entities/agent_create_system_fields_input_ignored
        """
        resp = api.create_agent(
            {
                "full_name": "Sneaky Sam", "email": "ss@x.com",
                "license_number": "LIC-E2", "joined_at": "2025-09-01",
                "id": "11111111-1111-1111-1111-111111111111",
                "status": "ACTIVE",
            },
            TEST_USERS["broker_admin_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"])


class TestAgentPagination:
    def test_agents_list_pagination_page_boundaries(self, api):
        """PRD §2.3: "The limit parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The offset
        parameter says how many items to skip and defaults to 0... Paginated list
        responses carry the fields limit, offset, total_count, and has_more in the
        meta object of the envelope."

        Design: Corner/entities/agents_list_pagination_envelope
        """
        for i, name in enumerate(("Page One", "Page Two")):
            api.create_agent(
                create_agent_payload(full_name=name, email=f"p{i}@x.com",
                                     license_number=f"LIC-P{i}", joined_at="2025-09-01"),
                TEST_USERS["broker_admin_headers"],
            )
        page1, meta1 = validate_paginated(
            api.list_agents(TEST_USERS["broker_admin_headers"], params={"limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["limit"] == 1 and meta1["offset"] == 0
        assert meta1["total_count"] == 2 and meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_agents(TEST_USERS["broker_admin_headers"], params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["total_count"] == 2 and meta2["has_more"] is False

    def test_agents_list_envelope_response_type_and_meta(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/entities/agents_list_pagination_envelope
        """
        api.create_agent(
            create_agent_payload(full_name="Page One", email="p1@x.com",
                                 license_number="LIC-P1", joined_at="2025-09-01"),
            TEST_USERS["broker_admin_headers"],
        )
        resp = api.list_agents(TEST_USERS["broker_admin_headers"], params={"limit": 10})
        body = resp.json()
        assert body["response_type"] == "array"
        assert body["meta"]["api_request_id"]
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


class TestDealNotFound:
    def test_get_nonexistent_deal_returns_404(self, api):
        """PRD §2.10: "The first identifier that does not correspond to an existing
        resource produces ERR_NOT_FOUND (HTTP 404)."

        Design: Corner/entities/deal_get_not_found_returns_404
        """
        resp = api.get_deal(NON_EXISTENT_UUID, TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestMissingRequiredField:
    def test_agent_create_missing_license_returns_invalid_request(self, api):
        """PRD §2.9 item 5: "Request schema: every required input field of the
        endpoint must be present and parse to its declared type ... else
        ERR_INVALID_REQUEST."

        Design: Corner/entities/agent_create_missing_required_license_returns_invalid_request
        """
        resp = api.create_agent(
            {"full_name": "No License", "email": "nl@x.com", "joined_at": "2025-09-01"},
            TEST_USERS["broker_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestInvalidEnumFilter:
    def test_deals_list_invalid_status_enum_returns_400(self, api):
        """PRD §2.9 item 5: "every query filter — including enum-valued filters —
        must parse to its declared type, else ERR_INVALID_REQUEST."

        Design: Corner/entities/deals_list_invalid_enum_status_returns_invalid_request
        """
        resp = api.list_deals(TEST_USERS["broker_admin_headers"], params={"status": "BOGUS"})
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
