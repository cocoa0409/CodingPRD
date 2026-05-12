"""Authentication, response envelope, pagination, and RBAC.

Covers PRD §2.1 (RBAC headers), §2.2 (envelope), §2.3 (pagination),
§2.4 (resource identity / timestamps / versioning).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_department_payload,
    create_material_template_payload,
    create_matter_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_single_department_published_version,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# PRD §2.1 -- header presence and role authorization
# ===========================================================================
class TestAuthHeaders:
    def test_missing_role_header_returns_err_auth_missing(self, api):
        """PRD §2.1: "Either header missing or empty is rejected with
        ERR_AUTH_MISSING and HTTP status 401."

        Claim: omitting X-User-Role yields ERR_AUTH_MISSING at HTTP 401.
        """
        resp = api._request("GET", "/departments", None,
                            {"X-User-ID": "anyone"})
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING)

    def test_missing_user_id_header_returns_err_auth_missing(self, api):
        """PRD §2.1: "Either header missing or empty is rejected with
        ERR_AUTH_MISSING and HTTP status 401."

        Claim: omitting X-User-ID yields ERR_AUTH_MISSING at HTTP 401.
        """
        resp = api._request("GET", "/departments", None,
                            {"X-User-Role": "PlatformAdmin"})
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING)

    def test_empty_role_header_returns_err_auth_missing(self, api):
        """PRD §2.1: "Either header missing or empty is rejected with
        ERR_AUTH_MISSING and HTTP status 401."

        Claim: empty X-User-Role yields ERR_AUTH_MISSING at HTTP 401.
        """
        resp = api._request("GET", "/departments", None,
                            {"X-User-ID": "anyone", "X-User-Role": ""})
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING)

    def test_role_not_authorized_returns_forbidden(self, api,
                                                   applicant_headers):
        """PRD §2.1: "A header pair that is well-formed but whose role
        lacks permission for the requested endpoint is rejected with
        ERR_FORBIDDEN and HTTP status 403."

        Claim: an Applicant cannot POST /departments (PlatformAdmin only).
        """
        resp = api.create_department(create_department_payload(),
                                     applicant_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ===========================================================================
# PRD §2.2 -- success and error envelopes
# ===========================================================================
class TestEnvelopeStructure:
    def test_success_envelope_has_meta_and_data(
        self, api, platform_admin_headers,
    ):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format" with a
        meta block carrying api_request_id and api_request_timestamp
        and a data payload.

        Claim: POST /departments returns an envelope with meta and data
        is the Department object.
        """
        resp = api.create_department(
            create_department_payload(), platform_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"])
        body = resp.json()
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id must start with req_"
        )
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: "The error_id is a unique, machine-readable string
        that identifies the specific error. The message provides a
        human-readable explanation of what went wrong."

        Claim: an error response body carries data.error_id and
        data.message.
        """
        resp = api._request("GET", "/departments", None, {})  # no headers
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_AUTH_MISSING"
        assert isinstance(body["data"].get("message"), str)


# ===========================================================================
# PRD §2.3 -- pagination
# ===========================================================================
class TestPagination:
    def test_list_returns_pagination_meta(
        self, api, platform_admin_headers,
    ):
        """PRD §2.3: "Every list response includes limit, offset,
        total_count, and has_more inside the meta object of the envelope."

        Claim: GET /departments returns a meta dict with these four keys.
        """
        resp = api.list_departments(platform_admin_headers)
        data, meta = validate_paginated(resp)
        for k in ("limit", "offset", "total_count", "has_more"):
            assert k in meta, f"meta missing {k}"
        assert isinstance(data, list)

    def test_list_default_limit_is_10(self, api, platform_admin_headers):
        """PRD §2.3: "The limit parameter sets the maximum number of items
        returned; it defaults to 10."

        Claim: omitting limit yields meta.limit == 10.
        """
        resp = api.list_departments(platform_admin_headers)
        _data, meta = validate_paginated(resp)
        assert meta["limit"] == 10


# ===========================================================================
# PRD §2.4 -- ID, timestamp, and version contract
# ===========================================================================
class TestResourceIdentity:
    def test_department_carries_common_fields(
        self, api, platform_admin_headers,
    ):
        """PRD §2.4: "Most top-level resources (Department, Matter,
        MatterVersion, MaterialTemplate, Application, ReviewTask,
        CertificateTemplate, Certificate) carry a uniform set of
        system-managed fields: id, created_at, updated_at, version."

        Claim: a freshly created Department exposes id/created_at/
        updated_at/version with version == 1.
        """
        resp = api.create_department(
            create_department_payload(), platform_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert isinstance(data["version"], int) and data["version"] == 1


# ===========================================================================
# PRD §2.6 -- left-to-right path-parameter validation
# ===========================================================================
class TestPathParameterValidationOrder:
    def test_missing_parent_yields_err_not_found(
        self, api, platform_admin_headers,
    ):
        """PRD §2.6: "Path parameters are validated strictly left-to-right:
        the parent Matter, Application, or Certificate is resolved first,
        and only if it exists does the server attempt to resolve the
        child. A missing parent yields ERR_NOT_FOUND for the parent
        identifier, never a child-level error."

        Claim: GET on /matters/{nonexistent}/versions/{nonexistent}
        yields ERR_NOT_FOUND.
        """
        resp = api.get_matter_version(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ===========================================================================
# Catalog manager ownership (PRD §2.1, entity_backed Department)
# ===========================================================================
class TestCatalogManagerOwnership:
    def test_catalog_manager_other_department_cannot_create_version(
        self, api, platform_admin_headers,
    ):
        """PRD §2.1: "When X-User-Role is CatalogManager, X-User-ID is the
        id of the acting Department; ownership checks (for example, may
        this manager edit this matter?) compare the matter's
        owning_department_id to X-User-ID."

        Claim: a CatalogManager whose department.id differs from the
        matter's owning_department_id is rejected with ERR_FORBIDDEN.
        """
        from test_helpers import (
            create_department,
            create_published_certificate_template,
            create_published_material_template,
            create_matter_payload,
            make_catalog_manager_headers,
            make_routing,
            create_matter_version_payload,
        )

        owner_dept = create_department()
        other_dept = create_department()
        owner_headers = make_catalog_manager_headers(owner_dept["id"])
        other_headers = make_catalog_manager_headers(other_dept["id"])
        primary = create_published_material_template(
            catalog_manager_headers=owner_headers,
        )
        cert = create_published_certificate_template()
        # Owner department creates the matter.
        matter_resp = api.create_matter(
            create_matter_payload(owning_department_id=owner_dept["id"]),
            owner_headers,
        )
        matter = validate_success(matter_resp, expected_status=201)
        # OTHER department attempts to create a version under it.
        routing = make_routing(
            mode="SERIAL",
            lead_department_id=owner_dept["id"],
            stages=[{"department_id": owner_dept["id"], "sla_days": 5}],
            aggregation_rule=None,
        )
        version_payload = create_matter_version_payload(
            required_material_template_ids=[primary["id"]],
            certificate_template_id=cert["id"],
            review_routing=routing,
        )
        resp = api.create_matter_version(
            matter["id"], version_payload, other_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
