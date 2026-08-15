"""Championship standings: the counted-event input set, provisional versus
final points under drop rounds, and the empty counted-set boundary."""
from test_helpers import (
    FULL_POINTS_SCHEME,
    SECOND_EVENT_DATE,
    create_event,
    enter_driver,
    get_season,
    open_registration,
    run_completed_round,
    setup_championship,
    standings_row_for,
    validate_success,
)


def _standings(api, season_id, class_id, headers):
    return validate_success(
        api.get_standings(season_id, headers, params={"class_id": class_id}), 200
    )


def test_cancelled_event_excluded_from_standings(api, league_admin_headers):
    """PRD 3.7: "Only counted events feed the totals — child events in `COMPLETED` or
    `FINALIZED` status; `CANCELLED` events are excluded — and the season's
    `rounds_completed` is exactly the count of those counted events."
    PRD 3.3: "A `LeagueAdmin` may instead cancel an event from `SCHEDULED`,
    `REGISTRATION_OPEN`, or `IN_PROGRESS`: the cancellation cascades, moving every
    child entry in `ENTERED`, `TECH_CHECK`, `TECH_FAILED`, `TECH_PASSED`, or
    `GRID_LOCKED` to `WITHDRAWN`, refunding each withdrawn entry whose `fee_status` was
    `PAID` with `collected_fees_cents` recomputed accordingly, and excluding the event
    from all standings calculations."

    Design: Corner/calculations/cancelled_event_excluded_from_standings
    """
    ctx = setup_championship(num_drivers=1)
    run_completed_round(ctx, round_number=1, rows_spec=[(0, 1, 45000, 600000)])

    # Round 2 is opened, entered, then cancelled before any running.
    event2 = create_event(
        ctx["season"]["id"], round_number=2, event_date=SECOND_EVENT_DATE
    )
    open_registration(event2["id"])
    enter_driver(
        event2["id"], ctx["drivers"][0]["id"], ctx["race_class"]["id"]
    )
    validate_success(api.cancel_event(event2["id"], league_admin_headers), 200)

    standings = _standings(api, ctx["season"]["id"], ctx["race_class"]["id"], league_admin_headers)
    row = standings_row_for(standings, ctx["drivers"][0]["id"])
    assert row["provisional_points"] == 25, (
        "the cancelled round contributes nothing to the totals"
    )

    season = get_season(ctx["season"]["id"])
    assert season["rounds_completed"] == 1, "CANCELLED events are not counted"


def test_provisional_and_final_points_diverge_with_drop_rounds(
    api, league_admin_headers
):
    """PRD 3.7: "The `provisional_points` are the plain sum of the driver's per-event
    scores over all counted events — nothing dropped."
    PRD 3.7: "The `final_points` apply the season's drop-rounds rule: order the
    driver's per-event scores ascending and discard the first `drop_rounds` of them —
    when scores tie at the drop boundary, the event with the lower `round_number` is
    discarded first — then sum what remains."
    PRD 3.7: "The discarded rounds are reported as `dropped_round_numbers`."

    Design: Difficulty/dual_variant_calc/standings_provisional_vs_final_drop_rounds
    """
    ctx = setup_championship(
        num_drivers=2,
        season_overrides={
            "drop_rounds": 1,
            "points_scheme": list(FULL_POINTS_SCHEME),
            "fastest_lap_bonus_points": 0,
        },
    )
    # Round 1: driver 0 wins (25), driver 1 second (22).
    run_completed_round(
        ctx, round_number=1, rows_spec=[(0, 1, 45000, 600000), (1, 2, 45100, 605000)]
    )
    # Round 2: driver 1 wins (25), driver 0 second (22).
    run_completed_round(
        ctx,
        round_number=2,
        rows_spec=[(1, 1, 45000, 598000), (0, 2, 45100, 602000)],
        event_date=SECOND_EVENT_DATE,
    )

    standings = _standings(api, ctx["season"]["id"], ctx["race_class"]["id"], league_admin_headers)
    row_a = standings_row_for(standings, ctx["drivers"][0]["id"])
    row_b = standings_row_for(standings, ctx["drivers"][1]["id"])

    assert row_a["provisional_points"] == 47
    assert row_a["final_points"] == 25, "the lowest of {25, 22} is dropped"
    assert sorted(row_a["dropped_round_numbers"]) == [2]
    assert row_b["provisional_points"] == 47
    assert row_b["final_points"] == 25
    assert sorted(row_b["dropped_round_numbers"]) == [1]
    assert row_a["provisional_points"] != row_a["final_points"], (
        "identical underlying results yield divergent provisional and final totals"
    )


def test_pre_finalize_rank_uses_provisional_points(api, league_admin_headers):
    """PRD 3.7: "Before the season reaches `FINALIZED`, rows rank by
    `provisional_points` descending, ties broken in favor of the driver who registered
    earlier (the lower `created_at`)."

    Design: Difficulty/dual_variant_calc/standings_provisional_vs_final_drop_rounds
    """
    ctx = setup_championship(
        num_drivers=2,
        season_overrides={
            "drop_rounds": 1,
            "points_scheme": list(FULL_POINTS_SCHEME),
            "fastest_lap_bonus_points": 0,
        },
    )
    run_completed_round(
        ctx, round_number=1, rows_spec=[(0, 1, 45000, 600000), (1, 2, 45100, 605000)]
    )
    run_completed_round(
        ctx,
        round_number=2,
        rows_spec=[(1, 1, 45000, 598000), (0, 2, 45100, 602000)],
        event_date=SECOND_EVENT_DATE,
    )

    standings = _standings(api, ctx["season"]["id"], ctx["race_class"]["id"], league_admin_headers)
    assert len(standings["rows"]) == 2
    # Both drivers hold 47 provisional points; the tie goes to the
    # earlier-registered driver (driver 0 was created first).
    assert standings["rows"][0]["driver_id"] == ctx["drivers"][0]["id"]
    assert standings["rows"][1]["driver_id"] == ctx["drivers"][1]["id"]
    assert standings["rows"][0]["provisional_points"] == 47
    assert standings["rows"][1]["provisional_points"] == 47


def test_drop_rounds_equal_to_completed_rounds_zeroes_final(
    api, league_admin_headers
):
    """PRD 3.7: "If the season's `drop_rounds` meets or exceeds the number of counted
    events the driver scored in, the driver's `final_points` are zero and every one of
    their round numbers appears in `dropped_round_numbers`."

    Design: Difficulty/boundary_precision_check/drop_rounds_equal_completed_counts_zero
    """
    ctx = setup_championship(
        num_drivers=1, season_overrides={"drop_rounds": 1}
    )
    run_completed_round(ctx, round_number=1, rows_spec=[(0, 1, 45000, 600000)])

    standings = _standings(api, ctx["season"]["id"], ctx["race_class"]["id"], league_admin_headers)
    row = standings_row_for(standings, ctx["drivers"][0]["id"])
    assert row["provisional_points"] == 25, "nothing is dropped provisionally"
    assert row["final_points"] == 0, (
        "drop_rounds (1) meets the counted-round count (1): the counted set is empty"
    )


def test_all_rounds_dropped_reports_every_round_number(api, league_admin_headers):
    """PRD 3.7: "If the season's `drop_rounds` meets or exceeds the number of counted
    events the driver scored in, the driver's `final_points` are zero and every one of
    their round numbers appears in `dropped_round_numbers`."
    PRD 3.7: "The discarded rounds are reported as `dropped_round_numbers`."

    Design: Difficulty/boundary_precision_check/drop_rounds_equal_completed_counts_zero
    """
    ctx = setup_championship(
        num_drivers=1, season_overrides={"drop_rounds": 1}
    )
    run_completed_round(ctx, round_number=1, rows_spec=[(0, 1, 45000, 600000)])

    standings = _standings(api, ctx["season"]["id"], ctx["race_class"]["id"], league_admin_headers)
    row = standings_row_for(standings, ctx["drivers"][0]["id"])
    assert row["dropped_round_numbers"] == [1]
    assert row["final_points"] == 0
