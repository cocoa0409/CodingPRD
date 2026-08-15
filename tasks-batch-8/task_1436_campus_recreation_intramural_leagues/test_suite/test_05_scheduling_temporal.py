"""Game scheduling: temporal gates, facility fit, half-open overlap rules,
league/facility OCC guards, and reschedule visibility (PRD §2.5, §2.10,
§3.3)."""
from datetime import datetime

from test_helpers import (
    COORDINATOR,
    FACILITY_MANAGER,
    REC_ADMIN,
    ApiErrorId,
    api_client,
    close_league,
    create_closure,
    create_closure_payload,
    create_eligible_member,
    create_facility,
    create_game_payload,
    create_team,
    make_member_headers,
    open_league_context,
    place_team,
    schedule_game,
    season_context,
    season_game_context,
    set_clock,
    start_season,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    create_class,
    create_instructor,
    create_official,
    game_with_accepted_official,
    register_for_class,
)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_adjacent_game_at_previous_end_allowed():
    """PRD §2.10: "A booking that overlaps another `SCHEDULED` game or
    `SCHEDULED` fitness class at the same facility is rejected with
    `ERR_FACILITY_DOUBLE_BOOKED` (HTTP 409); bookings are half-open intervals,
    so adjacency — one booking's end equal to the other's start — is allowed
    with no buffer."

    Design: Difficulty/resource_temporal_overlap/facility_half_open_adjacency_overlap
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_context(num_teams=4)
    schedule_game(ctx["league"]["id"], ctx["teams"][0]["id"],
                  ctx["teams"][1]["id"], ctx["facility"]["id"],
                  "2026-09-08T18:00:00Z", "2026-09-08T19:30:00Z")
    # g2 starts exactly when g1 ends: adjacency is allowed.
    g2 = schedule_game(ctx["league"]["id"], ctx["teams"][2]["id"],
                       ctx["teams"][3]["id"], ctx["facility"]["id"],
                       "2026-09-08T19:30:00Z", "2026-09-08T21:00:00Z")
    assert g2["status"] == "SCHEDULED"


def test_one_minute_overlap_rejected_facility_check_first():
    """PRD §2.10: "A booking that overlaps another `SCHEDULED` game or
    `SCHEDULED` fitness class at the same facility is rejected with
    `ERR_FACILITY_DOUBLE_BOOKED` (HTTP 409); bookings are half-open intervals,
    so adjacency — one booking's end equal to the other's start — is allowed
    with no buffer."
    PRD §2.8: "Temporal checks, in this fixed sub-order: `ERR_GAME_IN_PAST`,
    then `ERR_FACILITY_OUTSIDE_HOURS`, then `ERR_FACILITY_CLOSED`, then
    `ERR_FACILITY_DOUBLE_BOOKED`, then `ERR_TEAM_TIME_CONFLICT`, then
    `ERR_CLASS_TIME_CONFLICT`, then `ERR_OFFICIAL_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/facility_half_open_adjacency_overlap
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_context(num_teams=4)
    schedule_game(ctx["league"]["id"], ctx["teams"][0]["id"],
                  ctx["teams"][1]["id"], ctx["facility"]["id"],
                  "2026-09-08T18:00:00Z", "2026-09-08T19:30:00Z")
    schedule_game(ctx["league"]["id"], ctx["teams"][2]["id"],
                  ctx["teams"][3]["id"], ctx["facility"]["id"],
                  "2026-09-08T19:30:00Z", "2026-09-08T21:00:00Z")
    # 19:29 start overlaps g1 by one minute (and also team-conflicts with g2):
    # the facility check precedes the team check in the pinned sub-order.
    league = validate_success(api_client.get_league(
        ctx["league"]["id"], COORDINATOR))
    resp = api_client.create_game(
        ctx["league"]["id"],
        create_game_payload(
            ctx["teams"][2]["id"], ctx["teams"][3]["id"],
            ctx["facility"]["id"], league["version"],
            start_at="2026-09-08T19:29:00Z", end_at="2026-09-08T21:00:00Z"),
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_DOUBLE_BOOKED)


def test_error_game_in_past():
    """PRD §3.3: "The `start_at` must be at or after the logical now
    (otherwise `ERR_GAME_IN_PAST`, HTTP 422), `end_at` must be strictly after
    `start_at` and on the same local date, and the slot must satisfy §2.10's
    facility fit, closure, and double-booking rules."

    Design: Corner/errors/error_game_in_past
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_context(num_teams=2)
    set_clock("2026-09-08T18:00:00Z")
    league = validate_success(api_client.get_league(
        ctx["league"]["id"], COORDINATOR))
    resp = api_client.create_game(
        ctx["league"]["id"],
        create_game_payload(
            ctx["teams"][0]["id"], ctx["teams"][1]["id"],
            ctx["facility"]["id"], league["version"],
            start_at="2026-09-08T17:59:00Z", end_at="2026-09-08T19:00:00Z"),
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_GAME_IN_PAST)


def test_error_facility_outside_hours():
    """PRD §2.10: "The facility's `operating_windows` — recurring weekly
    windows, each a `day_of_week` (0 for Monday through 6 for Sunday) with
    `open_minute` and `close_minute` expressed as minutes after midnight,
    where the open minute is at least 0 and strictly before the close minute,
    which is at most 1440 — must contain a window matching the booking's
    weekday such that the booking's start minute is at or after `open_minute`
    and its end minute is at or before `close_minute`; ending exactly at the
    close minute is allowed. A booking that fits no single window is rejected
    with `ERR_FACILITY_OUTSIDE_HOURS` (HTTP 422)."

    Design: Corner/errors/error_facility_outside_hours
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_context(num_teams=2)
    league = validate_success(api_client.get_league(
        ctx["league"]["id"], COORDINATOR))
    # 21:30-22:30 ends past the 22:00 close of the 17:00-22:00 window.
    resp = api_client.create_game(
        ctx["league"]["id"],
        create_game_payload(
            ctx["teams"][0]["id"], ctx["teams"][1]["id"],
            ctx["facility"]["id"], league["version"],
            start_at="2026-09-08T21:30:00Z", end_at="2026-09-08T22:30:00Z"),
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_OUTSIDE_HOURS)


def test_error_facility_closed_half_open_boundary():
    """PRD §2.10: "A booking that overlaps any closure interval is rejected
    with `ERR_FACILITY_CLOSED` (HTTP 409): closures are half-open intervals
    from their start up to but not including their end, so a booking overlaps
    a closure when the booking starts before the closure ends and the closure
    starts before the booking ends; a booking starting exactly at a closure's
    end is allowed."

    Design: Corner/errors/error_facility_closed
    """
    set_clock("2026-08-24T00:00:00Z")
    facility = create_facility()
    create_closure(facility, "2026-09-08T17:00:00Z", "2026-09-08T21:00:00Z",
                   reason="refinish")
    ctx = season_context(num_teams=2, with_facility=False)
    league = validate_success(api_client.get_league(
        ctx["league"]["id"], COORDINATOR))
    # 20:59 start overlaps the closure's final minute.
    resp = api_client.create_game(
        ctx["league"]["id"],
        create_game_payload(
            ctx["teams"][0]["id"], ctx["teams"][1]["id"], facility["id"],
            league["version"], start_at="2026-09-08T20:59:00Z",
            end_at="2026-09-08T21:30:00Z"),
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_CLOSED)
    # 21:00 start == closure end: the closure's end instant is free.
    game = schedule_game(ctx["league"]["id"], ctx["teams"][0]["id"],
                         ctx["teams"][1]["id"], facility["id"],
                         "2026-09-08T21:00:00Z", "2026-09-08T21:45:00Z")
    assert game["status"] == "SCHEDULED"


def test_error_team_time_conflict():
    """PRD §3.3: "Neither team may already have a `SCHEDULED` game whose
    half-open interval overlaps the candidate at any facility
    (`ERR_TEAM_TIME_CONFLICT`)."

    Design: Corner/errors/error_team_time_conflict
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_context(num_teams=2)
    other_facility = create_facility(name="Court 2")
    schedule_game(ctx["league"]["id"], ctx["teams"][0]["id"],
                  ctx["teams"][1]["id"], ctx["facility"]["id"],
                  "2026-09-08T18:00:00Z", "2026-09-08T19:30:00Z")
    league = validate_success(api_client.get_league(
        ctx["league"]["id"], COORDINATOR))
    # Different facility, so the facility checks pass; the team overlap rules
    # it out (19:00 < 19:30).
    resp = api_client.create_game(
        ctx["league"]["id"],
        create_game_payload(
            ctx["teams"][0]["id"], ctx["teams"][1]["id"],
            other_facility["id"], league["version"],
            start_at="2026-09-08T19:00:00Z", end_at="2026-09-08T20:30:00Z"),
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_TEAM_TIME_CONFLICT)


def test_error_teams_not_in_same_division():
    """PRD §3.3: "The two teams must differ (`home_team_id` equal to
    `away_team_id` is `ERR_VALIDATION`) and must share the same non-null
    `division_name` (otherwise `ERR_TEAMS_NOT_IN_SAME_DIVISION`); the game
    records that shared division as its own `division_name`."

    Design: Corner/errors/error_teams_not_in_same_division
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = open_league_context(divisions=[
        {"name": "East", "capacity": 2, "skill_min": 1, "skill_max": 10},
        {"name": "West", "capacity": 2, "skill_min": 1, "skill_max": 10},
    ])
    captain_a = create_eligible_member("ca@x.edu", full_name="Cap A")
    team_a = create_team(ctx["league"]["id"], "Alpha", captain_a["id"])
    validate_success(api_client.add_roster_entry(
        team_a["id"], {"member_id": captain_a["id"]},
        make_member_headers(captain_a["id"])), 201)
    captain_b = create_eligible_member("cb@x.edu", full_name="Cap B")
    team_b = create_team(ctx["league"]["id"], "Beta", captain_b["id"])
    validate_success(api_client.add_roster_entry(
        team_b["id"], {"member_id": captain_b["id"]},
        make_member_headers(captain_b["id"])), 201)
    close_league(ctx["league"]["id"])
    place_team(team_a["id"], "East")
    place_team(team_b["id"], "West")
    league = start_season(ctx["league"]["id"])
    resp = api_client.create_game(
        league["id"],
        create_game_payload(
            team_a["id"], team_b["id"], ctx["facility"]["id"],
            league["version"], start_at="2026-09-08T18:00:00Z",
            end_at="2026-09-08T19:30:00Z"),
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_TEAMS_NOT_IN_SAME_DIVISION)


def test_create_response_immediate_computed_fields():
    """PRD §3.3: "A created game is born `SCHEDULED` with `bracket_round`
    `REGULAR`; its `duration_minutes` is the difference between `end_at` and
    `start_at` in minutes; `report_home`, `report_away`, `final_home_score`,
    `final_away_score`, `actual_duration_minutes`, `forfeiting_team_id`, and
    `next_game_id` are all null. Creating the game increments the league's
    `version`."
    PRD §3.3: "The two teams must differ (`home_team_id` equal to
    `away_team_id` is `ERR_VALIDATION`) and must share the same non-null
    `division_name` (otherwise `ERR_TEAMS_NOT_IN_SAME_DIVISION`); the game
    records that shared division as its own `division_name`."

    Design: Corner/endpoints/create_response_immediate_computed_fields
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_context(num_teams=2)
    league = validate_success(api_client.get_league(
        ctx["league"]["id"], COORDINATOR))
    data = validate_success(api_client.create_game(
        ctx["league"]["id"],
        create_game_payload(
            ctx["teams"][0]["id"], ctx["teams"][1]["id"],
            ctx["facility"]["id"], league["version"],
            start_at="2026-09-08T18:00:00Z", end_at="2026-09-08T19:30:00Z"),
        COORDINATOR,
    ), 201)
    assert data["status"] == "SCHEDULED"
    assert data["bracket_round"] == "REGULAR"
    assert data["duration_minutes"] == 90
    assert data["division_name"] == "A"


def test_occ_game_schedule_stale_league():
    """PRD §2.5: "Scheduling a game within a league must carry
    `expected_league_version` equal to the league's current `version`;
    scheduling mutates the league aggregate and increments `League.version`,
    and a stale expectation means the client's view of existing games and
    division loads is out of date. Two games at disjoint times are both
    legitimate — only the stale view is rejected, with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_game_schedule_stale_league
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_context(num_teams=2)
    league = validate_success(api_client.get_league(
        ctx["league"]["id"], COORDINATOR))
    stale_version = league["version"]
    validate_success(api_client.create_game(
        ctx["league"]["id"],
        create_game_payload(
            ctx["teams"][0]["id"], ctx["teams"][1]["id"],
            ctx["facility"]["id"], stale_version,
            start_at="2026-09-08T18:00:00Z", end_at="2026-09-08T19:30:00Z"),
        COORDINATOR,
    ), 201)
    # The first create bumped League.version; reusing the observation fails.
    resp = api_client.create_game(
        ctx["league"]["id"],
        create_game_payload(
            ctx["teams"][0]["id"], ctx["teams"][1]["id"],
            ctx["facility"]["id"], stale_version,
            start_at="2026-09-10T18:00:00Z", end_at="2026-09-10T19:30:00Z"),
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    # The same payload with the current version succeeds.
    game = schedule_game(ctx["league"]["id"], ctx["teams"][0]["id"],
                         ctx["teams"][1]["id"], ctx["facility"]["id"],
                         "2026-09-10T18:00:00Z", "2026-09-10T19:30:00Z")
    assert game["status"] == "SCHEDULED"


def test_occ_closure_stale_facility():
    """PRD §2.5: "Creating a closure on a facility must carry
    `expected_facility_version` equal to the facility's current `version`; a
    closure bumps games and classes out of its window, and the set of
    colliding bookings may have changed since the client last read the
    facility. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_closure_stale_facility
    """
    set_clock("2026-08-24T00:00:00Z")
    facility = create_facility()
    assert facility["version"] == 1
    create_closure(facility, "2026-09-08T17:00:00Z", "2026-09-08T21:00:00Z",
                   reason="burst pipe")
    resp = api_client.create_closure(
        facility["id"],
        create_closure_payload(
            1, start_at="2026-09-15T17:00:00Z",
            end_at="2026-09-15T21:00:00Z", reason="floor refinish"),
        FACILITY_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    fresh = validate_success(api_client.get_facility(
        facility["id"], FACILITY_MANAGER))
    data = validate_success(api_client.create_closure(
        facility["id"],
        create_closure_payload(
            fresh["version"], start_at="2026-09-15T17:00:00Z",
            end_at="2026-09-15T21:00:00Z", reason="floor refinish"),
        FACILITY_MANAGER,
    ), 201)
    assert data["version"] == 3
    assert len(data["closures"]) == 2


def test_immediate_visibility_after_reschedule():
    """PRD §3.3: "A successful reschedule leaves the game `SCHEDULED` with
    `start_at`, `end_at`, and `facility_id` replaced and `duration_minutes`
    recomputed."
    PRD §2.5: "Every resource carries an `id` that is a server-minted UUID
    with no type prefix, a `created_at` timestamp, and an `updated_at`
    timestamp, both ISO 8601 UTC with three fractional digits, plus a
    `version` integer that starts at 1 and increments by 1 on every mutation
    of that resource."

    Design: Corner/consistency_model/immediate_visibility_after_reschedule
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_game_context()
    game = ctx["game"]
    create_closure(ctx["facility"], "2026-09-08T17:00:00Z",
                   "2026-09-08T21:00:00Z", reason="burst pipe")
    bumped = validate_success(api_client.get_game(game["id"], COORDINATOR))
    assert bumped["status"] == "RESCHEDULE_REQUIRED"
    moved = validate_success(api_client.reschedule_game(
        game["id"],
        {"start_at": "2026-09-10T18:00:00Z",
         "end_at": "2026-09-10T19:30:00Z"},
        COORDINATOR,
    ))
    assert moved["status"] == "SCHEDULED"
    assert moved["duration_minutes"] == 90
    assert moved["version"] > bumped["version"]
    reread = validate_success(api_client.get_game(game["id"], COORDINATOR))
    # PRD pins the replaced instant, not its string rendering (the
    # three-fractional-digit format rule of §2.5 covers created_at/updated_at,
    # not domain datetimes) — compare as parsed instants.
    assert _parse_iso(reread["start_at"]) == _parse_iso("2026-09-10T18:00:00Z")
    assert reread["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Facility-closure deep cascade and the game-state gate on assignments
# (PRD §3.6, §3.9)
# ---------------------------------------------------------------------------

CLOSURE_START = "2026-09-08T17:00:00Z"
CLOSURE_END = "2026-09-08T21:00:00Z"


def _closure_context():
    """IN_SEASON game (Tue 18:00-19:30) with an ACCEPTED L2 official
    (provisional 3750 pending), plus a SCHEDULED YOGA class (19:30-20:30) at
    the same facility with one REGISTERED member; clock at 2026-09-07."""
    set_clock("2026-08-24T00:00:00Z")
    ctx = game_with_accepted_official(cert=2, rate=2000)
    instructor = create_instructor(rate=3000, class_types=("YOGA",))
    fclass = create_class(
        instructor["id"], ctx["facility"]["id"],
        start_at="2026-09-08T19:30:00Z", end_at="2026-09-08T20:30:00Z",
        capacity=5,
    )
    member = create_eligible_member("yy@x.edu", full_name="Yo Ga")
    registration = register_for_class(fclass["id"], member)
    ctx["instructor"] = instructor
    ctx["class"] = fclass
    ctx["registration"] = registration
    set_clock("2026-09-07T09:00:00Z")
    return ctx


def test_closure_bumps_game_and_cancels_assignment_with_pay_reversal():
    """PRD §3.9: "When a closure is created, every `SCHEDULED` game whose
    half-open interval overlaps the closure moves to `RESCHEDULE_REQUIRED`,
    and its `ASSIGNED` or `ACCEPTED` officiating assignments are `CANCELLED`
    with each provisional amount subtracted from the official's
    `payroll_pending_cents`."

    Design: Difficulty/transitive_cascade/facility_closure_three_level_cascade
    """
    ctx = _closure_context()
    staff_mid = validate_success(api_client.get_staff(
        ctx["official"]["id"], REC_ADMIN))
    assert staff_mid["payroll_pending_cents"] == 3750

    create_closure(ctx["facility"], CLOSURE_START, CLOSURE_END,
                   reason="burst pipe")
    game = validate_success(api_client.get_game(
        ctx["game"]["id"], FACILITY_MANAGER))
    assert game["status"] == "RESCHEDULE_REQUIRED", (
        "the [17:00,21:00) closure half-open-overlaps the 18:00-19:30 game"
    )
    assignment = validate_success(api_client.get_officiating_assignment(
        ctx["assignment"]["id"], FACILITY_MANAGER))
    assert assignment["status"] == "CANCELLED"
    staff = validate_success(api_client.get_staff(
        ctx["official"]["id"], FACILITY_MANAGER))
    assert staff["payroll_pending_cents"] == 0, (
        "the 3750 provisional is reversed exactly, with no drift"
    )


def test_closure_cancels_class_and_registrations_and_bumps_version():
    """PRD §3.9: "Every `SCHEDULED` fitness class overlapping the closure is
    cancelled as described in §3.8. The closure is appended to the facility's
    `closures` and the facility's `version` increments."
    PRD §3.8: "A facility closure whose half-open interval overlaps a
    `SCHEDULED` class's interval cancels the class: every `REGISTERED` and
    `WAITLISTED` registration becomes `CANCELLED`, no waitlist promotion runs
    (the class is dead), and no instructor pay accrues."

    Design: Difficulty/transitive_cascade/facility_closure_three_level_cascade
    """
    ctx = _closure_context()
    updated = create_closure(ctx["facility"], CLOSURE_START, CLOSURE_END,
                             reason="burst pipe")
    assert updated["version"] == ctx["facility"]["version"] + 1
    fclass = validate_success(api_client.get_fitness_class(
        ctx["class"]["id"], FACILITY_MANAGER))
    assert fclass["status"] == "CANCELLED"
    registration = validate_success(api_client.get_class_registration(
        ctx["registration"]["id"], FACILITY_MANAGER))
    assert registration["status"] == "CANCELLED"
    instructor = validate_success(api_client.get_staff(
        ctx["instructor"]["id"], FACILITY_MANAGER))
    assert instructor["payroll_paid_cents"] == 0


def test_assignment_rejected_after_closure_bump():
    """PRD §3.6: "A `LeagueCoordinator` assigns an official to a `SCHEDULED`
    game by supplying `staff_id`."
    PRD §5: `ERR_INVALID_STATE` (HTTP 409) — the generic illegal
    transition/state precondition.

    Design: Difficulty/cross_entity_state_dependency/assignment_gated_by_game_state
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_game_context()
    official = create_official(rate=2000, cert=2)
    create_closure(ctx["facility"], CLOSURE_START, CLOSURE_END,
                   reason="burst pipe")
    game = validate_success(api_client.get_game(
        ctx["game"]["id"], REC_ADMIN))
    assert game["status"] == "RESCHEDULE_REQUIRED"
    resp = api_client.create_officiating_assignment(
        ctx["game"]["id"], {"staff_id": official["id"]}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_rejected_assignment_creates_no_row():
    """PRD §3.6: "A `LeagueCoordinator` assigns an official to a `SCHEDULED`
    game by supplying `staff_id`."
    PRD §2.3: "officiating assignments by `game_id`, `staff_id`, or `status`;
    equipment pools by `item_type`".

    Design: Difficulty/cross_entity_state_dependency/assignment_gated_by_game_state
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_game_context()
    official = create_official(rate=2000, cert=2)
    create_closure(ctx["facility"], CLOSURE_START, CLOSURE_END,
                   reason="burst pipe")
    resp = api_client.create_officiating_assignment(
        ctx["game"]["id"], {"staff_id": official["id"]}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    _, meta = validate_paginated(api_client.list_officiating_assignments(
        REC_ADMIN, params={"game_id": ctx["game"]["id"]}))
    assert meta["total_count"] == 0
