"""Difficulty Rule 5 — priority_pair_validation_conflict.

Both instances rely on the PRD §2.7 priority order being explicitly stated.
  (A) State (ERR_INVALID_STATE) vs business-temporal (ERR_PARTY_TIME_CONFLICT):
      decline-then-accept on an already-DECLINED invitation surfaces the state
      error, not the time-conflict error.
  (B) Business-safety (ERR_CHAPTER_SUSPENDED) vs business-fiscal
      (ERR_CHAPTER_QUOTA_FULL): the safety gate wins.
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
    decline_invitation,
    complete_party,
    advance_round,
    file_pnm_preference,
    file_chapter_preference,
    file_risk_incident,
    list_pnm_bid_matches,
    create_bid_match_payload,
    make_chapter_officer_headers,
    make_pnm_headers,
    ApiErrorId,
    TEST_USERS,
)


class TestStateVsBusinessTemporalAcceptDeclinedInvitationWithTimeConflict:
    """PNM has ACCEPTED a party A and DECLINED an invitation to overlapping
    party B. A re-accept on B's DECLINED invitation has two simultaneous
    failures: state (priority 5) and time conflict (priority 8). Per PRD §2.7
    state precedes business-temporal."""

    def test_re_accept_on_declined_invitation_returns_invalid_state(self, api):
        """PRD §2.7: "then state-machine precondition (`ERR_INVALID_STATE`), then optimistic-concurrency match (`ERR_STALE_VERSION`), then the chapter-suspension safety gate (`ERR_CHAPTER_SUSPENDED`), then domain-temporal conflicts (`ERR_PARTY_TIME_CONFLICT` on invitation accept, `ERR_CHAPTER_DOUBLE_BOOK` on party create)"
        PRD §3.3: "From `INVITED`, the acting PNM may either accept or decline; the chapter cannot accept on the PNM's behalf."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_state_vs_business_temporal_accept_already_declined_with_time_conflict
        """
        set_clock("2026-09-01T00:00:00Z")
        ch_k1 = create_chapter(
            name="Kappa",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        ch_k2 = create_chapter(
            name="Lambda",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 ppvc1")
        z1 = register_and_activate_pnm(full_name="Z1", gpa=3.50)
        # Two overlapping parties on different chapters.
        pa = create_and_open_party(
            rnd["id"],
            ch_k1["id"],
            scheduled_start_utc="2026-09-05T18:00:00Z",
            duration_minutes=60,
        )
        pb = create_and_open_party(
            rnd["id"],
            ch_k2["id"],
            scheduled_start_utc="2026-09-05T18:30:00Z",
            duration_minutes=60,
        )
        inv_a = create_invitation(pa["id"], z1["id"], ch_k1["id"])
        inv_b = create_invitation(pb["id"], z1["id"], ch_k2["id"])
        accept_invitation(inv_a["id"], z1["id"])
        decline_invitation(inv_b["id"], z1["id"])
        # Trigger: try to accept the already-DECLINED inv_b.
        res = api.accept_invitation(inv_b["id"], make_pnm_headers(z1["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_declined_invitation_remains_declined_after_failed_accept(self, api):
        """PRD §3.3: "Declining an invitation — from either `INVITED` or `ACCEPTED` — transitions it to `DECLINED`"
        PRD §2.7: "When multiple validation conditions could apply to a single request, they are evaluated in a fixed order so that the response code identifies the first failure deterministically"

        Design: Difficulty/priority_pair_validation_conflict/ppvc_state_vs_business_temporal_accept_already_declined_with_time_conflict
        """
        set_clock("2026-09-01T00:00:00Z")
        ch_k1 = create_chapter(
            name="Kappa2",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        ch_k2 = create_chapter(
            name="Lambda2",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 ppvc1b")
        z1 = register_and_activate_pnm(full_name="Z1B", gpa=3.50)
        pa = create_and_open_party(
            rnd["id"],
            ch_k1["id"],
            scheduled_start_utc="2026-09-05T18:00:00Z",
            duration_minutes=60,
        )
        pb = create_and_open_party(
            rnd["id"],
            ch_k2["id"],
            scheduled_start_utc="2026-09-05T18:30:00Z",
            duration_minutes=60,
        )
        inv_a = create_invitation(pa["id"], z1["id"], ch_k1["id"])
        inv_b = create_invitation(pb["id"], z1["id"], ch_k2["id"])
        accept_invitation(inv_a["id"], z1["id"])
        decline_invitation(inv_b["id"], z1["id"])
        api.accept_invitation(inv_b["id"], make_pnm_headers(z1["id"]))  # expected to fail
        inv_b_after = validate_success(
            api.get_invitation(
                inv_b["id"], TEST_USERS["panhellenic_admin_headers"]
            ),
            200,
        )
        assert inv_b_after["rsvp_status"] == "DECLINED"


class TestBusinessSafetyVsBusinessFiscalSuspendedChapterWithQuotaFull:
    """Chapter at quota_total=1 with pledged_count=1 AND risk_status=SUSPENDED.
    Manual bid attempt has BOTH gates failing; safety wins per PRD §2.7."""

    @staticmethod
    def _setup_suspended_at_quota():
        set_clock("2026-09-01T00:00:00Z")
        ch_m = create_chapter(
            name="Mu",
            greek_type="SORORITY",
            quota_total=1,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 ppvc2")
        n1 = register_and_activate_pnm(full_name="N1", gpa=3.50)
        n2 = register_and_activate_pnm(full_name="N2", gpa=3.50)
        party = create_and_open_party(
            rnd["id"], ch_m["id"], scheduled_start_utc="2026-09-05T18:00:00Z"
        )
        inv_n1 = create_invitation(party["id"], n1["id"], ch_m["id"])
        inv_n2 = create_invitation(party["id"], n2["id"], ch_m["id"])
        accept_invitation(inv_n1["id"], n1["id"])
        accept_invitation(inv_n2["id"], n2["id"])
        complete_party(party["id"], ch_m["id"])
        advance_round(rnd["id"])  # PARTY -> MUTUAL_SELECTION
        file_pnm_preference(rnd["id"], n1["id"], ch_m["id"], rank=1)
        file_chapter_preference(rnd["id"], ch_m["id"], n1["id"], rank=1)
        advance_round(rnd["id"])  # MUTUAL_SELECTION -> BID_DAY
        # N1 accepts the matched bid -> Chapter at pledged_count=1=quota_total.
        bids_n1 = list_pnm_bid_matches(n1["id"])
        get_success_data(
            api_client.accept_bid_match(bids_n1[0]["id"], make_pnm_headers(n1["id"]))
        )
        # Then push chapter to SUSPENDED via risk_points >= 15.
        file_risk_incident(chapter_id=ch_m["id"], severity_points=10, reason="hazing")
        file_risk_incident(
            chapter_id=ch_m["id"], severity_points=5, reason="underage drinking"
        )
        ch_after = get_success_data(
            api_client.get_chapter(
                ch_m["id"], TEST_USERS["panhellenic_admin_headers"]
            )
        )
        return ch_m, rnd, n2, ch_after["version"]

    def test_manual_bid_against_suspended_full_chapter_returns_chapter_suspended(
        self, api
    ):
        """PRD §2.7: "then the chapter-suspension safety gate (`ERR_CHAPTER_SUSPENDED`), then domain-temporal conflicts (`ERR_PARTY_TIME_CONFLICT` on invitation accept, `ERR_CHAPTER_DOUBLE_BOOK` on party create), then preference eligibility (`ERR_PREFERENCE_NOT_ELIGIBLE`), then preference-rank uniqueness (`ERR_PREFERENCE_RANK_TAKEN`), then round-phase gating (`ERR_ROUND_PHASE_MISMATCH`), then chapter quota fullness (`ERR_CHAPTER_QUOTA_FULL`)"
        PRD §2.7: "the safety gate dominates every fiscal gate that follows it."

        Design: Difficulty/priority_pair_validation_conflict/ppvc_business_safety_vs_business_fiscal_suspended_chapter_with_quota_full
        """
        ch_m, rnd, n2, ch_version = self._setup_suspended_at_quota()
        payload = create_bid_match_payload(
            round_id=rnd["id"],
            chapter_id=ch_m["id"],
            pnm_id=n2["id"],
            expected_chapter_version=ch_version,
        )
        res = api.create_bid_match(payload, make_chapter_officer_headers(ch_m["id"]))
        validate_error(res, ApiErrorId.ERR_CHAPTER_SUSPENDED)

    def test_both_violations_present_at_call_time(self, api):
        """PRD §2.8: "if `risk_points` is at least 15, the chapter is `SUSPENDED`"
        PRD §3.5: "`Chapter.pledged_count` plus 1 must be at most `Chapter.quota_total` (else `ERR_CHAPTER_QUOTA_FULL`)"

        Design: Difficulty/priority_pair_validation_conflict/ppvc_business_safety_vs_business_fiscal_suspended_chapter_with_quota_full
        """
        ch_m, rnd, n2, ch_version = self._setup_suspended_at_quota()
        ch_now = validate_success(
            api.get_chapter(ch_m["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        # Both gates are independently active at the moment the bid is attempted.
        assert ch_now["risk_status"] == "SUSPENDED"
        assert ch_now["pledged_count"] == ch_now["quota_total"]
