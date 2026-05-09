"""Result submission, cross-verification, score validity, and disputes
(PRD §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_seconds,
    advance_clock,
    assert_dispute,
    assert_match,
    assert_result_entry,
    create_referee,
    event_in_progress,
    file_dispute,
    find_audit_logs,
    list_audit_logs,
    list_matches,
    list_rankings,
    lock_match,
    make_referee_headers,
    make_participant_headers,
    resolve_dispute_uphold,
    resolve_dispute_reject,
    submit_result_payload,
    validate_error,
    validate_success,
    assign_head_referee,
    assign_assistant_referee,
    api_client,
)


def _live_round1_match(event):
    matches = [m for m in list_matches(event["id"])
               if m["round_index"] == 1 and m["status"] != "BYE"
               and m.get("home_participant_id") and m.get("away_participant_id")]
    assert matches, "Setup failed: no live round-1 match"
    return matches[0]


# ===========================================================================
# 3.4 — First REFEREE_SUBMISSION transitions match to RESULT_PENDING
# ===========================================================================
class TestFirstSubmission:
    def test_first_submission_flips_to_result_pending(self, api):
        """PRD §3.4: 'The first valid REFEREE_SUBMISSION flips the match
        from SCHEDULED to RESULT_PENDING and persists the entry.'"""
        event, _, _ = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = _live_round1_match(event)
        # Match was assigned a HEAD referee in event_in_progress; we add
        # an ASSISTANT here so we have a distinct second submitter for
        # later tests, and use the HEAD for the first submission.
        # Locate the existing HEAD assignment via /audit-logs is unreliable;
        # instead create our own crew and re-assign.
        head = create_referee(country_code="GR", team_affiliation=None,
                               qualifications=[event["event_type"]])
        head_asg = assign_head_referee(match["id"], head["id"])
        advance_clock(add_seconds(match["scheduled_end_at"], 1))
        res = api.submit_result(
            match["id"],
            submit_result_payload(
                submitted_by_assignment_id=head_asg["id"],
                home_score=2,
                away_score=1,
            ),
            make_referee_headers(head["id"]),
        )
        entry = validate_success(res, expected_status=201)
        assert_result_entry(entry)
        assert entry["kind"] == "REFEREE_SUBMISSION"
        # Match must now be RESULT_PENDING.
        from test_helpers import get_match
        m_after = get_match(event["id"], match["id"])
        assert m_after["status"] == "RESULT_PENDING"


# ===========================================================================
# 3.4 — Cross-verification: duplicate referee, then disagreement
# ===========================================================================
class TestCrossVerification:
    def test_same_referee_second_submission_rejects_duplicate(self, api):
        """PRD §3.4: 'first, the cross-verifying referee must be a distinct
        person from the first submitter — the second entry's
        RefereeAssignment.referee_id cannot equal the first entry's
        referee, and a violation is rejected with
        ERR_DUPLICATE_REFEREE_ENTRY.'

        PRD §2.13 also confirms that 'the same referee submitting a
        non-matching second entry receives ERR_DUPLICATE_REFEREE_ENTRY,
        not ERR_RESULT_DISAGREEMENT.'"""
        event, _, _ = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = _live_round1_match(event)
        head = create_referee(country_code="GR", team_affiliation=None,
                               qualifications=[event["event_type"]])
        # Two assignments referencing the SAME referee id (different roles):
        head_asg = assign_head_referee(match["id"], head["id"])
        asst_asg = assign_assistant_referee(match["id"], head["id"])
        advance_clock(add_seconds(match["scheduled_end_at"], 1))
        # First submission via head_asg.
        first = api.submit_result(
            match["id"],
            submit_result_payload(
                submitted_by_assignment_id=head_asg["id"],
                home_score=2, away_score=1,
            ),
            make_referee_headers(head["id"]),
        )
        validate_success(first, expected_status=201)
        # Second submission, same referee, different scores → DUPLICATE,
        # not DISAGREEMENT (PRD §2.12 priority 7 / §2.13).
        second = api.submit_result(
            match["id"],
            submit_result_payload(
                submitted_by_assignment_id=asst_asg["id"],
                home_score=3, away_score=2,
            ),
            make_referee_headers(head["id"]),
        )
        validate_error(second, "ERR_DUPLICATE_REFEREE_ENTRY")

    def test_disagreement_keeps_match_in_result_pending(self, api):
        """PRD §3.4: 'a disagreement is rejected with
        ERR_RESULT_DISAGREEMENT, with the match remaining in
        RESULT_PENDING and no dispute auto-opened.'"""
        event, _, _ = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = _live_round1_match(event)
        head = create_referee(country_code="GR", team_affiliation=None,
                               qualifications=[event["event_type"]])
        asst = create_referee(country_code="HR", team_affiliation=None,
                                qualifications=[event["event_type"]])
        head_asg = assign_head_referee(match["id"], head["id"])
        asst_asg = assign_assistant_referee(match["id"], asst["id"])
        advance_clock(add_seconds(match["scheduled_end_at"], 1))
        # First submission.
        first = api.submit_result(
            match["id"],
            submit_result_payload(
                submitted_by_assignment_id=head_asg["id"],
                home_score=2, away_score=1,
            ),
            make_referee_headers(head["id"]),
        )
        validate_success(first, expected_status=201)
        # Second submission disagrees.
        second = api.submit_result(
            match["id"],
            submit_result_payload(
                submitted_by_assignment_id=asst_asg["id"],
                home_score=3, away_score=2,
            ),
            make_referee_headers(asst["id"]),
        )
        validate_error(second, "ERR_RESULT_DISAGREEMENT")
        # Match stays in RESULT_PENDING per PRD §3.4.
        from test_helpers import get_match
        m_after = get_match(event["id"], match["id"])
        assert m_after["status"] == "RESULT_PENDING"


# ===========================================================================
# 3.4 — Score validity per event_type (PRD §3.4)
# ===========================================================================
class TestScoreValidity:
    def test_single_elim_draw_rejected(self, api):
        """PRD §3.4: 'For SINGLE_ELIM, home_score and away_score must be
        unequal — exactly one side must win — otherwise the entry is
        rejected with ERR_INVALID_SCORE.'"""
        event, _, _ = event_in_progress(
            event_type="SINGLE_ELIM",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = _live_round1_match(event)
        head = create_referee(country_code="GR", team_affiliation=None,
                               qualifications=["SINGLE_ELIM"])
        head_asg = assign_head_referee(match["id"], head["id"])
        advance_clock(add_seconds(match["scheduled_end_at"], 1))
        # Equal scores → INVALID for SINGLE_ELIM.
        res = api.submit_result(
            match["id"],
            submit_result_payload(
                submitted_by_assignment_id=head_asg["id"],
                home_score=1, away_score=1,
            ),
            make_referee_headers(head["id"]),
        )
        validate_error(res, "ERR_INVALID_SCORE")

    def test_round_robin_draw_accepted(self, api):
        """PRD §3.4: 'For ROUND_ROBIN, equal scores are permitted (a draw).'"""
        event, parts, _ = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = _live_round1_match(event)
        head = create_referee(country_code="GR", team_affiliation=None,
                               qualifications=["ROUND_ROBIN"])
        head_asg = assign_head_referee(match["id"], head["id"])
        advance_clock(add_seconds(match["scheduled_end_at"], 1))
        res = api.submit_result(
            match["id"],
            submit_result_payload(
                submitted_by_assignment_id=head_asg["id"],
                home_score=2, away_score=2,
            ),
            make_referee_headers(head["id"]),
        )
        validate_success(res, expected_status=201)

    def test_sets_match_equal_sets_rejected(self, api):
        """PRD §3.4: 'For SETS_MATCH, the entry is invalid if home_sets_won
        and away_sets_won are equal, or if either of those fields is null;
        both of those conditions are rejected with ERR_INVALID_SCORE.'"""
        event, _, _ = event_in_progress(
            event_type="SETS_MATCH",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = _live_round1_match(event)
        head = create_referee(country_code="GR", team_affiliation=None,
                               qualifications=["SETS_MATCH"])
        head_asg = assign_head_referee(match["id"], head["id"])
        advance_clock(add_seconds(match["scheduled_end_at"], 1))
        res = api.submit_result(
            match["id"],
            submit_result_payload(
                submitted_by_assignment_id=head_asg["id"],
                home_score=2, away_score=1,
                home_sets_won=2, away_sets_won=2,
            ),
            make_referee_headers(head["id"]),
        )
        validate_error(res, "ERR_INVALID_SCORE")

    def test_sets_match_null_sets_rejected(self, api):
        """PRD §3.4: 'For SETS_MATCH, the entry is invalid if
        `home_sets_won` and `away_sets_won` are equal, or if either of
        those fields is `null`; both of those conditions are rejected
        with `ERR_INVALID_SCORE`.'"""
        event, _, _ = event_in_progress(
            event_type="SETS_MATCH",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = _live_round1_match(event)
        head = create_referee(country_code="GR", team_affiliation=None,
                               qualifications=["SETS_MATCH"])
        head_asg = assign_head_referee(match["id"], head["id"])
        advance_clock(add_seconds(match["scheduled_end_at"], 1))
        res = api.submit_result(
            match["id"],
            submit_result_payload(
                submitted_by_assignment_id=head_asg["id"],
                home_score=2, away_score=1,
                # sets fields omitted
            ),
            make_referee_headers(head["id"]),
        )
        validate_error(res, "ERR_INVALID_SCORE")


# ===========================================================================
# 3.4 — Successful lock
# ===========================================================================
class TestLock:
    def test_two_matching_submissions_lock_match(self, api):
        """PRD §3.4: 'When the second submission passes both checks, the
        match transitions from RESULT_PENDING to LOCKED. The locked scores
        are copied into locked_home_score, locked_away_score ... The
        winner is computed and written to winner_participant_id.'"""
        event, parts, _ = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = _live_round1_match(event)
        locked = lock_match(match, home_score=2, away_score=1,
                            event_type=event["event_type"])
        assert_match(locked)
        assert locked["status"] == "LOCKED"
        assert locked["locked_home_score"] == 2
        assert locked["locked_away_score"] == 1
        assert locked["winner_participant_id"] == match["home_participant_id"]


# ===========================================================================
# 3.4 — Disputes
# ===========================================================================
class TestDisputeFiling:
    def test_file_dispute_on_locked_match_flips_to_disputed(self, api):
        """PRD §3.4: 'A participant may file a dispute on a match that is
        in RESULT_PENDING or LOCKED ... If the match was LOCKED at the
        time of the filing, the match transitions to DISPUTED while
        preserving the snapshot of locked_home_score, locked_away_score,
        locked_home_sets_won, locked_away_sets_won, and
        winner_participant_id for restoration on a rejection.'"""
        event, parts, _ = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = _live_round1_match(event)
        locked = lock_match(match, home_score=2, away_score=1,
                            event_type=event["event_type"])
        # The losing participant files the dispute.
        loser = next(p for p in parts
                     if p["id"] != locked["winner_participant_id"])
        dispute = file_dispute(locked["id"], loser["id"])
        assert_dispute(dispute)
        assert dispute["status"] == "OPEN"
        from test_helpers import get_match
        m_after = get_match(event["id"], locked["id"])
        assert m_after["status"] == "DISPUTED"


# ===========================================================================
# 3.4 — Dispute resolution
# ===========================================================================
class TestDisputeResolution:
    def test_uphold_writes_audit_log_and_updates_locked_scores(self, api):
        """PRD §3.4: 'on success it persists a new ResultEntry of kind
        CORRECTION ... writes a RESULT_CHANGE audit row whose from_value
        snapshots the old locked-score fields and whose to_value
        snapshots the new ones, updates the locked_* fields and possibly
        winner_participant_id.'"""
        event, parts, _ = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = _live_round1_match(event)
        locked = lock_match(match, home_score=2, away_score=1,
                            event_type=event["event_type"])
        loser = next(p for p in parts
                     if p["id"] != locked["winner_participant_id"])
        dispute = file_dispute(locked["id"], loser["id"])
        # Uphold with reversed scores.
        resolved = resolve_dispute_uphold(
            dispute["id"], corrected_home_score=1, corrected_away_score=2
        )
        assert resolved["status"] == "UPHELD"
        # Match returns to LOCKED with corrected scores.
        from test_helpers import get_match
        m_after = get_match(event["id"], locked["id"])
        assert m_after["status"] == "LOCKED"
        assert m_after["locked_home_score"] == 1
        assert m_after["locked_away_score"] == 2
        # Audit log RESULT_CHANGE row exists.
        rows = list_audit_logs(kind="RESULT_CHANGE",
                               subject_kind="MATCH",
                               subject_id=locked["id"])
        assert len(rows) >= 1, (
            "PRD §3.4 / §2.10: a RESULT_CHANGE audit row must be written "
            "when the match's locked scores change after a dispute uphold."
        )

    def test_reject_restores_original_locked_state(self, api):
        """PRD §3.4: 'A reject (uphold false) flips the dispute to
        REJECTED and the match back to LOCKED with the original snapshot
        restored.'"""
        event, parts, _ = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = _live_round1_match(event)
        locked = lock_match(match, home_score=2, away_score=1,
                            event_type=event["event_type"])
        loser = next(p for p in parts
                     if p["id"] != locked["winner_participant_id"])
        dispute = file_dispute(locked["id"], loser["id"])
        rejected = resolve_dispute_reject(dispute["id"])
        assert rejected["status"] == "REJECTED"
        from test_helpers import get_match
        m_after = get_match(event["id"], locked["id"])
        assert m_after["status"] == "LOCKED"
        assert m_after["locked_home_score"] == 2
        assert m_after["locked_away_score"] == 1
        assert m_after["winner_participant_id"] == locked["winner_participant_id"]
