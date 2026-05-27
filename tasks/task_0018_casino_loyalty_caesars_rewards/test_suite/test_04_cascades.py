"""Transitive cascade chains: depth-3 self-exclusion cascade and depth-2
velocity-driven cascade onto comp-room bookings."""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    create_property,
    create_member,
    record_gaming_session,
    get_member_version,
    create_booking,
    confirm_booking,
    create_host,
    create_host_assignment,
    approve_host_assignment,
    self_exclude_member,
    make_loyalty_manager_headers,
    make_member_headers,
    make_member_services_headers,
    bootstrap_cascade_setup,
    bootstrap_platinum_with_pending_booking,
)


class TestSelfExclusionDepthThreeCascade:
    """PRD §3.7: a single POST /self-exclusions triggers a three-hop cascade:
    Member.exclusion_status → EXCLUDED; HostAssignment(ACTIVE) → REVOKED;
    CompRoomBooking(PENDING/CONFIRMED) → CANCELLED; Member.assigned_host_id
    → null when the active assignment was revoked."""

    def test_self_exclusion_revokes_active_host_assignment(self, api):
        """PRD §3.7: "In the same operation, the server transitions the
        member's exclusion_status from NOT_EXCLUDED (or REINSTATED, on a
        repeat self-exclusion) to EXCLUDED; transitions every
        HostAssignment for this member whose current status is in
        PENDING_APPROVAL or ACTIVE to REVOKED ... and, if any of the
        revoked assignments was the active one, nulls out
        assigned_host_id."

        Design: Difficulty/transitive_cascade/self_exclusion_cascade_depth_three
        """
        ctx = bootstrap_cascade_setup(
            clock="2026-11-01T00:00:00Z",
            check_in="2026-12-01T15:00:00Z",
            check_out="2026-12-02T11:00:00Z",
        )
        self_exclude_member(
            member_id=ctx["member"]["id"],
            exclusion_until="2027-11-02T00:00:00Z",
            reason="cascade",
        )
        m = validate_success(
            api.get_member(
                ctx["member"]["id"],
                make_loyalty_manager_headers(ctx["alice_id"]),
            ),
            expected_status=200,
        )
        assert m["exclusion_status"] == "EXCLUDED"
        assert m["assigned_host_id"] is None, (
            f"assigned_host_id must be null after the active assignment was "
            f"revoked, got {m['assigned_host_id']!r}"
        )
        ha = validate_success(
            api.get_host_assignment(
                ctx["host_assignment"]["id"],
                make_loyalty_manager_headers(ctx["alice_id"]),
            ),
            expected_status=200,
        )
        assert ha["status"] == "REVOKED"

    def test_self_exclusion_cancels_confirmed_booking_in_same_cascade(self, api):
        """PRD §3.7: "transitions every CompRoomBooking for this member
        whose current status is in PENDING or CONFIRMED to CANCELLED".

        Design: Difficulty/transitive_cascade/self_exclusion_cascade_depth_three
        """
        ctx = bootstrap_cascade_setup(
            clock="2026-11-01T00:00:00Z",
            check_in="2026-12-01T15:00:00Z",
            check_out="2026-12-02T11:00:00Z",
        )
        self_exclude_member(
            member_id=ctx["member"]["id"],
            exclusion_until="2027-11-02T00:00:00Z",
            reason="cascade",
        )
        b = validate_success(
            api.get_comp_room_booking(
                ctx["booking"]["id"],
                make_loyalty_manager_headers(ctx["alice_id"]),
            ),
            expected_status=200,
        )
        assert b["status"] == "CANCELLED", (
            f"CONFIRMED booking must cascade to CANCELLED on self-exclusion, "
            f"got {b['status']!r}"
        )


class TestVelocitySuspendCascadeOntoBookings:
    """PRD §3.4: velocity_status → SUSPENDED simultaneously cancels every
    PENDING / CONFIRMED CompRoomBooking for that member."""

    def test_velocity_suspend_cancels_pending_booking(self, api):
        """PRD §3.4: "From either NORMAL or FLAGGED, a SUSPENDED alert
        advances the member to SUSPENDED and, in the same operation,
        cancels every CompRoomBooking for that member whose current status
        is in PENDING or CONFIRMED — the suspension simultaneously protects
        the casino's compliance posture and clears the member's outstanding
        comp pipeline."

        Design: Difficulty/transitive_cascade/velocity_session_cascade_depth_two
        """
        ctx = bootstrap_platinum_with_pending_booking(
            clock="2026-11-15T00:00:00Z",
            check_in="2026-12-15T15:00:00Z",
            check_out="2026-12-16T11:00:00Z",
        )
        # Three SLOTS sessions, each 500_000 cents, within 60-min window
        # ending at the third session. Third session's window aggregate
        # = 1_500_000 cents → SUSPENDED threshold.
        for i, (start, end) in enumerate([
            ("2026-11-20T10:00:00Z", "2026-11-20T10:10:00Z"),
            ("2026-11-20T10:20:00Z", "2026-11-20T10:30:00Z"),
            ("2026-11-20T10:40:00Z", "2026-11-20T10:50:00Z"),
        ]):
            record_gaming_session(
                member_id=ctx["member"]["id"],
                property_id=ctx["property"]["id"],
                started_at=start, ended_at=end,
                game_type="SLOTS", theoretical_loss_cents=500_000,
            )
        m = validate_success(
            api.get_member(
                ctx["member"]["id"], make_loyalty_manager_headers("lm_1"),
            ),
            expected_status=200,
        )
        assert m["velocity_status"] == "SUSPENDED"
        b = validate_success(
            api.get_comp_room_booking(
                ctx["booking"]["id"], make_loyalty_manager_headers("lm_1"),
            ),
            expected_status=200,
        )
        assert b["status"] == "CANCELLED", (
            f"PENDING booking must cascade to CANCELLED on velocity SUSPEND, "
            f"got {b['status']!r}"
        )

    def test_velocity_suspend_transitions_member_status(self, api):
        """PRD §3.4: "From either NORMAL or FLAGGED, a SUSPENDED alert
        advances the member to SUSPENDED".

        Design: Difficulty/transitive_cascade/velocity_session_cascade_depth_two
        """
        ctx = bootstrap_platinum_with_pending_booking(
            clock="2026-11-15T00:00:00Z",
            check_in="2026-12-15T15:00:00Z",
            check_out="2026-12-16T11:00:00Z",
        )
        for start, end in [
            ("2026-11-20T10:00:00Z", "2026-11-20T10:10:00Z"),
            ("2026-11-20T10:20:00Z", "2026-11-20T10:30:00Z"),
            ("2026-11-20T10:40:00Z", "2026-11-20T10:50:00Z"),
        ]:
            record_gaming_session(
                member_id=ctx["member"]["id"],
                property_id=ctx["property"]["id"],
                started_at=start, ended_at=end,
                game_type="SLOTS", theoretical_loss_cents=500_000,
            )
        m = validate_success(
            api.get_member(
                ctx["member"]["id"], make_loyalty_manager_headers("lm_1"),
            ),
            expected_status=200,
        )
        assert m["velocity_status"] == "SUSPENDED", (
            f"Aggregate >= 1_500_000 cents must transition to SUSPENDED, "
            f"got {m['velocity_status']!r}"
        )
