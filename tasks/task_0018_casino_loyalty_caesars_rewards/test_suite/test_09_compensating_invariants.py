"""Compensating-action invariants: AnnualResetRun preserves the
SUM(Member.tier_credits_lifetime) invariant, and HostAssignment.revoke
restores the assigned_host_id pointer-consistency invariant."""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    set_clock,
    create_property,
    create_member,
    record_gaming_session,
    schedule_annual_reset,
    make_loyalty_manager_headers,
    make_compliance_officer_headers,
    bootstrap_member_with_active_host_assignment,
    assert_lifetime_invariant_preserved,
)


class TestAnnualResetPreservesLifetimeInvariant:
    """PRD §3.8: lifetime totals are never reset. /execute captures
    sum(Member.tier_credits_lifetime) before and after — the two values
    must match, proving the compensating action only zeros ytd."""

    def test_two_member_lifetime_sum_preserved_across_execute(self, api):
        """PRD §3.8: "Lifetime totals are never reset — the before-and-after
        invariant exists precisely so that the system can prove this — and
        excluded members are deliberately left out of the reset, preserving
        their state for post-reinstatement audit."

        Design: Difficulty/compensating_invariant/annual_reset_preserves_tier_credits_lifetime_total_invariant
        """
        set_clock("2027-11-01T00:00:00Z")
        prop = create_property()
        ma = create_member(
            property_id=prop["id"], full_name="M Inv A", email="minva@x.com",
        )
        mb = create_member(
            property_id=prop["id"], full_name="M Inv B", email="minvb@x.com",
        )
        # Member A: SLOTS at GOLD, $20000 loss → 20000 TC lifetime.
        record_gaming_session(
            member_id=ma["id"], property_id=prop["id"],
            started_at="2027-11-01T01:00:00Z",
            ended_at="2027-11-01T02:00:00Z",
            game_type="SLOTS", theoretical_loss_cents=2_000_000,
        )
        # Member B: SLOTS at GOLD, $30000 loss → 30000 TC lifetime.
        record_gaming_session(
            member_id=mb["id"], property_id=prop["id"],
            started_at="2027-11-01T03:00:00Z",
            ended_at="2027-11-01T04:00:00Z",
            game_type="SLOTS", theoretical_loss_cents=3_000_000,
        )
        ar = schedule_annual_reset(reset_year=2027,
                                   scheduled_for="2028-01-01T00:00:00Z")
        set_clock("2028-01-01T01:00:00Z")
        resp = api.execute_annual_reset_run(
            ar["id"], make_compliance_officer_headers("co_1"),
        )
        data = validate_success(resp, expected_status=200)
        # PRD §3.8 does not uniquely fix the units of
        # `tier_credits_lifetime_invariant_before_cents` / `..._after_cents`:
        # the prose says "sum of tier_credits_lifetime" (a Tier-Credit value)
        # while the field name is suffixed `_cents`. A PRD-faithful reader
        # could store either the TC sum directly or its cents-equivalent.
        # We therefore assert only the rule that PRD verbatim guarantees —
        # the before-and-after invariant — and not a specific unit choice.
        assert_lifetime_invariant_preserved(data)
        assert data["members_reset_count"] == 2

    def test_two_member_ytd_zeroed_and_tier_demoted_to_gold(self, api):
        """PRD §3.8: "for every member whose exclusion_status is not
        EXCLUDED, resets tier_credits_ytd to zero and sets tier_status to
        GOLD (every such member's version is incremented)".

        Design: Difficulty/compensating_invariant/annual_reset_preserves_tier_credits_lifetime_total_invariant
        """
        set_clock("2027-11-01T00:00:00Z")
        prop = create_property()
        ma = create_member(
            property_id=prop["id"], full_name="M Inv A",
            email="minva_2@x.com",
        )
        mb = create_member(
            property_id=prop["id"], full_name="M Inv B",
            email="minvb_2@x.com",
        )
        record_gaming_session(
            member_id=ma["id"], property_id=prop["id"],
            started_at="2027-11-01T01:00:00Z",
            ended_at="2027-11-01T02:00:00Z",
            game_type="SLOTS", theoretical_loss_cents=2_000_000,
        )
        record_gaming_session(
            member_id=mb["id"], property_id=prop["id"],
            started_at="2027-11-01T03:00:00Z",
            ended_at="2027-11-01T04:00:00Z",
            game_type="SLOTS", theoretical_loss_cents=3_000_000,
        )
        ar = schedule_annual_reset(reset_year=2027,
                                   scheduled_for="2028-01-01T00:00:00Z")
        set_clock("2028-01-01T01:00:00Z")
        validate_success(
            api.execute_annual_reset_run(
                ar["id"], make_compliance_officer_headers("co_1"),
            ),
            expected_status=200,
        )
        ma_after = validate_success(
            api.get_member(ma["id"], make_loyalty_manager_headers("lm_1")),
            expected_status=200,
        )
        mb_after = validate_success(
            api.get_member(mb["id"], make_loyalty_manager_headers("lm_1")),
            expected_status=200,
        )
        assert ma_after["tier_credits_ytd"] == pytest.approx(0, abs=0.01)
        assert ma_after["tier_credits_lifetime"] == pytest.approx(
            20000.00, abs=0.01,
        )
        assert ma_after["tier_status"] == "GOLD"
        assert mb_after["tier_credits_ytd"] == pytest.approx(0, abs=0.01)
        assert mb_after["tier_credits_lifetime"] == pytest.approx(
            30000.00, abs=0.01,
        )
        assert mb_after["tier_status"] == "GOLD"


class TestHostAssignmentRevokePointerConsistency:
    """PRD §3.5: after /revoke on an ACTIVE HostAssignment, the
    Member.assigned_host_id pointer integrity invariant must hold —
    pointer is null AND there is no other ACTIVE HostAssignment for the
    member."""

    def test_revoke_active_clears_assigned_host_id(self, api):
        """PRD §3.5: "An ACTIVE assignment can later be revoked, either by
        a LoyaltyManager or a ComplianceOfficer, transitioning the
        assignment ACTIVE → REVOKED and, because this was the member's
        active assignment, clearing assigned_host_id back to null and
        incrementing the member's version."

        Design: Difficulty/compensating_invariant/host_assignment_revoke_pointer_consistency_invariant
        """
        ctx = bootstrap_member_with_active_host_assignment(
            clock="2026-07-01T00:00:00Z",
        )
        assert ctx["member"]["assigned_host_id"] == ctx["host"]["id"]
        resp = api.revoke_host_assignment(
            ctx["host_assignment"]["id"],
            make_loyalty_manager_headers(ctx["alice_id"]),
        )
        ha = validate_success(resp, expected_status=200)
        assert ha["status"] == "REVOKED"
        m = validate_success(
            api.get_member(
                ctx["member"]["id"],
                make_loyalty_manager_headers(ctx["alice_id"]),
            ),
            expected_status=200,
        )
        assert m["assigned_host_id"] is None, (
            f"After revoke of the active assignment, assigned_host_id must be "
            f"null, got {m['assigned_host_id']!r}"
        )

    def test_no_other_active_host_assignment_remains_for_member(self, api):
        """PRD §3.5: "An ACTIVE assignment can later be revoked, either by
        a LoyaltyManager or a ComplianceOfficer, transitioning the
        assignment ACTIVE → REVOKED".

        After revoke, the listing of HostAssignments filtered by member_id
        and status=ACTIVE must be empty.

        Design: Difficulty/compensating_invariant/host_assignment_revoke_pointer_consistency_invariant
        """
        ctx = bootstrap_member_with_active_host_assignment(
            clock="2026-07-15T00:00:00Z",
        )
        validate_success(
            api.revoke_host_assignment(
                ctx["host_assignment"]["id"],
                make_loyalty_manager_headers(ctx["alice_id"]),
            ),
            expected_status=200,
        )
        resp = api.list_host_assignments(
            make_loyalty_manager_headers(ctx["alice_id"]),
            params={"member_id": ctx["member"]["id"], "status": "ACTIVE"},
        )
        items, meta = validate_paginated(resp)
        # Empty ACTIVE-list verifies the pointer-integrity invariant.
        assert meta["total_count"] == 0, (
            f"After revoke, no ACTIVE HostAssignment must remain for the "
            f"member; total_count = {meta['total_count']}"
        )
        assert items == []
