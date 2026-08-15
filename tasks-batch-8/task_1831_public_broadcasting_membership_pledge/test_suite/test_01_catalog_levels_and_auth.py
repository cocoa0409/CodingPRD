"""Membership level catalogue, basic entity reads, pagination, and auth entry rules."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_membership_level,
    create_level,
    create_level_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMembershipLevelCatalog:
    def test_create_membership_level_returns_all_fields(
            self, api, station_admin_headers):
        """PRD §3.1: "A `MembershipLevel` is created with a unique `code`
        (immutable after creation), a `min_annual_cents` threshold for one-time
        pledges, a `min_monthly_sustainer_cents` threshold for sustainer pledges,
        an optional `premium_eligible` flag defaulting to true, and an optional
        `active` flag defaulting to true."
        PRD §2.4: "`version` — an integer starting at 1 on creation and
        incremented by exactly 1 on every mutation of the entity, again
        including cascade-driven mutations."

        Design: Corner/entities/create_membership_level_returns_all_fields
        """
        resp = api.create_membership_level(
            create_level_payload(code="BASIC", min_annual_cents=6000,
                                 min_monthly_sustainer_cents=500),
            station_admin_headers,
        )
        level = validate_success(resp, 201)
        assert_membership_level(level)
        assert level["code"] == "BASIC"
        assert level["min_annual_cents"] == 6000
        assert level["min_monthly_sustainer_cents"] == 500
        assert level["premium_eligible"] is True, (
            "premium_eligible defaults to true when omitted")
        assert level["active"] is True, "active defaults to true when omitted"
        assert level["version"] == 1, "version starts at 1 on creation"
        assert is_valid_uuid(level["id"])
        assert is_iso8601_timestamp(level["created_at"])

    def test_create_membership_level_missing_required_field_returns_invalid_request(
            self, api, station_admin_headers):
        """PRD §2.9: "Request body well-formedness (missing fields, wrong types,
        malformed enums, `ends_at` not strictly after `starts_at`) →
        `ERR_INVALID_REQUEST` (400)."
        PRD §3.1: "A `MembershipLevel` is created with a unique `code`
        (immutable after creation), a `min_annual_cents` threshold for one-time
        pledges, a `min_monthly_sustainer_cents` threshold for sustainer
        pledges"

        Design: Corner/entities/create_membership_level_missing_required_field_returns_invalid_request
        """
        payload = {"code": "BASIC", "min_monthly_sustainer_cents": 500}
        resp = api.create_membership_level(payload, station_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _data, meta = validate_paginated(
            api.list_membership_levels(station_admin_headers))
        assert meta["total_count"] == 0, (
            "no level may be persisted by the rejected create")

    def test_duplicate_level_code_rejected(self, api, station_admin_headers):
        """PRD §3.1: "An attempt to create a level whose `code` is already in
        use is rejected with `ERR_DUPLICATE_CODE` (409)."

        Design: Corner/validations/duplicate_level_code_rejected
        """
        create_level(code="BASIC", min_annual_cents=6000,
                     min_monthly_sustainer_cents=500)
        resp = api.create_membership_level(
            create_level_payload(code="BASIC", min_annual_cents=9000,
                                 min_monthly_sustainer_cents=800),
            station_admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)

    def test_list_membership_levels_pagination_envelope(
            self, api, station_admin_headers):
        """PRD §2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum
        of 100. `offset` defaults to 0. The response `meta` block carries
        `limit`, `offset`, `total_count`, and `has_more` for every list
        response."
        PRD §3.1: "Levels can be listed with an optional `active` filter."

        Design: Corner/entities/list_membership_levels_pagination_envelope
        """
        create_level(code="BASIC", min_annual_cents=6000,
                     min_monthly_sustainer_cents=500)
        create_level(code="LEADERSHIP", min_annual_cents=120000,
                     min_monthly_sustainer_cents=10000)

        resp = api.list_membership_levels(station_admin_headers)
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "array"
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"expected 2 levels, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10, "limit defaults to 10"
        assert meta["offset"] == 0, "offset defaults to 0"
        for level in data:
            assert_membership_level(level)


class TestDonorReadsAndAuth:
    def test_get_donor_not_found_returns_404(self, api, coordinator_headers):
        """PRD §2.9: "Path-referenced resources exist, validated left-to-right
        → `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/get_donor_not_found_returns_404
        """
        resp = api.get_donor(NON_EXISTENT_UUID, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_unauthenticated_request_missing_headers(
            self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the
        server does not recognize, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."
        PRD §2.9: "a request missing its auth header must surface
        `ERR_UNAUTHENTICATED`, never `ERR_DRIVE_NOT_OPEN`, even if the drive is
        also closed"

        Design: Corner/rbac/unauthenticated_request_missing_headers
        """
        resp = api.get_drive(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
