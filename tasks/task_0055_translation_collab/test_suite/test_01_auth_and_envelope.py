"""Authentication, role headers, request envelope, and pagination.

PRD §2.1 (RBAC), §2.2 (envelope), §2.3 (pagination), §2.4 (common fields),
§2.6 (path resolution).
"""
from __future__ import annotations
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    PM,
    TEST_USERS,
    api_client,
    create_client,
    create_client_payload,
    create_project_payload,
    create_translator_payload,
    setup_client_and_project_in_draft,
)


# ===========================================================================
# Auth — missing headers
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_returns_unauthenticated(self):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Claim: missing X-User-ID -> ERR_UNAUTHENTICATED.
        """
        resp = api_client.create_client(
            create_client_payload(),
            headers={"X-User-Role": "ProjectManager"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_missing_user_role_returns_unauthenticated(self):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Claim: missing X-User-Role -> ERR_UNAUTHENTICATED.
        """
        resp = api_client.create_client(
            create_client_payload(),
            headers={"X-User-ID": "some-id"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_empty_user_id_returns_unauthenticated(self):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Claim: empty X-User-ID -> ERR_UNAUTHENTICATED.
        """
        resp = api_client.create_client(
            create_client_payload(),
            headers={"X-User-ID": "", "X-User-Role": "ProjectManager"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ===========================================================================
# Auth — wrong role
# ===========================================================================
class TestRoleForbidden:

    def test_translator_cannot_create_client(self):
        """PRD §2.1: "If both headers are present but the asserted role is
        not permitted to invoke the targeted endpoint per the role matrix
        in Section 4, the request is rejected with ERR_FORBIDDEN (HTTP 403)."

        Claim: Translator role -> POST /clients yields ERR_FORBIDDEN.
        """
        resp = api_client.create_client(
            create_client_payload(),
            headers={"X-User-ID": "trans-1", "X-User-Role": "Translator"},
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_translator_cannot_create_project(self):
        """PRD §2.1: "If both headers are present but the asserted role is
        not permitted to invoke the targeted endpoint per the role matrix
        in Section 4, the request is rejected with ERR_FORBIDDEN (HTTP 403)."

        Claim: POST /projects requires ProjectManager (per §4 endpoint table).
        """
        client = create_client()
        resp = api_client.create_project(
            create_project_payload(client["id"]),
            headers={"X-User-ID": "trans-2", "X-User-Role": "Translator"},
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_translator_cannot_dispatch_assignment(self):
        """PRD §2.1: "If both headers are present but the asserted role is
        not permitted to invoke the targeted endpoint per the role matrix
        in Section 4, the request is rejected with ERR_FORBIDDEN (HTTP 403)."

        Claim: POST /projects/{id}/assignments requires ProjectManager.
        """
        _, project = setup_client_and_project_in_draft()
        resp = api_client.dispatch_assignment(
            project["id"],
            {"translator_id": "x", "role": "TRANSLATOR",
             "segment_ids": [NON_EXISTENT_UUID]},
            headers={"X-User-ID": "trans-3", "X-User-Role": "Translator"},
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ===========================================================================
# Path resolution
# ===========================================================================
class TestPathResolution:

    def test_get_unknown_client_returns_not_found(self):
        """PRD §2.6: "a 404 with ERR_NOT_FOUND is returned the first time
        a path segment fails to resolve."

        Claim: GET /clients/{non-existent} -> ERR_NOT_FOUND.
        """
        resp = api_client.get_client(NON_EXISTENT_UUID, PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_get_unknown_project_returns_not_found(self):
        """PRD §2.6: "a 404 with ERR_NOT_FOUND is returned the first time
        a path segment fails to resolve."

        Claim: GET /projects/{non-existent} -> ERR_NOT_FOUND.
        """
        resp = api_client.get_project(NON_EXISTENT_UUID, PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_get_unknown_segment_returns_not_found(self):
        """PRD §2.6: "a 404 with ERR_NOT_FOUND is returned the first time
        a path segment fails to resolve."

        Claim: GET /segments/{non-existent} -> ERR_NOT_FOUND.
        """
        resp = api_client.get_segment(NON_EXISTENT_UUID, PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ===========================================================================
# Envelope shape
# ===========================================================================
class TestSuccessEnvelope:

    def test_success_envelope_carries_meta_request_id_and_timestamp(self):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with req_."

        Claim: success envelope contains meta.api_request_id (req_-prefixed)
        and meta.api_request_timestamp (ISO 8601).
        """
        client = create_client()
        resp = api_client.get_client(client["id"], PM)
        validate_success(resp)
        body = resp.json()
        assert "meta" in body
        meta = body["meta"]
        rid = meta.get("api_request_id", "")
        assert rid.startswith("req_"), f"api_request_id must start with req_, got {rid!r}"
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), \
            "api_request_timestamp must be ISO 8601"

    def test_success_envelope_response_type_is_object_for_resource(self):
        """PRD §2.2: "The response_type is either \\"object\\" for a single
        resource or \\"array\\" for a list of resources."

        Claim: GET /clients/{id} yields response_type == "object".
        """
        client = create_client()
        resp = api_client.get_client(client["id"], PM)
        body = resp.json()
        assert body.get("response_type") == "object"

    def test_error_envelope_carries_error_id_and_message(self):
        """PRD §2.2: "The error_id is a unique, machine-readable string
        that identifies the specific error."

        Claim: a 404 error response body has data.error_id and data.message.
        """
        resp = api_client.get_client(NON_EXISTENT_UUID, PM)
        body = resp.json()
        assert body.get("response_type") == "error"
        data = body.get("data", {})
        assert data.get("error_id") == "ERR_NOT_FOUND"
        assert isinstance(data.get("message"), str) and data["message"]


# ===========================================================================
# Common resource properties (PRD §2.4)
# ===========================================================================
class TestCommonResourceFields:

    def test_versioned_entity_starts_at_version_one(self):
        """PRD §2.4: "version (a non-negative integer that starts at 1 and
        increases by exactly one each time the row is mutated)."

        Claim: a freshly created Client has version == 1.
        """
        client = create_client()
        assert client["version"] == 1, \
            f"new Client must have version == 1, got {client['version']}"

    def test_versioned_entity_created_at_equals_updated_at_on_insert(self):
        """PRD §2.4: "updated_at (the ISO 8601 UTC timestamp of the most
        recent mutation, equal to created_at immediately after insert)."

        Claim: a freshly created Client has updated_at == created_at.
        """
        client = create_client()
        assert client["updated_at"] == client["created_at"], \
            "updated_at must equal created_at immediately after insert"

    def test_resource_id_is_plain_uuid(self):
        """PRD §2.4: "Every resource exposes an id that is a server-minted
        UUID, returned as a plain hyphenated UUID string with no entity-type
        prefix."

        Claim: Client.id is a UUID string (no entity-type prefix).
        """
        client = create_client()
        assert is_valid_uuid(client["id"])
        assert "_" not in client["id"], "no entity-type prefix permitted"


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
class TestPagination:

    def test_list_default_limit_is_ten(self):
        """PRD §2.3: "List endpoints accept two query parameters: limit
        defaults to 10."

        Claim: GET /clients with no limit returns at most 10 rows.
        """
        # Create 12 clients to exceed default limit
        for _ in range(12):
            create_client()
        resp = api_client.list_clients(PM)
        data, meta = validate_paginated(resp)
        assert len(data) <= 10, "default page size is 10"
        assert meta["limit"] == 10
        assert meta["offset"] == 0

    def test_list_meta_includes_total_count_and_has_more(self):
        """PRD §2.3: "The meta envelope for list responses includes limit,
        offset, total_count (the total number of rows that match the
        filter, ignoring pagination), and has_more (true when more rows
        exist beyond the current page)."

        Claim: meta carries limit, offset, total_count, has_more.
        """
        create_client()
        resp = api_client.list_clients(PM, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"meta must include {key}"

    def test_list_returns_created_at_ascending_by_default(self):
        """PRD §2.3: "Results are returned in created_at ascending order
        unless an endpoint explicitly states otherwise."

        Claim: GET /clients returns rows sorted by created_at ascending.
        """
        a = create_client()
        b = create_client()
        c = create_client()
        resp = api_client.list_clients(PM, params={"limit": 100})
        data, _ = validate_paginated(resp)
        ids = [row["id"] for row in data]
        # The three created in this test must appear with a before b before c.
        positions = {x: ids.index(x) for x in (a["id"], b["id"], c["id"])
                     if x in ids}
        assert positions[a["id"]] < positions[b["id"]] < positions[c["id"]], \
            "list must be created_at ascending"
