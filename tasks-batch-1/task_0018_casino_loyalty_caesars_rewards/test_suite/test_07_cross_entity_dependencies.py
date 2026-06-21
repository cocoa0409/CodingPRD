"""Cross-entity state dependencies: CompRoomBooking ↔ Member.exclusion_status
gating on creation, and HostAssignment ↔ Member/operator (SOD) on
/approve."""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    set_clock,
    create_property,
    create_member,
    record_gaming_session,
    get_member_version,
    create_host,
    create_host_assignment,
    self_exclude_member,
    ApiErrorId,
    make_loyalty_manager_headers,
    bootstrap_two_managers_with_pending_host_assignment,
)


class TestCompBookingCreateBlockedByMemberExcluded:
    """PRD §3.6: a CompRoomBooking creation against an EXCLUDED member is
    refused with ERR_MEMBER_EXCLUDED. This is a CompRoomBooking↔Member
    cross-entity dependency."""

    def test_create_booking_with_excluded_member_returns_member_excluded(
        self, api,
    ):
        """PRD §3.6: "The booking is refused if the member is excluded
        (ERR_MEMBER_EXCLUDED), if the member is velocity-suspended
        (ERR_MEMBER_VELOCITY_SUSPENDED), if check_out is not strictly
        greater than check_in (ERR_BOOKING_INVALID_DATES), if the supplied
        member version is stale (ERR_STALE_MEMBER_VERSION)".

        Design: Difficulty/cross_entity_state_dependency/comp_booking_confirm_requires_member_not_excluded_and_velocity_normal
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="M Cx1", email="mcx1@x.com",
        )
        # Self-exclude.
        self_exclude_member(
            member_id=mem["id"],
            exclusion_until="2027-06-02T00:00:00Z",
            reason="cx test",
        )
        v = get_member_version(mem["id"])
        resp = api.create_comp_room_booking(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "check_in": "2026-08-01T15:00:00Z",
                "check_out": "2026-08-02T11:00:00Z",
                "expected_member_version": v,
            },
            make_loyalty_manager_headers("lm_1"),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_EXCLUDED.value)

    def test_excluded_member_carries_exclusion_status(self, api):
        """PRD §3.7: "the server transitions the member's exclusion_status
        from NOT_EXCLUDED (or REINSTATED, on a repeat self-exclusion) to
        EXCLUDED".

        Design: Difficulty/cross_entity_state_dependency/comp_booking_confirm_requires_member_not_excluded_and_velocity_normal
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="M Cx1b", email="mcx1b@x.com",
        )
        self_exclude_member(
            member_id=mem["id"],
            exclusion_until="2027-06-02T00:00:00Z",
            reason="cx test",
        )
        m = validate_success(
            api.get_member(mem["id"], make_loyalty_manager_headers("lm_1")),
            expected_status=200,
        )
        assert m["exclusion_status"] == "EXCLUDED"


class TestHostAssignmentApproveRequiresDifferentOperator:
    """PRD §3.5 + §2.9: same LoyaltyManager X-User-ID cannot create AND
    approve the same HostAssignment. This is the segregation-of-duties
    cross-entity dependency (HostAssignment ↔ approver identity)."""

    def test_self_approve_is_rejected_with_sod_violation(self, api):
        """PRD §3.5: "Approving the assignment requires that the
        approver's X-User-ID differs from the creator's
        assigned_by_user_id (segregation of duties — same-operator
        approval is refused with ERR_SOD_VIOLATION)".

        Design: Difficulty/cross_entity_state_dependency/host_assignment_approve_requires_host_active
        """
        ctx = bootstrap_two_managers_with_pending_host_assignment(
            clock="2026-06-10T00:00:00Z",
            alice_id="lm_alice", bob_id="lm_bob",
        )
        # Alice (the creator) tries to approve her own assignment.
        resp = api.approve_host_assignment(
            ctx["host_assignment"]["id"],
            make_loyalty_manager_headers("lm_alice"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)

    def test_self_approve_leaves_assignment_in_pending_approval(self, api):
        """PRD §2.9: "A single LoyaltyManager X-User-ID may not both create
        and approve (or create and reject) the same HostAssignment. The
        creator's identifier is captured at create-time as
        assigned_by_user_id; the approver or rejecter's identifier must
        differ from that value ... A violation is rejected with
        ERR_SOD_VIOLATION and HTTP 422."

        Design: Difficulty/cross_entity_state_dependency/host_assignment_approve_requires_host_active
        """
        ctx = bootstrap_two_managers_with_pending_host_assignment(
            clock="2026-06-10T00:00:00Z",
            alice_id="lm_alice", bob_id="lm_bob",
        )
        resp = api.approve_host_assignment(
            ctx["host_assignment"]["id"],
            make_loyalty_manager_headers("lm_alice"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)
        ha = validate_success(
            api.get_host_assignment(
                ctx["host_assignment"]["id"],
                make_loyalty_manager_headers("lm_alice"),
            ),
            expected_status=200,
        )
        assert ha["status"] == "PENDING_APPROVAL", (
            f"After SOD-rejected approval, status must remain PENDING_APPROVAL, "
            f"got {ha['status']!r}"
        )
