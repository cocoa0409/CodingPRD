"""Client registration, onboarding defaults, envelope and pagination rules."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_client,
    create_client_payload,
    create_prospect_client,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_client_contact_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestClientCreation:
    def test_client_creation_applies_defaults_and_system_fields(
            self, api, account_manager_headers):
        """PRD section 3.1: "The new record starts as `PROSPECT` with
        `open_nc_score` zero, `risk_tier` `LOW`, and `total_billed_cents` zero."
        PRD section 2.4: "The `id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/client_creation_applies_defaults_and_system_fields
        """
        resp = api.create_client(
            create_client_payload(legal_name="Def Co",
                                  certification_scheme="HALAL",
                                  contact_email="d@x.com"),
            account_manager_headers)
        data = validate_success(resp, 201)
        assert_client(data)
        assert data["status"] == "PROSPECT"
        assert data["open_nc_score"] == 0
        assert data["risk_tier"] == "LOW"
        assert data["total_billed_cents"] == 0
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert isinstance(data["version"], int)

    def test_client_create_missing_required_field_returns_invalid_request(
            self, api, account_manager_headers):
        """PRD section 2.8: "then request-body shape — required fields present,
        enum members legal, datetimes parseable, and for any time range the end
        strictly later than the start (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/client_create_missing_required_field_returns_invalid_request
        """
        resp = api.create_client(
            {"legal_name": "Bad Co", "contact_email": "b@x.com"},
            account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_client_create_invalid_enum_returns_invalid_request(
            self, api, account_manager_headers):
        """PRD section 3.1: "The scheme is one of `KOSHER`, `HALAL`, or `DUAL`".
        PRD section 2.8: "then request-body shape — required fields present,
        enum members legal, datetimes parseable, and for any time range the end
        strictly later than the start (`ERR_INVALID_REQUEST`)".

        Design: Corner/entities/client_create_invalid_enum_returns_invalid_request
        """
        resp = api.create_client(
            create_client_payload(legal_name="Enum Co",
                                  certification_scheme="BOTH",
                                  contact_email="e@x.com"),
            account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestClientReads:
    def test_get_nonexistent_client_returns_not_found(
            self, api, account_manager_headers):
        """PRD section 2.5: "A missing id at any level yields `ERR_NOT_FOUND`
        (HTTP 404)".

        Design: Corner/entities/get_nonexistent_client_returns_not_found
        """
        resp = api.get_client(NON_EXISTENT_UUID, account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_list_pagination_envelope_fields_present(
            self, api, account_manager_headers):
        """PRD section 2.3: "List endpoints accept two query parameters, `limit`
        and `offset`." PRD section 2.2: "Pagination-related fields in `meta`
        (`limit`, `offset`, `total_count`, `has_more`) are included for list
        endpoints."

        Design: Corner/entities/list_pagination_envelope_fields_present
        """
        first = create_prospect_client(legal_name="Pg A",
                                       contact_email="pa@x.com")
        second = create_prospect_client(legal_name="Pg B",
                                        contact_email="pb@x.com",
                                        certification_scheme="HALAL")

        page1, meta1 = validate_paginated(
            api.list_clients(account_manager_headers, {"limit": 1, "offset": 0}))
        assert len(page1) == 1, f"page 1 must hold exactly 1 row, got {len(page1)}"
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_clients(account_manager_headers, {"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert meta2["offset"] == 1
        seen = {page1[0]["id"], page2[0]["id"]}
        assert seen == {first["id"], second["id"]}, (
            "both pages together must cover both clients exactly once")


class TestClientLifecycle:
    def test_client_withdraw_twice_terminal_lockdown(self, api):
        """PRD section 3.1: "Acting on a client already in a terminal state, or
        in a status outside the allowed set, yields `ERR_CLIENT_INVALID_STATE`."

        Design: Corner/state_machines/client_withdraw_twice_terminal_lockdown
        """
        client = create_prospect_client(legal_name="SM8 Co",
                                        contact_email="sm8@x.com")
        cc = make_client_contact_headers(client["id"])
        withdrawn = validate_success(api.withdraw_client(client["id"], cc))
        assert withdrawn["status"] == "WITHDRAWN"
        resp = api.withdraw_client(client["id"], cc)
        validate_error(resp, ApiErrorId.ERR_CLIENT_INVALID_STATE)
