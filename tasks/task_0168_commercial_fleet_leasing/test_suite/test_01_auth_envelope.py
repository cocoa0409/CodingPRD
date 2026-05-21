"""Authentication, role recognition, role permission, response envelope,
and ownership — PRD §2.1, §2.2, §2.5, §2.11.

These tests exercise the universal cross-cutting rules that apply to
every endpoint: missing headers, invalid role values, role-permission
mismatches, and the ownership check on Lessee-acting endpoints.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_clock_to_iso,
    api_client,
    create_lessee,
    create_lessee_payload,
    create_vehicle,
    finalize_settlement,
    is_iso8601_timestamp,
    make_lessee_headers,
    post_telematics_event,
    setup_active_lease,
    setup_active_lease_with_card,
    validate_error,
    validate_success,
)


# ===========================================================================
# Auth / role-recognition / role-permission probes — PRD §2.1
# ===========================================================================
class TestAuthHeaders:

    def test_missing_both_headers_returns_err_auth_required(self, api):
        """PRD §2.1: "Every request to the API must carry two custom
        HTTP headers identifying the caller: `X-User-ID` and
        `X-User-Role`. Both must be present and non-empty; a request
        that omits or empties either header is rejected with
        `ERR_AUTH_REQUIRED` and HTTP 401."

        Claim: a request with neither header is rejected with
        ERR_AUTH_REQUIRED / 401.
        """
        resp = api._request(
            "GET", f"/lessees/{NON_EXISTENT_UUID}", headers={},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_id_returns_err_auth_required(self, api):
        """PRD §2.1: "a request that omits or empties either header is
        rejected with `ERR_AUTH_REQUIRED` and HTTP 401."

        Claim: omitting X-User-ID alone returns ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", f"/lessees/{NON_EXISTENT_UUID}",
            headers={"X-User-Role": "FleetManager"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_role_returns_err_auth_required(self, api):
        """PRD §2.1: "a request that omits or empties either header is
        rejected with `ERR_AUTH_REQUIRED` and HTTP 401."

        Claim: omitting X-User-Role alone returns ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", f"/lessees/{NON_EXISTENT_UUID}",
            headers={"X-User-ID": "any-id"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_user_id_returns_err_auth_required(self, api):
        """PRD §2.1: "Both must be present and non-empty ... a request
        that omits or empties either header is rejected with
        `ERR_AUTH_REQUIRED` and HTTP 401."

        Claim: empty X-User-ID is rejected.
        """
        resp = api._request(
            "GET", f"/lessees/{NON_EXISTENT_UUID}",
            headers={"X-User-ID": "", "X-User-Role": "FleetManager"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_unknown_role_returns_err_auth_required(self, api):
        """PRD §2.1: "The `X-User-Role` value is then compared against
        the system's role registry, and any value that does not
        exactly match one of the declared role names is also rejected
        with `ERR_AUTH_REQUIRED`."

        Claim: an unrecognised role name returns ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", f"/lessees/{NON_EXISTENT_UUID}",
            headers={"X-User-ID": "x", "X-User-Role": "SuperAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)


class TestRolePermission:

    def test_tax_admin_cannot_create_lessee(self, api,
                                            tax_admin_headers):
        """PRD §2.1 + PRD §4: "POST /lessees | Register a new lessee. |
        FleetManager"

        PRD §2.1: "a recognised role attempting an operation it is not
        permitted to invoke is rejected with `ERR_FORBIDDEN` and HTTP
        403."

        Claim: TaxAdmin attempting POST /lessees returns ERR_FORBIDDEN
        (lessee registration is FleetManager-exclusive).
        """
        payload = create_lessee_payload()
        resp = api.create_lessee(payload, tax_admin_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_claim_adjuster_cannot_create_vehicle(
        self, api, claim_adjuster_headers,
    ):
        """PRD §4: "POST /vehicles | Add a vehicle to the fleet. |
        FleetManager"
        PRD §2.1: "a recognised role attempting an operation it is not
        permitted to invoke is rejected with `ERR_FORBIDDEN` and HTTP
        403."

        Claim: ClaimAdjuster attempting POST /vehicles returns
        ERR_FORBIDDEN.
        """
        from test_helpers import create_vehicle_payload
        resp = api.create_vehicle(
            create_vehicle_payload(), claim_adjuster_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_vendor_ops_cannot_activate_lease(
        self, api, vendor_ops_headers,
    ):
        """PRD §4: "POST /lease-agreements/{id}/activate | Allocate
        the lease's vehicle and move lease to active. | FleetManager"

        Claim: VendorOps attempting POST .../activate returns
        ERR_FORBIDDEN.
        """
        # Build a draft lease so the 403 fires on role, not on 404.
        from test_helpers import create_lease_agreement
        lessee = create_lessee()
        vehicle = create_vehicle()
        lease = create_lease_agreement(
            lessee_id=lessee["id"], vehicle_id=vehicle["id"],
        )
        resp = api.activate_lease(lease["id"], vendor_ops_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_fleet_manager_cannot_start_review_claim(
        self, api, fleet_manager_headers,
    ):
        """PRD §4: "POST /collision-claims/{id}/start-review | Begin
        adjudication of a filed claim. | ClaimAdjuster"

        Claim: FleetManager (not ClaimAdjuster) attempting
        start-review returns ERR_FORBIDDEN.
        """
        # Need a real claim id so the role check fires before 404.
        from test_helpers import api_client as _api
        from test_helpers import create_collision_claim_payload
        from test_helpers import TEST_USERS
        lessee, vehicle, lease = setup_active_lease()
        claim_resp = _api.create_collision_claim(
            lease["id"],
            create_collision_claim_payload(
                incident_ts="2026-03-15T12:00:00.000Z",
                estimate_cents=10_000,
            ),
            TEST_USERS["fleet_manager_headers"],
        )
        claim = claim_resp.json()["data"]
        resp = api.start_review_collision_claim(
            claim["id"], fleet_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Lessee ownership — PRD §2.1 ("X-User-ID must match lessee_id")
# ===========================================================================
class TestLesseeOwnership:

    def test_dispute_by_non_owning_lessee_forbidden(self, api):
        """PRD §2.1: "a `Lessee` caller invoking the dispute operation
        on an `OverageSettlement` must have an `X-User-ID` that
        matches the `lessee_id` of the parent `LeaseAgreement`;
        mismatch yields `ERR_FORBIDDEN`."

        Claim: a Lessee header whose X-User-ID is a different
        lessee's id is rejected with ERR_FORBIDDEN on dispute.
        """
        # Two lessees A and B; settlement on A's lease; B attempts to
        # dispute it.
        advance_clock_to_iso("2026-03-15T00:00:00.000Z")
        lessee_a, vehicle_a, lease_a = setup_active_lease()
        lessee_b = create_lessee()
        # Build a FINAL settlement owned by lessee_a.
        from test_helpers import create_draft_settlement
        settle = create_draft_settlement(
            lease_id=lease_a["id"],
            period_year=2026, period_month=2,
        )
        settle = finalize_settlement(settle["id"])
        # Lessee B attempts to dispute -- mismatched X-User-ID.
        resp = api.dispute_overage_settlement(
            settle["id"], make_lessee_headers(lessee_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_dispute_by_owning_lessee_inside_window_succeeds(self, api):
        """PRD §2.1: "ownership checks on any resource that ultimately
        references a `Lessee` ... compare the resource's foreign-key
        chain back to `X-User-ID`."
        PRD §3.6: "the lessee themselves may dispute a finalised
        settlement, advancing it from `FINAL` to `DISPUTED`."

        Claim: when X-User-ID matches the parent lease's lessee_id
        AND the dispute window is open, the dispute succeeds and the
        settlement moves to DISPUTED.
        """
        advance_clock_to_iso("2026-03-15T00:00:00.000Z")
        lessee, vehicle, lease = setup_active_lease()
        from test_helpers import create_draft_settlement
        settle = create_draft_settlement(
            lease_id=lease["id"], period_year=2026, period_month=2,
        )
        settle = finalize_settlement(settle["id"])
        resp = api.dispute_overage_settlement(
            settle["id"], make_lessee_headers(lessee["id"]),
        )
        data = validate_success(resp)
        assert data["settlement_status"] == "DISPUTED", (
            f"Expected DISPUTED after owning-lessee dispute, "
            f"got {data.get('settlement_status')!r}"
        )


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
class TestResponseEnvelope:

    def test_success_envelope_shape(self, api, fleet_manager_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format" with
        `meta` (containing `api_request_id` starting with `req_` and
        `api_request_timestamp`), `response_type` ("object" or
        "array"), and `data`.

        Claim: a successful create returns this envelope.
        """
        resp = api.create_lessee(create_lessee_payload(),
                                  fleet_manager_headers)
        assert resp.status_code == 201, (
            f"Expected 201, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "meta" in body, "envelope missing 'meta'"
        meta = body["meta"]
        rid = meta.get("api_request_id", "")
        assert isinstance(rid, str) and rid.startswith("req_"), (
            f"api_request_id must start with 'req_', got {rid!r}"
        )
        ts = meta.get("api_request_timestamp", "")
        assert is_iso8601_timestamp(str(ts)), (
            f"api_request_timestamp must be ISO 8601, got {ts!r}"
        )
        assert body.get("response_type") in {"object", "array"}, (
            f"response_type must be 'object' or 'array', "
            f"got {body.get('response_type')!r}"
        )
        assert "data" in body, "envelope missing 'data'"

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes)
        follow this standard envelope format" with
        response_type=="error" and data containing error_id and message.

        Claim: a 401 returns the error envelope.
        """
        resp = api._request("GET",
                            f"/lessees/{NON_EXISTENT_UUID}",
                            headers={})
        body = resp.json()
        assert body.get("response_type") == "error", (
            f"response_type must be 'error', "
            f"got {body.get('response_type')!r}"
        )
        d = body.get("data", {})
        assert isinstance(d.get("error_id"), str), (
            "error_id must be a string"
        )
        assert isinstance(d.get("message"), str) and d["message"], (
            "message must be a non-empty string"
        )


# ===========================================================================
# Existence ordering — PRD §2.5
# ===========================================================================
class TestPathExistence:

    def test_nonexistent_lease_returns_not_found(
        self, api, fleet_manager_headers,
    ):
        """PRD §2.5: "Any unresolved id along the chain yields
        `ERR_NOT_FOUND` with HTTP 404 for that id."

        Claim: GET /lease-agreements/{nonexistent} → ERR_NOT_FOUND.
        """
        resp = api.get_lease_agreement(NON_EXISTENT_UUID,
                                       fleet_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_nonexistent_vehicle_path_for_telematics(
        self, api, fleet_manager_headers,
    ):
        """PRD §2.5: "the leftmost id is resolved against its entity
        first, and only if it exists does the next id along the path
        get resolved. Any unresolved id along the chain yields
        `ERR_NOT_FOUND` with HTTP 404 for that id."

        Claim: POST /vehicles/{nonexistent}/telematics-events returns
        ERR_NOT_FOUND on the missing vehicle.
        """
        from test_helpers import create_telematics_event_payload
        resp = api.create_telematics_event(
            NON_EXISTENT_UUID,
            create_telematics_event_payload(
                event_ts="2026-03-15T12:00:00.000Z",
                odometer_reading=1000,
            ),
            fleet_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
