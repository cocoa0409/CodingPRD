"""Non-linear state-machine shapes: CompRoomBooking's branching with revert
cycle (PENDING ↔ CONFIRMED), and Member.exclusion_status's cyclic
NOT_EXCLUDED → EXCLUDED → REINSTATED → EXCLUDED."""
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
    self_exclude_member,
    make_loyalty_manager_headers,
    make_member_headers,
    bootstrap_platinum_with_confirmed_booking,
    bootstrap_cyclic_exclusion_setup,
)


class TestCompRoomBookingBranchingWithRevertCycle:
    """PRD §3.6: CONFIRMED → PENDING is permitted before check-in. The same
    booking can then re-CONFIRM, exercising a true cycle inside the
    branching state machine."""

    def test_revert_to_pending_from_confirmed(self, api):
        """PRD §3.6: "A confirmed booking may be reverted back to PENDING
        (transitioning CONFIRMED → PENDING) provided the server's current
        UTC clock is still strictly before the booking's check_in."

        Design: Difficulty/non_linear_state_machine/comp_room_booking_branching_with_revert_cycle
        """
        ctx = bootstrap_platinum_with_confirmed_booking(
            clock="2026-10-01T00:00:00Z",
            check_in="2026-12-01T15:00:00Z",
            check_out="2026-12-02T11:00:00Z",
        )
        resp = api.revert_comp_room_booking_to_pending(
            ctx["booking"]["id"], make_loyalty_manager_headers("lm_1"),
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "PENDING", (
            f"Expected status PENDING after revert, got {data['status']!r}"
        )

    def test_revert_then_reconfirm_completes_the_cycle(self, api):
        """PRD §3.9: "CompRoomBooking: PENDING → CONFIRMED, CONFIRMED →
        CHECKED_IN, CHECKED_IN → COMPLETED, PENDING → CANCELLED, CONFIRMED
        → CANCELLED, CONFIRMED → PENDING."
        PRD §3.6: "A second LoyaltyManager action confirms the booking,
        transitioning it PENDING → CONFIRMED."

        Design: Difficulty/non_linear_state_machine/comp_room_booking_branching_with_revert_cycle
        """
        ctx = bootstrap_platinum_with_confirmed_booking(
            clock="2026-10-01T00:00:00Z",
            check_in="2026-12-01T15:00:00Z",
            check_out="2026-12-02T11:00:00Z",
        )
        # CONFIRMED → PENDING.
        validate_success(
            api.revert_comp_room_booking_to_pending(
                ctx["booking"]["id"], make_loyalty_manager_headers("lm_1"),
            ),
            expected_status=200,
        )
        # PENDING → CONFIRMED again.
        re_confirmed = validate_success(
            api.confirm_comp_room_booking(
                ctx["booking"]["id"], make_loyalty_manager_headers("lm_1"),
            ),
            expected_status=200,
        )
        assert re_confirmed["status"] == "CONFIRMED", (
            f"After revert + re-confirm, status should be CONFIRMED, "
            f"got {re_confirmed['status']!r}"
        )


class TestMemberExclusionStatusCyclic:
    """PRD §3.7: NOT_EXCLUDED → EXCLUDED → REINSTATED → EXCLUDED forms a
    true cycle. A member can self-exclude, reinstate after the period
    elapses, then self-exclude again."""

    def test_first_self_exclusion_transitions_to_excluded(self, api):
        """PRD §3.7: "The server stamps requested_at with the current UTC
        clock. The submission is refused if the member already has an
        ACTIVE SelfExclusion row (state precondition: at most one active
        exclusion at a time) or if the duration from requested_at to
        exclusion_until is less than three hundred and sixty-five days".
        PRD §3.7: "the server transitions the member's exclusion_status
        from NOT_EXCLUDED (or REINSTATED, on a repeat self-exclusion) to
        EXCLUDED".

        Design: Difficulty/non_linear_state_machine/member_exclusion_status_cyclic_excluded_reinstated_excluded
        """
        set_clock("2026-01-01T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="M Cyc", email="mc@x.com",
        )
        se = self_exclude_member(
            member_id=mem["id"],
            exclusion_until="2027-01-02T00:00:00Z",
            reason="first",
        )
        assert se["status"] == "ACTIVE"
        m = validate_success(
            api.get_member(mem["id"], make_loyalty_manager_headers("lm_1")),
            expected_status=200,
        )
        assert m["exclusion_status"] == "EXCLUDED"

    def test_reinstated_member_can_self_exclude_again_cycling_to_excluded(self, api):
        """PRD §3.7: "From REINSTATED the member may self-exclude again
        under the same minimum-period rule, cycling the exclusion-status
        dimension back to EXCLUDED."

        Design: Difficulty/non_linear_state_machine/member_exclusion_status_cyclic_excluded_reinstated_excluded
        """
        ctx = bootstrap_cyclic_exclusion_setup(
            clock_first="2026-01-01T00:00:00Z",
            clock_after_expiry="2027-01-03T00:00:00Z",
            exclusion_until="2027-01-02T00:00:00Z",
        )
        # Member is now REINSTATED. Self-exclude again.
        resp = api.create_self_exclusion(
            {
                "member_id": ctx["member"]["id"],
                "exclusion_until": "2028-01-04T00:00:00Z",
                "reason": "second",
            },
            make_member_headers(ctx["member"]["id"]),
        )
        se2 = validate_success(resp, expected_status=201)
        assert se2["status"] == "ACTIVE"
        m = validate_success(
            api.get_member(
                ctx["member"]["id"], make_loyalty_manager_headers("lm_1"),
            ),
            expected_status=200,
        )
        assert m["exclusion_status"] == "EXCLUDED", (
            f"After REINSTATED→EXCLUDED cycle, exclusion_status should be "
            f"EXCLUDED, got {m['exclusion_status']!r}"
        )
        # And the first SelfExclusion remains REINSTATED.
        first_se = validate_success(
            api.get_self_exclusion(
                ctx["first_self_exclusion"]["id"],
                make_member_headers(ctx["member"]["id"]),
            ),
            expected_status=200,
        )
        assert first_se["status"] == "REINSTATED"
