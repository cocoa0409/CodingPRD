"""Creation defaults, computed swimmer fields, initial states, and request
envelope discipline (headers, required fields, enum/window sanity)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_event,
    add_swimmer,
    add_team,
    assert_meet,
    assert_swimmer,
    create_meet_payload,
    create_open_meet,
    get_success_data,
    make_team_coach_headers,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["meet_director_headers"]


class TestMeetCreationDefaults:
    def test_meet_creation_defaults_applied(self, api):
        """PRD §3.1: "The tuning knobs all carry defaults: `lane_count` defaults
        to 6 and fixes both the number of lanes per heat and the chunk size
        seeding works in; `points_table` defaults to `[9, 7, 6, 5, 4, 3, 2, 1]`
        — nine points for first place down to one point for eighth — and its
        length sets the scoring depth; `relay_points_multiplier` defaults to 2;
        `max_individual_entries_per_swimmer` defaults to 4;
        `dq_protest_window_minutes` defaults to 30; `min_recovery_minutes`
        defaults to 20; and `timing_delta_threshold_cs` defaults to 30
        centiseconds. The `scoring_tie_policy` is either `SPLIT` or `TOP`,
        defaults to `SPLIT`, and becomes immutable once the meet has been
        seeded. A new meet stands in `SETUP`."

        Design: Corner/entities/meet_creation_defaults_applied
        """
        resp = api.create_meet(create_meet_payload(meet_name="Defs"), DIRECTOR)
        meet = validate_success(resp, expected_status=201)
        assert_meet(meet)
        assert meet["lane_count"] == 6
        assert meet["points_table"] == [9, 7, 6, 5, 4, 3, 2, 1]
        assert meet["relay_points_multiplier"] == 2
        assert meet["max_individual_entries_per_swimmer"] == 4
        assert meet["dq_protest_window_minutes"] == 30
        assert meet["min_recovery_minutes"] == 20
        assert meet["timing_delta_threshold_cs"] == 30
        assert meet["scoring_tie_policy"] == "SPLIT"
        assert meet["status"] == "SETUP"


class TestSwimmerComputedFields:
    def test_birthday_on_start_date_counts(self, api):
        """PRD §3.1: "At registration the system derives `age_on_meet_start` as
        the swimmer's whole years from `birth_date` to the meet's `start_date`,
        counting a birthday that falls exactly on the start date — a swimmer
        born 2014-08-15 at a meet starting 2026-08-15 registers as twelve years
        old. From that age comes the `age_group`: ten or younger maps to
        `TEN_AND_UNDER`, eleven or twelve to `ELEVEN_TWELVE`, thirteen or
        fourteen to `THIRTEEN_FOURTEEN`, and fifteen or older to
        `FIFTEEN_AND_OVER`."

        Design: Corner/entities/swimmer_age_birthday_on_start_date_computed
        """
        meet = create_open_meet(meet_name="AgeM")
        team = add_team(meet["id"])
        resp = api.create_swimmer(
            {"team_id": team["id"], "full_name": "B Day",
             "birth_date": "2014-08-15", "gender": "F"},
            make_team_coach_headers(team["id"]))
        swimmer = validate_success(resp, expected_status=201)
        assert_swimmer(swimmer)
        assert swimmer["age_on_meet_start"] == 12
        assert swimmer["age_group"] == "ELEVEN_TWELVE"


class TestEntryInitialState:
    def test_new_entry_is_entered_and_unverified(self, api):
        """PRD §3.3: "A new entry stands `ENTERED` with `qualification_status`
        `UNVERIFIED`, and the team's `active_entry_count` is recomputed."

        Design: Corner/state_machines/entry_initial_state_entered_unverified
        """
        meet = create_open_meet(meet_name="IS1")
        team = add_team(meet["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw A")
        event = add_event(meet["id"], qualifying_time_cs=3000)
        resp = api.create_entry(
            {"event_id": event["id"], "swimmer_id": swimmer["id"],
             "seed_time_cs": 2900},
            make_team_coach_headers(team["id"]))
        entry = validate_success(resp, expected_status=201)
        assert entry["status"] == "ENTERED"
        assert entry["qualification_status"] == "UNVERIFIED"


class TestRequestEnvelopeDiscipline:
    def test_team_missing_required_field_rejected(self, api):
        """PRD §2.10: "Independently of this pipeline, malformed bodies, missing
        required fields, type mismatches, and invalid enum values are rejected
        with `ERR_INVALID_REQUEST` (HTTP 400) wherever they occur."
        PRD §3.1: "the director registers a Team with its `meet_id`, a
        `team_code` unique within the meet, and a `team_name`."

        Design: Corner/entities/team_missing_required_field_returns_invalid_request
        """
        meet = create_open_meet(meet_name="ReqM")
        resp = api.create_team(
            {"meet_id": meet["id"], "team_name": "No Code"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_event_unknown_stroke_enum_rejected(self, api):
        """PRD §2.10: "malformed bodies, missing required fields, type
        mismatches, and invalid enum values are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400) wherever they occur."
        PRD §3.2: "a `stroke` of `FREESTYLE`, `BACKSTROKE`, `BREASTSTROKE`,
        `BUTTERFLY`, `INDIVIDUAL_MEDLEY`, `FREESTYLE_RELAY`, or
        `MEDLEY_RELAY`"

        Design: Corner/entities/event_invalid_enum_returns_invalid_request
        """
        meet = create_open_meet(meet_name="EnumM")
        resp = api.create_event(
            {"meet_id": meet["id"], "event_number": 1, "gender": "M",
             "age_group": "ELEVEN_TWELVE", "stroke": "DOGGY_PADDLE",
             "distance_meters": 50, "is_relay": False,
             "session_date": "2026-08-15", "scheduled_start_minute": 540,
             "scheduled_end_minute": 570},
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_event_end_not_after_start_rejected(self, api):
        """PRD §3.2: "`scheduled_start_minute` and `scheduled_end_minute`
        position the race as minutes from midnight forming a half-open window
        — the start minute belongs to the event, the end minute does not — and
        the end must be strictly later than the start."
        PRD §2.10: "malformed bodies, missing required fields, type mismatches,
        and invalid enum values are rejected with `ERR_INVALID_REQUEST`
        (HTTP 400) wherever they occur."

        Design: Corner/entities/event_invalid_enum_returns_invalid_request
        """
        meet = create_open_meet(meet_name="EnumM2")
        resp = api.create_event(
            {"meet_id": meet["id"], "event_number": 2, "gender": "M",
             "age_group": "ELEVEN_TWELVE", "stroke": "FREESTYLE",
             "distance_meters": 50, "is_relay": False,
             "session_date": "2026-08-15", "scheduled_start_minute": 570,
             "scheduled_end_minute": 540},
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_missing_user_context_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity
        in which they act. A request missing either header, or carrying a role
        outside the declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/rbac/meet_create_missing_headers_unauthenticated
        """
        # Both headers omitted entirely.
        resp = api.create_meet(
            create_meet_payload(meet_name="NoHdr"), headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
