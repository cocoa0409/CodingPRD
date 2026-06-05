"""Difficulty Rule 6 — boundary_precision_check.

Two precise boundaries on different metrics:
  (A) risk_points == PROBATION_THRESHOLD == 6 (>= boundary; 5 is GOOD_STANDING).
  (B) PNM party time-conflict at zero-gap adjacency on a half-open interval —
      adjacency at exactly zero gap does NOT collide.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_clock,
    create_chapter,
    create_round,
    register_and_activate_pnm,
    create_and_open_party,
    create_invitation,
    accept_invitation,
    file_risk_incident,
    make_pnm_headers,
    TEST_USERS,
)


class TestRiskPointsAtProbationThreshold:
    """Chapter at 5 risk_points = GOOD_STANDING. Adding 1 more -> 6 = PROBATION.
    Tests the >= boundary on PROBATION_THRESHOLD."""

    def test_chapter_at_5_points_is_good_standing(self, api):
        """PRD §2.8: "if `risk_points` is at least 15, the chapter is `SUSPENDED`; otherwise, if `risk_points` is at least 6, the chapter is on `PROBATION`; otherwise it is in `GOOD_STANDING`. The boundary is inclusive on the lower bound — 6 points is `PROBATION` (not `GOOD_STANDING`), 5 points is `GOOD_STANDING`, 15 points is `SUSPENDED`, 14 points is `PROBATION`."

        Design: Difficulty/boundary_precision_check/bpc_risk_points_ge_probation_threshold
        """
        set_clock("2026-09-01T00:00:00Z")
        ch_n = create_chapter(
            name="Nu",
            greek_type="FRATERNITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        file_risk_incident(
            chapter_id=ch_n["id"], severity_points=5, reason="noise"
        )
        ch_at_5 = validate_success(
            api.get_chapter(ch_n["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert ch_at_5["risk_points"] == 5
        assert ch_at_5["risk_status"] == "GOOD_STANDING"

    def test_chapter_at_6_points_is_probation(self, api):
        """PRD §2.8: "The boundary is inclusive on the lower bound — 6 points is `PROBATION` (not `GOOD_STANDING`), 5 points is `GOOD_STANDING`, 15 points is `SUSPENDED`, 14 points is `PROBATION`."

        Design: Difficulty/boundary_precision_check/bpc_risk_points_ge_probation_threshold
        """
        set_clock("2026-09-01T00:00:00Z")
        ch_n = create_chapter(
            name="Nu2",
            greek_type="FRATERNITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        file_risk_incident(
            chapter_id=ch_n["id"], severity_points=5, reason="noise"
        )
        file_risk_incident(
            chapter_id=ch_n["id"], severity_points=1, reason="boundary push"
        )
        ch_at_6 = validate_success(
            api.get_chapter(ch_n["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert ch_at_6["risk_points"] == 6
        assert ch_at_6["risk_status"] == "PROBATION"


class TestPartyTimeAdjacencyAtZeroGapDoesNotCollide:
    """PNM has ACCEPTED party A (18:00-19:00). Inviting them to party B
    (19:00-20:00) — zero-gap adjacent — must accept successfully because the
    interval is half-open [start, start+duration)."""

    def test_zero_gap_adjacent_accept_succeeds(self, api):
        """PRD §3.3: "the system enforces a no-double-booking rule on the PNM's own schedule: the PNM must not have another `ACCEPTED` `PartyInvitation` whose party's half-open time interval, computed as `scheduled_start_utc` (inclusive) to `scheduled_start_utc` plus `duration_minutes` (exclusive), overlaps the new party's interval. Adjacency at exactly zero gap is allowed; any positive overlap is rejected with `ERR_PARTY_TIME_CONFLICT`."

        Design: Difficulty/boundary_precision_check/bpc_party_time_adjacency_at_zero_gap_does_not_collide
        """
        set_clock("2026-09-01T00:00:00Z")
        ch_o1 = create_chapter(
            name="Xi",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        ch_o2 = create_chapter(
            name="Omicron",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 bpc2")
        o1 = register_and_activate_pnm(full_name="O1", gpa=3.50)
        p_a = create_and_open_party(
            rnd["id"],
            ch_o1["id"],
            scheduled_start_utc="2026-09-05T18:00:00Z",
            duration_minutes=60,
        )
        p_b = create_and_open_party(
            rnd["id"],
            ch_o2["id"],
            scheduled_start_utc="2026-09-05T19:00:00Z",
            duration_minutes=60,
        )
        inv_a = create_invitation(p_a["id"], o1["id"], ch_o1["id"])
        inv_b = create_invitation(p_b["id"], o1["id"], ch_o2["id"])
        accept_invitation(inv_a["id"], o1["id"])
        # Trigger: accept zero-gap-adjacent invitation.
        accepted_b = validate_success(
            api.accept_invitation(inv_b["id"], make_pnm_headers(o1["id"])), 200
        )
        assert accepted_b["rsvp_status"] == "ACCEPTED"

    def test_zero_gap_adjacent_accept_both_parties_show_confirmed_count_one(
        self, api
    ):
        """PRD §3.3: "On a successful accept, the invitation transitions to `ACCEPTED`, the party's `confirmed_count` is incremented by 1, and the party's `version` advances."

        Design: Difficulty/boundary_precision_check/bpc_party_time_adjacency_at_zero_gap_does_not_collide
        """
        set_clock("2026-09-01T00:00:00Z")
        ch_o1 = create_chapter(
            name="Xi2",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        ch_o2 = create_chapter(
            name="Omicron2",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 bpc2b")
        o1 = register_and_activate_pnm(full_name="O1B", gpa=3.50)
        p_a = create_and_open_party(
            rnd["id"],
            ch_o1["id"],
            scheduled_start_utc="2026-09-05T18:00:00Z",
            duration_minutes=60,
        )
        p_b = create_and_open_party(
            rnd["id"],
            ch_o2["id"],
            scheduled_start_utc="2026-09-05T19:00:00Z",
            duration_minutes=60,
        )
        inv_a = create_invitation(p_a["id"], o1["id"], ch_o1["id"])
        inv_b = create_invitation(p_b["id"], o1["id"], ch_o2["id"])
        accept_invitation(inv_a["id"], o1["id"])
        accept_invitation(inv_b["id"], o1["id"])
        p_a_after = validate_success(
            api.get_party(p_a["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        p_b_after = validate_success(
            api.get_party(p_b["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert p_a_after["confirmed_count"] == 1
        assert p_b_after["confirmed_count"] == 1
