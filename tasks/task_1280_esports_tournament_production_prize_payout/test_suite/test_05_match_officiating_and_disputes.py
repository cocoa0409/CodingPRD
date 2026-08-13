"""Match officiating cycle, result SoD, dispute and adjudication workflows."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_dispute,
    api_client,
    assert_iso8601_instant_equal,
    confirm_result,
    create_dispute,
    create_server,
    get_dispute,
    get_match,
    make_referee_headers,
    make_team_manager_headers,
    officiate_match,
    play_match_to_completed,
    play_match_to_confirmed,
    report_result,
    schedule_match,
    set_clock,
    setup_dispute_under_review,
    setup_in_progress_2team,
    setup_in_progress_4team,
    setup_seeded_tournament,
    validate_error,
)

TD = TEST_USERS["tournament_director_headers"]


class TestPauseCycle:

    def test_third_tactical_pause_rejected_technical_free(self):
        """PRD §3.5: "If `pause_reason` is `TACTICAL`, the pausing side's
        tactical pause counter must be below 2 before the pause — a side that
        has already consumed 2 tactical pauses triggers
        `ERR_PAUSE_LIMIT_EXCEEDED` — and on success the corresponding counter
        (`tactical_pauses_home` or `tactical_pauses_away`) increments by 1.
        Technical pauses never count against the limit."

        Design: Difficulty/non_linear_state_machine/match_pause_resume_cycle_with_limit
        """
        ctx = setup_in_progress_2team("Pause Cup")
        match_id = ctx["match"]["id"]
        officiate_match(match_id, {"action": "OPEN_LOBBY"})
        officiate_match(match_id, {"action": "START"})

        for _ in range(2):
            paused = officiate_match(match_id, {
                "action": "PAUSE", "pause_reason": "TACTICAL",
                "pausing_side": "HOME"})
            assert paused["status"] == "PAUSED"
            officiate_match(match_id, {"action": "RESUME"})

        resp = api_client.officiate_match(
            match_id, {"action": "PAUSE", "pause_reason": "TACTICAL",
                       "pausing_side": "HOME"},
            make_referee_headers("ref-1"))
        validate_error(resp, ApiErrorId.ERR_PAUSE_LIMIT_EXCEEDED)
        assert get_match(match_id)["status"] == "LIVE", \
            "the third TACTICAL pause is rejected and the match stays LIVE"

        technical = officiate_match(match_id, {
            "action": "PAUSE", "pause_reason": "TECHNICAL",
            "pausing_side": "HOME"})
        assert technical["status"] == "PAUSED", \
            "TECHNICAL pauses never count against the limit"
        officiate_match(match_id, {"action": "RESUME"})

        completed = report_result(match_id, 13, 3)
        assert completed["status"] == "COMPLETED"
        assert completed["tactical_pauses_home"] == 2

    def test_tactical_pause_counters_are_per_side(self):
        """PRD §3.5: "If `pause_reason` is `TACTICAL`, the pausing side's
        tactical pause counter must be below 2 before the pause — a side that
        has already consumed 2 tactical pauses triggers
        `ERR_PAUSE_LIMIT_EXCEEDED` — and on success the corresponding counter
        (`tactical_pauses_home` or `tactical_pauses_away`) increments by 1."

        Design: Difficulty/non_linear_state_machine/match_pause_resume_cycle_with_limit
        """
        ctx = setup_in_progress_2team("Sides Cup")
        match_id = ctx["match"]["id"]
        officiate_match(match_id, {"action": "OPEN_LOBBY"})
        officiate_match(match_id, {"action": "START"})

        for side in ("HOME", "AWAY"):
            for _ in range(2):
                officiate_match(match_id, {
                    "action": "PAUSE", "pause_reason": "TACTICAL",
                    "pausing_side": side})
                officiate_match(match_id, {"action": "RESUME"})

        match = get_match(match_id)
        assert match["tactical_pauses_home"] == 2
        assert match["tactical_pauses_away"] == 2, \
            "each side's counter is independent of the other's"

        resp = api_client.officiate_match(
            match_id, {"action": "PAUSE", "pause_reason": "TACTICAL",
                       "pausing_side": "AWAY"},
            make_referee_headers("ref-1"))
        validate_error(resp, ApiErrorId.ERR_PAUSE_LIMIT_EXCEEDED)


class TestResultFlow:

    def test_match_confirm_before_report_returns_invalid_state(self):
        """PRD §3.5: "A `Referee` whose `X-User-ID` differs from the recorded
        `reported_by_user_id` may confirm a `COMPLETED` match, moving it to
        `CONFIRMED`"
        PRD §2.7: "requesting a transition from a state that does not permit
        it is rejected with the machine's specific invalid-status error
        (HTTP 409)."

        Design: Corner/state_machines/match_confirm_before_report_returns_invalid_state
        """
        ctx = setup_seeded_tournament("Order Cup")
        tournament_id = ctx["tournament"]["id"]
        server = create_server(tournament_id, "S1", "NA")
        match = ctx["matches"][0]
        schedule_match(match["id"], server["id"], "2026-08-11T10:00:00Z", 60,
                       "ref-1")
        resp = api_client.confirm_result(
            match["id"], make_referee_headers("ref-2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_MATCH_STATUS)
        after = get_match(match["id"])
        assert after["status"] == "SCHEDULED"
        assert after["confirmed_by_user_id"] is None

    def test_match_terminal_lockdown_report_on_confirmed(self):
        """PRD §3.5: "Reporting a result moves `LIVE → COMPLETED`."
        PRD §2.7: "requesting a transition from a state that does not permit
        it is rejected with the machine's specific invalid-status error
        (HTTP 409)."

        Design: Corner/state_machines/match_terminal_lockdown_report_on_confirmed
        """
        ctx = setup_in_progress_2team("Lockdown Cup")
        match_id = ctx["match"]["id"]
        play_match_to_confirmed(match_id, 13, 7)
        resp = api_client.report_result(
            match_id, {"home_score": 3, "away_score": 13},
            make_referee_headers("ref-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_MATCH_STATUS)
        after = get_match(match_id)
        assert after["status"] == "CONFIRMED"
        assert after["home_score"] == 13 and after["away_score"] == 7

    def test_report_tied_score_returns_invalid_request(self):
        """PRD §3.5: "The body carries `home_score` and `away_score`, both
        non-negative, and ties are not allowed — equal scores are rejected
        with `ERR_VALIDATION`."

        Design: Corner/validations/report_tied_score_returns_invalid_request
        """
        ctx = setup_in_progress_2team("Tie Score Cup")
        match_id = ctx["match"]["id"]
        officiate_match(match_id, {"action": "OPEN_LOBBY"})
        officiate_match(match_id, {"action": "START"})
        resp = api_client.report_result(
            match_id, {"home_score": 12, "away_score": 12},
            make_referee_headers("ref-1"))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        after = get_match(match_id)
        assert after["status"] == "LIVE"
        assert after["winner_registration_id"] is None

    def test_sod_reporter_cannot_confirm_own_result(self):
        """PRD §3.5: "The same referee who reported the result may not
        confirm it — the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.10: "A match result cannot be confirmed by the referee whose
        `X-User-ID` was recorded as `reported_by_user_id` on the same match."

        Design: Corner/rbac/sod_reporter_cannot_confirm_own_result
        """
        ctx = setup_in_progress_2team("SoD1 Cup")
        match_id = ctx["match"]["id"]
        play_match_to_completed(match_id, 13, 7, "ref-1")

        resp = api_client.confirm_result(
            match_id, make_referee_headers("ref-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        confirmed = confirm_result(match_id, "ref-2")
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["reported_by_user_id"] == "ref-1"
        assert confirmed["confirmed_by_user_id"] == "ref-2"


class TestDisputeFiling:

    def test_dispute_window_boundary_exact_close_allowed(self):
        """PRD §3.5: "Filing is only allowed while the logical clock is at or
        before the match's `dispute_window_closes_at`; after that the request
        is rejected with `ERR_DISPUTE_WINDOW_CLOSED`."
        PRD §3.5: "`completed_at` is set to the logical clock, and
        `dispute_window_closes_at` is set to 24 hours after `completed_at`."

        Design: Corner/validations/dispute_window_boundary_exact_close_allowed
        """
        ctx = setup_in_progress_4team("DisputeWindow Cup")
        m1, m2 = ctx["matches"][0], ctx["matches"][1]
        # Both matches report at the 2026-08-10 lock instant; windows close
        # at 2026-08-11T00:00:00Z.
        play_match_to_completed(m1["id"], 13, 5)
        play_match_to_completed(m2["id"], 13, 2)
        r3, r4 = ctx["registrations"][2], ctx["registrations"][3]

        set_clock("2026-08-11T00:00:00Z")
        dispute = create_dispute(m1["id"], r4["id"], "CONDUCT",
                                 "filed exactly at window close")
        assert dispute["status"] == "FILED", \
            "filing at exactly completed_at + 24h is inside the window"
        assert get_match(m1["id"])["status"] == "UNDER_DISPUTE"

        set_clock("2026-08-11T00:00:01Z")
        resp = api_client.create_dispute(
            {"match_id": m2["id"], "registration_id": r3["id"],
             "reason": "CONDUCT", "details": "filed one second late"},
            make_team_manager_headers(r3["id"]))
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)
        assert get_match(m2["id"])["status"] == "COMPLETED"

    def test_dispute_by_non_participant_rejected(self):
        """PRD §3.5: "The filing registration must be a participant — either
        home or away — else `ERR_NOT_MATCH_PARTICIPANT`."

        Design: Corner/validations/dispute_by_non_participant_rejected
        """
        ctx = setup_in_progress_4team("Filer Cup")
        m1 = ctx["matches"][0]
        play_match_to_completed(m1["id"], 13, 5)
        r3 = ctx["registrations"][2]
        resp = api_client.create_dispute(
            {"match_id": m1["id"], "registration_id": r3["id"],
             "reason": "CONDUCT", "details": "r3 was not in this match"},
            make_team_manager_headers(r3["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_MATCH_PARTICIPANT)
        assert get_match(m1["id"])["status"] == "COMPLETED"


class TestDisputeAppealCycle:

    def test_dispute_appeal_reopens_review_cycle(self):
        """PRD §3.5: "A dispute closed `CLOSED_UPHELD` may be appealed once
        by the owning `TeamManager`, moving it to `APPEALED` and setting
        `appeal_used` true; the match's `CONFIRMED` status is not reopened by
        the appeal — the appeal reopens review only. A second appeal is
        rejected with `ERR_APPEAL_EXHAUSTED`."
        PRD §3.5: "`RULE_UPHELD` moves `UNDER_REVIEW → CLOSED_UPHELD`,
        records `ruling` `UPHELD`, and cascades the match from
        `UNDER_DISPUTE → CONFIRMED`, with the adjudicating director's
        `X-User-ID` recorded as the match's `confirmed_by_user_id`."

        Design: Corner/state_machines/dispute_appeal_reopens_review_cycle
        """
        ctx = setup_in_progress_2team("Dispute Cup")
        r1, r2 = ctx["registrations"]
        match_id = ctx["match"]["id"]
        play_match_to_completed(match_id, 13, 7, "ref-1")

        dispute = create_dispute(match_id, r2["id"], "RULE_VIOLATION",
                                 "smoke bug round 4")
        assert dispute["status"] == "FILED"
        dispute = adjudicate_dispute(dispute["id"], {"action": "START_REVIEW"})
        assert dispute["status"] == "UNDER_REVIEW"
        dispute = adjudicate_dispute(dispute["id"], {"action": "RULE_UPHELD"})
        assert dispute["status"] == "CLOSED_UPHELD"
        assert dispute["ruling"] == "UPHELD"
        match = get_match(match_id)
        assert match["status"] == "CONFIRMED"
        assert match["confirmed_by_user_id"] == TD["X-User-ID"]

        resp = api_client.appeal_dispute(
            dispute["id"], make_team_manager_headers(r2["id"]))
        appealed = resp.json()["data"]
        assert appealed["status"] == "APPEALED"
        assert appealed["appeal_used"] is True
        assert get_match(match_id)["status"] == "CONFIRMED", \
            "the appeal reopens review only; the match stays CONFIRMED"

        dispute = adjudicate_dispute(dispute["id"], {"action": "START_REVIEW"})
        assert dispute["status"] == "UNDER_REVIEW"
        dispute = adjudicate_dispute(dispute["id"], {"action": "RULE_UPHELD"})
        assert dispute["status"] == "CLOSED_UPHELD"

        resp = api_client.appeal_dispute(
            dispute["id"], make_team_manager_headers(r2["id"]))
        validate_error(resp, ApiErrorId.ERR_APPEAL_EXHAUSTED)


class TestOverturnedRemedies:

    def _setup_m1_completed_r1_advanced(self, name="Flip Cup"):
        """4-team IN_PROGRESS; m1 (seed1 r1 home vs seed4 r4 away) reported
        13-5 for r1 (COMPLETED, not confirmed); the final's home slot holds
        r1 by propagation."""
        ctx = setup_in_progress_4team(name)
        m1 = ctx["matches"][0]
        play_match_to_completed(m1["id"], 13, 5)
        return ctx

    def test_winner_flip_rewrites_downstream_slot(self):
        """PRD §3.5: "On success the match moves `UNDER_DISPUTE → OVERTURNED
        → CONFIRMED` in the same request, `winner_registration_id` flips to
        the other participant, and if the winner had already been propagated
        to the next match's slot, that slot is replaced with the new winner."

        Design: Difficulty/transitive_cascade/overturned_winner_flip_propagates
        """
        ctx = self._setup_m1_completed_r1_advanced()
        r1, r4 = ctx["registrations"][0], ctx["registrations"][3]
        m1, mf = ctx["matches"][0], ctx["matches"][2]
        assert get_match(mf["id"])["home_registration_id"] == r1["id"]

        dispute = setup_dispute_under_review(m1["id"], r4["id"],
                                             "SCORE_DISCREPANCY",
                                             "round 9 score misreported")
        closed = adjudicate_dispute(
            dispute["id"], {"action": "RULE_OVERTURNED",
                            "remedy": "WINNER_FLIP"})
        assert closed["status"] == "CLOSED_OVERTURNED"

        match = get_match(m1["id"])
        assert match["status"] == "CONFIRMED"
        assert match["winner_registration_id"] == r4["id"], \
            "the winner flips to the other participant"
        final = get_match(mf["id"])
        assert final["home_registration_id"] == r4["id"], \
            "the propagated slot is rewritten to the new winner"
        assert final["status"] == "PENDING"

    def test_winner_flip_closes_dispute_and_confirms_match(self):
        """PRD §3.5: "`RULE_OVERTURNED` takes a `remedy` of `WINNER_FLIP` or
        `REMATCH` and moves the dispute `UNDER_REVIEW → CLOSED_OVERTURNED`."
        PRD §3.5: "For `WINNER_FLIP`, the downstream next match, if any, must
        be in `PENDING` or `SCHEDULED`; otherwise the request is rejected
        with `ERR_BRACKET_LOCKED_DOWNSTREAM`."

        Design: Difficulty/transitive_cascade/overturned_winner_flip_propagates
        """
        ctx = self._setup_m1_completed_r1_advanced("Flip2 Cup")
        r4 = ctx["registrations"][3]
        m1, mf = ctx["matches"][0], ctx["matches"][2]
        dispute = setup_dispute_under_review(m1["id"], r4["id"],
                                             "SCORE_DISCREPANCY",
                                             "round 9 score misreported")
        adjudicate_dispute(dispute["id"], {"action": "RULE_OVERTURNED",
                                           "remedy": "WINNER_FLIP"})
        after = get_dispute(dispute["id"])
        assert after["status"] == "CLOSED_OVERTURNED"
        assert after["ruling"] == "OVERTURNED"
        assert after["remedy"] == "WINNER_FLIP"
        # CONFIRMED is terminal for the result flow: a fresh confirm attempt
        # is now a from-state violation on the match machine.
        resp = api_client.confirm_result(
            m1["id"], make_referee_headers("ref-9"))
        validate_error(resp, ApiErrorId.ERR_INVALID_MATCH_STATUS)
        assert get_match(mf["id"])["away_registration_id"] is None

    def test_overturned_rematch_requeues_match(self):
        """PRD §3.5: "On success the match's `home_score`, `away_score`,
        `winner_registration_id`, `completed_at`, and
        `dispute_window_closes_at` are cleared, the advanced slot in the next
        match (if filled and still `PENDING`) is cleared, and the match moves
        `UNDER_DISPUTE → OVERTURNED → SCHEDULED` in the same request with the
        original `server_id` and `scheduled_start_at` retained."

        Design: Corner/state_machines/overturned_rematch_requeues_match
        """
        ctx = self._setup_m1_completed_r1_advanced("Rematch Cup")
        r4 = ctx["registrations"][3]
        m1, mf = ctx["matches"][0], ctx["matches"][2]
        server_id = ctx["server"]["id"]
        dispute = setup_dispute_under_review(m1["id"], r4["id"],
                                             "TECHNICAL_FAILURE",
                                             "server tickrate drop rounds 9-11")
        closed = adjudicate_dispute(
            dispute["id"], {"action": "RULE_OVERTURNED", "remedy": "REMATCH"})
        assert closed["status"] == "CLOSED_OVERTURNED"
        assert closed["remedy"] == "REMATCH"

        match = get_match(m1["id"])
        assert match["status"] == "SCHEDULED"
        assert match["home_score"] is None
        assert match["away_score"] is None
        assert match["winner_registration_id"] is None
        assert match["completed_at"] is None
        assert match["dispute_window_closes_at"] is None
        assert match["server_id"] == server_id
        assert_iso8601_instant_equal(match["scheduled_start_at"],
                                     "2026-08-11T10:00:00Z")

        final = get_match(mf["id"])
        assert final["home_registration_id"] is None, \
            "the advanced slot is cleared"
        assert final["status"] == "PENDING"

    def test_winner_flip_blocked_when_downstream_started(self):
        """PRD §3.5: "For `WINNER_FLIP`, the downstream next match, if any,
        must be in `PENDING` or `SCHEDULED`; otherwise the request is
        rejected with `ERR_BRACKET_LOCKED_DOWNSTREAM`."
        PRD §3.5: "For `REMATCH`, the same downstream precondition applies
        with one tightening: if the advanced slot was already filled, the
        next match must still be `PENDING` — a re-queue into a started match
        is rejected with `ERR_BRACKET_LOCKED_DOWNSTREAM`."

        Design: Corner/state_machines/winner_flip_blocked_when_downstream_started
        """
        ctx = setup_in_progress_4team("Downstream Cup")
        r1, r4 = ctx["registrations"][0], ctx["registrations"][3]
        m1, m2, mf = ctx["matches"]
        play_match_to_completed(m1["id"], 13, 5)
        play_match_to_completed(m2["id"], 13, 2)
        schedule_match(mf["id"], ctx["server"]["id"], "2026-08-11T14:00:00Z",
                       60, "ref-1")
        officiate_match(mf["id"], {"action": "OPEN_LOBBY"})

        dispute = setup_dispute_under_review(m1["id"], r4["id"],
                                             "SCORE_DISCREPANCY",
                                             "scoreboard error")
        resp = api_client.adjudicate_dispute(
            dispute["id"], {"action": "RULE_OVERTURNED",
                            "remedy": "WINNER_FLIP"}, TD)
        validate_error(resp, ApiErrorId.ERR_BRACKET_LOCKED_DOWNSTREAM)
        resp = api_client.adjudicate_dispute(
            dispute["id"], {"action": "RULE_OVERTURNED", "remedy": "REMATCH"},
            TD)
        validate_error(resp, ApiErrorId.ERR_BRACKET_LOCKED_DOWNSTREAM)

        assert get_dispute(dispute["id"])["status"] == "UNDER_REVIEW"
        match = get_match(m1["id"])
        assert match["status"] == "UNDER_DISPUTE"
        assert match["winner_registration_id"] == r1["id"]
        assert get_match(mf["id"])["home_registration_id"] == r1["id"]
