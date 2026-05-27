"""Endpoint corners: side-effect execution, FK reverse-reachability
filters on listing endpoints."""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    set_clock,
    create_property,
    create_member,
    record_gaming_session,
    make_loyalty_manager_headers,
    make_member_services_headers,
    bootstrap_member_with_active_host_assignment,
)


class TestGamingSessionSideEffectOnMember:
    """PRD §3.3: POST /gaming-sessions's accrual side effect updates
    Member.tier_credits_ytd and Member.tier_credits_lifetime."""

    def test_create_session_updates_member_ytd_and_lifetime(self, api):
        """PRD §3.3: "The same value is then added to the member's
        tier_credits_ytd (year-to-date) and to the member's
        tier_credits_lifetime (which never resets)."

        Calculation: SLOTS at GOLD, $1000 loss → 1000 TC; both ytd and
        lifetime become 1000.

        Design: Corner/endpoints/gaming_session_create_runs_tier_credit_accrual_side_effect
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="SE", email="se2@x.com",
        )
        resp = api.create_gaming_session(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "started_at": "2026-02-01T10:00:00Z",
                "ended_at": "2026-02-01T11:00:00Z",
                "game_type": "SLOTS",
                "theoretical_loss_cents": 100000,
            },
            make_member_services_headers("ms_1"),
        )
        sess = validate_success(resp, expected_status=201)
        assert sess["tier_credits_earned"] == pytest.approx(1000.00, abs=0.01)
        m = validate_success(
            api.get_member(mem["id"], make_loyalty_manager_headers("lm_1")),
            expected_status=200,
        )
        assert m["tier_credits_ytd"] == pytest.approx(1000.00, abs=0.01)
        assert m["tier_credits_lifetime"] == pytest.approx(1000.00, abs=0.01)


class TestHostAssignmentsListByMemberId:
    """PRD: GET /host-assignments?member_id=... filters by member."""

    def test_list_host_assignments_filtered_by_member_returns_only_that_member(
        self, api,
    ):
        """PRD §3.5: "Host assignments are inspectable individually and
        through a paginated list filterable by member_id, host_id, and
        status."

        Design: Corner/endpoints/host_assignments_list_filtered_by_member_id
        """
        ctx = bootstrap_member_with_active_host_assignment(
            clock="2026-02-01T00:00:00Z",
        )
        resp = api.list_host_assignments(
            make_loyalty_manager_headers(ctx["alice_id"]),
            params={"member_id": ctx["member"]["id"]},
        )
        items, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, (
            f"Expected 1 assignment for member, got {meta['total_count']}"
        )
