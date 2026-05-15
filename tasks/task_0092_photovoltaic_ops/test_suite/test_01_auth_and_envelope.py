"""Auth, role, envelope, and pagination tests (PRD §2.1, §2.2, §2.3)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    create_station_payload,
    create_supplier_payload,
    create_supplier,
    create_station,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthHeaders:
    """PRD §2.1: every request MUST carry X-User-ID and X-User-Role."""

    def test_missing_user_id_returns_auth_required(self, api):
        """PRD §2.1: "If either header is missing, malformed, or
        carries a role string outside the catalogue, the request is
        rejected with ERR_AUTH_REQUIRED (HTTP 401)."

        Claim: omitting X-User-ID rejects with ERR_AUTH_REQUIRED 401.
        """
        headers = {"X-User-Role": "PlatformAdmin"}
        resp = api.create_station(create_station_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_role_returns_auth_required(self, api):
        """PRD §2.1: "If either header is missing, malformed, or
        carries a role string outside the catalogue, the request is
        rejected with ERR_AUTH_REQUIRED (HTTP 401)."

        Claim: omitting X-User-Role rejects with ERR_AUTH_REQUIRED.
        """
        headers = {"X-User-ID": "test-user"}
        resp = api.create_station(create_station_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_unknown_role_returns_auth_required(self, api):
        """PRD §2.1: "If either header is missing, malformed, or
        carries a role string outside the catalogue, the request is
        rejected with ERR_AUTH_REQUIRED (HTTP 401)."

        Claim: a role string outside the catalogue rejects with
        ERR_AUTH_REQUIRED.
        """
        headers = build_user_headers("test-user", "Janitor")
        resp = api.create_station(create_station_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)


class TestRBAC:
    """PRD §2.1 + §4: role-gated operations reject the wrong role."""

    def test_field_operator_cannot_create_station(self, api, field_headers):
        """PRD §2.1: "If both headers are well-formed but the role is
        not entitled to perform the requested operation per the role
        catalogue, the request is rejected with ERR_FORBIDDEN (HTTP
        403)." PRD §4 names PlatformAdmin as the only role authorized
        for POST /pv-ops/stations.

        Claim: FieldOperator creating a station → ERR_FORBIDDEN.
        """
        resp = api.create_station(create_station_payload(), field_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_finance_officer_cannot_register_supplier(
        self, api, finance_headers,
    ):
        """PRD §4: POST /pv-ops/suppliers is PlatformAdmin-only.
        PRD §2.1: an unentitled role yields ERR_FORBIDDEN.

        Claim: FinanceOfficer creating a supplier → ERR_FORBIDDEN.
        """
        resp = api.create_supplier(create_supplier_payload(), finance_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_om_engineer_cannot_create_settlement_period(
        self, api, om_headers,
    ):
        """PRD §4: POST /pv-ops/stations/{station_id}/settlement-periods
        is FinanceOfficer-only.

        Claim: O&MEngineer creating a settlement period → ERR_FORBIDDEN.
        """
        station = create_station()
        resp = api.create_settlement_period(
            station["id"],
            {"period_start": "2026-02-01T00:00:00.000Z",
             "period_end": "2026-03-01T00:00:00.000Z"},
            om_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestNotFoundResolution:
    """PRD §2.6: path identifiers are validated strictly left-to-right."""

    def test_get_station_unknown_id_returns_not_found(self, api, admin_headers):
        """PRD §2.6: "The first unresolved id in the chain yields
        ERR_NOT_FOUND (HTTP 404), and no later validation runs."

        Claim: GET /pv-ops/stations/{unknown_id} → ERR_NOT_FOUND.
        """
        from test_helpers import NON_EXISTENT_UUID
        resp = api.get_station(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestPagination:
    """PRD §2.3: limit/offset, total_count, has_more in meta."""

    def test_list_stations_returns_paginated_envelope(
        self, api, admin_headers,
    ):
        """PRD §2.3: "The meta block for any list response carries
        four pagination fields: limit, offset, total_count (the
        number of rows that match the filters before pagination), and
        has_more (true when more rows are available beyond the current
        page)."

        Claim: GET /pv-ops/stations returns meta with limit, offset,
        total_count, has_more.
        """
        create_station()
        create_station()
        resp = api.list_stations(admin_headers)
        data, meta = validate_paginated(resp)
        assert "limit" in meta and "offset" in meta
        assert "total_count" in meta and "has_more" in meta
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)


class TestSuccessEnvelope:
    """PRD §2.2: success responses follow the standard envelope."""

    def test_create_station_returns_201_with_object_envelope(
        self, api, admin_headers,
    ):
        """PRD §2.2: "The `response_type` is either "object" for a
        single resource or "array" for a list of resources."
        PRD §2.2: "The `data` field contains the resource object or
        an array of resource objects."

        Claim: POST /pv-ops/stations returns response_type=object and
        data carries the created Station.
        """
        resp = api.create_station(
            create_station_payload(name=None), admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert "id" in data
        assert "name" in data
        body = resp.json()
        assert body["response_type"] == "object"
