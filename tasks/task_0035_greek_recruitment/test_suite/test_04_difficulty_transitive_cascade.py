"""Difficulty Rule 4 — transitive_cascade.

Two multi-link cascades:
  (A) round.advance PARTY -> MUTUAL_SELECTION expires party-tied RiskIncidents,
      which recomputes Chapter.risk_points and risk_status (depth-3 cascade).
  (B) PNM.withdraw cascades to invitations (ACCEPTED -> DECLINED), which
      decrements Party.confirmed_count (depth-2 derived recompute).
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
    complete_party,
    advance_round,
    file_risk_incident,
    make_chapter_officer_headers,
    make_pnm_headers,
    TEST_USERS,
)


class TestRoundAdvanceExpiresIncidentsAndRecomputesRiskStatus:
    """Chapter sits at risk_points=6 (PROBATION) from one ACTIVE incident tied
    to a party in the round. Advancing the round expires the incident, which
    triggers risk_points -> 0 and risk_status -> GOOD_STANDING."""

    def test_party_tied_active_incident_transitions_to_expired_on_round_advance(
        self, api
    ):
        """PRD §3.1: "every `ACTIVE` `RiskIncident` whose `party_id` belongs to a party on this round is transitioned to `EXPIRED`, with `Chapter.risk_points` and `Chapter.risk_status` recomputed for each affected chapter and the chapter's `version` advanced"
        PRD §3.8: "An incident may also be retired by the system as `EXPIRED` — but only as a side-effect of the round advancing from `phase` `PARTY` to `phase` `MUTUAL_SELECTION`, and only for incidents whose `party_id` ties them to a party on that round"

        Design: Difficulty/transitive_cascade/tcasc_round_advance_party_to_mutual_expires_risk_recomputes_status_unblocks_chapter
        """
        set_clock("2026-09-01T00:00:00Z")
        ch_h = create_chapter(
            name="Theta",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=20000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 tcasc1")
        party = create_and_open_party(
            rnd["id"], ch_h["id"], scheduled_start_utc="2026-09-05T18:00:00Z"
        )
        complete_party(party["id"], ch_h["id"])
        ri = file_risk_incident(
            chapter_id=ch_h["id"],
            severity_points=6,
            reason="noise complaint",
            party_id=party["id"],
        )
        # Pre-trigger: incident is ACTIVE, chapter on PROBATION.
        ch_pre = validate_success(
            api.get_chapter(ch_h["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert ch_pre["risk_status"] == "PROBATION"
        assert ch_pre["risk_points"] == 6
        # Trigger: advance round.
        advanced = validate_success(
            api.advance_round(rnd["id"], TEST_USERS["recruitment_chair_headers"]),
            200,
        )
        assert advanced["phase"] == "MUTUAL_SELECTION"
        ri_after = validate_success(
            api.get_risk_incident(ri["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert ri_after["status"] == "EXPIRED"

    def test_chapter_risk_status_recomputed_to_good_standing_after_expiry(self, api):
        """PRD §2.8: "Every chapter carries a derived risk posture, `risk_status`, drawn from the enumeration `GOOD_STANDING`, `PROBATION`, and `SUSPENDED`. It is recomputed from the chapter's cumulative `risk_points`, which is itself the sum of `severity_points` taken across that chapter's `RiskIncident` rows whose `status` is `ACTIVE` — incidents whose `status` is `EXPIRED` or `DISMISSED` no longer count."
        PRD §2.8: "if `risk_points` is at least 15, the chapter is `SUSPENDED`; otherwise, if `risk_points` is at least 6, the chapter is on `PROBATION`; otherwise it is in `GOOD_STANDING`."

        Design: Difficulty/transitive_cascade/tcasc_round_advance_party_to_mutual_expires_risk_recomputes_status_unblocks_chapter
        """
        set_clock("2026-09-01T00:00:00Z")
        ch_h = create_chapter(
            name="Theta2",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=20000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 tcasc1b")
        party = create_and_open_party(
            rnd["id"], ch_h["id"], scheduled_start_utc="2026-09-05T18:00:00Z"
        )
        complete_party(party["id"], ch_h["id"])
        file_risk_incident(
            chapter_id=ch_h["id"],
            severity_points=6,
            reason="noise",
            party_id=party["id"],
        )
        advance_round(rnd["id"])
        ch_after = validate_success(
            api.get_chapter(ch_h["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert ch_after["risk_points"] == 0
        assert ch_after["risk_status"] == "GOOD_STANDING"


class TestPnmWithdrawCascadesToInvitationsAndConfirmedCount:
    """Withdraw cascades to invitations (ACCEPTED -> DECLINED), which
    recomputes Party.confirmed_count downward."""

    @staticmethod
    def _setup_two_accepted():
        set_clock("2026-09-01T00:00:00Z")
        ch_j = create_chapter(
            name="Iota",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=20000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 tcasc2")
        y1 = register_and_activate_pnm(full_name="Y1", gpa=3.50)
        pj1 = create_and_open_party(
            rnd["id"],
            ch_j["id"],
            scheduled_start_utc="2026-09-05T18:00:00Z",
        )
        pj2 = create_and_open_party(
            rnd["id"],
            ch_j["id"],
            scheduled_start_utc="2026-09-06T18:00:00Z",
        )
        i1 = create_invitation(pj1["id"], y1["id"], ch_j["id"])
        i2 = create_invitation(pj2["id"], y1["id"], ch_j["id"])
        accept_invitation(i1["id"], y1["id"])
        accept_invitation(i2["id"], y1["id"])
        return ch_j, y1, pj1, pj2, i1, i2

    def test_withdraw_cascades_to_invitations_declined(self, api):
        """PRD §3.1: "A PNM may also voluntarily withdraw at any time while in `ACTIVE` status, which transitions them to `WITHDRAWN` and cascades: every one of that PNM's outstanding `PartyInvitation` rows whose `rsvp_status` is currently `INVITED` or `ACCEPTED` is transitioned to `DECLINED`."

        Design: Difficulty/transitive_cascade/tcasc_pnm_withdraw_cascades_decline_invitations_decrements_party_count
        """
        ch_j, y1, pj1, pj2, i1, i2 = self._setup_two_accepted()
        withdrawn = validate_success(
            api.withdraw_pnm(y1["id"], make_pnm_headers(y1["id"])), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"
        i1_after = validate_success(
            api.get_invitation(i1["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        i2_after = validate_success(
            api.get_invitation(i2["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert i1_after["rsvp_status"] == "DECLINED"
        assert i2_after["rsvp_status"] == "DECLINED"

    def test_party_confirmed_count_decremented_on_each_cascade_decline(self, api):
        """PRD §3.3: "Declining an invitation — from either `INVITED` or `ACCEPTED` — transitions it to `DECLINED`; if it was previously `ACCEPTED`, the party's `confirmed_count` is also decremented by 1."
        PRD §2.10: "Whenever a base row that feeds a derived counter is created or transitioned, the derived counter is recomputed in the same logical operation, and the parent entity's `version` and `updated_at` are advanced."

        Design: Difficulty/transitive_cascade/tcasc_pnm_withdraw_cascades_decline_invitations_decrements_party_count
        """
        ch_j, y1, pj1, pj2, i1, i2 = self._setup_two_accepted()
        api.withdraw_pnm(y1["id"], make_pnm_headers(y1["id"]))
        pj1_after = validate_success(
            api.get_party(pj1["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        pj2_after = validate_success(
            api.get_party(pj2["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert pj1_after["confirmed_count"] == 0
        assert pj2_after["confirmed_count"] == 0
