"""Error reachability and RBAC: email uniqueness, reset_year uniqueness,
session loss cap; RBAC denials for cross-role exclusive operations."""
import pytest

from test_helpers import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
    set_clock,
    create_property,
    create_member,
    schedule_annual_reset,
    get_member_version,
    ApiErrorId,
    make_loyalty_manager_headers,
    make_member_services_headers,
    make_compliance_officer_headers,
    make_member_headers,
)


# ───────────────────────────── Errors ────────────────────────────────────

class TestErrorEmailTakenOnDuplicateRegister:
    """PRD §3.1: email is unique across all Member rows under case-
    insensitive comparison."""

    def test_duplicate_email_case_insensitive_returns_email_taken(self, api):
        """PRD §3.1: "The email must be unique across all existing Member
        rows under case-insensitive comparison and must not exceed 254
        characters; a collision is rejected with ERR_EMAIL_TAKEN."

        Design: Corner/errors/error_email_taken_on_duplicate_register
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        create_member(
            property_id=prop["id"], full_name="D1", email="dup@x.com",
        )
        resp = api.create_member(
            {
                "full_name": "D2", "email": "DUP@x.com",
                "home_property_id": prop["id"],
            },
            make_member_services_headers("ms_1"),
        )
        validate_error(resp, ApiErrorId.ERR_EMAIL_TAKEN.value)


class TestErrorResetYearTaken:
    """PRD §3.8: reset_year must be unique across SCHEDULED rows."""

    def test_duplicate_reset_year_returns_reset_year_taken(self, api):
        """PRD §3.8: "reset_year must be unique across SCHEDULED rows — a
        duplicate scheduling is refused with ERR_RESET_YEAR_TAKEN."

        Design: Corner/errors/error_reset_year_taken_on_duplicate_scheduled
        """
        set_clock("2026-02-01T00:00:00Z")
        schedule_annual_reset(
            reset_year=2027, scheduled_for="2028-01-01T00:00:00Z",
        )
        resp = api.create_annual_reset_run(
            {"reset_year": 2027, "scheduled_for": "2028-02-01T00:00:00Z"},
            make_compliance_officer_headers("co_1"),
        )
        validate_error(resp, ApiErrorId.ERR_RESET_YEAR_TAKEN.value)


class TestErrorSessionLossOverCap:
    """PRD §3.3: theoretical_loss_cents > 100_000_000 is refused."""

    def test_session_loss_above_cap_returns_loss_over_cap(self, api):
        """PRD §3.3: "if theoretical_loss_cents exceeds one hundred million
        cents — the regulatory single-session reporting cap of one million
        US dollars — in which case the response is
        ERR_SESSION_LOSS_OVER_CAP".

        Design: Corner/errors/error_session_loss_over_cap_rejected
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="BC", email="bc@x.com",
        )
        resp = api.create_gaming_session(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "started_at": "2026-02-01T10:00:00Z",
                "ended_at": "2026-02-01T11:00:00Z",
                "game_type": "SLOTS",
                "theoretical_loss_cents": 100000001,
            },
            make_member_services_headers("ms_1"),
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_LOSS_OVER_CAP.value)


# ───────────────────────────── RBAC ──────────────────────────────────────

class TestRbacMemberServicesCannotCreateCompBooking:
    """PRD §4: POST /comp-room-bookings is LoyaltyManager-exclusive."""

    def test_member_services_create_comp_booking_returns_unauthorized(self, api):
        """PRD §2.1: "A request whose X-User-Role is not in the set of
        roles authorised for the target endpoint is rejected with
        ERR_UNAUTHORIZED and HTTP 403."

        Per the endpoint table in §4, POST /comp-room-bookings allows
        only LoyaltyManager.

        Design: Corner/rbac/rbac_member_services_cannot_create_comp_booking
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        mem = create_member(property_id=prop["id"], email="x@x.com")
        v = get_member_version(mem["id"])
        resp = api.create_comp_room_booking(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "check_in": "2026-03-01T15:00:00Z",
                "check_out": "2026-03-02T11:00:00Z",
                "expected_member_version": v,
            },
            make_member_services_headers("ms_1"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


class TestRbacComplianceOfficerCannotCreateHostAssignment:
    """PRD §4: POST /host-assignments is LoyaltyManager-exclusive."""

    def test_compliance_officer_create_host_assignment_returns_unauthorized(
        self, api,
    ):
        """PRD §2.1: "A request whose X-User-Role is not in the set of
        roles authorised for the target endpoint is rejected with
        ERR_UNAUTHORIZED and HTTP 403."

        Per the endpoint table in §4, POST /host-assignments allows only
        LoyaltyManager.

        Design: Corner/rbac/rbac_compliance_officer_cannot_create_host_assignment
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        host_resp = api.create_host(
            {
                "employee_email": "h@cz.com",
                "home_property_id": prop["id"],
            },
            make_compliance_officer_headers("co_1"),
        )
        host = validate_success(host_resp, expected_status=201)
        mem = create_member(property_id=prop["id"], email="y@x.com")
        v = get_member_version(mem["id"])
        resp = api.create_host_assignment(
            {
                "member_id": mem["id"], "host_id": host["id"],
                "expected_member_version": v,
            },
            make_compliance_officer_headers("co_1"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


class TestRbacMemberEntityBackedCanOnlyActOnOwnRecord:
    """PRD §2.1: Member is entity_backed:Member — X-User-ID must equal
    the acting member's id. A Member trying to self-exclude on a
    different member is treated as an unauthorized actor."""

    def test_member_self_exclude_for_other_member_returns_unauthorized(self, api):
        """PRD §2.1: "When X-User-Role is Member, X-User-ID is the id of
        the acting Member row, and any ownership check on a resource that
        references a member (the booking the member is trying to cancel,
        the self-exclusion the member is trying to reinstate) compares
        the resource's member_id field to X-User-ID."

        Design: Corner/rbac/rbac_member_entity_backed_can_only_view_own_record
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        alpha = create_member(
            property_id=prop["id"], full_name="Alpha",
            email="alpha@x.com",
        )
        beta = create_member(
            property_id=prop["id"], full_name="Beta", email="beta@x.com",
        )
        # Alpha tries to self-exclude on Beta's id.
        resp = api.create_self_exclusion(
            {
                "member_id": beta["id"],
                "exclusion_until": "2027-02-02T00:00:00Z",
                "reason": "wrong subject",
            },
            make_member_headers(alpha["id"]),
        )
        # PRD §2.1 mandates the ownership check (X-User-ID must equal the
        # resource's member_id) but does not pin a specific error_id for
        # body-mismatch; ERR_UNAUTHORIZED (forbidden non-owner) and
        # ERR_NOT_FOUND (resource invisible to actor) are both PRD-consistent.
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_UNAUTHORIZED.value,
            ApiErrorId.ERR_NOT_FOUND.value,
        ])
