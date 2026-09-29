"""Compensating actions measured against the two conservation identities: an
abandonment that must remove exactly one term from each side of the series-points
identity, and a duty release that must settle a volunteer's and a mark boat's
minute ledgers at once.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    MEASUREMENT_A,
    MEASUREMENT_B,
    abandon_race_payload,
    build_accepted_fleet_world,
    build_racing_world,
    charter_mark_boat,
    confirm_duty,
    propose_duty,
    read_duty,
    read_entry,
    read_mark_boat,
    read_member,
    read_race,
    read_regatta,
    read_standing,
    record_result,
    release_duty_payload,
    score_race,
    set_clock,
)

RACE_STARTS = ("2026-08-05T14:00:00Z", "2026-08-05T14:10:00Z")
RESULTS_CLOCK = "2026-08-05T18:00:00Z"
A_BEATS_B = {"A": 5027.8, "B": 5412.8}


def _two_scored_races_world():
    """A LOW_POINT series with nothing discarded, carried to two FINAL races that
    A won and B lost, so the identity reads 2.0 plus 4.0 against 3.0 plus 3.0."""
    world = build_accepted_fleet_world(
        regatta_overrides={"discard_policy": "NONE", "planned_race_count": 6},
        entrants=(
            {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
            {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_B},
        ),
        panel=True,
        racing=True,
        staffing=True,
        races=tuple(
            {"race_number": number, "scheduled_start_utc": start}
            for number, start in enumerate(RACE_STARTS, start=1)
        ),
        start_races=(1, 2),
    )
    set_clock(RESULTS_CLOCK)
    pro_id = world["ids"]["pro"]
    world["results"] = {}
    for race_number in (1, 2):
        race_id = world["races"][race_number]["id"]
        world["results"][race_number] = {
            key: record_result(race_id, world["entries"][key]["id"], pro_id,
                               elapsed_seconds=elapsed)
            for key, elapsed in A_BEATS_B.items()
        }
        world["races"][race_number] = score_race(race_id, pro_id)
    return world


def test_abandoning_a_final_race_removes_one_term_from_each_side_of_the_identity(api):
    """PRD 2.12: "The series-points identity, evaluated per regatta: summed over
    the regatta's `ACCEPTED` entries, `series_points_gross` equals the summed
    `points_pool_total` of the regatta's races whose `scoring_status` is `FINAL` and
    whose `start_status` is not `ABANDONED`. Scoring a race adds exactly one term to
    each side. Abandoning a race that was `FINAL` removes exactly one term from each
    side: every entry's `series_points_gross` drops by precisely the points that
    race had awarded it, the race's `points_pool_total` becomes 0, and the race
    leaves the counted set."

    Design: Difficulty/compensating_invariant/abandon_restores_series_points_conservation
    """
    world = _two_scored_races_world()
    first_id = world["races"][1]["id"]
    second_id = world["races"][2]["id"]
    assert read_race(first_id)["points_pool_total"] == 3.0
    assert read_race(second_id)["points_pool_total"] == 3.0
    assert read_entry(world["entries"]["A"]["id"])["series_points_gross"] == 2.0
    assert read_entry(world["entries"]["B"]["id"])["series_points_gross"] == 4.0

    abandoned = validate_success(
        api.abandon_race(second_id, abandon_race_payload(), world["h"]["pro"])
    )

    assert abandoned["start_status"] == "ABANDONED"
    assert abandoned["scoring_status"] == "NOT_SCORED", (
        "the only way a scored race leaves FINAL"
    )
    assert abandoned["abandon_reason_code"] == "WIND_SHIFT"
    assert abandoned["points_pool_total"] == 0

    survivor = read_race(first_id)
    assert survivor["points_pool_total"] == 3.0
    assert survivor["scoring_status"] == "FINAL", "the other race was not disturbed"

    winner = read_entry(world["entries"]["A"]["id"])
    loser = read_entry(world["entries"]["B"]["id"])
    assert winner["series_points_gross"] == 1.0
    assert loser["series_points_gross"] == 2.0
    assert winner["series_points_gross"] + loser["series_points_gross"] == 3.0, (
        "the entry side equals the single surviving points_pool_total with no drift"
    )


def test_the_abandonment_keeps_the_voided_audit_trail_and_the_derived_totals_agree(api):
    """PRD 3.7: "Hop two rewrites every result of the race: `voided` becomes true,
    `points` becomes 0, `place` becomes null and `corrected_seconds` becomes null.
    Hop three re-runs the series standing for every `ACCEPTED` entry of the regatta,
    so each entry's `series_points_gross` falls by precisely the points this race
    had awarded it. Finally the regatta's `final_race_count` is refreshed, since an
    abandoned race never counts towards the planned total."

    Design: Difficulty/compensating_invariant/abandon_restores_series_points_conservation
    """
    world = _two_scored_races_world()
    second_id = world["races"][2]["id"]
    assert read_regatta(world["regatta_id"])["final_race_count"] == 2

    validate_success(api.abandon_race(second_id, abandon_race_payload(), world["h"]["pro"]))

    rows, pagination = validate_paginated(
        api.list_race_results(world["h"]["pro"], {"race_id": second_id})
    )
    assert pagination["total_count"] == 2, "the audit trail survives the compensation"
    for row in rows:
        assert row["voided"] is True
        assert row["points"] == 0
        assert row["place"] is None
        assert row["corrected_seconds"] is None

    winner = read_entry(world["entries"]["A"]["id"])
    assert winner["series_points_net"] == 1.0, "nets follow the grosses under NONE"
    assert winner["discarded_race_numbers"] == []
    assert winner["series_rank"] == 1
    loser = read_entry(world["entries"]["B"]["id"])
    assert loser["series_points_net"] == 2.0
    assert loser["series_rank"] == 2

    standing = read_standing(world["entries"]["A"]["id"])
    assert standing["gross_points"] == 1.0
    assert standing["net_points"] == 1.0
    assert standing["races_counted"] == 1, "the abandoned race left the counted set"
    assert standing["rank"] == 1

    regatta = read_regatta(world["regatta_id"])
    assert regatta["final_race_count"] == 1
    assert regatta["status"] == "RACING"


LONG_WINDOW = ("2026-08-05T12:00:00Z", "2026-08-05T20:00:00Z")
EIGHT_HOURS = 480


def _two_ledger_world():
    """One mark boat carrying two eight-hour driver duties over the very same
    window, the first of them confirmed, so both ledgers stand at their full
    values before the release.
    """
    world = build_racing_world()
    chair_id = world["ids"]["chair"]
    world["mark_boat"] = charter_mark_boat(world["regatta_id"], chair_id)
    world["drivers"] = {
        key: world["roster"][key]["id"] for key in ("helm_1", "helm_2")
    }
    world["duties"] = {
        key: propose_duty(
            world["regatta_id"], chair_id, member_id, "MARK_BOAT_DRIVER",
            window_start_utc=LONG_WINDOW[0], window_end_utc=LONG_WINDOW[1],
            mark_boat_id=world["mark_boat"]["id"],
        )
        for key, member_id in world["drivers"].items()
    }
    world["duties"]["helm_1"] = confirm_duty(world["duties"]["helm_1"]["id"], chair_id)
    return world


def test_confirming_moves_neither_ledger_and_releasing_settles_both_exactly(api):
    """PRD 3.6: "Release subtracts `duty_minutes` from the volunteer's
    `assigned_duty_minutes` and, where a mark boat was named, the same figure from
    that boat's `committed_minutes`, leaving both ledgers exactly at their
    pre-creation values with no residue."

    PRD 2.12 states the identity the two ledgers answer to: "The duty-minutes
    identity: summed over every club member, `assigned_duty_minutes` equals the
    summed `duty_minutes` of every duty assignment whose `status` is `PROPOSED` or
    `CONFIRMED`. Creating an assignment and then releasing it must leave both sides
    exactly at their pre-creation values — no half decrement, no residue on the mark
    boat's `committed_minutes` — and confirming the assignment in between changes
    neither side, because a `PROPOSED` row already counted."

    Design: Difficulty/compensating_invariant/duty_release_restores_member_and_mark_boat_minute_ledgers
    """
    world = _two_ledger_world()
    confirmed = world["duties"]["helm_1"]
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["duty_minutes"] == EIGHT_HOURS
    assert confirmed["version"] == 2, "one increment from the confirm alone"
    assert read_member(world["drivers"]["helm_1"])["assigned_duty_minutes"] == EIGHT_HOURS, (
        "confirming added nothing, because the proposed row already counted"
    )
    assert read_member(world["drivers"]["helm_2"])["assigned_duty_minutes"] == EIGHT_HOURS
    assert read_mark_boat(world["mark_boat"]["id"])["committed_minutes"] == 960

    released = validate_success(
        api.release_duty_assignment(
            confirmed["id"], release_duty_payload(), world["h"]["chair"]
        )
    )

    assert released["status"] == "RELEASED"
    assert released["duty_minutes"] == EIGHT_HOURS, "the row keeps its magnitude for audit"
    assert released["release_reason_code"] == "ILLNESS"
    assert read_member(world["drivers"]["helm_1"])["assigned_duty_minutes"] == 0, (
        "back to its pre-create value with no negative residue"
    )
    assert read_mark_boat(world["mark_boat"]["id"])["committed_minutes"] == EIGHT_HOURS, (
        "exactly one duty was subtracted, not the whole ledger recomputed to zero"
    )


def test_the_release_leaves_the_sibling_duty_and_its_ledger_untouched(api):
    """PRD 3.6: "Both ledgers count assignments whose `status` is `PROPOSED` or
    `CONFIRMED` and ignore those in `RELEASED`, which remain queryable."

    PRD 3.6 also fixes the version increments on the volunteer: "Creating a duty
    advances the volunteer's `version`" and release "advances the volunteer's
    `version`".

    Design: Difficulty/compensating_invariant/duty_release_restores_member_and_mark_boat_minute_ledgers
    """
    world = _two_ledger_world()
    boat_id = world["mark_boat"]["id"]
    sibling_id = world["duties"]["helm_2"]["id"]
    validate_success(
        api.release_duty_assignment(
            world["duties"]["helm_1"]["id"], release_duty_payload(), world["h"]["chair"]
        )
    )

    sibling = read_duty(sibling_id)
    assert sibling["status"] == "PROPOSED"
    assert sibling["duty_minutes"] == EIGHT_HOURS
    assert sibling["mark_boat_id"] == boat_id
    assert read_member(world["drivers"]["helm_2"])["assigned_duty_minutes"] == EIGHT_HOURS

    settled = read_member(world["drivers"]["helm_1"])
    assert settled["assigned_duty_minutes"] == 0
    assert settled["version"] == 3, "enrolment, the duty create and the release"
    assert (
        settled["assigned_duty_minutes"]
        + read_member(world["drivers"]["helm_2"])["assigned_duty_minutes"]
        == read_mark_boat(boat_id)["committed_minutes"]
        == EIGHT_HOURS
    ), "the single non-released row of 480 minutes is all that either side counts"

    rows, pagination = validate_paginated(
        api.list_duty_assignments(world["h"]["chair"], {"mark_boat_id": boat_id})
    )
    assert pagination["total_count"] == 2, "the released row remains queryable"
    assert sorted(row["status"] for row in rows) == ["PROPOSED", "RELEASED"]
