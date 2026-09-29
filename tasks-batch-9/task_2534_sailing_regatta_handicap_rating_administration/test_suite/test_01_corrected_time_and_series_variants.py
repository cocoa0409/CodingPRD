"""Both corrected-time variants and both series scoring systems, on data held
identical across the variants so only the selected rule can explain the answer.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    MEASUREMENT_A,
    MEASUREMENT_B,
    MEASUREMENT_D,
    build_accepted_fleet_world,
    build_started_race_world,
    read_result,
    read_standing,
    record_result,
    score_race,
)


def _tod_versus_tot_world():
    """One PER_CERTIFICATE regatta, one division, two boats measured alike but
    rated under the two competing rules."""
    return build_started_race_world(
        regatta_overrides={"handicap_basis": "PER_CERTIFICATE", "scoring_system": "LOW_POINT"},
        entrants=(
            {"helm": "helm_1", "measurement": MEASUREMENT_A, "rule_code": "TOD_PHRF"},
            {"helm": "helm_2", "measurement": MEASUREMENT_A, "rule_code": "TOT_ORC"},
        ),
    )


def _three_boat_scored_race(scoring_system, day):
    """Three boats whose corrected times land on 3900.0, 4000.0 and 4000.0, so a
    single-boat lead sits above a two-boat tie under either scoring system."""
    series_start = f"{day}T00:00:00Z"
    world = build_accepted_fleet_world(
        regatta_overrides={
            "scoring_system": scoring_system,
            "series_start_utc": series_start,
        },
        entrants=(
            {"helm": "helm_3", "measurement": MEASUREMENT_D},
            {"helm": "helm_1", "measurement": MEASUREMENT_A},
            {"helm": "helm_2", "measurement": MEASUREMENT_B},
        ),
        panel=True,
        racing=True,
        staffing=True,
        duty_window=(f"{day}T12:00:00Z", f"{day}T20:00:00Z"),
        races=({"race_number": 1, "scheduled_start_utc": f"{day}T14:00:00Z"},),
        start_races=(1,),
        clock=f"{day}T14:00:00Z",
    )
    race_id = world["races"][1]["id"]
    pro_id = world["ids"]["pro"]
    for key, elapsed in (("helm_3", 5105.4), ("helm_1", 5027.8), ("helm_2", 5312.8)):
        world.setdefault("results", {})[key] = record_result(
            race_id, world["entries"][key]["id"], pro_id, elapsed_seconds=elapsed
        )
    world["scored"] = score_race(race_id, pro_id)
    return world


def test_time_on_distance_and_time_on_time_correct_the_same_elapsed_differently(api):
    """PRD 3.8: "For one and the same time-on-time certificate and one and the
    same elapsed time the two variants return different corrected times, and on a
    long light-wind race they can invert the finishing order — which is why
    `handicap_basis` is fixed for the whole event at regatta creation rather than
    chosen per race."

    The time-on-distance boat subtracts 171.3 seconds per mile over 6.0 miles
    from 4800.0, while the time-on-time boat multiplies 4800.0 by its factor of
    0.8582.

    Design: Difficulty/dual_variant_calc/corrected_time_tod_versus_tot_on_identical_elapsed
    """
    world = _tod_versus_tot_world()
    race_id = world["races"][1]["id"]
    pro_id = world["ids"]["pro"]

    tod = validate_success(
        api.create_race_result(
            {
                "race_id": race_id,
                "entry_id": world["entries"]["helm_1"]["id"],
                "finish_status": "FINISHED",
                "elapsed_seconds": 4800.0,
            },
            world["h"]["pro"],
        ),
        expected_status=201,
    )
    tot = record_result(
        race_id, world["entries"]["helm_2"]["id"], pro_id, elapsed_seconds=4800.0
    )

    assert tod["corrected_seconds"] == 3772.2, (
        "time-on-distance corrects 4800.0 by 171.3 x 6.0 to 3772.2"
    )
    assert tot["corrected_seconds"] == 4119.4, (
        "time-on-time corrects 4800.0 by the factor 0.8582 to 4119.4"
    )
    assert round(tot["corrected_seconds"] - tod["corrected_seconds"], 1) == 347.2, (
        "the two variants separate identical elapsed times by 347.2 seconds"
    )


def test_the_two_corrected_time_variants_decide_the_finishing_order(api):
    """PRD 3.9: "The finishers among the candidates are ordered by
    `corrected_seconds` ascending; equal corrected times are broken by
    `elapsed_seconds` ascending, and any remaining tie by the entry's
    `created_at` ascending — never by identifier."

    Design: Difficulty/dual_variant_calc/corrected_time_tod_versus_tot_on_identical_elapsed
    """
    world = _tod_versus_tot_world()
    race_id = world["races"][1]["id"]
    pro_id = world["ids"]["pro"]
    tod = record_result(
        race_id, world["entries"]["helm_1"]["id"], pro_id, elapsed_seconds=4800.0
    )
    tot = record_result(
        race_id, world["entries"]["helm_2"]["id"], pro_id, elapsed_seconds=4800.0
    )

    scored = validate_success(api.score_race(race_id, world["h"]["pro"]))

    assert scored["scoring_status"] == "FINAL"
    assert scored["points_pool_total"] == 3.0, "1.0 and 2.0 pool to 3.0"
    tod_row = read_result(tod["id"])
    tot_row = read_result(tot["id"])
    assert tod_row["place"] == 1 and tod_row["points"] == 1.0, (
        "the lower corrected time takes slot 1 and one point under LOW_POINT"
    )
    assert tot_row["place"] == 2 and tot_row["points"] == 2.0


def test_low_point_scores_the_tie_group_at_two_and_a_half(api):
    """PRD 3.9: "Under `LOW_POINT`, the base value of a slot is simply the slot
    number, so consecutive slots always differ by exactly 1.0." and "Every member
    also takes the same group score: the mean of the base values of all the slots
    the group occupies, rounded half-up to one decimal place."

    Corrected times 3900.0, 4000.0 and 4000.0 give slot 1 to the leader and slots
    2 and 3 to the tie group, whose mean base value is 2.5.

    Design: Difficulty/dual_variant_calc/series_standing_low_point_versus_bonus_point_on_identical_race_data
    """
    world = _three_boat_scored_race("LOW_POINT", "2026-08-05")

    leader = read_result(world["results"]["helm_3"]["id"])
    tie_a = read_result(world["results"]["helm_1"]["id"])
    tie_b = read_result(world["results"]["helm_2"]["id"])

    assert leader["corrected_seconds"] == 3900.0
    assert tie_a["corrected_seconds"] == 4000.0 and tie_b["corrected_seconds"] == 4000.0
    assert (leader["place"], leader["points"]) == (1, 1.0)
    assert (tie_a["place"], tie_a["points"]) == (2, 2.5), (
        "the tie group takes the first slot it occupies and the mean base value"
    )
    assert (tie_b["place"], tie_b["points"]) == (2, 2.5)
    assert world["scored"]["points_pool_total"] == 6.0, "1.0 + 2.5 + 2.5 pools to 6.0"

    leader_standing = read_standing(world["entries"]["helm_3"]["id"])
    assert (leader_standing["gross_points"], leader_standing["net_points"]) == (1.0, 1.0)
    assert leader_standing["rank"] == 1
    assert read_standing(world["entries"]["helm_1"]["id"])["rank"] == 2, (
        "the earlier-created entry of the tie ranks ahead on the final tie-break"
    )
    assert read_standing(world["entries"]["helm_2"]["id"])["rank"] == 3


def test_bonus_point_scores_the_same_race_data_from_the_published_slot_table(api):
    """PRD 3.9: "Under `BONUS_POINT`, the first six slots are worth 0.0, 3.0,
    5.7, 8.0, 10.0 and 11.7 respectively, and every slot from the seventh onwards
    is worth its slot number plus 6.0."

    On corrected times identical to the low-point case the leader scores 0.0 and
    the tie group takes the mean of 3.0 and 5.7, which is 4.35 and rounds half-up
    to 4.4.

    Design: Difficulty/dual_variant_calc/series_standing_low_point_versus_bonus_point_on_identical_race_data
    """
    world = _three_boat_scored_race("BONUS_POINT", "2026-08-06")

    leader = read_result(world["results"]["helm_3"]["id"])
    tie_a = read_result(world["results"]["helm_1"]["id"])
    tie_b = read_result(world["results"]["helm_2"]["id"])

    assert (leader["place"], leader["points"]) == (1, 0.0), "slot 1 is worth nothing"
    assert (tie_a["place"], tie_a["points"]) == (2, 4.4)
    assert (tie_b["place"], tie_b["points"]) == (2, 4.4)
    assert world["scored"]["points_pool_total"] == 8.8, "0.0 + 4.4 + 4.4 pools to 8.8"

    leader_standing = read_standing(world["entries"]["helm_3"]["id"])
    assert (leader_standing["gross_points"], leader_standing["net_points"]) == (0.0, 0.0)
    assert leader_standing["rank"] == 1
    tie_a_standing = read_standing(world["entries"]["helm_1"]["id"])
    assert (tie_a_standing["gross_points"], tie_a_standing["net_points"]) == (4.4, 4.4)
    assert tie_a_standing["rank"] == 2
    assert read_standing(world["entries"]["helm_2"]["id"])["rank"] == 3
