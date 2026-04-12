"""Test authentication, authorization, and RBAC enforcement.

Covers:
- Missing X-User-ID header -> ERR_AUTH_REQUIRED
- Missing X-User-Role header -> ERR_AUTH_REQUIRED
- Invalid role value -> ERR_AUTH_REQUIRED
- Role-restricted endpoints: facility_admin-only, manager-only
- Employee cannot: create/update rooms, run ops, approve/reject bookings, view audit logs
- Manager cannot: create/update rooms, run ops, view audit logs
- Optimistic concurrency via version field (ERR_VERSION_CONFLICT)
- SQL injection and malicious input resilience
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    create_room_payload, create_booking_payload,
    create_standard_room, create_premium_room,
    create_confirmed_booking, create_pending_approval_booking,
)


_admin = TEST_USERS["facility_admin_headers"]
_employee = TEST_USERS["employee_headers"]
_manager = TEST_USERS["manager_headers"]


class TestAuthRequired:
    """Missing or invalid auth headers -> ERR_AUTH_REQUIRED."""

    def test_missing_both_headers(self):
        """Request with no X-User-ID and no X-User-Role -> ERR_AUTH_REQUIRED."""
        resp = api_client.list_rooms({})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED)

    def test_missing_user_id(self):
        """Request with X-User-Role but no X-User-ID -> ERR_AUTH_REQUIRED."""
        resp = api_client.list_rooms({"X-User-Role": "employee"})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED)

    def test_missing_user_role(self):
        """Request with X-User-ID but no X-User-Role -> ERR_AUTH_REQUIRED."""
        resp = api_client.list_rooms({"X-User-ID": "user-1"})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED)

    def test_invalid_role(self):
        """Unrecognized role value -> ERR_AUTH_REQUIRED."""
        resp = api_client.list_rooms({"X-User-ID": "user-1", "X-User-Role": "superadmin"})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED)

    def test_empty_user_id(self):
        """Empty X-User-ID -> ERR_AUTH_REQUIRED."""
        resp = api_client.list_rooms({"X-User-ID": "", "X-User-Role": "employee"})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED)


class TestRBACRoomEndpoints:
    """Room management restricted to facility_admin."""

    def test_employee_cannot_create_room(self):
        """POST /rooms as employee -> ERR_FORBIDDEN."""
        payload = create_room_payload()
        resp = api_client.create_room(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_manager_cannot_create_room(self):
        """POST /rooms as manager -> ERR_FORBIDDEN."""
        payload = create_room_payload()
        resp = api_client.create_room(payload, _manager)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_employee_cannot_update_room(self):
        """PUT /rooms/{id} as employee -> ERR_FORBIDDEN."""
        room = create_standard_room()
        resp = api_client.update_room(room["id"], {"name": "Hacked"}, _employee)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_manager_cannot_update_room(self):
        """PUT /rooms/{id} as manager -> ERR_FORBIDDEN."""
        room = create_standard_room()
        resp = api_client.update_room(room["id"], {"name": "Hacked"}, _manager)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_employee_cannot_run_ops(self):
        """POST /rooms/{id}/run_ops as employee -> ERR_FORBIDDEN."""
        room = create_standard_room()
        resp = api_client.run_ops(room["id"], _employee)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_manager_cannot_run_ops(self):
        """POST /rooms/{id}/run_ops as manager -> ERR_FORBIDDEN."""
        room = create_standard_room()
        resp = api_client.run_ops(room["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestRBACBookingApproval:
    """Booking approval/rejection restricted to manager and facility_admin."""

    def test_employee_cannot_approve(self):
        """POST /bookings/{id}/approve as employee -> ERR_FORBIDDEN."""
        booking, room = create_pending_approval_booking()
        resp = api_client.approve_booking(booking["id"], _employee)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_employee_cannot_reject(self):
        """POST /bookings/{id}/reject as employee -> ERR_FORBIDDEN."""
        booking, room = create_pending_approval_booking()
        resp = api_client.reject_booking(
            booking["id"],
            {"rejection_reason": "No"},
            _employee,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_manager_can_approve(self):
        """Manager can approve bookings."""
        booking, room = create_pending_approval_booking()
        resp = api_client.approve_booking(booking["id"], _manager)
        validate_success(resp, 200)

    def test_facility_admin_can_approve(self):
        """Facility admin can approve bookings."""
        booking, room = create_pending_approval_booking()
        resp = api_client.approve_booking(booking["id"], _admin)
        validate_success(resp, 200)


class TestRBACAuditLogs:
    """Audit log access restricted to facility_admin."""

    def test_employee_cannot_list_audit_logs(self):
        """GET /audit-logs as employee -> ERR_FORBIDDEN."""
        resp = api_client.list_audit_logs(_employee)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_manager_cannot_list_audit_logs(self):
        """GET /audit-logs as manager -> ERR_FORBIDDEN."""
        resp = api_client.list_audit_logs(_manager)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_facility_admin_can_list_audit_logs(self):
        """facility_admin can list audit logs."""
        create_standard_room()
        resp = api_client.list_audit_logs(_admin)
        from test_helpers import validate_paginated
        validate_paginated(resp)


class TestOptimisticConcurrency:
    """Optimistic concurrency via version field."""

    def test_version_conflict_on_stale_update(self):
        """Updating with stale version -> ERR_VERSION_CONFLICT."""
        room = create_standard_room()
        v1 = room["version"]

        # First update succeeds
        resp = api_client.update_room(room["id"], {"capacity": 15, "version": v1}, _admin)
        validate_success(resp, 200)

        # Second update with same (stale) version fails
        resp = api_client.update_room(room["id"], {"capacity": 20, "version": v1}, _admin)
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT)

    def test_version_omitted_bypasses_check(self):
        """Omitting version field allows update without concurrency check."""
        room = create_standard_room()
        # Update without version
        resp = api_client.update_room(room["id"], {"capacity": 15}, _admin)
        validate_success(resp, 200)
        # Another update without version
        resp = api_client.update_room(room["id"], {"capacity": 20}, _admin)
        validate_success(resp, 200)

    def test_version_increments_on_mutation(self):
        """Each mutation increments version by 1."""
        room = create_standard_room()
        v1 = room["version"]
        resp = api_client.update_room(room["id"], {"capacity": 15}, _admin)
        data = validate_success(resp, 200)
        assert data["version"] == v1 + 1

        resp = api_client.update_room(room["id"], {"capacity": 20}, _admin)
        data = validate_success(resp, 200)
        assert data["version"] == v1 + 2


class TestMaliciousInput:
    """Resilience against SQL injection and XSS."""

    @pytest.mark.parametrize("malicious_value", [
        "'; DROP TABLE rooms; --",
        "' OR '1'='1",
        "<script>alert('xss')</script>",
        "Robert'); DROP TABLE bookings;--",
        "1 UNION SELECT * FROM users",
    ])
    def test_sql_injection_in_room_name(self, malicious_value):
        """SQL injection attempts in room name should not crash the server."""
        payload = create_room_payload(name=malicious_value)
        resp = api_client.create_room(payload, _admin)
        # Should either succeed (name is just stored) or return a clean error
        assert resp.status_code in (201, 400, 409), (
            f"Unexpected status {resp.status_code} for SQL injection input"
        )

    @pytest.mark.parametrize("malicious_value", [
        "'; DROP TABLE bookings; --",
        "<img src=x onerror=alert(1)>",
    ])
    def test_sql_injection_in_booking_title(self, malicious_value):
        """SQL injection in booking title should not crash."""
        room = create_standard_room()
        payload = create_booking_payload(room["id"], title=malicious_value)
        resp = api_client.create_booking(payload, _employee)
        assert resp.status_code in (201, 400), (
            f"Unexpected status {resp.status_code} for malicious booking title"
        )
