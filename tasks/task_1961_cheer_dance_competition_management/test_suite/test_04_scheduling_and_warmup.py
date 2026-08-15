"""Scheduling geometry, warm-up overlap/rest rules, release-and-rebook, and
the generate-schedule OCC guard."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_roster_entry,
    create_athlete,
    create_division,
    create_event,
    create_panel,
    create_team,
    create_warm_up_assignment_payload,
    generate_schedule,
    get_success_data,
    make_team_coach_headers,
    open_registration,
    setup_event_with_division,
    setup_registered_team,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["event_director_headers"]


def _setup_scheduled_division(api):
    """Division scheduled with one REGISTERED team (no music/lock needed).

    The team's SCHEDULED performance starts at 2026-09-05T10:00:00Z.
    """
    event, division, panel, head, safety = setup_event_with_division()
    team, athlete, entry = setup_registered_team(division, coach_id="coach-1")
    get_success_data(api.close_registration(event["id"], DIRECTOR))
    division = get_success_data(api.get_division(division["id"], DIRECTOR))
    generate_schedule(division["id"], division["version"])
    return event, division, team, athlete


class TestSchedulingGeometry:
    def test_performance_mat_buffer_pitch_and_mat_sufficiency(self, api):
        """PRD §3.4: "The **performance pitch** is
        `routine_time_limit_seconds` plus a 180-second transition buffer, in
        whole seconds. Teams are ordered by their `created_at` ascending —
        registration order — and receive `performance_order` values 1 through
        N. Each created **Performance** records its `team_id` and
        `division_id`, and its `scheduled_start` is the division's
        `schedule_start_at` plus (order − 1) pitches."
        PRD §3.1: "The division's `warmup_mats` is an ordered list of warm-up
        mat labels, and it must contain enough entries to cycle the warm-up
        pipeline: at least the warm-up duration divided by the performance
        pitch (the routine time limit plus a 180-second transition buffer),
        rounded up to a whole number."

        Design: Difficulty/resource_temporal_overlap/performance_mat_buffer_pitch_and_mat_sufficiency
        """
        event = create_event()
        panel, head, safety = create_panel(count=3)
        dv1 = create_division(event["id"], [j["id"] for j in panel])
        dv2 = create_division(event["id"], [j["id"] for j in panel],
                              name="D2", category="DANCE",
                              warmup_mats=["A", "B"],
                              schedule_start_at="2026-09-05T14:00:00Z")
        open_registration(event["id"])

        a1 = create_athlete("Ann", "2010-05-01", "coach-1")
        a2 = create_athlete("Bob", "2010-06-01", "coach-2")
        a3 = create_athlete("Cat", "2010-07-01", "coach-3")
        t1 = create_team(event["id"], dv1["id"], "coach-1", name="T1",
                         organization="Gym1")
        t2 = create_team(event["id"], dv1["id"], "coach-2", name="T2",
                         organization="Gym2")
        t3 = create_team(event["id"], dv2["id"], "coach-3", name="T3",
                         organization="Gym3", category="DANCE")
        add_roster_entry(t1["id"], a1["id"], "coach-1")
        add_roster_entry(t2["id"], a2["id"], "coach-2")
        add_roster_entry(t3["id"], a3["id"], "coach-3")

        get_success_data(api.close_registration(event["id"], DIRECTOR))

        # dv1 (3 mats >= ceil(900/330) = 3): generation succeeds, pitch 330s.
        dv1_fresh = get_success_data(api.get_division(dv1["id"], DIRECTOR))
        generate_schedule(dv1["id"], dv1_fresh["version"])
        p1, _ = validate_paginated(api.list_team_performances(t1["id"], DIRECTOR))
        p2, _ = validate_paginated(api.list_team_performances(t2["id"], DIRECTOR))
        assert p1[0]["scheduled_start"] == "2026-09-05T10:00:00Z"
        assert p1[0]["performance_order"] == 1
        assert p2[0]["scheduled_start"] == "2026-09-05T10:05:30Z"
        assert p2[0]["performance_order"] == 2

        # dv2 (2 mats < 3): rejected.
        dv2_fresh = get_success_data(api.get_division(dv2["id"], DIRECTOR))
        resp = api.generate_schedule(dv2["id"], dv2_fresh["version"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WARM_UP_MATS)

    def test_warmup_mat_half_open_interval_adjacency(self, api):
        """PRD §3.4: "Overlap is evaluated per (`event_id`, `mat`) pair over
        half-open intervals: a new window that intersects any `BOOKED`
        assignment on the same mat is rejected with `ERR_WARM_UP_OVERLAP`,
        while pure adjacency — one window's `ends_at` equal to the other's
        `starts_at` — does not overlap and is allowed."
        PRD §3.4: "for the team's `SCHEDULED` performance, the window's
        `ends_at` plus 600 seconds must not be later than that performance's
        `scheduled_start`; violating it is `ERR_MIN_REST_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/warmup_mat_half_open_interval_adjacency
        """
        event, division, team, athlete = _setup_scheduled_division(api)
        coach = make_team_coach_headers("coach-1")

        # [09:20, 09:35) then [09:35, 09:50): adjacency at 09:35 is legal, and
        # 09:50 + 600s == 10:00:00 satisfies the rest rule exactly.
        resp = api.create_warm_up_assignment(
            create_warm_up_assignment_payload(
                event["id"], team["id"], mat="M1",
                starts_at="2026-09-05T09:20:00Z",
                ends_at="2026-09-05T09:35:00Z"),
            coach)
        validate_success(resp, 201)
        resp = api.create_warm_up_assignment(
            create_warm_up_assignment_payload(
                event["id"], team["id"], mat="M1",
                starts_at="2026-09-05T09:35:00Z",
                ends_at="2026-09-05T09:50:00Z"),
            coach)
        validate_success(resp, 201)

        # [09:34, 09:40) intersects the first BOOKED window: rejected.
        resp = api.create_warm_up_assignment(
            create_warm_up_assignment_payload(
                event["id"], team["id"], mat="M1",
                starts_at="2026-09-05T09:34:00Z",
                ends_at="2026-09-05T09:40:00Z"),
            coach)
        validate_error(resp, ApiErrorId.ERR_WARM_UP_OVERLAP)

    def test_min_rest_rule_rejects_late_warmup(self, api):
        """PRD §3.4: "for the team's `SCHEDULED` performance, the window's
        `ends_at` plus 600 seconds must not be later than that performance's
        `scheduled_start`; violating it is `ERR_MIN_REST_VIOLATION`."

        Design: Corner/endpoints/min_rest_rule_rejects_late_warmup
        """
        event, division, team, athlete = _setup_scheduled_division(api)
        coach = make_team_coach_headers("coach-1")

        # 09:55:00 + 600s = 10:05:00 > 10:00:00 scheduled_start.
        resp = api.create_warm_up_assignment(
            create_warm_up_assignment_payload(
                event["id"], team["id"], mat="M9",
                starts_at="2026-09-05T09:40:00Z",
                ends_at="2026-09-05T09:55:00Z"),
            coach)
        validate_error(resp, ApiErrorId.ERR_MIN_REST_VIOLATION)

    def test_warmup_release_then_rebook_same_interval(self, api):
        """PRD §3.4: "Either the coach who owns the team may later
        **release** a `BOOKED` assignment (moving it to `RELEASED` and freeing
        the interval for future overlap checks)"

        Design: Corner/endpoints/warmup_release_then_rebook_same_interval
        """
        event, division, team, athlete = _setup_scheduled_division(api)
        coach = make_team_coach_headers("coach-1")

        first = get_success_data(api.create_warm_up_assignment(
            create_warm_up_assignment_payload(
                event["id"], team["id"], mat="M1",
                starts_at="2026-09-05T09:20:00Z",
                ends_at="2026-09-05T09:35:00Z"),
            coach))

        released = get_success_data(
            api.release_warm_up_assignment(first["id"], coach))
        assert released["status"] == "RELEASED"

        # The identical interval is bookable again once RELEASED.
        resp = api.create_warm_up_assignment(
            create_warm_up_assignment_payload(
                event["id"], team["id"], mat="M1",
                starts_at="2026-09-05T09:20:00Z",
                ends_at="2026-09-05T09:35:00Z"),
            coach)
        validate_success(resp, 201)


class TestGenerateScheduleGates:
    def test_generate_schedule_on_empty_division_rejected(self, api):
        """PRD §3.4: "Generation requires at least one eligible team in the
        division — teams whose `reg_status` is `REGISTERED`, `ROSTER_LOCKED`,
        or `CHECKED_IN` — else `ERR_DIVISION_HAS_NO_TEAMS`"
        PRD §3.4: "When both fail, the no-teams rejection takes precedence and
        the mats check is reported second."

        Design: Corner/errors/generate_schedule_on_empty_division_rejected
        """
        event, division, panel, head, safety = setup_event_with_division()
        get_success_data(api.close_registration(event["id"], DIRECTOR))
        division = get_success_data(api.get_division(division["id"], DIRECTOR))

        resp = api.generate_schedule(division["id"], division["version"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_DIVISION_HAS_NO_TEAMS)
        after = get_success_data(api.get_division(division["id"], DIRECTOR))
        assert after["scheduled"] is False

    def test_occ_generate_schedule_stale_division_version(self, api):
        """PRD §2.5: "Regenerating a division's schedule requires
        `expected_division_version` as a non-optional input field, carrying
        the client's last observed `version` of the `Division`. If another
        writer has advanced the division's version since the client last read
        it — a prior regeneration, or any other division mutation — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/complexity_layers/occ_generate_schedule_stale_division_version
        """
        event, division, panel, head, safety = setup_event_with_division()
        team, athlete, entry = setup_registered_team(division, coach_id="coach-1")
        get_success_data(api.close_registration(event["id"], DIRECTOR))
        stale_version = division["version"]

        first = get_success_data(
            api.generate_schedule(division["id"], stale_version, DIRECTOR))
        assert first["version"] == stale_version + 1

        resp = api.generate_schedule(division["id"], stale_version, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestOverlapSecondAngles:
    def test_warmup_overlap_scoped_per_mat(self, api):
        """PRD §3.4: "Overlap is evaluated per (`event_id`, `mat`) pair over
        half-open intervals: a new window that intersects any `BOOKED`
        assignment on the same mat is rejected with `ERR_WARM_UP_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/warmup_mat_half_open_interval_adjacency
        """
        event, division, team, athlete = _setup_scheduled_division(api)
        coach = make_team_coach_headers("coach-1")

        # Same interval on two different mats: no collision (overlap is
        # scoped per (event_id, mat)).
        validate_success(api.create_warm_up_assignment(
            create_warm_up_assignment_payload(
                event["id"], team["id"], mat="M1",
                starts_at="2026-09-05T09:20:00Z",
                ends_at="2026-09-05T09:35:00Z"),
            coach), 201)
        validate_success(api.create_warm_up_assignment(
            create_warm_up_assignment_payload(
                event["id"], team["id"], mat="M2",
                starts_at="2026-09-05T09:20:00Z",
                ends_at="2026-09-05T09:35:00Z"),
            coach), 201)

    def test_warmup_pitch_creates_system_assignments_with_rest(self, api):
        """PRD §3.4: "Team number *n* warms up on the mat at position
        (n − 1) modulo the number of `warmup_mats`, in a half-open window
        that ends 600 seconds (ten minutes of mandatory rest) before its
        `scheduled_start` and begins `warmup_duration_seconds` before that.
        These system-created **WarmUpAssignment** rows carry `source` of
        `SYSTEM`"

        Design: Difficulty/resource_temporal_overlap/performance_mat_buffer_pitch_and_mat_sufficiency
        """
        event = create_event()
        panel, head, safety = create_panel(count=3)
        division = create_division(event["id"], [j["id"] for j in panel])
        open_registration(event["id"])
        team, athlete, entry = setup_registered_team(division, coach_id="coach-1")
        get_success_data(api.close_registration(event["id"], DIRECTOR))
        division = get_success_data(api.get_division(division["id"], DIRECTOR))
        generate_schedule(division["id"], division["version"])

        assignments, _ = validate_paginated(
            api.list_team_warm_up_assignments(team["id"], DIRECTOR))
        assert len(assignments) == 1
        warmup = assignments[0]
        assert warmup["source"] == "SYSTEM"
        assert warmup["mat"] == "A"  # position (1-1) mod 3
        assert warmup["status"] == "BOOKED"
        # Window ends 600s before the 10:00:00 performance and starts
        # warmup_duration_seconds (900) earlier: [09:35:00, 09:50:00).
        assert warmup["starts_at"] == "2026-09-05T09:35:00Z"
        assert warmup["ends_at"] == "2026-09-05T09:50:00Z"
