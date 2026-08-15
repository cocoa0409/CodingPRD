"""Site creation, envelope shape, pagination, and authentication gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_housing_site,
    create_housing_site_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSiteCreationDefaults:
    def test_create_site_returns_defaults(self, api, operator_admin_headers):
        """PRD §3.1: "the site is born in `DRAFT` with a `compliance_posture` of
        `NORMAL`."
        PRD §2.5: "`id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/create_site_returns_defaults
        """
        resp = api.create_housing_site(
            create_housing_site_payload(name="Dawn Site", state_code="CA"),
            operator_admin_headers)
        site = validate_success(resp, expected_status=201)
        assert_housing_site(site)
        assert site["status"] == "DRAFT"
        assert site["compliance_posture"] == "NORMAL"
        assert site["version"] == 1
        assert is_valid_uuid(site["id"])

    def test_create_site_missing_state_code_returns_invalid_request(
            self, api, operator_admin_headers):
        """PRD §2.8: "Third, request-body shape — required fields present, types
        correct, enum values inside their declared sets ... — all under
        `ERR_INVALID_REQUEST` (HTTP 400), applied on every mutation endpoint."

        Design: Corner/entities/create_site_missing_state_code_returns_invalid_request
        """
        resp = api.create_housing_site({"name": "No State"},
                                       operator_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_system_field_input_ignored_on_create(self, api,
                                                  operator_admin_headers):
        """PRD §3.1: "the site is born in `DRAFT` with a `compliance_posture` of
        `NORMAL`."
        PRD §2.5: "`version` is an integer that increments by one on every
        mutation of the resource."

        Design: Corner/entities/system_field_input_ignored_on_create
        """
        resp = api.create_housing_site(
            {"name": "S", "state_code": "CA", "status": "OPEN", "version": 99},
            operator_admin_headers)
        site = validate_success(resp, expected_status=201)
        assert site["status"] == "DRAFT", (
            "Client-supplied status must not be honored on create")
        assert site["version"] == 1, (
            "Client-supplied version must not be honored on create")


class TestSiteReadsAndPagination:
    def test_get_site_not_found_returns_404(self, api, operator_admin_headers):
        """PRD §2.11: "Six resource types carry dedicated not-found codes —
        `ERR_SITE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`,
        `ERR_TENANCY_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, and
        `ERR_INSPECTION_NOT_FOUND` — and the specific code takes precedence for
        its type."

        Design: Corner/entities/get_site_not_found_returns_404
        """
        resp = api.get_housing_site("00000000-0000-4000-8000-000000000000",
                                    operator_admin_headers)
        validate_error(resp, ApiErrorId.ERR_SITE_NOT_FOUND)

    def test_list_sites_pagination_defaults(self, api, operator_admin_headers):
        """PRD §2.3: "`limit` sets the page size: it defaults to 10, with a
        minimum of 1 and a maximum of 100. `offset` sets how many matching
        records to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_sites_pagination_defaults
        """
        for i in range(12):
            resp = api.create_housing_site(
                {"name": f"S{i:02d}", "state_code": "CA"},
                operator_admin_headers)
            assert resp.status_code == 201, f"Setup failed creating S{i:02d}"

        data, meta = validate_paginated(api.list_housing_sites(
            operator_admin_headers))
        assert len(data) == 10, "Default page size must be 10"
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0

        data2, meta2 = validate_paginated(api.list_housing_sites(
            operator_admin_headers, params={"limit": 10, "offset": 10}))
        assert len(data2) == 2
        assert meta2["has_more"] is False


class TestEnvelopeAndConsistency:
    def test_envelope_and_immediate_consistency(self, api, site_manager_headers,
                                                operator_admin_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/consistency_model/envelope_and_immediate_consistency
        """
        create_resp = api.create_housing_site(
            {"name": "Env Site", "state_code": "WA"}, operator_admin_headers)
        assert create_resp.status_code == 201
        body = create_resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        site = body["data"]

        # Immediate consistency: the write is visible on a follow-up read.
        got = validate_success(api.get_housing_site(site["id"],
                                                    site_manager_headers))
        assert got["name"] == "Env Site"
        assert got["state_code"] == "WA"

        data, meta = validate_paginated(api.list_housing_sites(
            site_manager_headers))
        assert isinstance(data, list)
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"list meta missing {field}"

        # Error envelope shape: data.error_id + data.message.
        err_resp = api.get_housing_site(
            "00000000-0000-4000-8000-000000000000", site_manager_headers)
        err = validate_error(err_resp, ApiErrorId.ERR_SITE_NOT_FOUND)
        assert isinstance(err["message"], str) and err["message"].strip()


class TestAuthGates:
    def test_missing_auth_header_rejected(self, api, operator_admin_headers):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside the declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before anything
        else is evaluated."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api.create_housing_site({"name": "S", "state_code": "CA"},
                                       operator_admin_headers)
        assert resp.status_code == 201, "Setup failed"

        # No X-User-ID / X-User-Role headers at all.
        bare = api._request("GET", "/housing-sites", headers={})
        validate_error(bare,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_role_denied_site_create_by_intake_coordinator(
            self, api, intake_coordinator_headers):
        """PRD §4: the POST /housing-sites row lists only OperatorAdmin.
        PRD §2.1: "A recognized role attempting an operation it is not
        permitted to perform is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/validations/role_denied_site_create_by_intake_coordinator
        """
        resp = api.create_housing_site({"name": "S", "state_code": "CA"},
                                       intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
