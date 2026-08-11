"""Authentication, authorization, ownership scoping, and role boundaries
(PRD §2.1, §3.1, §4)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_staff, staff_headers, create_open_slot,
    register_guardian, guardian_headers,
)
from test_helpers import api_client


class TestAuthentication:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or
        carries an undeclared role, or whose `X-User-ID` is missing for an
        entity-backed role, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)".

        Reading a guardian record without any auth headers fails the
        priority-1 authentication tier before existence or ownership checks.

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        guardian = register_guardian("G O", "go@x.com", "912")
        res = api_client.get_guardian(guardian["id"], headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestOwnershipScoping:
    def test_guardian_cannot_read_other_guardian_record(self, api):
        """PRD §2.1: "When `X-User-Role` is `Guardian`, `X-User-ID` is the
        `id` of the acting `Guardian`; ownership checks on any resource that
        references a `Guardian` compare the resource's guardian foreign-key
        field (in the path or body) to `X-User-ID`, and a mismatch is
        `ERR_FORBIDDEN`."

        Design: Corner/validations/guardian_cannot_read_other_guardian_record
        """
        ga = register_guardian("G A", "ga2@x.com", "913")
        gb = register_guardian("G B", "gb2@x.com", "914")
        res = api_client.get_guardian(ga["id"], guardian_headers(gb))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestRoleBoundaries:
    def test_guardian_cannot_create_session_slot(self, api):
        """PRD §4: `POST /session-slots` is authorized for "Manager, Admin"
        only.
        PRD §2.1: "A request whose role is not permitted on the target
        endpoint, whose staff identity fails the staff checks below, or where
        a `Guardian` attempts to act on another guardian's resources, is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/guardian_cannot_create_session_slot
        """
        guardian = register_guardian("G AB", "gab@x.com", "927")
        res = api_client.create_session_slot(
            {"slot_date": "2026-06-06", "start_at": "2026-06-06T14:00:00Z",
             "end_at": "2026-06-06T15:30:00Z", "capacity": 10},
            guardian_headers(guardian))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_cafe_staff_cannot_close_session_slot(self, api):
        """PRD §4: `POST /session-slots/{id}/close` is authorized for
        "Manager" only.
        PRD §2.1: "A request whose role is not permitted on the target
        endpoint, whose staff identity fails the staff checks below, or where
        a `Guardian` attempts to act on another guardian's resources, is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        CafeStaff is a peer role, not a superset: closing a slot is denied.

        Design: Corner/rbac/cafe_staff_cannot_close_session_slot
        """
        cafe = make_staff("CAFE_STAFF", "Cafe One")
        mgr = make_staff("MANAGER", "Mgr One")
        slot = create_open_slot(staff_headers(mgr))

        res = api_client.close_session_slot(
            slot["id"], {"reason": "MANAGER_CLOSE"}, staff_headers(cafe))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        fresh = validate_success(
            api_client.get_session_slot(slot["id"], staff_headers(mgr)), 200)
        assert fresh["status"] == "OPEN"


class TestAnonymousRegistration:
    def test_anonymous_registration_allowed(self, api):
        """PRD §3.1: "A family enters the system when an unauthenticated
        visitor self-registers a guardian account with a `full_name`,
        `email`, and `phone`. The new `Guardian` starts with
        `membership_status` of `NONE`, `loyalty_tier` of `BRONZE`, every
        counter at zero, and `version` 1."

        Design: Corner/rbac/anonymous_registration_allowed
        """
        guardian = validate_success(api_client.create_guardian(
            {"full_name": "G AD", "email": "gad@x.com", "phone": "929"},
            headers={}), 201)
        assert guardian["loyalty_tier"] == "BRONZE"
        assert guardian["membership_status"] == "NONE"
