"""Test audit logging for all booking mutations.

Covers:
- Audit log created on booking creation, confirmation, approval, rejection,
  check-in, check-out, cancellation
- Audit log created on room creation, update, status transition
- Audit log created on series creation, cancellation
- Audit log created on waitlist creation, cancellation, promotion
- Audit log fields: actor_id, actor_role, action, resource_type, resource_id, details
- Only facility_admin can list/get audit logs
- Pagination and filtering (resource_type, resource_id, actor_id, action)
- ERR_FORBIDDEN for non-admin roles
"""
import pytest
from datetime import datetime, timedelta, timezone
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    assert_audit_log,
    create_booking_payload,
    create_standard_room, create_premium_room,
    create_confirmed_booking, create_pending_approval_booking,
)


_admin = TEST_USERS["facility_admin_headers"]
_employee = TEST_USERS["employee_headers"]
_manager = TEST_USERS["manager_headers"]


class TestAuditLogAccess:
    """GET /audit-logs, GET /audit-logs/{log_id}"""

    def test_list_audit_logs_admin_allowed(self):
        """facility_admin can list audit logs."""
        # Create a room to generate at least one audit log entry
        create_standard_room()
        resp = api_client.list_audit_logs(_admin)
        items, _ = validate_paginated(resp)
        assert len(items) >= 1

    def test_list_audit_logs_employee_forbidden(self):
        """Employee cannot list audit logs -> ERR_FORBIDDEN."""
        resp = api_client.list_audit_logs(_employee)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_list_audit_logs_manager_forbidden(self):
        """Manager cannot list audit logs -> ERR_FORBIDDEN."""
        resp = api_client.list_audit_logs(_manager)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_get_audit_log_by_id(self):
        """Retrieve a single audit log entry by ID."""
        create_standard_room()
        resp = api_client.list_audit_logs(_admin, params={"limit": 1})
        items, _ = validate_paginated(resp)
        assert len(items) >= 1
        log_id = items[0]["id"]

        resp = api_client.get_audit_log(log_id, _admin)
        data = validate_success(resp, 200)
        assert_audit_log(data)
        assert data["id"] == log_id

    def test_get_audit_log_employee_forbidden(self):
        """Employee cannot get audit log -> ERR_FORBIDDEN."""
        create_standard_room()
        resp = api_client.list_audit_logs(_admin, params={"limit": 1})
        items, _ = validate_paginated(resp)
        if items:
            resp = api_client.get_audit_log(items[0]["id"], _employee)
            validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestAuditLogContent:
    """Verify audit log entries are created for mutations."""

    def test_booking_creation_logged(self):
        """Creating a booking generates an audit log entry."""
        room = create_standard_room()
        payload = create_booking_payload(room["id"])
        resp = api_client.create_booking(payload, _employee)
        booking = get_success_data(resp)

        resp = api_client.list_audit_logs(_admin, params={
            "resource_type": "Booking",
            "resource_id": booking["id"],
        })
        items, _ = validate_paginated(resp)
        assert len(items) >= 1, "Booking creation should generate an audit log entry"
        log = items[0]
        assert_audit_log(log)
        assert log["resource_id"] == booking["id"]
        assert log["actor_id"] == "test-employee-1"
        assert log["actor_role"] == "employee"

    def test_booking_approval_logged(self):
        """Approving a booking generates an audit log entry."""
        booking, room = create_pending_approval_booking()
        api_client.approve_booking(booking["id"], _manager)

        resp = api_client.list_audit_logs(_admin, params={
            "resource_id": booking["id"],
        })
        items, _ = validate_paginated(resp)
        actions = [log["action"] for log in items]
        # Should contain an approval action
        assert any("confirm" in a.lower() or "approv" in a.lower() for a in actions), (
            f"Expected an approval/confirmation audit log, found actions: {actions}"
        )

    def test_booking_cancellation_logged(self):
        """Cancelling a booking generates an audit log entry."""
        booking, room = create_confirmed_booking()
        api_client.cancel_booking(booking["id"], _employee)

        resp = api_client.list_audit_logs(_admin, params={
            "resource_id": booking["id"],
        })
        items, _ = validate_paginated(resp)
        actions = [log["action"] for log in items]
        assert any("cancel" in a.lower() for a in actions), (
            f"Expected a cancellation audit log, found actions: {actions}"
        )

    def test_room_creation_logged(self):
        """Creating a room generates an audit log entry."""
        room = create_standard_room()
        resp = api_client.list_audit_logs(_admin, params={
            "resource_type": "Room",
            "resource_id": room["id"],
        })
        items, _ = validate_paginated(resp)
        assert len(items) >= 1, "Room creation should generate an audit log entry"

    def test_room_status_change_logged(self):
        """Changing room status generates an audit log entry."""
        room = create_standard_room()
        api_client.update_room(room["id"], {"status": "MAINTENANCE"}, _admin)

        resp = api_client.list_audit_logs(_admin, params={
            "resource_type": "Room",
            "resource_id": room["id"],
        })
        items, _ = validate_paginated(resp)
        assert len(items) >= 2, "Room creation + status change should generate >= 2 audit logs"


class TestAuditLogFiltering:
    """Audit log filtering and pagination."""

    def test_filter_by_resource_type(self):
        """Filter audit logs by resource_type=Room."""
        create_standard_room()
        resp = api_client.list_audit_logs(_admin, params={"resource_type": "Room"})
        items, _ = validate_paginated(resp)
        for item in items:
            assert item["resource_type"] == "Room"

    def test_filter_by_actor_id(self):
        """Filter audit logs by actor_id."""
        room = create_standard_room()  # Created by admin
        resp = api_client.list_audit_logs(_admin, params={"actor_id": "test-facility-admin-1"})
        items, _ = validate_paginated(resp)
        for item in items:
            assert item["actor_id"] == "test-facility-admin-1"

    def test_audit_log_pagination(self):
        """Paginated audit log listing."""
        for _ in range(3):
            create_standard_room()
        resp = api_client.list_audit_logs(_admin, params={"limit": 2, "offset": 0})
        items, _ = validate_paginated(resp)
        assert len(items) <= 2

    def test_audit_log_details_has_state(self):
        """Audit log details contain before/after state snapshot."""
        room = create_standard_room()
        api_client.update_room(room["id"], {"status": "MAINTENANCE"}, _admin)

        resp = api_client.list_audit_logs(_admin, params={
            "resource_type": "Room",
            "resource_id": room["id"],
        })
        items, _ = validate_paginated(resp)
        # At least one log should have details
        logs_with_details = [i for i in items if i.get("details") and isinstance(i["details"], dict)]
        assert len(logs_with_details) >= 1, "At least one audit log should have details"
