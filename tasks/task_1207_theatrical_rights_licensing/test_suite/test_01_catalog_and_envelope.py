"""Catalogue basics (Title CRUD) and response-envelope shape tests (PRD §2.2, §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_title,
    create_title_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    reset_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTitleCreation:
    def test_create_title_with_all_required_fields_returns_201(
        self, api, rights_admin_headers
    ):
        """PRD §3.1: "A new title starts in `status` `ACTIVE` and at `version` 1."
        PRD §4: "Successful resource-creation requests return HTTP 201".

        Design: Corner/entities/create_title_with_all_required_fields_returns_201
        """
        reset_clock()
        payload = create_title_payload(
            name="Hamlet",
            author="Shakespeare",
            title_kind="PLAY",
            royalty_basis="PER_PERFORMANCE",
        )
        resp = api.create_title(payload, rights_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_title(data)
        assert data["status"] == "ACTIVE", "New title must start ACTIVE"
        assert data["version"] == 1, "New title must start at version 1"
        assert data["name"] == "Hamlet"
        assert data["author"] == "Shakespeare"

    def test_get_title_by_id_returns_stored_data(self, api, rights_admin_headers):
        """PRD §2.2: "operations that create or modify a resource will return the
        created or updated resource object in the data field."
        PRD §4 lists GET /licensing/titles/{title_id} as "Read a Title".

        Design: Corner/entities/get_title_by_id_returns_stored_data
        """
        reset_clock()
        created = validate_success(
            api.create_title(
                create_title_payload(name="Hamlet", author="Shakespeare"),
                rights_admin_headers,
            ),
            expected_status=201,
        )
        resp = api.get_title(created["id"], rights_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert_title(data)
        assert data["id"] == created["id"]
        assert data["name"] == "Hamlet"
        assert data["author"] == "Shakespeare"

    def test_get_title_missing_returns_404(self, api, rights_admin_headers):
        """PRD §2.6: "the first segment that fails to resolve yields
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_title_missing_returns_404
        """
        reset_clock()
        resp = api.get_title(NON_EXISTENT_UUID, rights_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_create_title_missing_required_field_returns_invalid_request(
        self, api, rights_admin_headers
    ):
        """PRD §2.7: "then payload shape and typing (`ERR_INVALID_REQUEST`)".
        PRD §3.1: "A title has a `name` and an `author`".

        Design: Corner/entities/create_title_missing_required_field_returns_invalid_request
        """
        reset_clock()
        payload = create_title_payload()
        del payload["name"]
        resp = api.create_title(payload, rights_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_title_invalid_enum_title_kind_rejected(self, api, rights_admin_headers):
        """PRD §3.1: "is classified by `title_kind` as one of `PLAY`, `MUSICAL`,
        or `MUSICAL_WITH_SCORE`."
        PRD §2.7: "then payload shape and typing (`ERR_INVALID_REQUEST`)".

        Design: Corner/entities/title_invalid_enum_title_kind_rejected
        """
        reset_clock()
        resp = api.create_title(
            create_title_payload(title_kind="OPERA"), rights_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_list_titles_pagination_defaults(self, api, rights_admin_headers):
        """PRD §2.3: "The default `limit` is 10 ... The `meta` block of a list
        response carries the pagination fields `limit`, `offset`, `total_count`,
        and `has_more`; `total_count` reflects the total number of matching
        records after filters are applied".

        Design: Corner/entities/list_titles_pagination_defaults
        """
        reset_clock()
        validate_success(
            api.create_title(create_title_payload(name="A"), rights_admin_headers),
            expected_status=201,
        )
        validate_success(
            api.create_title(
                create_title_payload(
                    name="B",
                    title_kind="MUSICAL",
                    royalty_basis="HYBRID",
                    gross_percent_bp=500,
                ),
                rights_admin_headers,
            ),
            expected_status=201,
        )
        data, meta = validate_paginated(api.list_titles(rights_admin_headers))
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert isinstance(data, list) and len(data) == 2


class TestResponseEnvelope:
    def test_response_envelope_shape_on_success(self, api, rights_admin_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`." and "The `response_type` is
        either "object" for a single resource or "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_shape_on_success
        """
        reset_clock()
        resp = api.create_title(create_title_payload(), rights_admin_headers)
        assert resp.status_code == 201
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert_title(body["data"])

    def test_response_envelope_shape_on_error(self, api, rights_admin_headers):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
        unique, machine-readable string that identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape_on_error
        """
        reset_clock()
        resp = api.get_title(NON_EXISTENT_UUID, rights_admin_headers)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0

    def test_immediate_consistency_reads_see_writes(self, api, rights_admin_headers):
        """PRD §3.1: "A new title starts in `status` `ACTIVE` and at `version` 1."
        PRD §2.2: "operations that create or modify a resource will return the
        created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_consistency_reads_see_writes
        """
        reset_clock()
        resp = api.create_title(create_title_payload(), rights_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1
