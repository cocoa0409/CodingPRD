"""Difficulty Rule 8 — resource_temporal_overlap.

Two distinct resources and overlap semantics:
  (A) PNM's accepted-invitation interval set — POINTWISE half-open overlap.
  (B) Party's confirmed-attendance pool — AGGREGATE CAPACITY at boundary.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    set_clock,
    create_chapter,
    create_round,
    register_and_activate_pnm,
    create_and_open_party,
    create_invitation,
    accept_invitation,
    make_pnm_headers,
    ApiErrorId,
    TEST_USERS,
)


class TestPnmInvitationAcceptanceOverlapHalfOpenPointwise:
    """PNM ACCEPTED party A (18:00-19:00). Party B (18:30-19:30) overlaps the
    interior at [18:30, 19:00). Accepting B's invitation must fail with
    ERR_PARTY_TIME_CONFLICT."""

    @staticmethod
    def _setup_overlapping():
        set_clock("2026-09-01T00:00:00Z")
        c1 = create_chapter(
            name="Sigma",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        c2 = create_chapter(
            name="Tau",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 rto1")
        r1 = register_and_activate_pnm(full_name="R1", gpa=3.50)
        pa = create_and_open_party(
            rnd["id"],
            c1["id"],
            scheduled_start_utc="2026-09-05T18:00:00Z",
            duration_minutes=60,
        )
        pb = create_and_open_party(
            rnd["id"],
            c2["id"],
            scheduled_start_utc="2026-09-05T18:30:00Z",
            duration_minutes=60,
        )
        inv_a = create_invitation(pa["id"], r1["id"], c1["id"])
        inv_b = create_invitation(pb["id"], r1["id"], c2["id"])
        accept_invitation(inv_a["id"], r1["id"])
        return c1, c2, rnd, r1, pa, pb, inv_a, inv_b

    def test_overlap_accept_returns_party_time_conflict(self, api):
        """PRD §3.3: "the system enforces a no-double-booking rule on the PNM's own schedule: the PNM must not have another `ACCEPTED` `PartyInvitation` whose party's half-open time interval, computed as `scheduled_start_utc` (inclusive) to `scheduled_start_utc` plus `duration_minutes` (exclusive), overlaps the new party's interval. Adjacency at exactly zero gap is allowed; any positive overlap is rejected with `ERR_PARTY_TIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/rto_pnm_invitation_acceptance_overlap_half_open_pointwise
        """
        c1, c2, rnd, r1, pa, pb, inv_a, inv_b = self._setup_overlapping()
        res = api.accept_invitation(inv_b["id"], make_pnm_headers(r1["id"]))
        validate_error(res, ApiErrorId.ERR_PARTY_TIME_CONFLICT)

    def test_overlap_accept_leaves_invitations_state_unchanged(self, api):
        """PRD §3.3: "Accepting an invitation has four preconditions, evaluated against the live party state."

        Design: Difficulty/resource_temporal_overlap/rto_pnm_invitation_acceptance_overlap_half_open_pointwise
        """
        c1, c2, rnd, r1, pa, pb, inv_a, inv_b = self._setup_overlapping()
        api.accept_invitation(inv_b["id"], make_pnm_headers(r1["id"]))  # expected fail
        inv_a_after = validate_success(
            api.get_invitation(
                inv_a["id"], TEST_USERS["panhellenic_admin_headers"]
            ),
            200,
        )
        inv_b_after = validate_success(
            api.get_invitation(
                inv_b["id"], TEST_USERS["panhellenic_admin_headers"]
            ),
            200,
        )
        assert inv_a_after["rsvp_status"] == "ACCEPTED"
        assert inv_b_after["rsvp_status"] == "INVITED"


class TestPartyCapacityAggregateOverlapAtCapacityBoundary:
    """One OPEN party with capacity=1; S1 fills it; S2 attempts accept and is
    rejected because the party's confirmed_count == capacity precondition fails."""

    @staticmethod
    def _setup_full_party():
        set_clock("2026-09-01T00:00:00Z")
        cu = create_chapter(
            name="Upsilon",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 rto2")
        s1 = register_and_activate_pnm(full_name="S1", gpa=3.50)
        s2 = register_and_activate_pnm(full_name="S2", gpa=3.50)
        pu = create_and_open_party(
            rnd["id"],
            cu["id"],
            scheduled_start_utc="2026-09-05T18:00:00Z",
            duration_minutes=60,
            capacity=1,
        )
        i_s1 = create_invitation(pu["id"], s1["id"], cu["id"])
        i_s2 = create_invitation(pu["id"], s2["id"], cu["id"])
        accept_invitation(i_s1["id"], s1["id"])
        return cu, rnd, s1, s2, pu, i_s1, i_s2

    def test_accept_at_capacity_returns_invalid_state(self, api):
        """PRD §3.3: "Third, the party's `confirmed_count` must be strictly less than its `capacity`."
        PRD §2.7: "then state-machine precondition (`ERR_INVALID_STATE`)"

        Design: Difficulty/resource_temporal_overlap/rto_party_capacity_aggregate_overlap_at_capacity_boundary
        """
        cu, rnd, s1, s2, pu, i_s1, i_s2 = self._setup_full_party()
        res = api.accept_invitation(i_s2["id"], make_pnm_headers(s2["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_accept_leaves_party_at_capacity_with_invited_remaining(self, api):
        """PRD §3.3: "On a successful accept, the invitation transitions to `ACCEPTED`, the party's `confirmed_count` is incremented by 1, and the party's `version` advances."

        Design: Difficulty/resource_temporal_overlap/rto_party_capacity_aggregate_overlap_at_capacity_boundary
        """
        cu, rnd, s1, s2, pu, i_s1, i_s2 = self._setup_full_party()
        api.accept_invitation(i_s2["id"], make_pnm_headers(s2["id"]))  # expected fail
        pu_after = validate_success(
            api.get_party(pu["id"], TEST_USERS["panhellenic_admin_headers"]), 200
        )
        assert pu_after["confirmed_count"] == 1
        assert pu_after["capacity"] == 1
        i_s2_after = validate_success(
            api.get_invitation(
                i_s2["id"], TEST_USERS["panhellenic_admin_headers"]
            ),
            200,
        )
        assert i_s2_after["rsvp_status"] == "INVITED"
