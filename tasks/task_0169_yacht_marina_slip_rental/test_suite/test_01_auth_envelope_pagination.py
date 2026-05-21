"""Authentication, role permission, response envelope, and pagination —
PRD §2.1, §2.2, §2.3.

These tests exercise the universal cross-cutting rules that apply to
every endpoint: missing headers, role-permission mismatches, response
envelope shape, and pagination bounds.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_marina,
    create_marina_payload,
    make_dock_master_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth header probes — PRD §2.1
# ===========================================================================
class TestAuthHeaders:

    def test_missing_both_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers:
        `X-User-ID`, identifying the caller, and `X-User-Role`, naming
        the caller's role. ... Requests missing either header are
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401).\""""
        resp = api._request(
            "GET", f"/marinas/{NON_EXISTENT_UUID}", headers={},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_id_returns_unauthenticated(self, api):
        """PRD §2.1: "Requests missing either header are rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401).\""""
        resp = api._request(
            "GET", f"/marinas/{NON_EXISTENT_UUID}",
            headers={"X-User-Role": "DockMaster"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_role_returns_unauthenticated(self, api):
        """PRD §2.1: "Requests missing either header are rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401).\""""
        resp = api._request(
            "GET", f"/marinas/{NON_EXISTENT_UUID}",
            headers={"X-User-ID": "any-id"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Role permission — PRD §2.1 / §4
# ===========================================================================
class TestRolePermission:

    def test_boater_cannot_create_marina(self, api, boater_headers):
        """PRD §4: "POST /marinas — Create a marina — DockMaster,
        BillingClerk".

        Claim: a Boater attempting POST /marinas → ERR_FORBIDDEN."""
        resp = api.create_marina(create_marina_payload(), boater_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_billing_clerk_cannot_advance_clock(
        self, api, billing_clerk_headers,
    ):
        """PRD §4: "POST /marinas/:marina_id/_clock/advance — Advance
        the marina logical clock to a supplied instant (test-driving) —
        DockMaster".

        Claim: a BillingClerk attempting clock advance → ERR_FORBIDDEN."""
        marina = create_marina()
        resp = api.clock_advance(
            marina["id"], {"to": "2024-01-01T00:00:00.000Z"},
            billing_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_boater_cannot_create_slip(self, api, boater_headers):
        """PRD §4: "POST /marinas/:marina_id/slips — Create a slip —
        DockMaster".

        Claim: a Boater attempting slip create → ERR_FORBIDDEN."""
        marina = create_marina()
        resp = api.create_slip(
            marina["id"], {"code": "X-99", "length_feet": 40.0,
                           "beam_feet": 14.0, "depth_feet": 6.0,
                           "flat_daily_charge_cents": 2000},
            boater_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_boater_cannot_approve_reservation(self, api, boater_headers):
        """PRD §4: "POST /marinas/:marina_id/reservations/:reservation_id/
        approve — Approve a reservation (DRAFT to APPROVED) —
        DockMaster".

        Claim: a Boater attempting approve → ERR_FORBIDDEN."""
        marina = create_marina()
        resp = api.approve_reservation(
            marina["id"], NON_EXISTENT_UUID, boater_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_billing_clerk_cannot_create_reservation(
        self, api, billing_clerk_headers,
    ):
        """PRD §4: "POST /marinas/:marina_id/reservations — Create a
        reservation in DRAFT — Boater, DockMaster". BillingClerk is not
        on this list.

        Claim: a BillingClerk attempting to create a reservation →
        ERR_FORBIDDEN."""
        marina = create_marina()
        body = {
            "boater_id": NON_EXISTENT_UUID,
            "vessel_id": NON_EXISTENT_UUID,
            "slip_id": NON_EXISTENT_UUID,
            "check_in_date": "2024-05-01T00:00:00.000Z",
            "check_out_date": "2024-05-05T00:00:00.000Z",
            "insurance_policy_id": NON_EXISTENT_UUID,
        }
        resp = api.create_reservation(
            marina["id"], body, billing_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
class TestResponseEnvelope:

    def test_success_envelope_carries_meta_response_type_data(
        self, api, dock_master_headers,
    ):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body ... `meta` ... `api_request_id` ... `response_type`
        ... `data` ..."

        Claim: a 2xx response has meta.api_request_id starting with
        `req_`, response_type in {object, array}, and a `data` field."""
        resp = api.create_marina(create_marina_payload(), dock_master_headers)
        assert resp.status_code == 201, (
            f"Expected 201 for marina create, got {resp.status_code}"
        )
        body = resp.json()
        assert "meta" in body, "envelope missing 'meta'"
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str), (
            "meta.api_request_id must be a string"
        )
        assert meta["api_request_id"].startswith("req_"), (
            f"meta.api_request_id must start with 'req_'; "
            f"got {meta['api_request_id']!r}"
        )
        assert isinstance(meta.get("api_request_timestamp"), str)
        assert body.get("response_type") in {"object", "array"}, (
            f"response_type must be object or array, got "
            f"{body.get('response_type')!r}"
        )
        assert "data" in body, "envelope missing 'data'"

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format ... `response_type` is "error"
        ... `data` contains `error_id` and `message`."

        Claim: a 4xx response carries response_type=error and
        data.error_id."""
        resp = api._request(
            "GET", f"/marinas/{NON_EXISTENT_UUID}", headers={},
        )
        body = resp.json()
        assert body.get("response_type") == "error", (
            f"response_type must be 'error', got "
            f"{body.get('response_type')!r}"
        )
        data = body.get("data", {})
        assert isinstance(data.get("error_id"), str), (
            "error data must carry error_id string"
        )
        assert isinstance(data.get("message"), str), (
            "error data must carry message string"
        )


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_list_reservations_has_paginated_meta(
        self, api, dock_master_headers,
    ):
        """PRD §2.3: "The `meta` envelope on list responses includes
        `limit`, `offset`, `total_count` ... and `has_more` ..."

        Claim: GET /reservations returns meta with all four pagination
        fields."""
        marina = create_marina()
        resp = api.list_reservations(marina["id"], dock_master_headers)
        data, meta = validate_paginated(resp)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"meta missing pagination key {key!r}"

    def test_default_limit_is_10(self, api, dock_master_headers):
        """PRD §2.3: "The default `limit` is 10..."

        Claim: omitting limit yields meta.limit == 10."""
        marina = create_marina()
        resp = api.list_reservations(marina["id"], dock_master_headers)
        data, meta = validate_paginated(resp)
        assert meta.get("limit") == 10, (
            f"Default limit must be 10, got {meta.get('limit')!r}"
        )

    def test_default_offset_is_0(self, api, dock_master_headers):
        """PRD §2.3: "the default `offset` is 0."

        Claim: omitting offset yields meta.offset == 0."""
        marina = create_marina()
        resp = api.list_reservations(marina["id"], dock_master_headers)
        data, meta = validate_paginated(resp)
        assert meta.get("offset") == 0, (
            f"Default offset must be 0, got {meta.get('offset')!r}"
        )
