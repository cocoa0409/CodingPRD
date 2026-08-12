"""Entity creation defaults, response envelope shape, listing filters, pagination,
and immediate read-after-write consistency (PRD §2.2, §2.3, §2.4, §3.1, §3.2, §3.3)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, is_iso8601_timestamp,
    set_logical_clock, make_client, make_platform_profile, make_project,
    activate_client, create_client_payload, create_engineer_payload,
    create_project_payload, make_client_headers, TEST_USERS, NON_EXISTENT_UUID,
    ApiErrorId,
)

MANAGER = TEST_USERS["manager_headers"]


class TestEntityCreationDefaults:

    def test_client_creation_initializes_defaults(self, api):
        """PRD §3.1: "A freshly registered client starts in `PROSPECT` status with
        `account_credit_cents` at zero and `lifetime_revision_count` at zero."
        PRD §2.4: "`id` (string): a unique, server-generated identifier for the
        resource, formatted as a UUID with no type prefix."

        Design: Corner/entities/client_creation_initializes_defaults
        """
        set_logical_clock()
        client = validate_success(api.create_client(
            create_client_payload(legal_name="X Label", contact_email="x@x.com"),
            MANAGER), 201)
        assert client["status"] == "PROSPECT"
        assert client["account_credit_cents"] == 0
        assert client["lifetime_revision_count"] == 0
        assert is_valid_uuid(client["id"])
        assert is_iso8601_timestamp(client["created_at"])

    def test_engineer_creation_defaults_available(self, api):
        """PRD §3.2: "New engineers start with `availability_status` set to
        `AVAILABLE` and an `active_project_count` of zero."

        Design: Corner/entities/engineer_creation_defaults_availability_available
        """
        set_logical_clock()
        engineer = validate_success(api.create_engineer(
            create_engineer_payload(display_name="E", tier="JUNIOR",
                                    hourly_rate_cents=50000,
                                    capacity_minutes_per_day=240),
            MANAGER), 201)
        assert engineer["availability_status"] == "AVAILABLE"
        assert engineer["active_project_count"] == 0

    def test_project_missing_required_field_rejected(self, api):
        """PRD §2.5: "Independently of this chain, a payload that is missing a
        required field or carries a malformed value or a value of the wrong type is
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)." PRD §3.3: "The creation
        payload carries the release `title`, an optional `upc`, the
        `target_platform_profile_id` of the distribution target the master must
        satisfy, the requested `scheduled_start_at`, the `scheduled_duration_minutes`,
        and an optional `rush_tier` that defaults to `STANDARD`."

        Omitting target_platform_profile_id is rejected.

        Design: Corner/entities/project_missing_required_field_rejected
        """
        set_logical_clock()
        client = make_client()
        payload = {
            "client_id": client["id"],
            "title": "P",
            "scheduled_start_at": "2026-05-11T10:00:00Z",
            "scheduled_duration_minutes": 60,
        }
        res = api.create_project(payload, make_client_headers(client["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_project_upc_invalid_format_rejected(self, api):
        """PRD §3.3: "The `upc`, when present, is a 12-digit numeric string and must
        be unique across every project in the studio — a collision on creation, or on
        any later update of the project, is rejected with `ERR_DUPLICATE_UPC` (HTTP
        409) — and a malformed `upc` fails format validation with
        `ERR_INVALID_FORMAT` (HTTP 400)."

        An 11-digit UPC is malformed.

        Design: Corner/entities/project_upc_invalid_format_rejected
        """
        set_logical_clock()
        profile = make_platform_profile()
        client = make_client()
        payload = create_project_payload(
            client["id"], profile["id"], upc="12345678901", rush_tier="STANDARD")
        res = api.create_project(payload, make_client_headers(client["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_FORMAT, expected_status=400)

    def test_project_upc_uniqueness_enforced(self, api):
        """PRD §3.3: "The `upc`, when present, is a 12-digit numeric string and must
        be unique across every project in the studio — a collision on creation, or on
        any later update of the project, is rejected with `ERR_DUPLICATE_UPC` (HTTP
        409)".

        Design: Corner/entities/project_upc_uniqueness_enforced
        """
        set_logical_clock()
        profile = make_platform_profile()
        client = make_client()
        headers = make_client_headers(client["id"])
        validate_success(api.create_project(
            create_project_payload(client["id"], profile["id"], title="P1",
                                   upc="999999999999", rush_tier="STANDARD"),
            headers), 201)
        res = api.create_project(
            create_project_payload(client["id"], profile["id"], title="P2",
                                   upc="999999999999", rush_tier="STANDARD",
                                   scheduled_start_at="2026-05-11T13:00:00Z"),
            headers)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_UPC, expected_status=409)

    def test_get_nonexistent_project_returns_not_found(self, api):
        """PRD §2.5: "Third (priority 3), path existence: every resource identified
        by a path segment must exist, validated left to right, failing with
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/entity_not_found_returns_404
        """
        set_logical_clock()
        res = api.get_project(NON_EXISTENT_UUID, MANAGER)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_system_fields_id_and_created_at_server_minted(self, api):
        """PRD §2.4: "`id` (string): a unique, server-generated identifier for the
        resource, formatted as a UUID with no type prefix." PRD §2.4: "`created_at`
        (string): an ISO 8601 timestamp in UTC with three fractional digits (for
        example, `2026-05-01T00:00:00.000Z`) recording when the resource was first
        created."

        Design: Corner/entities/system_fields_id_and_created_at_server_minted
        """
        set_logical_clock()
        client = validate_success(api.create_client(
            create_client_payload(legal_name="X", contact_email="x@x.com"),
            MANAGER), 201)
        assert is_valid_uuid(client["id"]), "id must be a server-minted UUID"
        assert is_iso8601_timestamp(client["created_at"])
        assert is_iso8601_timestamp(client["updated_at"])
        assert isinstance(client["version"], int)


class TestListingAndEnvelope:

    def test_list_projects_filter_by_client(self, api):
        """PRD §3.3: "The project list can be filtered by `client_id`, `status`,
        `assigned_engineer_id`, `target_platform_profile_id`,
        `current_revision_round_id`, and `archive_bundle_id`." PRD §2.3: "Paginated
        list-based responses include the following fields in the `meta` object of the
        response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_projects_filter_by_client
        """
        set_logical_clock()
        profile = make_platform_profile()
        c1 = make_client(legal_name="C1", contact_email="c1@x.com")
        c2 = make_client(legal_name="C2", contact_email="c2@x.com")
        validate_success(api.create_project(
            create_project_payload(c1["id"], profile["id"], title="P1",
                                   upc="111111111111", rush_tier="STANDARD"),
            make_client_headers(c1["id"])), 201)
        validate_success(api.create_project(
            create_project_payload(c2["id"], profile["id"], title="P2",
                                   upc="222222222222", rush_tier="STANDARD",
                                   scheduled_start_at="2026-05-11T13:00:00Z"),
            make_client_headers(c2["id"])), 201)

        res = api.list_projects(MANAGER, params={"client_id": c1["id"]})
        data, meta = validate_paginated(res)
        assert len(data) == 1
        assert data[0]["client_id"] == c1["id"]
        assert "api_request_id" in meta
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"pagination meta must include {field}"

    def test_response_envelope_success_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`." PRD §2.2: "The `response_type` is
        either "object" for a single resource or "array" for a list of resources."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/endpoints/response_envelope_success_shape
        """
        set_logical_clock()
        res = api.create_client(
            create_client_payload(legal_name="C", contact_email="c@x.com"), MANAGER)
        body = res.json()
        assert res.status_code == 201
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        data = body["data"]
        for field in ("id", "status", "version", "created_at", "updated_at"):
            assert field in data, f"created resource must carry {field}"

    def test_response_envelope_error_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." PRD §2.2: "The `error_id` is a
        unique, machine-readable string that identifies the specific error." PRD
        §2.2: "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/endpoints/response_envelope_error_shape
        """
        set_logical_clock()
        res = api.get_project(NON_EXISTENT_UUID, MANAGER)
        body = res.json()
        assert res.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]

    def test_pagination_limit_offset_interaction(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
        return. If not provided, it defaults to 10, with a minimum of 1 and a maximum
        of 100. The `offset` parameter specifies the number of items to skip and
        defaults to 0." PRD §2.3: "Paginated list-based responses include the
        following fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."

        Three clients exist; limit=2&offset=1 returns the second page of 2 with
        total_count 3 and has_more false.

        Design: Corner/cross_cutting/pagination_limit_offset_interaction
        """
        set_logical_clock()
        make_client(legal_name="A", contact_email="a@x.com")
        make_client(legal_name="B", contact_email="b@x.com")
        make_client(legal_name="C", contact_email="c@x.com")
        data, meta = validate_paginated(
            api.list_clients(MANAGER, params={"limit": 2, "offset": 1}))
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is False, (
            "offset+limit (1+2) covers total_count (3), so no further page remains")


class TestImmediateConsistency:

    def test_state_change_visible_immediately(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field." PRD §3.1: "Activation moves a client from `PROSPECT` to `ACTIVE`, and
        a first activation is only possible once at least one project row exists for
        that client, in any status at all; the transition increments the client's
        `version` and refreshes `updated_at`."

        The activate response already reads ACTIVE with an incremented version, and a
        subsequent GET reflects the same state.

        Design: Corner/consistency/state_change_visible_immediately
        """
        set_logical_clock()
        profile = make_platform_profile()
        client = make_client()
        version_before = client["version"]
        make_project(client["id"], profile["id"], upc=None)
        activated = validate_success(api.activate_client(client["id"], MANAGER), 200)
        assert activated["status"] == "ACTIVE"
        assert activated["version"] > version_before, (
            "activation must increment the client's version")
        fetched = validate_success(api.get_client(client["id"], MANAGER), 200)
        assert fetched["status"] == "ACTIVE"
        assert fetched["version"] == activated["version"]
