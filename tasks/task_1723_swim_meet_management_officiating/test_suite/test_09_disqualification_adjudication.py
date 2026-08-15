"""Disqualification recording gates, the protest-window boundaries, the
branching protest paths, segregation of duties, terminal lockdown, and the
depth-4 confirm rescore cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    CLOCK_MEET_DAY_1000,
    CLOCK_MEET_DAY_1030,
    CLOCK_MEET_DAY_1031,
    add_entry,
    add_event,
    add_swimmer,
    add_team,
    complete_event_with_times,
    create_disqualification_payload,
    create_open_meet,
    get_success_data,
    lane_for_entry,
    make_deck_official_headers,
    make_meet_referee_headers,
    make_team_coach_headers,
    notify_dq,
    record_dq,
    seed_meet,
    setup_deck_coverage,
    setup_in_progress_event,
    start_event,
    submit_clean_readings,
    validate_error,
    validate_success,
    verify_entry,
)

DIRECTOR = TEST_USERS["meet_director_headers"]


def _in_progress_with_reconciled_lane(api, meet_name="DQ", stroke="BUTTERFLY"):
    """Event IN_PROGRESS with one AUTO_CONFIRMED lane. Returns workspace."""
    workspace = setup_in_progress_event(meet_name=meet_name,
                                        event_overrides={"stroke": stroke})
    lane = workspace["lanes"][0]
    submit_clean_readings(lane["id"], 2500)
    return workspace


def _recorded_dq(api, workspace, dq_code="TURN_NO_TOUCH", notes="call"):
    """Judge records a call on the workspace's first lane. Returns the DQ."""
    lane = workspace["lanes"][0]
    judge_id = workspace["coverage"]["judge"]["id"]
    return record_dq(lane["id"], judge_id, dq_code=dq_code, call_notes=notes)


class TestRecordingGates:
    def test_dq_record_on_unreconciled_lane_rejected(self, api):
        """PRD §3.8: "The lane's `reconciliation_status` must be
        `AUTO_CONFIRMED` or `RESOLVED` (`ERR_LANE_NOT_RECONCILED`)".

        Design: Corner/errors/dq_record_on_unreconciled_lane_rejected
        """
        workspace = setup_in_progress_event(meet_name="RE11",
                                            event_overrides={"stroke": "BUTTERFLY"})
        lane = workspace["lanes"][0]  # PENDING_READINGS: no readings submitted
        judge_id = workspace["coverage"]["judge"]["id"]
        resp = api.record_disqualification(
            lane["id"],
            create_disqualification_payload(dq_code="TURN_NO_TOUCH",
                                            call_notes="early call"),
            make_deck_official_headers(judge_id))
        validate_error(resp, ApiErrorId.ERR_LANE_NOT_RECONCILED)

    def test_second_live_dq_on_lane_rejected(self, api):
        """PRD §3.8: "no other non-terminal disqualification may already exist
        on the same lane (`ERR_DQ_ALREADY_ACTIVE`)".

        Design: Corner/validations/dq_already_active_on_lane
        """
        workspace = _in_progress_with_reconciled_lane(api, meet_name="DA1")
        _recorded_dq(api, workspace, dq_code="FLY_ARMS_ALTERNATING",
                     notes="arms")
        lane = workspace["lanes"][0]
        judge_id = workspace["coverage"]["judge"]["id"]
        resp = api.record_disqualification(
            lane["id"],
            create_disqualification_payload(dq_code="TURN_NO_TOUCH",
                                            call_notes="second call"),
            make_deck_official_headers(judge_id))
        validate_error(resp, ApiErrorId.ERR_DQ_ALREADY_ACTIVE)

    def test_referee_cannot_record_dq(self, api):
        """PRD §4: `POST /lane-assignments/{id}/disqualifications` is
        authorized for DeckOfficial only. PRD §2.1: "An authenticated caller
        whose role is not permitted for an endpoint — or who fails an ownership
        check — is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/referee_cannot_record_dq
        """
        workspace = _in_progress_with_reconciled_lane(api, meet_name="RB2")
        lane = workspace["lanes"][0]
        referee_id = workspace["coverage"]["referee"]["id"]
        resp = api.record_disqualification(
            lane["id"],
            create_disqualification_payload(dq_code="FALSE_START",
                                            call_notes="ref tries"),
            make_meet_referee_headers(referee_id))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestProtestWindowBoundaries:
    def _setup_two_notified_dqs(self, api):
        workspace = setup_in_progress_event(
            meet_name="PW1", seed_times=(2900, 2910),
            event_overrides={"stroke": "BUTTERFLY"})
        for lane, pad in zip(workspace["lanes"], (2500, 2510)):
            submit_clean_readings(lane["id"], pad)
        judge_id = workspace["coverage"]["judge"]["id"]
        referee_id = workspace["coverage"]["referee"]["id"]
        get_success_data(api.set_clock(CLOCK_MEET_DAY_1000, DIRECTOR))
        dq_a = record_dq(workspace["lanes"][0]["id"], judge_id,
                         dq_code="TURN_NO_TOUCH", call_notes="a")
        dq_b = record_dq(workspace["lanes"][1]["id"], judge_id,
                         dq_code="TURN_NO_TOUCH", call_notes="b")
        notify_dq(dq_a["id"], referee_id)  # notified_at := 2026-08-15T10:00Z
        notify_dq(dq_b["id"], referee_id)
        return workspace, dq_a, dq_b

    def test_protest_window_exact_boundaries(self, api):
        """PRD §3.8: "A `TeamCoach` may protest, moving the call to
        `PROTESTED`, provided the logical clock has not advanced beyond
        `notified_at` plus the meet's `dq_protest_window_minutes` — a protest
        landing exactly at the window's end is still accepted, and anything
        later fails with `ERR_PROTEST_WINDOW_EXPIRED`."
        PRD §3.8: "An unprotested call is confirmed once its protest window
        has fully elapsed — the logical clock must have advanced strictly past
        `notified_at` plus `dq_protest_window_minutes`, and an attempt earlier
        fails with `ERR_PROTEST_WINDOW_OPEN`".

        Design: Corner/validations/dq_protest_window_exact_boundaries
        """
        workspace, dq_a, dq_b = self._setup_two_notified_dqs(api)
        team = workspace["teams"]["AAA"]
        referee_id = workspace["coverage"]["referee"]["id"]
        # Exactly at the window end (10:00 + 30m): protest accepted (<=).
        get_success_data(api.set_clock(CLOCK_MEET_DAY_1030, DIRECTOR))
        protested = validate_success(api.protest_disqualification(
            dq_a["id"], make_team_coach_headers(team["id"])))
        assert protested["status"] == "PROTESTED"
        # Confirm at exactly the window end is too early (strictly past).
        resp = api.confirm_disqualification(
            dq_b["id"], make_meet_referee_headers(referee_id))
        validate_error(resp, ApiErrorId.ERR_PROTEST_WINDOW_OPEN)
        # One minute past the window: protest expired.
        get_success_data(api.set_clock(CLOCK_MEET_DAY_1031, DIRECTOR))
        resp = api.protest_disqualification(
            dq_b["id"], make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_PROTEST_WINDOW_EXPIRED)


class TestProtestBranchingPaths:
    """Difficulty pair: the Disqualification fork-join — two identically
    recorded DQs diverge at PROTESTED."""

    def _setup_two_protested_dqs(self, api):
        workspace = setup_in_progress_event(
            meet_name="SM1", seed_times=(2900, 2910),
            event_overrides={"stroke": "BUTTERFLY"})
        for lane, pad in zip(workspace["lanes"], (2500, 2510)):
            submit_clean_readings(lane["id"], pad)
        judge_id = workspace["coverage"]["judge"]["id"]
        referee_id = workspace["coverage"]["referee"]["id"]
        team = workspace["teams"]["AAA"]
        get_success_data(api.set_clock(CLOCK_MEET_DAY_1000, DIRECTOR))
        dq_a = record_dq(workspace["lanes"][0]["id"], judge_id,
                         dq_code="FLY_ARMS_ALTERNATING",
                         call_notes="arms alternating")
        dq_b = record_dq(workspace["lanes"][1]["id"], judge_id,
                         dq_code="TURN_NO_TOUCH", call_notes="no touch at turn")
        notify_dq(dq_a["id"], referee_id)
        notify_dq(dq_b["id"], referee_id)
        coach = make_team_coach_headers(team["id"])
        validate_success(api.protest_disqualification(dq_a["id"], coach))
        validate_success(api.protest_disqualification(dq_b["id"], coach))
        return workspace, dq_a, dq_b

    def test_upheld_then_confirmed_branch_moves_entry_to_dq(self, api):
        """PRD §3.8: "A protested call is either upheld (`PROTESTED` →
        `UPHELD`) and then confirmed (`UPHELD` → `CONFIRMED`), or overturned
        (`PROTESTED` → `OVERTURNED`)."
        PRD §3.8: "the EventEntry tied to the sanctioned lane moves to `DQ` —
        from `SEEDED` when the event has not yet completed, or from `FINISHED`
        after completion."

        Design: Difficulty/non_linear_state_machine/dq_branching_protest_paths
        """
        workspace, dq_a, _dq_b = self._setup_two_protested_dqs(api)
        referee_id = workspace["coverage"]["referee"]["id"]
        referee = make_meet_referee_headers(referee_id)
        upheld = validate_success(api.uphold_disqualification(dq_a["id"],
                                                              referee))
        assert upheld["status"] == "UPHELD"
        confirmed = validate_success(api.confirm_disqualification(dq_a["id"],
                                                                  referee))
        assert confirmed["status"] == "CONFIRMED"
        entry_after = get_success_data(
            api.get_entry(workspace["entries"][0]["id"], DIRECTOR))
        assert entry_after["status"] == "DQ", \
            "confirmation moves the sanctioned entry SEEDED -> DQ"

    def test_overturned_branch_leaves_entry_untouched(self, api):
        """PRD §3.8: "A protested call is either upheld (`PROTESTED` →
        `UPHELD`) and then confirmed (`UPHELD` → `CONFIRMED`), or overturned
        (`PROTESTED` → `OVERTURNED`)."
        PRD §3.8: "the entry returns from `DQ` to `FINISHED`, but only when the
        disqualification had actually been confirmed — overturning a call that
        never reached confirmation leaves the entry's status untouched."

        Design: Difficulty/non_linear_state_machine/dq_branching_protest_paths
        """
        workspace, _dq_a, dq_b = self._setup_two_protested_dqs(api)
        referee_id = workspace["coverage"]["referee"]["id"]
        overturned = validate_success(api.overturn_disqualification(
            dq_b["id"], make_meet_referee_headers(referee_id)))
        assert overturned["status"] == "OVERTURNED"
        entry_after = get_success_data(
            api.get_entry(workspace["entries"][1]["id"], DIRECTOR))
        assert entry_after["status"] == "SEEDED", \
            "the DQ never reached confirmation, so the entry is untouched"


class TestTerminalLockdown:
    def test_uphold_after_overturn_rejected(self, api):
        """PRD §3.8: "`CONFIRMED` and `OVERTURNED` are terminal, and any
        transition attempted from a posture that forbids it — confirming
        straight from `RECORDED`, or protesting an already-`PROTESTED` call —
        fails with `ERR_DQ_INVALID_STATE`."

        Design: Corner/state_machines/dq_terminal_lockdown_overturned
        """
        workspace = _in_progress_with_reconciled_lane(api, meet_name="TL1")
        team = workspace["teams"]["AAA"]
        referee_id = workspace["coverage"]["referee"]["id"]
        dq = _recorded_dq(api, workspace, notes="missed wall")
        notify_dq(dq["id"], referee_id)
        validate_success(api.protest_disqualification(
            dq["id"], make_team_coach_headers(team["id"])))
        overturned = validate_success(api.overturn_disqualification(
            dq["id"], make_meet_referee_headers(referee_id)))
        assert overturned["status"] == "OVERTURNED"
        resp = api.uphold_disqualification(
            dq["id"], make_meet_referee_headers(referee_id))
        validate_error(resp, ApiErrorId.ERR_DQ_INVALID_STATE)


class TestSegregationOfDuties:
    def test_recorder_cannot_confirm_own_call(self, api):
        """PRD §3.8: "the confirming, upholding, or overturning referee's
        `X-User-ID` must differ from `reporting_official_id`, with violations
        rejected as `ERR_SEGREGATION_OF_DUTY`, and the ruling referee's
        identity is recorded in `resolved_by_referee_id`, which therefore
        always differs from `reporting_official_id`."

        Design: Corner/rbac/segregation_of_duty_on_own_dq_confirm
        """
        meet = create_open_meet(meet_name="RB4")
        team = add_team(meet["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw A")
        event = add_event(meet["id"], stroke="BUTTERFLY",
                          qualifying_time_cs=3000)
        entry = add_entry(event["id"], swimmer["id"], team["id"],
                          seed_time_cs=2900)
        verify_entry(entry["id"])
        # Deck coverage from two distinct officials — PRD §3.5 forbids one
        # official holding overlapping assignments on the same session_date,
        # so a single official cannot cover both roles on one event.
        coverage = setup_deck_coverage(event["id"], meet["id"])
        judge_id = coverage["judge"]["id"]
        referee_id = coverage["referee"]["id"]
        seed_meet(meet["id"])
        start_event(event["id"])
        lane = lane_for_entry(entry["id"])
        submit_clean_readings(lane["id"], 2500)
        get_success_data(api.set_clock(CLOCK_MEET_DAY_1000, DIRECTOR))
        dq = record_dq(lane["id"], judge_id,
                       dq_code="FLY_ARMS_ALTERNATING", call_notes="own call")
        notify_dq(dq["id"], referee_id)
        get_success_data(api.set_clock(CLOCK_MEET_DAY_1031, DIRECTOR))
        # The recording judge presents the MeetReferee role (their X-User-ID
        # is the acting Official's id per PRD §2.1) and attempts the ruling.
        resp = api.confirm_disqualification(
            dq["id"], make_meet_referee_headers(judge_id))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTY)


class TestPublishBlockedByLiveDq:
    def test_publish_blocked_by_nonterminal_dq(self, api):
        """PRD §3.9: "but only once every disqualification on the event's lane
        assignments has reached `CONFIRMED` or `OVERTURNED`; a live call blocks
        publication with `ERR_DQ_NOT_TERMINAL`."

        Design: Corner/validations/publish_blocked_by_nonterminal_dq
        """
        workspace = _in_progress_with_reconciled_lane(api, meet_name="PD1")
        _recorded_dq(api, workspace, dq_code="FLY_ARMS_ALTERNATING",
                     notes="arms")  # stays RECORDED (non-terminal)
        completed = validate_success(api.complete_event(
            workspace["event"]["id"], workspace["event_version"], DIRECTOR))
        assert completed["status"] == "COMPLETED"
        resp = api.publish_event(workspace["event"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_DQ_NOT_TERMINAL)


class TestDqConfirmRescoreCascade:
    """Difficulty pair: the depth-4 cascade — CONFIRMED -> entry DQ -> Result
    DQ_EXCLUDED -> surviving results re-placed/re-pointed -> team rollups."""

    def _setup_completed_with_dq(self, api):
        """Event COMPLETED: A (team XXX) place 1, B and C (team YYY) places
        2-3; DQ recorded on A's lane post-completion, notified at 10:00, and
        the clock moved past the 30-minute protest window."""
        workspace = setup_in_progress_event(
            meet_name="TC1", seed_times=(2400, 2450, 2470),
            team_codes=("XXX", "YYY"),
            swimmer_teams=["XXX", "YYY", "YYY"])
        complete_event_with_times(workspace, [2490, 2500, 2510])
        judge_id = workspace["coverage"]["judge"]["id"]
        referee_id = workspace["coverage"]["referee"]["id"]
        get_success_data(api.set_clock(CLOCK_MEET_DAY_1000, DIRECTOR))
        dq = record_dq(workspace["lanes"][0]["id"], judge_id,
                       dq_code="FALSE_START", call_notes="left early")
        notify_dq(dq["id"], referee_id)
        get_success_data(api.set_clock(CLOCK_MEET_DAY_1031, DIRECTOR))
        return workspace, dq

    def test_confirm_excludes_the_sanctioned_swim(self, api):
        """PRD §3.8: "Confirmation detonates a four-level cascade. The
        Disqualification itself settles at `CONFIRMED`; the EventEntry tied to
        the sanctioned lane moves to `DQ` — from `SEEDED` when the event has
        not yet completed, or from `FINISHED` after completion. If the event
        is already `COMPLETED`, that entry's Result is rewritten to
        `DQ_EXCLUDED` with its `place` set to null and its `points` to 0.00".

        Design: Difficulty/transitive_cascade/dq_confirm_rescore_cascade_depth4
        """
        workspace, dq = self._setup_completed_with_dq(api)
        referee_id = workspace["coverage"]["referee"]["id"]
        confirmed = validate_success(api.confirm_disqualification(
            dq["id"], make_meet_referee_headers(referee_id)))
        assert confirmed["status"] == "CONFIRMED"
        entry_a = get_success_data(
            api.get_entry(workspace["entries"][0]["id"], DIRECTOR))
        assert entry_a["status"] == "DQ", "hop 1: confirm -> entry DQ"
        results = get_success_data(
            api.get_entry_result(workspace["entries"][0]["id"], DIRECTOR))
        assert len(results) == 1
        assert results[0]["status"] == "DQ_EXCLUDED", \
            "hop 2: the sanctioned entry's Result is rewritten"
        assert results[0]["place"] is None
        assert results[0]["points"] == 0.0

    def test_confirm_rescores_survivors_and_team_totals(self, api):
        """PRD §3.8: "and the event is re-scored: the surviving `FINISHED`
        entries are re-placed from first through last and their points
        recomputed per the scoring rules of §3.9. The `provisional_points` of
        every affected team are then recomputed, and whenever a rescore occurs
        the event's `version` increments."

        Design: Difficulty/transitive_cascade/dq_confirm_rescore_cascade_depth4
        """
        workspace, dq = self._setup_completed_with_dq(api)
        referee_id = workspace["coverage"]["referee"]["id"]
        event_version_after_complete = get_success_data(
            api.get_event(workspace["event"]["id"], DIRECTOR))["version"]
        validate_success(api.confirm_disqualification(
            dq["id"], make_meet_referee_headers(referee_id)))
        # hop 3: surviving results promoted — B 2500 -> place 1 (9.00),
        # C 2510 -> place 2 (7.00).
        results_b = get_success_data(
            api.get_entry_result(workspace["entries"][1]["id"], DIRECTOR))
        results_c = get_success_data(
            api.get_entry_result(workspace["entries"][2]["id"], DIRECTOR))
        assert results_b[0]["place"] == 1
        assert results_b[0]["points"] == 9.0
        assert results_c[0]["place"] == 2
        assert results_c[0]["points"] == 7.0
        # hop 4: team rollups recomputed from the rows.
        team_x = get_success_data(
            api.get_team(workspace["teams"]["XXX"]["id"], DIRECTOR))
        team_y = get_success_data(
            api.get_team(workspace["teams"]["YYY"]["id"], DIRECTOR))
        assert team_x["provisional_points"] == 0.0
        assert team_y["provisional_points"] == 16.0
        event_after = get_success_data(
            api.get_event(workspace["event"]["id"], DIRECTOR))
        assert event_after["version"] == event_version_after_complete + 1, \
            "the rescore bumps the event version"
