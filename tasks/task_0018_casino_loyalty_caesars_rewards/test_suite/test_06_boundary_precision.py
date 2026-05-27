"""Boundary-precision checks: velocity FLAG threshold at exactly 500_000
cents and AnnualResetRun execute with zero eligible members (empty-set
edge)."""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    create_property,
    create_member,
    record_gaming_session,
    self_exclude_member,
    schedule_annual_reset,
    make_loyalty_manager_headers,
    make_compliance_officer_headers,
    bootstrap_due_annual_reset_with_only_excluded_member,
    assert_lifetime_invariant_preserved,
)


class TestVelocityThresholdExactly500000CentsFlags:
    """PRD §3.4: "a total that is greater than or equal to ... five hundred
    thousand cents (five thousand US dollars) but below the suspend
    threshold creates a VelocityAlert with severity FLAGGED. A total of
    exactly five hundred thousand cents trips FLAGGED, not NORMAL." """

    def test_exact_500000_cents_single_session_trips_flagged(self, api):
        """PRD §3.4: "A total of exactly five hundred thousand cents trips
        FLAGGED, not NORMAL."

        Design: Difficulty/boundary_precision_check/velocity_threshold_exact_500000_cents_triggers_flagged
        """
        set_clock("2026-05-01T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="M Bd", email="mbd@x.com",
        )
        # Single session at exactly 500_000 cents within a fresh 60-min
        # window: sum = 500_000 → FLAGGED.
        record_gaming_session(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-05-01T10:00:00Z",
            ended_at="2026-05-01T10:30:00Z",
            game_type="SLOTS", theoretical_loss_cents=500_000,
        )
        m = validate_success(
            api.get_member(mem["id"], make_loyalty_manager_headers("lm_1")),
            expected_status=200,
        )
        assert m["velocity_status"] == "FLAGGED", (
            f"Exactly 500_000 cents must trip FLAGGED, "
            f"got velocity_status={m['velocity_status']!r}"
        )

    def test_just_below_threshold_stays_normal(self, api):
        """PRD §3.4: "a total that is greater than or equal to ... five
        hundred thousand cents (five thousand US dollars) but below the
        suspend threshold creates a VelocityAlert with severity FLAGGED."

        Below 500_000 must NOT trip FLAGGED — the gate is ">=".

        Design: Difficulty/boundary_precision_check/velocity_threshold_exact_500000_cents_triggers_flagged
        """
        set_clock("2026-05-02T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="M BdLow", email="mbdlow@x.com",
        )
        record_gaming_session(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-05-02T10:00:00Z",
            ended_at="2026-05-02T10:30:00Z",
            game_type="SLOTS", theoretical_loss_cents=499_999,
        )
        m = validate_success(
            api.get_member(mem["id"], make_loyalty_manager_headers("lm_1")),
            expected_status=200,
        )
        assert m["velocity_status"] == "NORMAL", (
            f"499_999 cents must stay NORMAL (just below FLAG threshold), "
            f"got velocity_status={m['velocity_status']!r}"
        )


class TestAnnualResetEmptyEligibleSet:
    """PRD §3.8: /execute resets only members whose exclusion_status is not
    EXCLUDED. When the eligible set is empty, the run still completes
    successfully — members_reset_count is 0, and the invariant capture is
    zero on both sides."""

    def test_execute_with_only_excluded_member_yields_zero_reset_count(
        self, api,
    ):
        """PRD §3.8: "On execution, the server captures
        tier_credits_lifetime_invariant_before_cents as the sum of
        tier_credits_lifetime across every Member; then, for every member
        whose exclusion_status is not EXCLUDED, resets tier_credits_ytd to
        zero and sets tier_status to GOLD ...; counts those members into
        members_reset_count; captures
        tier_credits_lifetime_invariant_after_cents as the post-reset sum
        of tier_credits_lifetime; transitions the run SCHEDULED →
        EXECUTED".

        Design: Difficulty/boundary_precision_check/annual_reset_zero_eligible_members_empty_collection_edge
        """
        ctx = bootstrap_due_annual_reset_with_only_excluded_member(
            clock_before_scheduled="2027-12-01T00:00:00Z",
            reset_year=2027,
            scheduled_for="2028-01-01T00:00:00Z",
            clock_after_scheduled="2028-01-01T01:00:00Z",
            exclusion_until="2029-12-02T00:00:00Z",
        )
        resp = api.execute_annual_reset_run(
            ctx["annual_reset_run"]["id"],
            make_compliance_officer_headers("co_1"),
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "EXECUTED"
        assert data["members_reset_count"] == 0, (
            f"Expected 0 reset (only member is EXCLUDED), "
            f"got {data['members_reset_count']}"
        )

    def test_execute_with_only_excluded_member_preserves_lifetime_invariant(
        self, api,
    ):
        """PRD §3.8: "Lifetime totals are never reset — the before-and-after
        invariant exists precisely so that the system can prove this — and
        excluded members are deliberately left out of the reset, preserving
        their state for post-reinstatement audit."

        Design: Difficulty/boundary_precision_check/annual_reset_zero_eligible_members_empty_collection_edge
        """
        ctx = bootstrap_due_annual_reset_with_only_excluded_member(
            clock_before_scheduled="2027-12-01T00:00:00Z",
            reset_year=2027,
            scheduled_for="2028-01-01T00:00:00Z",
            clock_after_scheduled="2028-01-01T01:00:00Z",
            exclusion_until="2029-12-02T00:00:00Z",
        )
        resp = api.execute_annual_reset_run(
            ctx["annual_reset_run"]["id"],
            make_compliance_officer_headers("co_1"),
        )
        data = validate_success(resp, expected_status=200)
        # Only an EXCLUDED member exists, and that member never recorded
        # any sessions — sum(lifetime) is 0 on both sides.
        assert data["tier_credits_lifetime_invariant_before_cents"] == 0
        assert data["tier_credits_lifetime_invariant_after_cents"] == 0
        assert_lifetime_invariant_preserved(data)
        # Member's exclusion_status is unchanged by /execute.
        m = validate_success(
            api.get_member(
                ctx["member"]["id"], make_loyalty_manager_headers("lm_1"),
            ),
            expected_status=200,
        )
        assert m["exclusion_status"] == "EXCLUDED"
