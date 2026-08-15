"""Meet lifecycle posture gates, seeding preconditions, and meet-level OCC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    CLOCK_PAST_DEADLINE,
    add_entry,
    add_event,
    add_official,
    add_swimmer,
    add_team,
    api_client,
    confirm_assignment,
    create_meet,
    create_open_meet,
    get_success_data,
    make_team_coach_headers,
    open_meet,
    propose_assignment,
    seed_meet,
    setup_deck_coverage,
    setup_in_progress_event,
    start_event,
    validate_error,
    validate_success,
    verify_entry,
)

DIRECTOR = TEST_USERS["meet_director_headers"]


class TestMeetLifecyclePosture:
    def test_open_entries_twice_rejected(self, api):
        """PRD §3.1: "a lifecycle action attempted from a posture that forbids it
        — opening entries when the meet is not in `SETUP`, for instance — is
        rejected with `ERR_MEET_INVALID_STATE`."

        Design: Corner/state_machines/meet_open_entries_twice_invalid_state
        """
        meet = create_open_meet(meet_name="MM1")
        resp = api.open_entries(meet["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_MEET_INVALID_STATE)

    def test_close_entries_before_deadline_rejected(self, api):
        """PRD §3.1: "Closing entries requires the logical clock to have advanced
        strictly past `entry_deadline_utc`; entries are accepted inclusively at
        the deadline instant itself, so while the clock is at or before the
        deadline the close attempt fails with `ERR_ENTRY_WINDOW_STILL_OPEN`."
        PRD §2.4: "Before any explicit set, the logical clock reads exactly
        2026-08-01T00:00:00Z at server startup, and it never falls back to
        wall-clock time thereafter."

        Design: Corner/state_machines/close_entries_before_deadline_returns_window_open
        """
        meet = create_open_meet(meet_name="MM2")
        # Clock untouched: still the 2026-08-01 startup default, before the
        # 2026-08-10 entry deadline.
        resp = api.close_entries(meet["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_ENTRY_WINDOW_STILL_OPEN)

    def test_seed_while_entries_open_rejected(self, api):
        """PRD §3.6: "Posture itself requires the meet to stand in
        `ENTRIES_CLOSED` — seeding from anywhere else fails with
        `ERR_MEET_NOT_SEEDABLE`"

        Design: Corner/errors/seed_while_entries_open_returns_not_seedable
        """
        meet = create_open_meet(meet_name="RE4")
        resp = api.seed_meet(meet["id"], meet["version"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_MEET_NOT_SEEDABLE)

    def test_seed_blocked_by_undecided_qualification(self, api):
        """PRD §3.6: "every entry in the meet must hold a decided qualification,
        `VERIFIED` or `REJECTED`, because a single `UNVERIFIED` row blocks the
        write with `ERR_QUALIFICATION_UNDECIDED`."

        Design: Corner/validations/seed_blocked_undecided_qualification
        """
        meet = create_open_meet(meet_name="VQ1")
        team = add_team(meet["id"])
        swimmer_a = add_swimmer(team["id"], full_name="Sw A",
                                birth_date="2014-03-10")
        swimmer_b = add_swimmer(team["id"], full_name="Sw B",
                                birth_date="2014-04-11")
        event = add_event(meet["id"], qualifying_time_cs=3000)
        entry_a = add_entry(event["id"], swimmer_a["id"], team["id"],
                            seed_time_cs=2900)
        add_entry(event["id"], swimmer_b["id"], team["id"], seed_time_cs=2910)
        verify_entry(entry_a["id"])
        # swimmer_b's entry is deliberately left UNVERIFIED.
        get_success_data(api.set_clock(CLOCK_PAST_DEADLINE, DIRECTOR))
        closed = get_success_data(api.close_entries(meet["id"], DIRECTOR))
        resp = api.seed_meet(meet["id"], closed["version"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_QUALIFICATION_UNDECIDED)

    def test_event_start_blocked_until_meet_seeded(self, api):
        """PRD §3.7: "the meet must stand in `SEEDED` (`ERR_MEET_NOT_SEEDED`)".

        Design: Corner/errors/event_start_blocked_until_meet_seeded
        """
        meet = create_open_meet(meet_name="RE16")
        event = add_event(meet["id"])
        resp = api.start_event(event["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_MEET_NOT_SEEDED)

    def test_event_start_cancelled_event_rejected(self, api):
        """PRD §3.7: "the event itself must stand in `SEEDED`, so starting a
        `PENDING` or `CANCELLED` event fails with `ERR_EVENT_NOT_SEEDED`"
        PRD §3.6: "An event with no candidates moves straight to `CANCELLED`,
        its `version` incrementing, and processing continues with the next
        event."

        Design: Corner/errors/event_start_cancelled_returns_not_seeded
        """
        meet = create_open_meet(meet_name="RE3")
        event = add_event(meet["id"])
        seed_meet(meet["id"])  # zero candidates: the event is auto-CANCELLED
        seeded_event = get_success_data(api.get_event(event["id"], DIRECTOR))
        assert seeded_event["status"] == "CANCELLED"
        resp = api.start_event(event["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_SEEDED)

    def test_reopen_entries_blocked_when_event_underway(self, api):
        """PRD §3.6: "It is lawful only while no event of the meet has reached
        `IN_PROGRESS`, `COMPLETED`, or `OFFICIAL` — otherwise
        `ERR_EVENTS_ALREADY_UNDERWAY`"

        Design: Corner/errors/reopen_entries_blocked_when_event_underway
        """
        workspace = setup_in_progress_event(meet_name="RE14")
        resp = api.reopen_entries(workspace["meet"]["id"],
                                  "2026-08-12T00:00:00Z", DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_EVENTS_ALREADY_UNDERWAY)

    def test_coach_cannot_seed_meet(self, api):
        """PRD §4: `POST /meets/{id}/seed` is authorized for MeetDirector only.
        PRD §2.1: "An authenticated caller whose role is not permitted for an
        endpoint — or who fails an ownership check — is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/coach_cannot_seed_meet
        """
        meet = create_open_meet(meet_name="RB1")
        team = add_team(meet["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw A")
        event = add_event(meet["id"], qualifying_time_cs=3000)
        entry = add_entry(event["id"], swimmer["id"], team["id"],
                          seed_time_cs=2900)
        verify_entry(entry["id"])
        get_success_data(api.set_clock(CLOCK_PAST_DEADLINE, DIRECTOR))
        closed = get_success_data(api.close_entries(meet["id"], DIRECTOR))
        resp = api.seed_meet(meet["id"], closed["version"],
                             make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestSeedingAlgorithm:
    def test_heat_lane_order_and_rejected_exclusion(self, api):
        """PRD §3.6: "Heat construction counts the number of heats as the
        candidate count divided by the meet's `lane_count`, rounded up to a
        whole number. Heat numbers run from 1 — the slowest heat — up to the
        highest number, the fastest heat. Filling proceeds fastest-first: the
        fastest `lane_count` candidates form the highest-numbered heat, the
        next chunk the heat below it, and so on down to heat 1, which holds
        the remainder and may run partially filled."
        PRD §3.6: "Under the default six-lane pool the preference order is
        lane 3, then 4, then 2, then 5, then 1, then 6".
        PRD §3.6: "The candidate set for an event is its entries standing in
        `ENTERED` with qualification `VERIFIED`; `REJECTED` entries are never
        seeded and receive no lane assignment."
        PRD §3.3: "a slower seed, or an `NT` entry with nothing to compare
        against the cut, is marked `REJECTED`."

        Design: Corner/calculations/seeding_heat_lane_order_and_rejected_exclusion
        """
        meet = create_open_meet(meet_name="SD1")
        team = add_team(meet["id"])
        event = add_event(meet["id"], qualifying_time_cs=3000)
        entries = []
        # Seven timed entries 2400..2460, one NT (null seed), one 3001.
        seeds = [2400, 2410, 2420, 2430, 2440, 2450, 2460, None, 3001]
        for i, seed in enumerate(seeds):
            swimmer = add_swimmer(team["id"], full_name=f"S{i + 1:02d}",
                                  birth_date=f"2014-01-{i + 1:02d}")
            entry = add_entry(event["id"], swimmer["id"], team["id"],
                              seed_time_cs=seed)
            entries.append(entry)
        qualifications = [verify_entry(entry["id"])["qualification_status"]
                          for entry in entries]
        assert qualifications[7] == "REJECTED", \
            "an NT entry cannot satisfy a cut event"
        assert qualifications[8] == "REJECTED", "3001 is 1cs over the cut"

        seed_meet(meet["id"])

        # Seven verified candidates over six lanes -> heats 2 (fastest six)
        # and 1 (remainder); lanes dealt middle-out [3,4,2,5,1,6].
        placement = {}
        for entry in entries[:7]:
            lanes = get_success_data(api.list_lane_assignments(
                DIRECTOR, params={"entry_id": entry["id"]}))
            assert len(lanes) == 1
            placement[entry["id"]] = (lanes[0]["heat_number"],
                                      lanes[0]["lane_number"])
        assert placement[entries[0]["id"]] == (2, 3), \
            "fastest overall (2400) -> fastest heat, middle lane"
        assert placement[entries[5]["id"]] == (2, 6), \
            "6th fastest (2450) -> the lane-priority tail"
        assert placement[entries[6]["id"]] == (1, 3), \
            "the sole remainder swimmer (2460) leads the slowest heat"
        for entry in entries[7:]:
            lanes = get_success_data(api.list_lane_assignments(
                DIRECTOR, params={"entry_id": entry["id"]}))
            assert lanes == [], "REJECTED entries receive no lane assignment"
        rejected_entry = get_success_data(
            api.get_entry(entries[8]["id"], DIRECTOR))
        assert rejected_entry["status"] == "ENTERED", \
            "REJECTED entries are never seeded"


class TestMeetSeedOcc:
    def test_seed_with_stale_version_rejected(self, api):
        """PRD §2.7: "If the meet's current `version` has advanced since —
        because an intervening reopen-and-close cycle or an earlier successful
        seed moved it — the seed is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/complexity_layers/occ_meet_seed_stale_version
        """
        meet = create_open_meet(meet_name="OC1")
        team = add_team(meet["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw A")
        event = add_event(meet["id"], qualifying_time_cs=3000)
        entry = add_entry(event["id"], swimmer["id"], team["id"],
                          seed_time_cs=2900)
        verify_entry(entry["id"])
        get_success_data(api.set_clock(CLOCK_PAST_DEADLINE, DIRECTOR))
        closed = get_success_data(api.close_entries(meet["id"], DIRECTOR))
        stale_version = closed["version"]
        seeded = get_success_data(
            api.seed_meet(meet["id"], stale_version, DIRECTOR))
        assert seeded["status"] == "SEEDED", "first seed with the current version succeeds"
        # Reopen-and-close cycle advances the meet version twice more.
        get_success_data(api.reopen_entries(meet["id"],
                                            "2026-08-12T00:00:00Z", DIRECTOR))
        get_success_data(api.set_clock("2026-08-13T00:00:00Z", DIRECTOR))
        get_success_data(api.close_entries(meet["id"], DIRECTOR))
        resp = api.seed_meet(meet["id"], stale_version, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestEntryStateVsTemporalPriority:
    """One POST /entries violating both the state posture and the entry window
    must surface the state error (pipeline tier 6 precedes tier 8)."""

    def test_seeded_meet_and_past_deadline_reports_state_error(self, api):
        """PRD §2.10: "6. **State-machine posture** — the target resource stands
        in a state permitting the transition" precedes "8. **Entry window** —
        entry and relay creation against the logical clock
        (`ERR_ENTRY_DEADLINE_PASSED`)", and "A request failing two checks always
        reports the earlier tier's error."
        PRD §3.3: "Entries are accepted only while the meet stands in
        `ENTRIES_OPEN`; from any other posture the write fails with
        `ERR_MEET_NOT_ACCEPTING_ENTRIES`."

        Design: Difficulty/priority_pair_validation_conflict/entry_state_vs_temporal_priority
        """
        workspace_meet = create_open_meet(meet_name="PC1")
        team = add_team(workspace_meet["id"])
        swimmer_a = add_swimmer(team["id"], full_name="Sw A",
                                birth_date="2014-03-10")
        swimmer_b = add_swimmer(team["id"], full_name="Sw B",
                                birth_date="2014-04-11")
        event = add_event(workspace_meet["id"], qualifying_time_cs=3000)
        entry_a = add_entry(event["id"], swimmer_a["id"], team["id"],
                            seed_time_cs=2900)
        verify_entry(entry_a["id"])
        # Clock past the deadline AND meet no longer ENTRIES_OPEN (SEEDED):
        # both the state gate and the temporal gate fail.
        seed_meet(workspace_meet["id"])
        resp = api.create_entry(
            {"event_id": event["id"], "swimmer_id": swimmer_b["id"],
             "seed_time_cs": 2950},
            make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_MEET_NOT_ACCEPTING_ENTRIES)

    def test_closed_meet_and_past_deadline_reports_state_error(self, api):
        """PRD §2.10: "A request failing two checks always reports the earlier
        tier's error." — tier 6 "**State-machine posture** — the target
        resource stands in a state permitting the transition" masks tier 8
        "**Entry window** — entry and relay creation against the logical clock
        (`ERR_ENTRY_DEADLINE_PASSED`)".
        PRD §3.3: "Entries are accepted only while the meet stands in
        `ENTRIES_OPEN`; from any other posture the write fails with
        `ERR_MEET_NOT_ACCEPTING_ENTRIES`."

        Design: Difficulty/priority_pair_validation_conflict/entry_state_vs_temporal_priority
        """
        meet = create_open_meet(meet_name="PC1b")
        team = add_team(meet["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw A")
        event = add_event(meet["id"], qualifying_time_cs=3000)
        # ENTRIES_CLOSED with the clock past the deadline: both gates fail.
        get_success_data(api.set_clock(CLOCK_PAST_DEADLINE, DIRECTOR))
        get_success_data(api.close_entries(meet["id"], DIRECTOR))
        resp = api.create_entry(
            {"event_id": event["id"], "swimmer_id": swimmer["id"],
             "seed_time_cs": 2900},
            make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_MEET_NOT_ACCEPTING_ENTRIES)
