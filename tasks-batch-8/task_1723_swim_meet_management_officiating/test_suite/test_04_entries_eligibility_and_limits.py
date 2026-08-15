"""Entry admission: entry window, eligibility (team/age/gender), per-swimmer
entry cap, recovery buffer, and qualifying-time verification boundaries."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    CLOCK_PAST_DEADLINE,
    add_entry,
    add_event,
    add_swimmer,
    add_team,
    create_open_meet,
    get_success_data,
    make_team_coach_headers,
    seed_meet,
    validate_error,
    validate_success,
    verify_entry,
)

DIRECTOR = TEST_USERS["meet_director_headers"]


class TestEntryWindow:
    def test_entry_after_deadline_rejected(self, api):
        """PRD §3.3: "Independently, the logical clock must not have passed
        `entry_deadline_utc` — a submission landing exactly at the deadline
        instant is still accepted, while anything later fails with
        `ERR_ENTRY_DEADLINE_PASSED`."

        Design: Corner/errors/entry_after_deadline_returns_deadline_passed
        """
        meet = create_open_meet(meet_name="RE5")
        team = add_team(meet["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw A")
        event = add_event(meet["id"])
        get_success_data(api.set_clock(CLOCK_PAST_DEADLINE, DIRECTOR))
        # Meet still ENTRIES_OPEN (state gate passes); only the window fails.
        resp = api.create_entry(
            {"event_id": event["id"], "swimmer_id": swimmer["id"],
             "seed_time_cs": 2900},
            make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_ENTRY_DEADLINE_PASSED)


class TestEligibility:
    def test_age_group_mismatch_rejected(self, api):
        """PRD §3.3: "the swimmer's derived `age_group` must equal the event's
        `age_group` (`ERR_AGE_GROUP_INELIGIBLE`)".
        PRD §3.1: "thirteen or fourteen to `THIRTEEN_FOURTEEN`".

        Design: Corner/errors/age_group_mismatch_returns_ineligible
        """
        meet = create_open_meet(meet_name="RE6")
        team = add_team(meet["id"])
        # Born 2013-01-01, meet starts 2026-08-15 -> age 13 (THIRTEEN_FOURTEEN).
        swimmer = add_swimmer(team["id"], full_name="Sw Old",
                              birth_date="2013-01-01")
        event = add_event(meet["id"], age_group="ELEVEN_TWELVE")
        resp = api.create_entry(
            {"event_id": event["id"], "swimmer_id": swimmer["id"],
             "seed_time_cs": 2900},
            make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_AGE_GROUP_INELIGIBLE)

    def test_gender_mismatch_rejected(self, api):
        """PRD §3.3: "the swimmer's `gender` must match the event's `gender`
        unless the event is `MIXED`, which accepts any swimmer
        (`ERR_GENDER_INELIGIBLE`)."

        Design: Corner/errors/gender_mismatch_returns_ineligible
        """
        meet = create_open_meet(meet_name="RE7")
        team = add_team(meet["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw F", gender="F")
        event = add_event(meet["id"], gender="M")
        resp = api.create_entry(
            {"event_id": event["id"], "swimmer_id": swimmer["id"],
             "seed_time_cs": 2900},
            make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_GENDER_INELIGIBLE)

    def test_entry_for_withdrawn_team_rejected(self, api):
        """PRD §3.3: "the team must be `REGISTERED` (`ERR_TEAM_NOT_ACTIVE`)".
        PRD §2.10: "team standing first: a withdrawn club's swimmers are
        already inactive, so `ERR_TEAM_NOT_ACTIVE` always surfaces ahead of
        any swimmer-level failure".

        Design: Corner/errors/entry_for_withdrawn_team_rejected
        """
        meet = create_open_meet(meet_name="RE12")
        team = add_team(meet["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw A")
        event = add_event(meet["id"], qualifying_time_cs=3000)
        get_success_data(api.withdraw_team(team["id"], DIRECTOR))
        resp = api.create_entry(
            {"event_id": event["id"], "swimmer_id": swimmer["id"],
             "seed_time_cs": 2900},
            make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_TEAM_NOT_ACTIVE)


class TestEntryAggregateLimit:
    def test_fourth_entry_allowed_fifth_rejected(self, api):
        """PRD §3.3: "A swimmer may hold at most
        `max_individual_entries_per_swimmer` non-`SCRATCHED` individual entries
        in the meet — at the default of four, the fourth entry succeeds and the
        fifth is refused with `ERR_SWIMMER_ENTRY_LIMIT`."

        Design: Corner/validations/swimmer_entry_limit_four_ok_five_rejected
        """
        meet = create_open_meet(meet_name="LM1")
        team = add_team(meet["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw A")
        coach = make_team_coach_headers(team["id"])
        strokes = ["FREESTYLE", "BACKSTROKE", "BREASTSTROKE", "BUTTERFLY",
                   "INDIVIDUAL_MEDLEY"]
        events = []
        for i, stroke in enumerate(strokes):
            events.append(add_event(
                meet["id"], event_number=i + 1, stroke=stroke,
                distance_meters=100 if stroke == "INDIVIDUAL_MEDLEY" else 50,
                scheduled_start_minute=540 + i * 60,
                scheduled_end_minute=570 + i * 60))
        for event in events[:3]:
            resp = api.create_entry(
                {"event_id": event["id"], "swimmer_id": swimmer["id"]}, coach)
            validate_success(resp, expected_status=201)
        fourth = api.create_entry(
            {"event_id": events[3]["id"], "swimmer_id": swimmer["id"]}, coach)
        fourth_entry = validate_success(fourth, expected_status=201)
        assert fourth_entry["status"] == "ENTERED", "the 4th entry is allowed"
        fifth = api.create_entry(
            {"event_id": events[4]["id"], "swimmer_id": swimmer["id"]}, coach)
        validate_error(fifth, ApiErrorId.ERR_SWIMMER_ENTRY_LIMIT)


class TestRecoveryBuffer:
    """Difficulty pair: back-to-back events (gap 0) violate the buffer while a
    gap exactly equal to min_recovery_minutes is accepted."""

    def _setup(self, api):
        meet = create_open_meet(meet_name="OV2", min_recovery_minutes=20)
        team = add_team(meet["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw A")
        ev1 = add_event(meet["id"], event_number=1, stroke="FREESTYLE",
                        scheduled_start_minute=540, scheduled_end_minute=570)
        ev2 = add_event(meet["id"], event_number=2, stroke="BACKSTROKE",
                        scheduled_start_minute=570, scheduled_end_minute=590)
        ev3 = add_event(meet["id"], event_number=3, stroke="BREASTSTROKE",
                        scheduled_start_minute=590, scheduled_end_minute=610)
        add_entry(ev1["id"], swimmer["id"], team["id"], seed_time_cs=2900)
        return team, swimmer, ev1, ev2, ev3

    def test_back_to_back_events_rejected(self, api):
        """PRD §3.3: "the gap from the earlier event's end to the later event's
        start must be at least `min_recovery_minutes`, a gap exactly equal to
        the buffer is allowed, and any overlap between the two windows is
        always a violation, rejected as `ERR_RECOVERY_WINDOW_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/swimmer_recovery_buffer_vs_back_to_back
        """
        team, swimmer, _ev1, ev2, _ev3 = self._setup(api)
        # [570,590) starts the minute [540,570) ends: gap 0 < 20.
        resp = api.create_entry(
            {"event_id": ev2["id"], "swimmer_id": swimmer["id"],
             "seed_time_cs": 3100},
            make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_RECOVERY_WINDOW_VIOLATION)

    def test_gap_exactly_at_buffer_allowed(self, api):
        """PRD §3.3: "the gap from the earlier event's end to the later event's
        start must be at least `min_recovery_minutes`, a gap exactly equal to
        the buffer is allowed, and any overlap between the two windows is
        always a violation, rejected as `ERR_RECOVERY_WINDOW_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/swimmer_recovery_buffer_vs_back_to_back
        """
        team, swimmer, _ev1, _ev2, ev3 = self._setup(api)
        # [590,610) leaves a gap of exactly 20 minutes after [540,570).
        resp = api.create_entry(
            {"event_id": ev3["id"], "swimmer_id": swimmer["id"],
             "seed_time_cs": 3300},
            make_team_coach_headers(team["id"]))
        entry = validate_success(resp, expected_status=201)
        assert entry["status"] == "ENTERED"


class TestQualifyingTimeBoundary:
    """Difficulty pair: the <= boundary on seed_time_cs vs qualifying_time_cs."""

    def _setup(self, api):
        meet = create_open_meet(meet_name="BP1")
        team = add_team(meet["id"])
        swimmer_e = add_swimmer(team["id"], full_name="Sw E",
                                birth_date="2014-03-10")
        swimmer_f = add_swimmer(team["id"], full_name="Sw F",
                                birth_date="2014-04-11")
        event = add_event(meet["id"], qualifying_time_cs=3000)
        entry_e = add_entry(event["id"], swimmer_e["id"], team["id"],
                            seed_time_cs=3000)
        entry_f = add_entry(event["id"], swimmer_f["id"], team["id"],
                            seed_time_cs=3001)
        return entry_e, entry_f

    def test_seed_equal_to_cut_verifies(self, api):
        """PRD §3.3: "the entry verifies — moving to `VERIFIED` — if and only if
        its `seed_time_cs` is less than or equal to `qualifying_time_cs`, with
        a seed exactly equal to the cut qualifying".

        Design: Difficulty/boundary_precision_check/qualifying_time_equality_boundary
        """
        entry_e, _entry_f = self._setup(api)
        resp = api.verify_entry(entry_e["id"], DIRECTOR)
        entry = validate_success(resp)
        assert entry["qualification_status"] == "VERIFIED", \
            "seed exactly equal to the cut (3000 == 3000) qualifies"

    def test_seed_one_centisecond_slower_rejected(self, api):
        """PRD §3.3: "a slower seed, or an `NT` entry with nothing to compare
        against the cut, is marked `REJECTED`."

        Design: Difficulty/boundary_precision_check/qualifying_time_equality_boundary
        """
        _entry_e, entry_f = self._setup(api)
        resp = api.verify_entry(entry_f["id"], DIRECTOR)
        entry = validate_success(resp)
        assert entry["qualification_status"] == "REJECTED", \
            "3001 is one centisecond slower than the 3000 cut"


class TestVerificationWindow:
    def test_verify_after_seed_rejected(self, api):
        """PRD §3.3: "Verification is lawful only while the meet stands in
        `ENTRIES_OPEN` or `ENTRIES_CLOSED` and the entry stands `ENTERED`;
        otherwise it fails with `ERR_ENTRY_NOT_VERIFIABLE`."

        Design: Corner/errors/verify_after_seed_returns_not_verifiable
        """
        meet = create_open_meet(meet_name="RE8")
        team = add_team(meet["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw A")
        event = add_event(meet["id"], qualifying_time_cs=3000)
        entry = add_entry(event["id"], swimmer["id"], team["id"],
                          seed_time_cs=2900)
        verify_entry(entry["id"])
        seed_meet(meet["id"])  # meet SEEDED; the entry is SEEDED
        resp = api.verify_entry(entry["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_VERIFIABLE)
