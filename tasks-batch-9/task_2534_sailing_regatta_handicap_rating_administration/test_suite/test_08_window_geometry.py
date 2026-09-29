"""Three resources booked against three different interval geometries: a
volunteer's half-open duty windows, a mark boat's buffer-widened windows counted
against an aggregate limit, and the start line's closed prestart windows with a
mandatory separation gap.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    build_racing_world,
    charter_mark_boat,
    create_duty_assignment_payload,
    create_race_payload,
    propose_duty,
    read_duty,
    read_mark_boat,
    read_member,
    read_race,
)

EARLY = ("2026-08-05T12:00:00Z", "2026-08-05T14:00:00Z")
TOUCHING = ("2026-08-05T14:00:00Z", "2026-08-05T16:00:00Z")
OVERLAPPING = ("2026-08-05T15:00:00Z", "2026-08-05T17:00:00Z")


def _volunteer_world():
    """A regatta with sailing instructions published and one volunteer already
    holding a proposed duty over the half-open window from 12:00 to 14:00."""
    world = build_racing_world()
    world["volunteer_id"] = world["roster"]["signals"]["id"]
    world["first_duty"] = propose_duty(
        world["regatta_id"], world["ids"]["chair"], world["volunteer_id"], "TIMEKEEPER",
        window_start_utc=EARLY[0], window_end_utc=EARLY[1],
    )
    return world


def _duty(world, position, window, member_id=None):
    return create_duty_assignment_payload(
        world["regatta_id"],
        member_id or world["volunteer_id"],
        position,
        window[0],
        window[1],
    )


def test_two_duties_that_touch_at_one_instant_do_not_collide(api):
    """PRD 3.6: "The window is **half-open**: `window_start_utc` is included,
    `window_end_utc` is excluded, and the end must fall strictly after the start.
    Because the window is half-open, two back-to-back duties on the same volunteer
    that touch at exactly one instant do **not** collide; any genuine overlap of
    two non-released windows on the same `member_id` is refused with
    `ERR_MEMBER_DUTY_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/member_duty_windows_touch_allowed_overlap_rejected
    """
    world = _volunteer_world()
    chair = world["h"]["chair"]
    assert world["first_duty"]["duty_minutes"] == 120

    handover = validate_success(
        api.create_duty_assignment(_duty(world, "SIGNALS", TOUCHING), chair),
        expected_status=201,
    )

    assert handover["duty_minutes"] == 120
    assert handover["status"] == "PROPOSED"
    assert handover["window_start_utc"] == TOUCHING[0]
    assert handover["mark_boat_id"] is None

    validate_error(
        api.create_duty_assignment(_duty(world, "SIGNALS", OVERLAPPING), chair),
        ApiErrorId.ERR_MEMBER_DUTY_OVERLAP,
        expected_status=409,
    )


def test_the_refused_overlap_adds_nothing_to_the_volunteers_minute_ledger(api):
    """PRD 3.6: "A proposed duty already counts in both ledgers. Its
    `duty_minutes` is the number of whole minutes between `window_start_utc` and
    `window_end_utc`; that figure is added to the volunteer's
    `assigned_duty_minutes` and, when a mark boat is named, to that boat's
    `committed_minutes`."

    PRD 3.6 also fixes the version increment the ledger move rides on: "Creating a
    duty advances the volunteer's `version`, and the assignment itself opens in
    `PROPOSED`."

    Design: Difficulty/resource_temporal_overlap/member_duty_windows_touch_allowed_overlap_rejected
    """
    world = _volunteer_world()
    chair = world["h"]["chair"]
    validate_success(
        api.create_duty_assignment(_duty(world, "SIGNALS", TOUCHING), chair),
        expected_status=201,
    )
    validate_error(
        api.create_duty_assignment(_duty(world, "SIGNALS", OVERLAPPING), chair),
        ApiErrorId.ERR_MEMBER_DUTY_OVERLAP,
    )

    volunteer = read_member(world["volunteer_id"])
    assert volunteer["assigned_duty_minutes"] == 240, "exactly 120 plus 120"
    assert volunteer["version"] == 3, "one increment per accepted duty and none for the refusal"

    rows, pagination = validate_paginated(
        api.list_duty_assignments(chair, {"member_id": world["volunteer_id"]})
    )
    assert pagination["total_count"] == 2
    assert sorted(row["window_start_utc"] for row in rows) == [EARLY[0], TOUCHING[0]]


DRIVER_ONE_WINDOW = ("2026-08-05T13:00:00Z", "2026-08-05T14:00:00Z")
DRIVER_TWO_WINDOW = ("2026-08-05T15:00:00Z", "2026-08-05T16:00:00Z")
IN_THE_RAW_HOLE = ("2026-08-05T14:15:00Z", "2026-08-05T14:45:00Z")
IN_THE_DEAD_BAND = ("2026-08-05T14:25:00Z", "2026-08-05T14:35:00Z")


def _mark_boat_world():
    """One mark boat holding two proposed driver duties an hour apart in raw time,
    driven by two different volunteers so no member rule can interfere.

    Widened by the boat's 20-minute buffer those windows occupy 12:40 to 14:20 and
    14:40 to 16:20, leaving a 20-minute dead band between them.
    """
    world = build_racing_world()
    chair_id = world["ids"]["chair"]
    world["mark_boat"] = charter_mark_boat(
        world["regatta_id"], chair_id,
        concurrent_assignment_limit=2, turnaround_buffer_minutes=20,
    )
    world["drivers"] = {
        key: world["roster"][key]["id"] for key in ("helm_1", "helm_2", "helm_3")
    }
    world["boat_duties"] = [
        propose_duty(
            world["regatta_id"], chair_id, world["drivers"][key], "MARK_BOAT_DRIVER",
            window_start_utc=window[0], window_end_utc=window[1],
            mark_boat_id=world["mark_boat"]["id"],
        )
        for key, window in (("helm_1", DRIVER_ONE_WINDOW), ("helm_2", DRIVER_TWO_WINDOW))
    ]
    return world


def _driver_duty(world, window):
    return create_duty_assignment_payload(
        world["regatta_id"], world["drivers"]["helm_3"], "MARK_BOAT_DRIVER",
        window[0], window[1], mark_boat_id=world["mark_boat"]["id"],
    )


def test_a_window_in_the_raw_hole_still_reaches_the_boats_concurrent_limit(api):
    """PRD 3.6: "On a mark boat the test is different: the requested window is
    compared against every non-released assignment of that boat after each of those
    existing windows has been widened by `turnaround_buffer_minutes` at both ends,
    and if the number of such buffer-widened windows intersecting the request has
    already reached the boat's `concurrent_assignment_limit`, the request is refused
    with `ERR_MARK_BOAT_OVERBOOKED`."

    The candidate from 14:15 to 14:45 overlaps neither stored window in raw time —
    there is a clean hour between 14:00 and 15:00 — so only the widening can
    explain the refusal.

    Design: Difficulty/resource_temporal_overlap/mark_boat_buffer_widened_aggregate_limit_rejects_third_window
    """
    world = _mark_boat_world()
    boat = read_mark_boat(world["mark_boat"]["id"])
    assert boat["turnaround_buffer_minutes"] == 20
    assert boat["concurrent_assignment_limit"] == 2
    assert boat["committed_minutes"] == 120

    validate_error(
        api.create_duty_assignment(_driver_duty(world, IN_THE_RAW_HOLE), world["h"]["chair"]),
        ApiErrorId.ERR_MARK_BOAT_OVERBOOKED,
        expected_status=409,
    )

    assert read_mark_boat(world["mark_boat"]["id"])["committed_minutes"] == 120, (
        "the refused thirty-minute window contributed nothing"
    )
    assert read_member(world["drivers"]["helm_3"])["assigned_duty_minutes"] == 0


def test_a_window_inside_the_buffer_dead_band_intersects_nothing_and_is_accepted(api):
    """PRD 3.6: "`turnaround_buffer_minutes`, defaulting to 20 minutes and
    constrained to between 0 and 120, is added to **both** ends of every window
    already committed on that boat before overlap is tested, which is why two
    windows that merely touch nose-to-tail still collide on a mark boat."

    A ten-minute window from 14:25 to 14:35 lies wholly inside the twenty-minute
    dead band the two buffers leave open, so the intersecting count is zero rather
    than the limit, which shows the rule counts intersections instead of banning
    the hole outright.

    Design: Difficulty/resource_temporal_overlap/mark_boat_buffer_widened_aggregate_limit_rejects_third_window
    """
    world = _mark_boat_world()
    chair = world["h"]["chair"]
    validate_error(
        api.create_duty_assignment(_driver_duty(world, IN_THE_RAW_HOLE), chair),
        ApiErrorId.ERR_MARK_BOAT_OVERBOOKED,
    )

    accepted = validate_success(
        api.create_duty_assignment(_driver_duty(world, IN_THE_DEAD_BAND), chair),
        expected_status=201,
    )

    assert accepted["duty_minutes"] == 10
    assert accepted["status"] == "PROPOSED"
    assert accepted["mark_boat_id"] == world["mark_boat"]["id"]
    assert read_duty(accepted["id"])["position"] == "MARK_BOAT_DRIVER"

    assert read_mark_boat(world["mark_boat"]["id"])["committed_minutes"] == 130, (
        "exactly 60 plus 60 plus 10"
    )
    assert read_member(world["drivers"]["helm_3"])["assigned_duty_minutes"] == 10
    assert read_member(world["drivers"]["helm_1"])["assigned_duty_minutes"] == 60

    rows, pagination = validate_paginated(
        api.list_duty_assignments(chair, {"mark_boat_id": world["mark_boat"]["id"]})
    )
    assert pagination["total_count"] == 3
    assert all(row["mark_boat_id"] == world["mark_boat"]["id"] for row in rows)


FIRST_START = "2026-08-05T14:00:00Z"
OVERLAPPING_START = "2026-08-05T14:03:00Z"
TWO_MINUTE_GAP_START = "2026-08-05T14:07:00Z"
THREE_MINUTE_GAP_START = "2026-08-05T14:08:00Z"


def _start_line_world():
    """A regatta holding one race at 14:00, which occupies the closed prestart
    window from 13:55 up to and including 14:00."""
    world = build_racing_world(
        races=({"race_number": 1, "scheduled_start_utc": FIRST_START},),
    )
    return world


def _schedule(api, world, race_number, scheduled_start_utc):
    return api.create_race(
        create_race_payload(world["regatta_id"], race_number, scheduled_start_utc),
        world["h"]["pro"],
    )


def test_a_disjoint_prestart_window_two_minutes_clear_is_still_refused(api):
    """PRD 3.7: "The start line is a physical resource, so each race occupies it
    for a closed prestart window running from five minutes before
    `scheduled_start_utc` up to and including `scheduled_start_utc`. Two
    non-abandoned races of the same regatta may not have overlapping prestart
    windows, and consecutive races additionally need a three-minute gap between the
    end of one window and the start of the next; a schedule that violates either
    condition is refused with `ERR_START_LINE_WINDOW_CONFLICT`."

    A start at 14:03 occupies 13:58 to 14:03 and overlaps outright. A start at
    14:07 occupies 14:02 to 14:07, which is provably disjoint from 13:55 to 14:00,
    and is refused all the same because only two minutes separate them.

    Design: Difficulty/resource_temporal_overlap/race_prestart_window_needs_three_minute_gap
    """
    world = _start_line_world()

    validate_error(
        _schedule(api, world, 2, OVERLAPPING_START),
        ApiErrorId.ERR_START_LINE_WINDOW_CONFLICT,
        expected_status=409,
    )
    validate_error(
        _schedule(api, world, 3, TWO_MINUTE_GAP_START),
        ApiErrorId.ERR_START_LINE_WINDOW_CONFLICT,
        expected_status=409,
    )

    assert read_race(world["races"][1]["id"])["scheduled_start_utc"] == FIRST_START


def test_exactly_three_minutes_of_separation_is_enough_and_leaves_no_ghost_rows(api):
    """PRD 3.7: "A new race opens with `start_status` `PENDING` and `scoring_status`
    `NOT_SCORED`, with `actual_start_utc` null, `general_recall_count` 0,
    `black_flag_active` false, `points_pool_total` 0, `results_closed_utc` null,
    `rescore_count` 0 and `abandon_reason_code` null."

    PRD 3.7 also fixes when the block is stamped instead: "`start_blocked_reason`
    is set to `DIVISION_UNDER_MINIMUM` right away if some division of the regatta
    that already holds at least one assigned entry is still short of the greater of
    its `min_entries` and the regatta's `fleet_minimum`. Otherwise
    `start_blocked_reason` is null."

    Design: Difficulty/resource_temporal_overlap/race_prestart_window_needs_three_minute_gap
    """
    world = _start_line_world()
    validate_error(
        _schedule(api, world, 2, OVERLAPPING_START),
        ApiErrorId.ERR_START_LINE_WINDOW_CONFLICT,
    )
    validate_error(
        _schedule(api, world, 3, TWO_MINUTE_GAP_START),
        ApiErrorId.ERR_START_LINE_WINDOW_CONFLICT,
    )

    accepted = validate_success(
        _schedule(api, world, 4, THREE_MINUTE_GAP_START), expected_status=201
    )

    assert accepted["scheduled_start_utc"] == THREE_MINUTE_GAP_START
    assert accepted["start_status"] == "PENDING"
    assert accepted["scoring_status"] == "NOT_SCORED"
    assert accepted["start_blocked_reason"] is None, (
        "the regatta holds no division with assigned entries"
    )
    assert accepted["actual_start_utc"] is None
    assert accepted["general_recall_count"] == 0
    assert accepted["black_flag_active"] is False

    rows, pagination = validate_paginated(
        api.list_races(world["h"]["pro"], {"regatta_id": world["regatta_id"]})
    )
    assert pagination["total_count"] == 2, "neither refusal created a race row"
    assert sorted(row["race_number"] for row in rows) == [1, 4]
