"""Three thresholds probed from both sides: the strict deep-draft comparison, the
integer race count that switches a discard on, and the exclusive upper edge of a
division band.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    MEASUREMENT_A,
    MEASUREMENT_B,
    ApiErrorId,
    build_accepted_fleet_world,
    create_division_payload,
    file_certificate,
    read_boat,
    read_division,
    read_entry,
    read_race,
    read_regatta,
    read_standing,
    record_result,
    register_boat,
    run_race_to_started,
    score_race,
    set_clock,
)

DRAFT_HULL = {"sail_area_m2": 61.0, "hull_length_m": 10.2, "displacement_kg": 4700}


def _certificate_at_draft(roster, draft_m):
    """One MONOHULL certificate whose only distinguishing input is its draft."""
    boat = register_boat(roster["helm_1"]["id"])
    certificate = file_certificate(
        boat["id"], roster["measurer"]["id"],
        measurement={**DRAFT_HULL, "draft_m": draft_m},
    )
    return boat, certificate


def test_a_draft_of_exactly_two_point_two_zero_escapes_the_deep_draft_penalty(api, roster):
    """PRD 3.2: "A boat whose `draft_m` is strictly greater than 2.20 metres
    carries the deep-draft penalty of 0.03, so its draft multiplier is 0.97; a
    draft of exactly 2.20 metres carries no penalty and a multiplier of 1.00."

    Design: Difficulty/boundary_precision_check/deep_draft_penalty_strict_greater_than_2_20
    """
    below_boat, below = _certificate_at_draft(roster, 2.19)
    at_boat, at_threshold = _certificate_at_draft(roster, 2.20)

    assert below["raw_speed_index"] == 0.5945
    assert at_threshold["raw_speed_index"] == 0.5945, (
        "the comparison is strict, so the threshold itself is clean"
    )
    assert below["rating_value"] == at_threshold["rating_value"] == 194.1
    assert below["band_key_spm"] == at_threshold["band_key_spm"] == 194.1
    for certificate in (below, at_threshold):
        assert certificate["status"] == "DRAFT"
        assert certificate["measured_by_member_id"] == roster["measurer"]["id"]
    assert read_boat(at_boat["id"])["version"] == 2, (
        "one increment from the minting call alone"
    )
    assert read_boat(below_boat["id"])["version"] == 2


def test_one_centimetre_over_the_draft_threshold_costs_six_point_eight_seconds_a_mile(api, roster):
    """PRD 3.2: "Under `TOD_PHRF`, multiply `raw_speed_index` by 380.0, subtract
    that product from 420.0, round half-up to one decimal place, and then confine
    the result to the closed range from −30.0 to 300.0; the outcome is
    `rating_value`, expressed in seconds per nautical mile, and `band_key_spm` is
    set equal to it."

    Design: Difficulty/boundary_precision_check/deep_draft_penalty_strict_greater_than_2_20
    """
    _, at_threshold = _certificate_at_draft(roster, 2.20)
    above_boat, above = _certificate_at_draft(roster, 2.21)

    assert above["raw_speed_index"] == 0.5767, "the 0.97 multiplier is now in play"
    assert above["rating_value"] == 200.9
    assert above["band_key_spm"] == 200.9
    assert round(above["rating_value"] - at_threshold["rating_value"], 1) == 6.8, (
        "one centimetre of draft moves the allowance by 6.8 seconds per mile"
    )
    assert above["status"] == "DRAFT"
    assert read_boat(above_boat["id"])["version"] == 2


FIVE_RACE_STARTS = (
    "2026-08-05T14:00:00Z",
    "2026-08-05T14:10:00Z",
    "2026-08-05T14:20:00Z",
    "2026-08-05T14:30:00Z",
    "2026-08-05T14:40:00Z",
)
A_WINS = {"A": 5027.8, "B": 5412.8}
B_WINS = {"A": 5127.8, "B": 5312.8}


def _four_final_races_world():
    """A ONE_PER_FIVE series carried to exactly four counted races, one short of
    the discard threshold, with the fifth race scheduled but not yet started.
    """
    world = build_accepted_fleet_world(
        regatta_overrides={"discard_policy": "ONE_PER_FIVE", "planned_race_count": 6},
        entrants=(
            {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
            {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_B},
        ),
        panel=True,
        racing=True,
        staffing=True,
        races=tuple(
            {"race_number": number, "scheduled_start_utc": start}
            for number, start in enumerate(FIVE_RACE_STARTS, start=1)
        ),
    )
    set_clock("2026-08-05T18:00:00Z")
    for race_number in (1, 2, 3, 4):
        _sail(world, race_number, B_WINS if race_number == 4 else A_WINS)
    return world


def _sail(world, race_number, elapsed_by_key):
    """Start, result and score one already-scheduled race, leaving the clock be."""
    race = world["races"][race_number]
    pro_id = world["ids"]["pro"]
    run_race_to_started(race["id"], pro_id, race["scheduled_start_utc"])
    rows = {}
    for key, elapsed in elapsed_by_key.items():
        rows[key] = record_result(
            race["id"], world["entries"][key]["id"], pro_id, elapsed_seconds=elapsed
        )
    world.setdefault("results", {})[race_number] = rows
    world["races"][race_number] = score_race(race["id"], pro_id)
    return world["races"][race_number]


def test_four_counted_races_leave_the_discard_set_empty(api):
    """PRD 3.9: "Under `ONE_PER_FIVE` one result is discarded once at least 5
    races have been counted, and never more than one."

    PRD 3.9 also fixes what an empty entitlement means for the totals:
    "`series_points_net` is `series_points_gross` minus the summed `points` of the
    discarded results, rounded half-up to one decimal place, and
    `discarded_race_numbers` holds the `race_number` values of the discarded
    results in ascending order."

    Design: Difficulty/boundary_precision_check/discard_activates_exactly_at_fifth_final_race
    """
    world = _four_final_races_world()

    leader = read_standing(world["entries"]["A"]["id"])
    assert leader["races_counted"] == 4, "one short of the threshold"
    assert leader["gross_points"] == 5.0, "1.0 three times and 2.0 once"
    assert leader["net_points"] == 5.0, "net equals gross while nothing is discarded"
    assert leader["discarded_race_numbers"] == []

    chaser = read_standing(world["entries"]["B"]["id"])
    assert chaser["races_counted"] == 4
    assert chaser["gross_points"] == 7.0
    assert chaser["net_points"] == 7.0
    assert chaser["discarded_race_numbers"] == []
    assert read_regatta(world["regatta_id"])["final_race_count"] == 4


def test_the_fifth_counted_race_discards_the_highest_scoring_and_latest_race(api):
    """PRD 3.9: "The discard pool for an entry is its results in the counted races
    that are not voided and whose `discardable` flag is true; the entitlement is
    spent on the highest-scoring members of that pool, and when two pool members
    carry equal `points`, the one from the **higher** `race_number` is discarded
    first, never the one with the lower identifier."

    Design: Difficulty/boundary_precision_check/discard_activates_exactly_at_fifth_final_race
    """
    world = _four_final_races_world()
    _sail(world, 5, A_WINS)

    leader = read_standing(world["entries"]["A"]["id"])
    assert leader["races_counted"] == 5
    assert leader["gross_points"] == 6.0
    assert leader["net_points"] == 4.0, "the single 2.0 is the highest-scoring member"
    assert leader["discarded_race_numbers"] == [4]
    assert leader["rank"] == 1

    chaser = read_standing(world["entries"]["B"]["id"])
    assert chaser["races_counted"] == 5
    assert chaser["gross_points"] == 9.0
    assert chaser["net_points"] == 7.0
    assert chaser["discarded_race_numbers"] == [5], (
        "among four equal 2.0 scores the highest race number goes"
    )
    assert chaser["rank"] == 2

    stored = read_entry(world["entries"]["A"]["id"])
    assert stored["series_points_gross"] == 6.0
    assert stored["series_points_net"] == 4.0
    assert stored["discarded_race_numbers"] == [4]
    assert stored["series_rank"] == 1

    for race_number in (1, 2, 3, 4, 5):
        assert read_race(world["races"][race_number]["id"])["points_pool_total"] == 3.0
    regatta = read_regatta(world["regatta_id"])
    assert regatta["final_race_count"] == 5
    assert regatta["status"] == "RACING", "six races were planned"


BAND_KEY_ON_THE_EDGE = 171.3
NARROW_LOW = {
    "code": "NLOW",
    "boat_type_filter": "MONOHULL",
    "rating_band_low": 150.0,
    "rating_band_high": BAND_KEY_ON_THE_EDGE,
    "min_entries": 2,
}


def _unassigned_entry_world():
    """One submitted, crewed, unassigned entry whose band key is exactly the upper
    edge of the only division in the regatta."""
    return build_accepted_fleet_world(
        divisions=(NARROW_LOW,),
        entrants=(
            {
                "key": "A",
                "helm": "helm_1",
                "measurement": MEASUREMENT_A,
                "inspect": None,
                "assign": False,
                "accept": False,
            },
        ),
        confirm_division_codes=(),
    )


def test_a_band_key_equal_to_the_exclusive_upper_edge_matches_no_division(api):
    """PRD 3.5: "Eligible divisions are those of the entry's own regatta whose
    `status` is `PROVISIONAL` or `CONFIRMED` — a `MERGED` division is never
    eligible — whose `boat_type_filter` either equals the boat's `boat_type` or is
    `ANY`, and whose band contains the key, meaning `rating_band_low` is less than
    or equal to the key and the key is strictly less than `rating_band_high`."

    PRD 2.5 forbids any softening of that comparison: "Band comparisons use the
    1-decimal `band_key_spm` value with no tolerance whatsoever — a key exactly
    equal to a band's exclusive upper bound is outside that band."

    Design: Difficulty/boundary_precision_check/division_band_high_is_exclusive_at_exact_key
    """
    world = _unassigned_entry_world()
    entry_id = world["entries"]["A"]["id"]
    low_id = world["divisions"]["NLOW"]["id"]
    assert world["certificates"]["A"]["band_key_spm"] == BAND_KEY_ON_THE_EDGE

    validate_error(
        api.assign_division(entry_id, world["h"]["chair"]),
        ApiErrorId.ERR_NO_ELIGIBLE_DIVISION,
        expected_status=422,
    )

    assert read_entry(entry_id)["division_id"] is None, (
        "PRD 3.5: division_id is left null when no division is eligible"
    )
    low = read_division(low_id)
    assert low["assigned_entry_count"] == 0
    assert low["status"] == "PROVISIONAL"


def test_a_band_key_equal_to_the_inclusive_lower_edge_matches_that_division(api):
    """PRD 3.4: "The band is asymmetric and deliberately so: `rating_band_low` is
    an **inclusive** lower bound and `rating_band_high` an **exclusive** upper
    bound, and the high edge must be strictly greater than the low edge."

    The very same key of 171.3 that the exclusive upper edge rejected is admitted
    by the inclusive lower edge of a second band opening at 171.3.

    Design: Difficulty/boundary_precision_check/division_band_high_is_exclusive_at_exact_key
    """
    world = _unassigned_entry_world()
    entry_id = world["entries"]["A"]["id"]
    chair = world["h"]["chair"]
    validate_error(api.assign_division(entry_id, chair), ApiErrorId.ERR_NO_ELIGIBLE_DIVISION)

    high = validate_success(
        api.create_division(
            create_division_payload(
                world["regatta_id"],
                code="NHIGH",
                boat_type_filter="MONOHULL",
                rating_band_low=BAND_KEY_ON_THE_EDGE,
                rating_band_high=200.0,
                min_entries=2,
            ),
            chair,
        ),
        expected_status=201,
    )
    assigned = validate_success(api.assign_division(entry_id, chair))

    assert assigned["division_id"] == high["id"]
    assert assigned["registration_status"] == "SUBMITTED"
    assert assigned["version"] == 3, "one increment for the crew addition and one for this"
    target = read_division(high["id"])
    assert target["assigned_entry_count"] == 1
    assert target["accepted_entry_count"] == 0
    assert target["status"] == "PROVISIONAL"
    assert read_division(world["divisions"]["NLOW"]["id"])["assigned_entry_count"] == 0
