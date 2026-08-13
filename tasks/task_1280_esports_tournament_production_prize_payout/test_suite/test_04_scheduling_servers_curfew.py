"""Match scheduling: curfew boundary, server windows, maintenance, cancel."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_tournament,
    api_client,
    confirm_result,
    create_server,
    create_talent,
    create_talent_booking,
    get_match,
    get_server,
    get_talent_booking,
    get_tournament,
    officiate_match,
    report_result,
    schedule_match,
    set_server_maintenance,
    setup_in_progress_2team,
    setup_seeded_tournament,
    transition_talent_booking,
    validate_error,
)

TD = TEST_USERS["tournament_director_headers"]

MINOR_TEAM_SPECS = [
    {"handle": "p1", "dob": "2010-06-15", "team_name": "Alpha", "rank": 100},
    {"handle": "p2", "dob": "2000-02-02", "team_name": "Beta", "rank": 80},
]

MINOR_4_TEAM_SPECS = [
    {"handle": "p1", "dob": "2010-06-15", "team_name": "Alpha", "rank": 100},
    {"handle": "p2", "dob": "2000-02-02", "team_name": "Beta", "rank": 80},
    {"handle": "p3", "dob": "2000-03-03", "team_name": "Gamma", "rank": 60},
    {"handle": "p4", "dob": "2000-04-04", "team_name": "Delta", "rank": 40},
]


class TestMinorCurfew:

    def test_curfew_exact_end_rejected_one_minute_before_allowed(self):
        """PRD §3.4: "The minor curfew rule then applies: if any `ACTIVE`
        roster slot of either participant has `is_minor` true, the UTC
        time-of-day of (`scheduled_start_at` plus `duration_minutes`) must be
        strictly before the tournament's `minor_curfew_local`; violation is
        rejected with `ERR_MINOR_CURFEW_VIOLATION`."

        Design: Difficulty/boundary_precision_check/curfew_exact_end_rejected
        """
        ctx = setup_seeded_tournament("Strict Curfew Cup",
                                      team_specs=MINOR_TEAM_SPECS)
        tournament_id = ctx["tournament"]["id"]
        server = create_server(tournament_id, "S1", "NA")
        match = ctx["matches"][0]

        resp = api_client.schedule_match(
            match["id"],
            {"server_id": server["id"],
             "scheduled_start_at": "2026-08-11T20:00:00Z",
             "duration_minutes": 120, "assigned_referee_id": "ref-1"},
            TD)
        validate_error(resp, ApiErrorId.ERR_MINOR_CURFEW_VIOLATION)
        assert get_match(match["id"])["status"] == "PENDING", \
            "an end exactly at 22:00 equals the curfew and is rejected"

        scheduled = schedule_match(match["id"], server["id"],
                                   "2026-08-11T20:00:00Z", 119, "ref-1")
        assert scheduled["status"] == "SCHEDULED", \
            "an end at 21:59 is strictly before the curfew and is allowed"

    def test_curfew_not_applied_without_minors(self):
        """PRD §3.4: "The minor curfew rule then applies: if any `ACTIVE`
        roster slot of either participant has `is_minor` true, the UTC
        time-of-day of (`scheduled_start_at` plus `duration_minutes`) must be
        strictly before the tournament's `minor_curfew_local`; violation is
        rejected with `ERR_MINOR_CURFEW_VIOLATION`."

        Design: Difficulty/boundary_precision_check/curfew_exact_end_rejected
        """
        ctx = setup_seeded_tournament("Adult Cup")
        tournament_id = ctx["tournament"]["id"]
        server = create_server(tournament_id, "S1", "NA")
        match = ctx["matches"][0]
        scheduled = schedule_match(match["id"], server["id"],
                                   "2026-08-11T20:30:00Z", 120, "ref-1")
        assert scheduled["status"] == "SCHEDULED", \
            "with no minor on either roster the curfew rule does not apply"


class TestScheduleValidationPriority:

    def test_curfew_error_beats_window_conflict(self):
        """PRD §2.9: "Business-safety rules (minor curfew, minor payee, tax
        threshold, segregation of duties) follow the state checks."
        PRD §2.9: "Business-constraint rules (uniqueness, roster shape,
        window overlaps, pause limit, participant, appeal budget, downstream
        bracket lock, server maintenance) come after safety."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_schedule
        """
        ctx = setup_seeded_tournament("Curfew Cup", team_count=4,
                                      team_specs=MINOR_4_TEAM_SPECS)
        tournament_id = ctx["tournament"]["id"]
        server = create_server(tournament_id, "S1", "NA")
        m1, m2 = ctx["matches"][0], ctx["matches"][1]
        # m2 (seed2 vs seed3, both adult rosters) occupies [21:00, 22:15).
        schedule_match(m2["id"], server["id"], "2026-08-11T21:00:00Z", 60,
                       "ref-1")
        # m1 (seed1, minor, vs seed4): violates the curfew (ends 23:30) AND
        # overlaps m2's buffered window; the safety error must surface.
        resp = api_client.schedule_match(
            m1["id"],
            {"server_id": server["id"],
             "scheduled_start_at": "2026-08-11T21:30:00Z",
             "duration_minutes": 120, "assigned_referee_id": "ref-1"},
            TD)
        validate_error(resp, ApiErrorId.ERR_MINOR_CURFEW_VIOLATION)
        assert get_match(m1["id"])["status"] == "PENDING"

    def test_window_conflict_without_curfew_violation(self):
        """PRD §3.4: "The server window overlap rule treats each booking as
        the half-open interval from start to (end plus 15 minutes of teardown
        buffer), where the end is `scheduled_start_at` plus
        `duration_minutes`: two such intervals on the same server must be
        disjoint, and adjacency where the next match starts exactly when the
        prior match's buffered window ends is allowed. A collision is
        rejected with `ERR_SERVER_WINDOW_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_schedule
        """
        ctx = setup_seeded_tournament("IsoCup", team_count=4,
                                      team_specs=MINOR_4_TEAM_SPECS)
        tournament_id = ctx["tournament"]["id"]
        server = create_server(tournament_id, "S1", "NA")
        m1, m2 = ctx["matches"][0], ctx["matches"][1]
        # m1 carries the minor and ends 11:00, safely before the 22:00
        # curfew; m2 (adults) overlaps m1's buffered window [10:00, 11:15).
        schedule_match(m1["id"], server["id"], "2026-08-11T10:00:00Z", 60,
                       "ref-1")
        resp = api_client.schedule_match(
            m2["id"],
            {"server_id": server["id"],
             "scheduled_start_at": "2026-08-11T10:30:00Z",
             "duration_minutes": 60, "assigned_referee_id": "ref-1"},
            TD)
        validate_error(resp, ApiErrorId.ERR_SERVER_WINDOW_CONFLICT)
        assert get_match(m2["id"])["status"] == "PENDING"


class TestServerWindowOverlap:

    def test_buffer_adjacency_allowed_one_minute_inside_rejected(self):
        """PRD §3.4: "The server window overlap rule treats each booking as
        the half-open interval from start to (end plus 15 minutes of teardown
        buffer), where the end is `scheduled_start_at` plus
        `duration_minutes`: two such intervals on the same server must be
        disjoint, and adjacency where the next match starts exactly when the
        prior match's buffered window ends is allowed. A collision is
        rejected with `ERR_SERVER_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/server_halfopen_buffer_adjacency
        """
        ctx = setup_seeded_tournament("Buffer Cup", team_count=4)
        tournament_id = ctx["tournament"]["id"]
        server = create_server(tournament_id, "S1", "NA")
        m1, m2 = ctx["matches"][0], ctx["matches"][1]
        # m2 occupies the half-open window [10:00, 11:15).
        schedule_match(m2["id"], server["id"], "2026-08-11T10:00:00Z", 60,
                       "ref-1")
        resp = api_client.schedule_match(
            m1["id"],
            {"server_id": server["id"],
             "scheduled_start_at": "2026-08-11T11:14:00Z",
             "duration_minutes": 60, "assigned_referee_id": "ref-1"},
            TD)
        validate_error(resp, ApiErrorId.ERR_SERVER_WINDOW_CONFLICT)

        scheduled = schedule_match(m1["id"], server["id"],
                                   "2026-08-11T11:15:00Z", 60, "ref-1")
        assert scheduled["status"] == "SCHEDULED", \
            "a start exactly at the prior buffered end is allowed"
        assert get_server(server["id"])["booked_minutes"] == 150, \
            "two 60-minute bookings plus two 15-minute buffers"

    def test_overlap_inside_window_rejected_other_server_free(self):
        """PRD §3.4: "two such intervals on the same server must be disjoint"
        PRD §3.4: "A collision is rejected with
        `ERR_SERVER_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/server_halfopen_buffer_adjacency
        """
        ctx = setup_seeded_tournament("TwoServer Cup", team_count=4)
        tournament_id = ctx["tournament"]["id"]
        s1 = create_server(tournament_id, "S1", "NA")
        s2 = create_server(tournament_id, "S2", "NA")
        m1, m2 = ctx["matches"][0], ctx["matches"][1]
        schedule_match(m1["id"], s1["id"], "2026-08-11T10:00:00Z", 60,
                       "ref-1")
        resp = api_client.schedule_match(
            m2["id"],
            {"server_id": s1["id"],
             "scheduled_start_at": "2026-08-11T10:30:00Z",
             "duration_minutes": 60, "assigned_referee_id": "ref-1"},
            TD)
        validate_error(resp, ApiErrorId.ERR_SERVER_WINDOW_CONFLICT)

        scheduled = schedule_match(m2["id"], s2["id"],
                                   "2026-08-11T10:30:00Z", 60, "ref-1")
        assert scheduled["status"] == "SCHEDULED", \
            "the window rule is per-server; another server is free"
        assert get_server(s1["id"])["booked_minutes"] == 75
        assert get_server(s2["id"])["booked_minutes"] == 75


class TestServerMaintenance:

    def test_schedule_blocked_in_maintenance_then_allowed_after_exit(self):
        """PRD §3.4: "the supplied `server_id` must reference a server that
        exists, belongs to the same tournament as the match, and is `ACTIVE`
        (a `MAINTENANCE` server yields `ERR_SERVER_IN_MAINTENANCE`)"
        PRD §3.4: "Maintenance is controlled by an `OrganizerAdmin` action of
        `ENTER` or `EXIT`, toggling the server between `ACTIVE` and
        `MAINTENANCE`"

        Design: Difficulty/cross_entity_state_dependency/schedule_blocked_by_server_maintenance
        """
        ctx = setup_seeded_tournament("Maint Cup")
        tournament_id = ctx["tournament"]["id"]
        server = create_server(tournament_id, "S1", "NA")
        match = ctx["matches"][0]

        set_server_maintenance(server["id"], "ENTER")
        resp = api_client.schedule_match(
            match["id"],
            {"server_id": server["id"],
             "scheduled_start_at": "2026-08-11T10:00:00Z",
             "duration_minutes": 60, "assigned_referee_id": "ref-1"},
            TD)
        validate_error(resp, ApiErrorId.ERR_SERVER_IN_MAINTENANCE)
        assert get_match(match["id"])["status"] == "PENDING"

        set_server_maintenance(server["id"], "EXIT")
        scheduled = schedule_match(match["id"], server["id"],
                                   "2026-08-11T10:00:00Z", 60, "ref-1")
        assert scheduled["status"] == "SCHEDULED"
        assert get_server(server["id"])["booked_minutes"] == 75

    def test_maintenance_enter_exit_toggle_roundtrip(self):
        """PRD §3.4: "Maintenance is controlled by an `OrganizerAdmin` action
        of `ENTER` or `EXIT`, toggling the server between `ACTIVE` and
        `MAINTENANCE`; entering maintenance is blocked while the server has
        matches in `LOBBY_OPEN`, `LIVE`, or `PAUSED`."
        PRD §3.4: "A new server starts `ACTIVE` with `booked_minutes` at 0."

        Design: Difficulty/cross_entity_state_dependency/schedule_blocked_by_server_maintenance
        """
        ctx = setup_seeded_tournament("Toggle Cup")
        tournament_id = ctx["tournament"]["id"]
        server = create_server(tournament_id, "S1", "NA")
        assert server["status"] == "ACTIVE"
        assert server["booked_minutes"] == 0
        assert server["version"] == 1

        maintenance = set_server_maintenance(server["id"], "ENTER")
        assert maintenance["status"] == "MAINTENANCE"
        assert maintenance["version"] == 2

        resp = api_client.schedule_match(
            ctx["matches"][0]["id"],
            {"server_id": server["id"],
             "scheduled_start_at": "2026-08-11T10:00:00Z",
             "duration_minutes": 60, "assigned_referee_id": "ref-1"},
            TD)
        validate_error(resp, ApiErrorId.ERR_SERVER_IN_MAINTENANCE)

        active = set_server_maintenance(server["id"], "EXIT")
        assert active["status"] == "ACTIVE"
        assert active["version"] == 3

        scheduled = schedule_match(ctx["matches"][0]["id"], server["id"],
                                   "2026-08-11T10:00:00Z", 60, "ref-1")
        assert scheduled["status"] == "SCHEDULED"


class TestScheduleInPast:

    def test_schedule_in_past_rejected(self):
        """PRD §3.4: "the supplied `scheduled_start_at` must be at or after
        the logical clock (a past instant yields `ERR_SCHEDULE_IN_PAST`)"

        Design: Corner/validations/schedule_in_past_rejected
        """
        ctx = setup_seeded_tournament("Past Cup")
        tournament_id = ctx["tournament"]["id"]
        server = create_server(tournament_id, "S1", "NA")
        match = ctx["matches"][0]
        # The logical clock sits at the 2026-08-10 lock instant.
        resp = api_client.schedule_match(
            match["id"],
            {"server_id": server["id"],
             "scheduled_start_at": "2026-08-09T10:00:00Z",
             "duration_minutes": 60, "assigned_referee_id": "ref-1"},
            TD)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_IN_PAST)
        assert get_match(match["id"])["status"] == "PENDING"


class TestBookedMinutesInvariant:

    def test_booked_minutes_released_on_forfeit(self):
        """PRD §3.4: "Matches in `PENDING`, `FORFEIT`, or `CANCELLED`
        contribute zero."
        PRD §3.5: "Forfeiting (`FORFEIT`) takes a `forfeiting_side` of `HOME`
        or `AWAY` and moves a `SCHEDULED` or `LOBBY_OPEN` match to `FORFEIT`;
        the winner becomes the other participant,
        `forfeiting_registration_id` is set to the forfeiting side,
        `completed_at` is set to the logical clock, and the dispute window is
        immediately closed (its close equals `completed_at`)."

        Design: Difficulty/compensating_invariant/server_minutes_conserved_across_forfeit
        """
        ctx = setup_in_progress_2team("Release Cup")
        server = ctx["server"]
        match = ctx["match"]
        assert get_server(server["id"])["booked_minutes"] == 75, \
            "60 scheduled minutes plus the 15-minute buffer"

        forfeited = officiate_match(
            match["id"], {"action": "FORFEIT", "forfeiting_side": "AWAY"})
        assert forfeited["status"] == "FORFEIT"
        r1, r2 = ctx["registrations"]
        assert forfeited["winner_registration_id"] == r1["id"]
        assert forfeited["forfeiting_registration_id"] == r2["id"]
        assert forfeited["dispute_window_closes_at"] == \
            forfeited["completed_at"], \
            "forfeits open no dispute window"
        assert get_server(server["id"])["booked_minutes"] == 0, \
            "the forfeit releases the booking and restores booked_minutes to 0"

    def test_booked_minutes_held_through_completed_and_confirmed(self):
        """PRD §3.4: "`booked_minutes` on a server is the sum over matches
        assigned to that server whose status is in {`SCHEDULED`,
        `LOBBY_OPEN`, `LIVE`, `PAUSED`, `COMPLETED`, `UNDER_DISPUTE`,
        `CONFIRMED`, `OVERTURNED`} of (`duration_minutes` plus 15 minutes of
        buffer)."

        Design: Difficulty/compensating_invariant/server_minutes_conserved_across_forfeit
        """
        ctx = setup_in_progress_2team("Hold Cup")
        server_id = ctx["server"]["id"]
        match_id = ctx["match"]["id"]
        assert get_server(server_id)["booked_minutes"] == 75
        officiate_match(match_id, {"action": "OPEN_LOBBY"})
        assert get_server(server_id)["booked_minutes"] == 75
        officiate_match(match_id, {"action": "START"})
        assert get_server(server_id)["booked_minutes"] == 75
        report_result(match_id, 13, 7)
        assert get_server(server_id)["booked_minutes"] == 75, \
            "COMPLETED remains in the booked set"
        confirm_result(match_id)
        assert get_server(server_id)["booked_minutes"] == 75, \
            "CONFIRMED remains in the booked set"


class TestTournamentCancelCascade:

    def test_tournament_cancel_cascades_to_matches_and_bookings(self):
        """PRD §3.6: "Cancelling from `SEEDED` cascades: every match in
        `PENDING` or `SCHEDULED` moves to `CANCELLED` and each affected
        server's `booked_minutes` is recomputed; every talent booking of the
        tournament in `TENTATIVE` or `CONFIRMED` moves to `CANCELLED`; the
        tournament's `version` increments."

        Design: Corner/state_machines/tournament_cancel_cascades_to_matches_and_bookings
        """
        ctx = setup_seeded_tournament("Cancel Cup", team_count=4)
        tournament_id = ctx["tournament"]["id"]
        server = create_server(tournament_id, "S1", "NA")
        m1 = ctx["matches"][0]
        schedule_match(m1["id"], server["id"], "2026-08-11T10:00:00Z", 60,
                       "ref-1")
        assert get_server(server["id"])["booked_minutes"] == 75

        talent = create_talent("CasterX", "NA", 80000)
        booking = create_talent_booking(
            tournament_id, talent["id"], "MAIN",
            "2026-08-11T09:00:00Z", "2026-08-11T12:00:00Z")
        transition_talent_booking(booking["id"], "CONFIRM")
        assert get_talent_booking(booking["id"])["status"] == "CONFIRMED"

        cancelled = advance_tournament(tournament_id, "CANCELLED")
        assert cancelled["status"] == "CANCELLED"

        matches = api_client.list_matches(
            TD, params={"tournament_id": tournament_id}).json()["data"]
        assert all(m["status"] == "CANCELLED" for m in matches)
        assert get_match(m1["id"])["status"] == "CANCELLED"
        assert get_server(server["id"])["booked_minutes"] == 0
        assert get_talent_booking(booking["id"])["status"] == "CANCELLED"
