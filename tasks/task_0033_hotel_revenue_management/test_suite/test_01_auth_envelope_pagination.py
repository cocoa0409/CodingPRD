"""Auth, RBAC, envelope, pagination, and existence checks (PRD §2)."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_room_type_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 — Auth header presence
# ===========================================================================
class TestAuthHeaders:
    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'A request that omits either header is rejected with
        ERR_AUTH_MISSING (HTTP 401).'"""
        bad_headers = {"X-User-Role": "PlatformAdmin"}
        res = api.create_room_type(create_room_type_payload(), bad_headers)
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: 'A request that omits either header is rejected with
        ERR_AUTH_MISSING (HTTP 401).'"""
        bad_headers = {"X-User-ID": "admin-001"}
        res = api.create_room_type(create_room_type_payload(), bad_headers)
        validate_error(res, "ERR_AUTH_MISSING")

    def test_both_headers_missing_rejected(self, api):
        """PRD §2.1: 'A request that omits either header is rejected with
        ERR_AUTH_MISSING (HTTP 401).'"""
        res = api.create_room_type(create_room_type_payload(), {})
        validate_error(res, "ERR_AUTH_MISSING")

    def test_get_clock_requires_auth(self, api):
        """PRD §2.1: 'Every request to the API (except the public GET
        /_health probe, if present) MUST carry two HTTP headers:
        X-User-ID and X-User-Role.'"""
        res = api.get_clock({})
        validate_error(res, "ERR_AUTH_MISSING")


# ===========================================================================
# §2.1 — RBAC mismatch
# ===========================================================================
class TestRBAC:
    @pytest.mark.parametrize(
        "role",
        ["RevenueAnalyst", "RevenueManager", "ReservationsAgent",
         "FrontDeskClerk", "HousekeepingStaff", "Guest"],
    )
    def test_create_room_type_requires_platform_admin(self, api, role):
        """PRD §2.1: 'A request whose X-User-Role value is not authorized
        for the targeted endpoint per the RBAC matrix in §4 is rejected
        with ERR_FORBIDDEN (HTTP 403).'

        Per the PRD §4 RBAC matrix, only PlatformAdmin may create a
        RoomType; all other roles are rejected with ERR_FORBIDDEN."""
        headers = build_user_headers(f"{role.lower()}-001", role)
        res = api.create_room_type(create_room_type_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_resolve_dispute_requires_platform_admin(
        self, api, manager_headers,
    ):
        """PRD §2.1: 'A request whose X-User-Role value is not authorized
        for the targeted endpoint per the RBAC matrix in §4 is rejected
        with ERR_FORBIDDEN (HTTP 403).'

        Per the PRD §4 RBAC matrix, dispute resolution is restricted to
        PlatformAdmin; RevenueManager is rejected."""
        res = api.resolve_dispute(
            NON_EXISTENT_UUID, {"resolution": "GUEST"}, manager_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_advance_clock_requires_platform_admin(self, api, agent_headers):
        """PRD §2.1: 'A request whose X-User-Role value is not authorized
        for the targeted endpoint per the RBAC matrix in §4 is rejected
        with ERR_FORBIDDEN (HTTP 403).'

        Per the PRD §4 RBAC matrix, the logical clock is driven only by
        PlatformAdmin."""
        res = api.advance_clock("2026-01-01T00:00:00.000Z", agent_headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_confirm_reservation_requires_reservations_agent(
        self, api, clerk_headers,
    ):
        """PRD §2.1: 'A request whose X-User-Role value is not authorized
        for the targeted endpoint per the RBAC matrix in §4 is rejected
        with ERR_FORBIDDEN (HTTP 403).'

        Per the PRD §4 RBAC matrix, only ReservationsAgent may confirm
        a reservation. FrontDeskClerk receives ERR_FORBIDDEN — RBAC
        rejects before id-existence is even consulted."""
        res = api.confirm_reservation(NON_EXISTENT_UUID, clerk_headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_check_in_requires_front_desk_clerk(self, api, agent_headers):
        """PRD §2.1: 'A request whose X-User-Role value is not authorized
        for the targeted endpoint per the RBAC matrix in §4 is rejected
        with ERR_FORBIDDEN (HTTP 403).'

        Per the PRD §4 RBAC matrix, only FrontDeskClerk may check guests
        in. ReservationsAgent receives ERR_FORBIDDEN."""
        res = api.check_in_reservation(
            NON_EXISTENT_UUID, {"room_id": NON_EXISTENT_UUID}, agent_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_create_overbooking_policy_requires_revenue_manager(
        self, api, agent_headers,
    ):
        """PRD §2.1: 'A request whose X-User-Role value is not authorized
        for the targeted endpoint per the RBAC matrix in §4 is rejected
        with ERR_FORBIDDEN (HTTP 403).'

        Per the PRD §4 RBAC matrix, OverbookingPolicy creation is
        restricted to RevenueManager; ReservationsAgent is rejected."""
        res = api.create_overbooking_policy(
            {
                "room_type_id": NON_EXISTENT_UUID,
                "stay_date": "2026-12-25",
                "overbook_ratio_basis_points": 1000,
                "estimated_no_show_probability_basis_points": 1000,
                "walkout_compensation_cents": 10000,
            },
            agent_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_audit_logs_restricted_to_admin_and_manager(
        self, api, agent_headers,
    ):
        """PRD §2.10: 'query access is limited to the PlatformAdmin and
        RevenueManager roles.'"""
        res = api.list_audit_logs(agent_headers)
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.2 — Envelope structure
# ===========================================================================
class TestEnvelope:
    def test_success_envelope_shape_for_room_type_create(self, api):
        """PRD §2.2: 'All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body.'"""
        res = api.create_room_type(
            create_room_type_payload(), TEST_USERS["admin_headers"],
        )
        assert res.status_code == 201
        body = res.json()
        assert "meta" in body
        assert "response_type" in body
        assert "data" in body
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_"), (
            "PRD §2.2: 'a server-generated unique identifier for the "
            "request that starts with req_.'"
        )
        assert isinstance(meta.get("api_request_timestamp"), str)
        assert body["response_type"] == "object"

    def test_error_envelope_shape(self, api):
        """PRD §2.2: 'All error API responses (4xx status codes) follow
        this standard envelope format.'"""
        res = api.create_room_type(create_room_type_payload(), {})
        body = res.json()
        assert body["response_type"] == "error"
        data = body["data"]
        assert isinstance(data["error_id"], str)
        assert isinstance(data["message"], str)


# ===========================================================================
# §2.3 — Pagination
# ===========================================================================
class TestPagination:
    def test_list_room_types_default_pagination_limit_is_10(
        self, api, admin_headers,
    ):
        """PRD §2.3: 'The default limit is 10.'"""
        res = api.list_room_types(admin_headers)
        _, meta = validate_paginated(res)
        assert meta["limit"] == 10

    def test_list_with_limit_zero_rejected(self, api, admin_headers):
        """PRD §2.3: 'values must lie in the inclusive range from 1 to 100.
        ... Any value outside these ranges is rejected with
        ERR_INVALID_PAGINATION (HTTP 422).'"""
        res = api.list_room_types(admin_headers, params={"limit": 0})
        validate_error(res, "ERR_INVALID_PAGINATION")

    def test_list_with_limit_above_max_rejected(self, api, admin_headers):
        """PRD §2.3: 'values must lie in the inclusive range from 1 to 100.'"""
        res = api.list_room_types(admin_headers, params={"limit": 101})
        validate_error(res, "ERR_INVALID_PAGINATION")

    def test_list_with_negative_offset_rejected(self, api, admin_headers):
        """PRD §2.3: 'The default offset is 0 and must be non-negative.'"""
        res = api.list_room_types(admin_headers, params={"offset": -1})
        validate_error(res, "ERR_INVALID_PAGINATION")

    def test_pagination_meta_fields_present(self, api, admin_headers):
        """PRD §2.3: 'The meta block on every list response surfaces
        limit, offset, total_count, and has_more.'"""
        res = api.list_room_types(admin_headers, params={"limit": 5, "offset": 0})
        _, meta = validate_paginated(res)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"meta missing {key}"


# ===========================================================================
# §2.6 — Path validation: ERR_NOT_FOUND for missing path id
# ===========================================================================
class TestPathExistence:
    def test_get_room_type_missing_returns_not_found(
        self, api, admin_headers,
    ):
        """PRD §2.6: 'the server first resolves the room_type_id segment;
        if the RoomType does not exist, the response is ERR_NOT_FOUND
        (HTTP 404).'"""
        res = api.get_room_type(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_reservation_missing_returns_not_found(
        self, api, admin_headers,
    ):
        """PRD §2.6: 'The same rule applies uniformly to all path
        parameters that resolve to a RoomType, Room, Channel, RatePlan,
        RateOverride, MaintenanceBlock, OverbookingPolicy, or Reservation id.'"""
        res = api.get_reservation(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_confirm_missing_reservation_returns_not_found(
        self, api, agent_headers,
    ):
        """PRD §2.6: '... if the RoomType does not exist, the response is
        ERR_NOT_FOUND (HTTP 404), and no subsequent segment is evaluated.'
        Same uniform rule applies to Reservation."""
        res = api.confirm_reservation(NON_EXISTENT_UUID, agent_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_walkout_estimate_missing_room_type_returns_not_found(
        self, api, manager_headers,
    ):
        """PRD §2.6: 'For an endpoint such as the walkout-cost-estimate
        read on (room_type_id, stay_date), the server first resolves the
        room_type_id segment; if the RoomType does not exist, the
        response is ERR_NOT_FOUND (HTTP 404).'"""
        res = api.get_walkout_cost_estimate(
            NON_EXISTENT_UUID, "2026-12-25", manager_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")
