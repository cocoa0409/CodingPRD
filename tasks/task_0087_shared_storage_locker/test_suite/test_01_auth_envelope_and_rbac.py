"""Auth, response envelope, and RBAC tests (PRD §2.1, §2.2, §2.9)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_cabinet_payload,
    create_pricing_profile_payload,
    make_renter_headers,
    setup_basic_rental,
    setup_cabinet_with_compartment,
    validate_error,
    validate_success,
)


# ===========================================================================
# Auth: missing/malformed headers (PRD §2.1)
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_header_returns_unauthorized(self, api):
        """PRD §2.1: "Every request to the API MUST carry two headers:
        X-User-ID (the caller's identity) and X-User-Role (the caller's
        role). A request that omits either header, or supplies a
        malformed value, is rejected with ERR_UNAUTHORIZED."

        Claim: omitting X-User-ID → ERR_UNAUTHORIZED.
        """
        resp = api._request(
            "GET", "/cabinets", headers={"X-User-Role": "Operator"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_missing_user_role_header_returns_unauthorized(self, api):
        """PRD §2.1: "A request that omits either header, or supplies a
        malformed value, is rejected with ERR_UNAUTHORIZED."

        Claim: omitting X-User-Role → ERR_UNAUTHORIZED.
        """
        resp = api._request(
            "GET", "/cabinets", headers={"X-User-ID": "op-1"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_empty_user_id_header_returns_unauthorized(self, api):
        """PRD §2.1: "A request that omits either header, or supplies a
        malformed value, is rejected with ERR_UNAUTHORIZED."

        Claim: empty string X-User-ID is malformed → ERR_UNAUTHORIZED.
        """
        resp = api._request(
            "GET", "/cabinets",
            headers={"X-User-ID": "", "X-User-Role": "Operator"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ===========================================================================
# Auth: ordering — unauthorized fires before forbidden (PRD §2.9)
# ===========================================================================
class TestValidationOrdering:

    def test_missing_role_returns_unauthorized_not_forbidden(self, api):
        """PRD §2.9: "a Renter who is missing the role header receives
        ERR_UNAUTHORIZED rather than ERR_FORBIDDEN."

        Claim: header presence is evaluated before role permission.
        """
        resp = api._request(
            "POST", "/cabinets",
            payload=create_cabinet_payload(),
            headers={"X-User-ID": "renter-1"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ===========================================================================
# RBAC: role-not-permitted (PRD §2.1, §4)
# ===========================================================================
class TestRoleForbidden:

    def test_renter_cannot_create_cabinet(self, api, renter_fallback_headers):
        """PRD §2.1: "A request whose X-User-Role is not permitted for the
        target endpoint is rejected with ERR_FORBIDDEN."
        PRD §4: POST /cabinets is restricted to Operator.

        Claim: Renter creating a cabinet → ERR_FORBIDDEN.
        """
        resp = api.create_cabinet(create_cabinet_payload(),
                                  renter_fallback_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_renter_cannot_create_pricing_profile(self, api,
                                                  renter_fallback_headers):
        """PRD §2.1: "A request whose X-User-Role is not permitted for the
        target endpoint is rejected with ERR_FORBIDDEN."
        PRD §4: POST /pricing-profiles is restricted to Operator.

        Claim: Renter creating a pricing profile → ERR_FORBIDDEN.
        """
        resp = api.create_pricing_profile(create_pricing_profile_payload(),
                                          renter_fallback_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_renter_cannot_run_sweep(self, api, renter_fallback_headers):
        """PRD §4: POST /_sweep/run is restricted to Operator.

        Claim: Renter calling sweep → ERR_FORBIDDEN.
        """
        resp = api.sweep_run(renter_fallback_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_operator_cannot_renew_rental(self, api, operator_headers):
        """PRD §4: POST /rentals/{rental_id}/renew is restricted to Renter.

        Claim: Operator renewing a rental → ERR_FORBIDDEN.
        """
        ctx = setup_basic_rental()
        resp = api.renew_rental(
            ctx["rental"]["id"], {"renewal_billing_units": 1},
            operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Renter ownership check (PRD §2.1, §3.3)
# ===========================================================================
class TestRenterOwnership:

    def test_non_owner_renter_cannot_renew(self, api):
        """PRD §2.1: "A Renter whose X-User-ID does not match the
        resource's owning renter on an ownership-checked endpoint is
        rejected with ERR_FORBIDDEN."
        PRD §3.3: "the renter's X-User-ID must equal the rental's
        renter_id."

        Claim: a different Renter renewing someone else's rental →
        ERR_FORBIDDEN.
        """
        ctx = setup_basic_rental(renter_id="renter-owner")
        other_headers = make_renter_headers("renter-impostor")
        resp = api.renew_rental(
            ctx["rental"]["id"], {"renewal_billing_units": 1}, other_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_non_owner_renter_cannot_return(self, api):
        """PRD §3.6: "The owning renter check applies."
        PRD §2.1: "A Renter whose X-User-ID does not match the
        resource's owning renter on an ownership-checked endpoint is
        rejected with ERR_FORBIDDEN."

        Claim: a different Renter returning someone else's rental →
        ERR_FORBIDDEN.
        """
        ctx = setup_basic_rental(renter_id="renter-owner-2")
        other_headers = make_renter_headers("renter-impostor-2")
        resp = api.return_rental(
            ctx["rental"]["id"], {"unlock_channel": "QR"}, other_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Response envelope (PRD §2.2)
# ===========================================================================
class TestSuccessEnvelope:

    def test_success_envelope_shape_on_cabinet_creation(self, api,
                                                        operator_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format ... The
        api_request_id is a server-generated unique identifier for
        the request that starts with req_."

        Claim: success response carries meta with api_request_id
        starting with 'req_' and response_type ∈ {object, array}.
        """
        resp = api.create_cabinet(create_cabinet_payload(), operator_headers)
        assert resp.status_code == 201, (
            f"Expected 201 Created (PRD §4), got {resp.status_code}"
        )
        body = resp.json()
        assert body["response_type"] in ("object", "array")
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"meta.api_request_id must start with 'req_', got "
            f"{body['meta']['api_request_id']!r}"
        )

    def test_paginated_envelope_on_cabinet_list(self, api, operator_headers):
        """PRD §2.3: "The meta block of every list response includes
        limit, offset, total_count, and has_more."

        Claim: GET /cabinets carries the four pagination fields.
        """
        resp = api.list_cabinets(operator_headers)
        body = resp.json()
        for f in ("limit", "offset", "total_count", "has_more"):
            assert f in body["meta"], f"meta.{f} missing on list response"


class TestErrorEnvelope:

    def test_error_envelope_shape_on_not_found(self, api, operator_headers):
        """PRD §2.2: error responses carry meta with api_request_id and
        api_request_timestamp, response_type='error', and data with
        error_id and message.

        Claim: a 404 on a missing cabinet carries that exact shape.
        """
        resp = api.get_cabinet("00000000-0000-0000-0000-000000000000",
                               operator_headers)
        body = resp.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]
        assert len(body["data"]["message"].strip()) > 0


# ===========================================================================
# Common-fields shape (PRD §2.4)
# ===========================================================================
class TestCommonFields:

    def test_cabinet_carries_id_created_updated_version(self, api,
                                                       operator_headers):
        """PRD §2.4: "Cabinet, Compartment, Rental, InsuranceClaim, and
        RepairTicket resources additionally carry created_at (set on
        creation), updated_at (refreshed on every mutation), and
        version (a non-negative integer that starts at zero on
        creation and increments by one on every mutation)."

        Claim: a freshly created Cabinet exposes id/created_at/
        updated_at/version, and version starts at zero.
        """
        resp = api.create_cabinet(create_cabinet_payload(), operator_headers)
        data = validate_success(resp, expected_status=201)
        for f in ("id", "created_at", "updated_at", "version"):
            assert f in data, f"Cabinet missing {f}"
        assert data["version"] == 0, (
            f"Cabinet.version must start at 0, got {data['version']}"
        )

    def test_pricing_profile_has_no_version_or_updated_at(self, api,
                                                         operator_headers):
        """PRD §2.4: "PricingProfile, RevenueRecord, and AuditEvent are
        immutable once written and carry only id and created_at; they
        have no updated_at and no version field."

        Claim: PricingProfile must not expose updated_at or version.
        """
        resp = api.create_pricing_profile(
            create_pricing_profile_payload(), operator_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data.get("updated_at") in (None,) or "updated_at" not in data, (
            "PricingProfile must not carry updated_at (PRD §2.4)"
        )
        assert data.get("version") in (None,) or "version" not in data, (
            "PricingProfile must not carry version (PRD §2.4)"
        )
