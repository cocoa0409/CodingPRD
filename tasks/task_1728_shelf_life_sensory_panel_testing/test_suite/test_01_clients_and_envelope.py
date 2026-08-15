"""Client accounts, response envelope, listing/pagination, and auth context."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_client,
    create_client,
    create_qualified_panelist,
    create_panelist_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

LD = TEST_USERS["lab_director_headers"]
PC = TEST_USERS["coordinator_headers"]
SCI = TEST_USERS["scientist_headers"]


class TestClientCreation:
    def test_client_creation_defaults_and_system_fields(self, api):
        """PRD §3.1: "The account's service `tier` is either `STANDARD` or `PREMIUM`, defaulting to `STANDARD` when omitted. New accounts start with a `retainer_hours_balance` of zero prepaid laboratory hours and an `active_study_count` of zero"
        PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix." and "`created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (e.g., `2026-08-01T09:15:00.123Z`) recorded at creation."
        PRD §4: "Operations that create new resources — clients, studies, arms, time points, chambers, panelists, sessions (including makeups), assignments, scores, lab results, recommendations, reports, claims, retainer top-ups, and sample pulls — return `201 Created`."

        Design: Corner/entities/client_creation_defaults_and_system_fields
        """
        set_clock()
        resp = api.create_client(
            {"name": "Plain Co", "contact_email": "plain@acme.example.com"}, LD)
        assert resp.status_code == 201, f"client creation must return 201, got {resp.status_code}"
        client = validate_success(resp, 201)
        assert_client(client)
        assert client["tier"] == "STANDARD", "omitted tier must default to STANDARD"
        assert client["retainer_hours_balance"] == 0, "new accounts start with zero hours"
        assert client["active_study_count"] == 0, "new accounts start with zero active studies"
        assert is_valid_uuid(client["id"])
        assert is_iso8601_timestamp(client["created_at"])
        assert isinstance(client["version"], int), "version is a system-managed integer"
        # PRD §2.5: three fractional digits, e.g. 2026-08-01T09:15:00.123Z
        fraction = client["created_at"].split(".")[-1].rstrip("Z")
        assert fraction.isdigit() and len(fraction) == 3, (
            f"created_at must carry three fractional digits, got {client['created_at']}")

    def test_client_email_uniqueness_rejected(self, api):
        """PRD §3.1: "The email must be well-formed — a malformed address is `ERR_INVALID_REQUEST` — and unique across all clients, with duplicates rejected as `ERR_EMAIL_NOT_UNIQUE`."

        Design: Corner/entities/client_email_uniqueness_rejected
        """
        first = create_client(name="First", contact_email="dup@acme.example.com")
        resp = api.create_client(
            {"name": "Second", "contact_email": "dup@acme.example.com"}, LD)
        validate_error(resp, ApiErrorId.ERR_EMAIL_NOT_UNIQUE)
        data, meta = validate_paginated(api.list_clients(LD))
        assert meta["total_count"] == 1, "the rejected write must persist nothing"
        assert data[0]["id"] == first["id"]


class TestEnvelope:
    def test_response_envelope_success_and_error(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error." and "The `message` provides a human-readable explanation of what went wrong."
        PRD §2.6: "Path identifiers and body foreign-key references are resolved left to right; the first reference that does not exist yields `ERR_NOT_FOUND` (404)."

        Design: Corner/endpoints/response_envelope_success_and_error
        """
        set_clock()
        resp = api.create_client(
            {"name": "Env Co", "contact_email": "env@acme.example.com"}, LD)
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id must start with 'req_'")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        client = validate_success(resp, 201)
        assert body["data"]["id"] == client["id"]

        err_resp = api.get_client(NON_EXISTENT_UUID, LD)
        assert err_resp.status_code == 404
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        validate_error(err_resp, ApiErrorId.ERR_NOT_FOUND)
        assert err_body["data"]["message"].strip(), "error message must be non-empty"


class TestStudyRead:
    def test_study_get_and_not_found(self, api):
        """PRD §2.6: "Path identifiers and body foreign-key references are resolved left to right; the first reference that does not exist yields `ERR_NOT_FOUND` (404)."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/entities/study_get_and_not_found
        """
        client = create_client()
        study = get_success_data(api.create_study(
            {"client_id": client["id"], "product_name": "Puffs",
             "study_type": "REAL_TIME", "storage_temp_c": 20,
             "target_shelf_life_days": 30, "sensory_fail_threshold": 6.0,
             "min_detectable_difference": 3.0,
             "planned_start_utc": "2026-08-01T00:00:00Z"}, SCI))

        validate_error(api.get_study(NON_EXISTENT_UUID, SCI),
                       ApiErrorId.ERR_NOT_FOUND, 404)

        fetched = validate_success(api.get_study(study["id"], SCI))
        assert fetched["id"] == study["id"]
        assert fetched["product_name"] == "Puffs"


class TestListing:
    def test_clients_list_pagination(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0."
        PRD §2.3: "Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order."
        PRD §2.3: "Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/clients_list_pagination
        """
        create_client(name="C A", contact_email="ca@acme.example.com")
        create_client(name="C B", contact_email="cb@acme.example.com")
        create_client(name="C C", contact_email="cc@acme.example.com")

        page1, meta1 = validate_paginated(
            api.list_clients(LD, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0
        assert [c["name"] for c in page1] == ["C A", "C B"], (
            "default sort is created_at ascending")

        page2, meta2 = validate_paginated(
            api.list_clients(LD, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page2[0]["name"] == "C C"

    def test_list_filters_and_created_at_order(self, api):
        """PRD §2.3: "List endpoints accept additional filter parameters specific to their resource — for example `tier` on the client list"
        PRD §2.3: "Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order."

        Design: Corner/endpoints/list_filters_and_created_at_order
        """
        qualified = create_qualified_panelist(full_name="List One")
        applied = get_success_data(api.create_panelist(
            create_panelist_payload(full_name="List Two"), PC))

        rows, meta = validate_paginated(
            api.list_panelists(PC, params={"status": "QUALIFIED"}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == qualified["id"]

        rows, meta = validate_paginated(
            api.list_panelists(PC, params={"status": "APPLIED"}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == applied["id"]

        rows, meta = validate_paginated(api.list_panelists(PC))
        assert meta["total_count"] == 2
        assert [r["id"] for r in rows] == [qualified["id"], applied["id"]], (
            "unfiltered list is ordered created_at ASC")


class TestAuthContext:
    def test_create_client_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
        PRD §2.6: "Every request is validated against an ordered ladder of checks, and the first rung that fails determines the error returned."

        Design: Corner/validations/create_client_missing_auth_headers_returns_unauthenticated
        """
        set_clock()
        resp = api.create_client(
            {"name": "NoAuth Co", "contact_email": "noauth@acme.example.com"},
            {"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 401)

        _rows, meta = validate_paginated(api.list_clients(LD))
        assert meta["total_count"] == 0, "the unauthenticated write must persist nothing"
