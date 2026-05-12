"""Auth, RBAC, envelope, pagination, and path-existence checks.

PRD references:
  - §2.1 User and Role-Based Access Control
  - §2.2 API Response Structure
  - §2.3 Pagination
  - §2.5 Nested Resource Resolution
  - §2.8 Validation Priority Order
  - §4 Endpoint Definitions (RBAC matrix)
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    build_user_headers,
    create_enterprise_payload,
    create_allocation_cycle_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 — Auth header presence
# ===========================================================================
class TestAuthHeaders:
    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'A request missing either header, or with either header
        empty, is rejected with ERR_AUTH_REQUIRED (HTTP 401).'

        Claim: missing X-User-ID -> ERR_AUTH_REQUIRED.
        """
        bad = {"X-User-Role": "Regulator"}
        res = api.create_enterprise(create_enterprise_payload(), bad)
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: 'A request missing either header, or with either header
        empty, is rejected with ERR_AUTH_REQUIRED (HTTP 401).'

        Claim: missing X-User-Role -> ERR_AUTH_REQUIRED.
        """
        bad = {"X-User-ID": "regulator-001"}
        res = api.create_enterprise(create_enterprise_payload(), bad)
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_empty_user_id_header_rejected(self, api):
        """PRD §2.1: 'A request missing either header, or with either header
        empty, is rejected with ERR_AUTH_REQUIRED (HTTP 401).'

        Claim: empty X-User-ID -> ERR_AUTH_REQUIRED.
        """
        bad = {"X-User-ID": "", "X-User-Role": "Regulator"}
        res = api.create_enterprise(create_enterprise_payload(), bad)
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_empty_user_role_header_rejected(self, api):
        """PRD §2.1: 'A request missing either header, or with either header
        empty, is rejected with ERR_AUTH_REQUIRED (HTTP 401).'

        Claim: empty X-User-Role -> ERR_AUTH_REQUIRED.
        """
        bad = {"X-User-ID": "regulator-001", "X-User-Role": ""}
        res = api.create_enterprise(create_enterprise_payload(), bad)
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_both_headers_missing_rejected(self, api):
        """PRD §2.1: 'A request missing either header, or with either header
        empty, is rejected with ERR_AUTH_REQUIRED (HTTP 401).'

        Claim: no auth headers at all -> ERR_AUTH_REQUIRED.
        """
        res = api.create_enterprise(create_enterprise_payload(), {})
        validate_error(res, "ERR_AUTH_REQUIRED")


# ===========================================================================
# §2.1 — RBAC: ERR_FORBIDDEN for unauthorized roles
# ===========================================================================
class TestRBAC:
    @pytest.mark.parametrize("role", ["Enterprise", "VerifierAgency"])
    def test_create_enterprise_requires_regulator(self, api, role):
        """PRD §2.1: 'A request whose role is not authorized for the
        requested endpoint per the RBAC matrix in §4 is rejected with
        ERR_FORBIDDEN (HTTP 403).'
        PRD §4: 'POST | /enterprises | Register a new enterprise | Regulator'.

        Claim: a non-Regulator role hitting POST /enterprises -> ERR_FORBIDDEN.
        """
        headers = build_user_headers(f"id-{role}", role)
        res = api.create_enterprise(create_enterprise_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN")

    @pytest.mark.parametrize("role", ["Enterprise", "VerifierAgency"])
    def test_create_allocation_cycle_requires_regulator(self, api, role):
        """PRD §4: 'POST | /allocation-cycles | Create a draft allocation
        cycle | Regulator'.
        PRD §2.1: 'A request whose role is not authorized for the requested
        endpoint per the RBAC matrix in §4 is rejected with ERR_FORBIDDEN
        (HTTP 403).'

        Claim: non-Regulator role hitting POST /allocation-cycles
        -> ERR_FORBIDDEN.
        """
        headers = build_user_headers(f"id-{role}", role)
        res = api.create_allocation_cycle(
            create_allocation_cycle_payload(), headers
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_audit_logs_requires_regulator(self, api):
        """PRD §4: 'GET | /audit-logs | List audit log entries ... | Regulator'.

        Claim: an Enterprise reading /audit-logs -> ERR_FORBIDDEN.
        """
        headers = build_user_headers("ent-1", "Enterprise")
        res = api.list_audit_logs(headers)
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.5 — Nested Resource Resolution (path 404)
# ===========================================================================
class TestPathExistence:
    def test_get_unknown_enterprise_returns_not_found(
        self, api, regulator_headers
    ):
        """PRD §2.5: 'If any segment fails to resolve to an existing entity,
        the request is rejected with ERR_NOT_FOUND (HTTP 404), and the
        message identifies the first segment that failed.'

        Claim: GET /enterprises/{unknown-uuid} -> ERR_NOT_FOUND.
        """
        res = api.get_enterprise(NON_EXISTENT_UUID, regulator_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_unknown_allocation_cycle_returns_not_found(
        self, api, regulator_headers
    ):
        """PRD §2.5: 'If any segment fails to resolve to an existing entity,
        the request is rejected with ERR_NOT_FOUND (HTTP 404)'.

        Claim: GET /allocation-cycles/{unknown-uuid} -> ERR_NOT_FOUND.
        """
        res = api.get_allocation_cycle(NON_EXISTENT_UUID, regulator_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_publish_unknown_cycle_returns_not_found(
        self, api, regulator_headers
    ):
        """PRD §2.5: 'If any segment fails to resolve to an existing entity,
        the request is rejected with ERR_NOT_FOUND'.

        Claim: POST /allocation-cycles/{unknown}/publish -> ERR_NOT_FOUND.
        """
        res = api.publish_allocation_cycle(
            NON_EXISTENT_UUID, regulator_headers
        )
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# §2.2 — Success envelope shape
# ===========================================================================
class TestSuccessEnvelope:
    def test_create_enterprise_returns_envelope_and_201(
        self, api, regulator_headers
    ):
        """PRD §2.2: 'All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body'
        with response_type 'object' and a data resource field.
        PRD §4: 'POST | /enterprises ... | Regulator' returning 201 (PRD §4:
        'Successful creation of a new resource returns HTTP 201').

        Claim: POST /enterprises returns 201 + standard envelope with
        response_type=object and a data dict containing id.
        """
        res = api.create_enterprise(
            create_enterprise_payload(), regulator_headers
        )
        data = validate_success(res, expected_status=201)
        assert isinstance(data, dict), (
            "Success envelope's data should be the resource object"
        )
        assert "id" in data, "Created enterprise must surface its id"

    def test_envelope_includes_meta_request_id_and_timestamp(
        self, api, regulator_headers
    ):
        """PRD §2.2: 'The api_request_id is a server-generated unique
        identifier for the request that starts with req_.' Also: 'The
        api_request_timestamp is a server-generated ISO 8601 UTC timestamp
        with three fractional digits.'

        Claim: success responses carry meta.api_request_id (req_-prefixed)
        and meta.api_request_timestamp.
        """
        res = api.create_enterprise(
            create_enterprise_payload(), regulator_headers
        )
        body = res.json()
        meta = body.get("meta", {})
        rid = meta.get("api_request_id", "")
        assert isinstance(rid, str) and rid.startswith("req_"), (
            f"api_request_id must start with req_, got {rid!r}"
        )
        ts = meta.get("api_request_timestamp", "")
        # PRD §2.2 example uses three fractional digits ending Z.
        assert isinstance(ts, str) and len(ts) > 0, (
            "api_request_timestamp must be present"
        )


# ===========================================================================
# §2.2 — Error envelope shape
# ===========================================================================
class TestErrorEnvelope:
    def test_error_envelope_has_error_id_and_message(self, api):
        """PRD §2.2: 'The error_id is a unique, machine-readable string ...
        The message provides a human-readable explanation of what went wrong.'

        Claim: 4xx responses surface response_type=error plus
        data.error_id (string) and data.message (string).
        """
        res = api.create_enterprise(create_enterprise_payload(), {})
        body = res.json()
        assert body.get("response_type") == "error"
        d = body.get("data", {})
        assert isinstance(d.get("error_id"), str)
        assert isinstance(d.get("message"), str)


# ===========================================================================
# §2.3 — Pagination
# ===========================================================================
class TestPagination:
    def test_list_audit_logs_returns_paginated_envelope(
        self, api, regulator_headers
    ):
        """PRD §2.3: 'The pagination block in meta exposes the four fields
        limit, offset, total_count, and has_more; the has_more flag is true
        exactly when offset + limit < total_count.'

        Claim: GET /audit-logs returns a paginated envelope whose meta has
        the four pagination fields and has_more is consistent with the
        formula.
        """
        res = api.list_audit_logs(regulator_headers, params={"limit": 10})
        data, meta = validate_paginated(res)
        assert isinstance(data, list)
        for f in ("limit", "offset", "total_count", "has_more"):
            assert f in meta, f"meta must include {f}"
        assert (
            meta["has_more"]
            is (meta["offset"] + meta["limit"] < meta["total_count"])
        ), (
            "has_more must equal (offset + limit < total_count) per PRD §2.3"
        )

    def test_list_enterprises_default_limit_is_ten(
        self, api, regulator_headers
    ):
        """PRD §2.3: 'List endpoints support two query-string parameters:
        limit (default 10, minimum 1, maximum 100) and offset (default 0).'

        Claim: GET /enterprises with no `limit` returns meta.limit == 10.
        """
        res = api.list_enterprises(regulator_headers)
        _data, meta = validate_paginated(res)
        assert meta["limit"] == 10, (
            f"PRD §2.3 default limit is 10; got {meta['limit']}"
        )
