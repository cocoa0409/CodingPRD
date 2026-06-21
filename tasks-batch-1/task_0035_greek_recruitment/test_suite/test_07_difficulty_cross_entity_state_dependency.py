"""Difficulty Rule 7 — cross_entity_state_dependency.

Two cross-entity precondition pairs:
  (A) Party valid create requires Chapter.risk_status != SUSPENDED.
  (B) Manual bid create requires RecruitmentRound.phase == BID_DAY.
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
    complete_party,
    advance_round,
    file_risk_incident,
    file_pnm_preference,
    file_chapter_preference,
    create_party_payload,
    create_bid_match_payload,
    make_chapter_officer_headers,
    ApiErrorId,
    TEST_USERS,
)


class TestPartyCreateRequiresChapterNotSuspended:
    """A SUSPENDED chapter cannot host a new party."""

    @staticmethod
    def _setup_suspended():
        set_clock("2026-09-01T00:00:00Z")
        ch_p = create_chapter(
            name="Pi",
            greek_type="FRATERNITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 cesd1")
        file_risk_incident(chapter_id=ch_p["id"], severity_points=10, reason="violation")
        file_risk_incident(chapter_id=ch_p["id"], severity_points=5, reason="violation")
        return ch_p, rnd

    def test_post_party_against_suspended_chapter_returns_chapter_suspended(
        self, api
    ):
        """PRD §3.2: "The hosting chapter must not be `SUSPENDED`: if `risk_status` is `SUSPENDED`, the request is rejected with `ERR_CHAPTER_SUSPENDED`."
        PRD §2.8: "A `SUSPENDED` chapter is barred from two operations: scheduling a new party and producing a new bid. Both rejections use `ERR_CHAPTER_SUSPENDED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/cesd_party_create_requires_chapter_not_suspended
        """
        ch_p, rnd = self._setup_suspended()
        payload = create_party_payload(
            round_id=rnd["id"],
            chapter_id=ch_p["id"],
            scheduled_start_utc="2026-09-05T18:00:00Z",
            duration_minutes=60,
            capacity=10,
        )
        res = api.create_party(payload, make_chapter_officer_headers(ch_p["id"]))
        validate_error(res, ApiErrorId.ERR_CHAPTER_SUSPENDED)

    def test_chapter_at_suspended_after_15_points(self, api):
        """PRD §2.8: "if `risk_points` is at least 15, the chapter is `SUSPENDED`; otherwise, if `risk_points` is at least 6, the chapter is on `PROBATION`; otherwise it is in `GOOD_STANDING`."

        Design: Difficulty/cross_entity_state_dependency/cesd_party_create_requires_chapter_not_suspended
        """
        ch_p, rnd = self._setup_suspended()
        ch_now = validate_success(
            api.get_chapter(ch_p["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert ch_now["risk_points"] == 15
        assert ch_now["risk_status"] == "SUSPENDED"


class TestManualBidRequiresRoundInBidDayPhase:
    """A manual POST /bid-matches while the round is in MUTUAL_SELECTION must
    be rejected with ERR_ROUND_PHASE_MISMATCH."""

    @staticmethod
    def _setup_mutual_selection_only():
        set_clock("2026-09-01T00:00:00Z")
        ch_q = create_chapter(
            name="Rho",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 cesd2")
        qx = register_and_activate_pnm(full_name="Qx", gpa=3.50)
        party = create_and_open_party(
            rnd["id"], ch_q["id"], scheduled_start_utc="2026-09-05T18:00:00Z"
        )
        inv_qx = create_invitation(party["id"], qx["id"], ch_q["id"])
        accept_invitation(inv_qx["id"], qx["id"])
        complete_party(party["id"], ch_q["id"])
        advance_round(rnd["id"])  # PARTY -> MUTUAL_SELECTION
        ch_now = get_success_data(
            api_client.get_chapter(
                ch_q["id"], TEST_USERS["panhellenic_admin_headers"]
            )
        )
        return ch_q, rnd, qx, ch_now["version"]

    def test_manual_bid_in_mutual_selection_returns_round_phase_mismatch(self, api):
        """PRD §3.5: "the round must be in `phase` `BID_DAY` (else `ERR_ROUND_PHASE_MISMATCH`)"

        Design: Difficulty/cross_entity_state_dependency/cesd_bid_accept_requires_round_in_bid_day_phase
        """
        ch_q, rnd, qx, ch_version = self._setup_mutual_selection_only()
        payload = create_bid_match_payload(
            round_id=rnd["id"],
            chapter_id=ch_q["id"],
            pnm_id=qx["id"],
            expected_chapter_version=ch_version,
        )
        res = api.create_bid_match(payload, make_chapter_officer_headers(ch_q["id"]))
        validate_error(res, ApiErrorId.ERR_ROUND_PHASE_MISMATCH)

    def test_round_phase_remains_mutual_selection_after_failed_manual_bid(self, api):
        """PRD §3.1: "A new round opens in `phase` `PARTY` and walks forward through `MUTUAL_SELECTION`, `BID_DAY`, and finally the terminal `CLOSED` state in strictly linear order. Advancement is the responsibility of the `RecruitmentChair`."

        Design: Difficulty/cross_entity_state_dependency/cesd_bid_accept_requires_round_in_bid_day_phase
        """
        ch_q, rnd, qx, ch_version = self._setup_mutual_selection_only()
        payload = create_bid_match_payload(
            round_id=rnd["id"],
            chapter_id=ch_q["id"],
            pnm_id=qx["id"],
            expected_chapter_version=ch_version,
        )
        api.create_bid_match(payload, make_chapter_officer_headers(ch_q["id"]))
        rnd_after = validate_success(
            api.get_round(rnd["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert rnd_after["phase"] == "MUTUAL_SELECTION"
