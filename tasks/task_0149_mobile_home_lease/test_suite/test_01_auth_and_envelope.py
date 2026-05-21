"""Authentication, authorization, response-envelope, and 404 probes.

Each test cites the PRD sentence that pins the rule under assertion.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_park_payload,
    create_resident_payload,
    create_park,
    make_park_manager_headers,
    validate_error,
    validate_success,
)


# ===========================================================================
# Auth required — PRD §2.1, §2.10 step 1
# ===========================================================================
class TestAuthRequired:
    """PRD §2.1: 'Every request to the API must carry two HTTP headers:
    X-User-ID, which identifies the acting principal, and X-User-Role,
    which declares the role under which the request is made. Both
    headers must be present and non-empty; a request that violates this
    rule is rejected with ERR_AUTH_REQUIRED.'"""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: 'Both headers must be present and non-empty;
        a request that violates this rule is rejected with
        ERR_AUTH_REQUIRED.'

        Claim: empty headers dict → ERR_AUTH_REQUIRED (HTTP 401).
        """
        resp = api.create_park(create_park_payload(), headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_id_rejected(self, api):
        """PRD §2.1: 'Both headers must be present and non-empty;
        a request that violates this rule is rejected with
        ERR_AUTH_REQUIRED.'

        Claim: only X-User-Role present → ERR_AUTH_REQUIRED.
        """
        resp = api.create_park(
            create_park_payload(),
            headers={"X-User-Role": "ParkManager"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_role_rejected(self, api):
        """PRD §2.1: 'Both headers must be present and non-empty;
        a request that violates this rule is rejected with
        ERR_AUTH_REQUIRED.'

        Claim: only X-User-ID present → ERR_AUTH_REQUIRED.
        """
        resp = api.create_park(
            create_park_payload(),
            headers={"X-User-ID": "someone"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_user_id_rejected(self, api):
        """PRD §2.1: 'Both headers must be present and non-empty;
        a request that violates this rule is rejected with
        ERR_AUTH_REQUIRED.'

        Claim: empty X-User-ID string → ERR_AUTH_REQUIRED.
        """
        resp = api.create_park(
            create_park_payload(),
            headers={"X-User-ID": "", "X-User-Role": "ParkManager"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)


# ===========================================================================
# Forbidden — PRD §2.1, §2.10 step 2
# ===========================================================================
class TestForbidden:
    """PRD §2.1: 'A request whose role is not authorized for the
    targeted endpoint per the §4 endpoint table is rejected with
    ERR_FORBIDDEN.'"""

    def test_resident_cannot_create_lot(self, api):
        """PRD §4: 'POST /parks/{park_id}/lots ... Authorized Role(s):
        ParkManager.'

        Claim: a Resident calling POST /parks/{park_id}/lots →
        ERR_FORBIDDEN.
        """
        park = create_park()
        resp = api.create_lot(
            park["id"],
            {"lot_number": "Z1", "base_rent_cents": 100_000},
            TEST_USERS["resident_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_resident_cannot_advance_clock(self, api):
        """PRD §4: 'POST /_clock/advance ... Authorized Role(s):
        PlatformAdmin.'

        Claim: a Resident calling POST /_clock/advance → ERR_FORBIDDEN.
        """
        resp = api.advance_clock(
            {"seconds": 60}, TEST_USERS["resident_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_park_manager_cannot_run_billing_sweep(self, api):
        """PRD §4: 'POST /_sweep/billing ... Authorized Role(s):
        PlatformAdmin.'

        Claim: a ParkManager calling POST /_sweep/billing → ERR_FORBIDDEN.
        """
        park = create_park()
        resp = api.sweep_billing(
            {
                "park_id": park["id"],
                "billing_period_start": "2025-01-01T00:00:00.000Z",
                "billing_period_end": "2025-02-01T00:00:00.000Z",
                "master_total_cents": 1000,
            },
            make_park_manager_headers(park["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Path-resource existence — PRD §2.5
# ===========================================================================
class TestPathResourceNotFound:
    """PRD §2.5: 'The first path identifier that does not correspond
    to an existing resource yields an immediate ERR_RESOURCE_NOT_FOUND
    response, before any subsequent identifier or any body-level
    reference is consulted.'"""

    def test_get_unknown_park_returns_resource_not_found(self, api):
        """PRD §2.5: 'The first path identifier that does not
        correspond to an existing resource yields an immediate
        ERR_RESOURCE_NOT_FOUND response.'

        Claim: GET /parks/{nonexistent} → ERR_RESOURCE_NOT_FOUND.
        """
        resp = api.get_park(
            NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    def test_get_unknown_lease_returns_resource_not_found(self, api):
        """PRD §2.5: 'The first path identifier that does not
        correspond to an existing resource yields an immediate
        ERR_RESOURCE_NOT_FOUND response.'

        Claim: GET /leases/{nonexistent} → ERR_RESOURCE_NOT_FOUND.
        """
        resp = api.get_lease(
            NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


# ===========================================================================
# Body-resource existence — PRD §2.5
# ===========================================================================
class TestBodyResourceNotFound:
    """PRD §2.5: 'Body-level references — a lease_id, home_id,
    resident_id, or any other identifier embedded in the request
    payload — are checked only after every path identifier has
    resolved, and a missing body-level resource yields
    ERR_REFERENCED_RESOURCE_NOT_FOUND.'"""

    def test_create_lease_with_unknown_resident(self, api):
        """PRD §2.5: 'a missing body-level resource yields
        ERR_REFERENCED_RESOURCE_NOT_FOUND.'

        Claim: POST /lots/{lot_id}/leases with unknown resident_id
        → ERR_REFERENCED_RESOURCE_NOT_FOUND (path lot_id resolves first).
        """
        from test_helpers import create_lot
        park = create_park()
        lot = create_lot(park["id"])
        resp = api.create_lease(
            lot["id"],
            {"resident_id": NON_EXISTENT_UUID,
             "start_date": "2025-01-01T00:00:00.000Z"},
            make_park_manager_headers(park["id"]),
        )
        validate_error(
            resp,
            ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value,
        )


# ===========================================================================
# Success envelope — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2: response envelope shape."""

    def test_success_envelope_carries_meta_and_data(self, api):
        """PRD §2.2: 'All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body: { "meta": { "api_request_id": ...,
        "api_request_timestamp": ... }, "response_type": "object" |
        "array", "data": { } }.'

        Claim: a successful POST /parks returns the standard
        envelope with meta + response_type + data.
        """
        resp = api.create_park(
            create_park_payload(),
            TEST_USERS["park_manager_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert "id" in data, "data must contain the created resource"

    def test_create_park_returns_201(self, api):
        """PRD §4: 'Endpoints that create a fresh resource ... return
        201 Created.'

        Claim: POST /parks returns HTTP 201.
        """
        resp = api.create_park(
            create_park_payload(),
            TEST_USERS["park_manager_headers"],
        )
        assert resp.status_code == 201, (
            f"POST /parks must return 201 per PRD §4, "
            f"got {resp.status_code}"
        )

    def test_create_resident_returns_201(self, api):
        """PRD §4: 'Endpoints that create a fresh resource ... return
        201 Created.'

        Claim: POST /residents returns HTTP 201.
        """
        resp = api.create_resident(
            create_resident_payload(),
            TEST_USERS["park_manager_headers"],
        )
        assert resp.status_code == 201
