"""Server-side computations driven to the edges of their own constants: rating
clamps at saturation, the length factor pinned against both of its bounds,
readiness over a filtered input set, the two selector rankings, and the variant
switch that decides which allowance a corrected time reads.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    MEASUREMENT_A,
    MEASUREMENT_B,
    assert_same_instant,
    build_racing_world,
    build_started_race_world,
    confirm_duty,
    create_race_result_payload,
    enrol_member,
    file_certificate,
    make_race_officer_headers,
    open_regatta,
    propose_duty,
    read_boat,
    read_certificate,
    read_division,
    read_duty,
    read_entry,
    read_race,
    read_regatta,
    register_boat,
    schedule_race,
    set_clock,
)

EXTREME_SAILPLAN = {
    "sail_area_m2": 400.0,
    "hull_length_m": 14.0,
    "displacement_kg": 1000,
    "draft_m": 2.00,
}
EXTREME_LEAD_MINE = {
    "sail_area_m2": 4.0,
    "hull_length_m": 4.0,
    "displacement_kg": 8000,
    "draft_m": 1.00,
}


def test_both_rating_lines_saturate_against_their_declared_clamps(api, roster):
    """PRD 3.2: "Under `TOD_PHRF`, multiply `raw_speed_index` by 380.0, subtract
    that product from 420.0, round half-up to one decimal place, and then confine the
    result to the closed range from −30.0 to 300.0; the outcome is `rating_value`,
    expressed in seconds per nautical mile, and `band_key_spm` is set equal to it.
    Under `TOT_ORC`, multiply `raw_speed_index` by 0.7000, add 0.4000, round half-up
    to four decimal places, and then confine the result to the closed range 0.5000 to
    1.6000; the outcome is `rating_value`, a dimensionless factor."

    PRD 3.2 then fixes that the projection reads the clamped figure: "Because
    divisions are banded on a single scale, a time-on-time certificate additionally
    gets a seconds-per-mile projection: subtract 0.4000 from `rating_value`, multiply
    the difference by 542.8571, subtract that product from 420.0 and round half-up to
    one decimal place, and store the result as `band_key_spm`."

    Design: Corner/calculations/rating_value_saturates_at_tot_and_tod_clamp_ceilings
    """
    measurer_id = roster["measurer"]["id"]
    over_canvassed = register_boat(roster["helm_1"]["id"])
    under_canvassed = register_boat(roster["helm_2"]["id"])

    high_tot = file_certificate(
        over_canvassed["id"], measurer_id,
        measurement=EXTREME_SAILPLAN, rule_code="TOT_ORC",
    )
    high_tod = file_certificate(
        over_canvassed["id"], measurer_id,
        measurement=EXTREME_SAILPLAN, rule_code="TOD_PHRF",
    )
    low_tod = file_certificate(
        under_canvassed["id"], measurer_id,
        measurement=EXTREME_LEAD_MINE, rule_code="TOD_PHRF",
    )
    low_tot = file_certificate(
        under_canvassed["id"], measurer_id,
        measurement=EXTREME_LEAD_MINE, rule_code="TOT_ORC",
    )

    assert high_tot["raw_speed_index"] == 3.2
    assert high_tot["rating_value"] == 1.6, "0.4000 plus 0.7000 times 3.2 is 2.64"
    assert high_tot["band_key_spm"] == -231.4, (
        "projected from the clamped 1.6000, never from the unclamped 2.64"
    )
    assert high_tod["raw_speed_index"] == 3.2
    assert high_tod["rating_value"] == -30.0, "420.0 less 380.0 times 3.2 is -796.0"
    assert high_tod["band_key_spm"] == -30.0

    assert low_tod["raw_speed_index"] == 0.1
    assert low_tod["rating_value"] == 300.0, "420.0 less 380.0 times 0.1 is 382.0"
    assert low_tod["band_key_spm"] == 300.0
    assert low_tot["raw_speed_index"] == 0.1
    assert low_tot["rating_value"] == 0.5, "0.4000 plus 0.7000 times 0.1 is 0.47"
    assert low_tot["band_key_spm"] == 365.7

    assert read_boat(over_canvassed["id"])["version"] == 3, "two certificate creates"
    assert read_boat(under_canvassed["id"])["version"] == 3


FLOOR_HULLS = (7.0, 8.0)
CEILING_HULLS = (12.8, 13.6)
BROAD_BEAM = {"sail_area_m2": 64.0, "displacement_kg": 8000, "draft_m": 1.80}


def test_two_hulls_below_the_length_floor_and_two_above_the_ceiling_collapse_to_two_ratings(api, roster):
    """PRD 3.2: "Divide `hull_length_m` by 8.0 and confine the result to the closed
    range 1.00 to 1.60 — a quotient below 1.00 is treated as 1.00 and one above 1.60
    as 1.60 — giving the length factor."

    PRD 3.2 also fixes the rest of the product these four boats share: "Take the
    square root of `sail_area_m2` and divide it by the cube root of
    `displacement_kg`; that quotient is the base figure."

    Design: Corner/calculations/length_factor_floor_and_ceiling_bound_the_speed_index
    """
    measurer_id = roster["measurer"]["id"]
    owner_id = roster["helm_1"]["id"]
    ratings = {}
    for hull_length_m in FLOOR_HULLS + CEILING_HULLS:
        boat = register_boat(owner_id)
        ratings[hull_length_m] = file_certificate(
            boat["id"], measurer_id,
            measurement={**BROAD_BEAM, "hull_length_m": hull_length_m},
            rule_code="TOD_PHRF",
        )

    assert ratings[7.0]["raw_speed_index"] == 0.4, "the ratio 0.875 was raised to 1.00"
    assert ratings[7.0]["rating_value"] == 268.0
    assert ratings[8.0]["raw_speed_index"] == 0.4, "the ratio is exactly the floor"
    assert ratings[8.0]["rating_value"] == 268.0

    assert ratings[12.8]["raw_speed_index"] == 0.64, "the ratio is exactly the ceiling"
    assert ratings[12.8]["rating_value"] == 176.8
    assert ratings[13.6]["raw_speed_index"] == 0.64, "the ratio 1.70 was cut back to 1.60"
    assert ratings[13.6]["rating_value"] == 176.8

    assert ratings[13.6]["rating_value"] - ratings[12.8]["rating_value"] == 0.0, (
        "the extra 0.8 metres of hull above the ceiling buys nothing at all"
    )
    assert round(ratings[8.0]["rating_value"] - ratings[12.8]["rating_value"], 1) == 91.2, (
        "while the 4.8 metres between the two bounds buys 91.2 seconds per mile"
    )
    for certificate in ratings.values():
        assert certificate["band_key_spm"] == certificate["rating_value"], (
            "a time-on-distance rule needs no projection"
        )


FULL_DAY = ("2026-08-05T12:00:00Z", "2026-08-05T20:00:00Z")
AFTERNOON_ONLY = ("2026-08-05T13:30:00Z", "2026-08-05T15:00:00Z")
RACE_START = "2026-08-05T14:00:00Z"


def _staffing_world(roster):
    """A race at 14:00 whose coverage window runs 13:30 to 16:00, standing behind a
    confirmed PRO and TIMEKEEPER across the whole day, a confirmed SIGNALS duty that
    stops an hour into the window, and a second SIGNALS duty that spans everything
    but was left PROPOSED.
    """
    chair_id = roster["chair"]["id"]
    understudy = enrol_member(full_name="Iris Vale")
    regatta = open_regatta(chair_id)
    duties = {}
    for key, position in (("pro", "PRO"), ("timekeeper", "TIMEKEEPER")):
        duty = propose_duty(
            regatta["id"], chair_id, roster[key]["id"], position,
            window_start_utc=FULL_DAY[0], window_end_utc=FULL_DAY[1],
        )
        duties[position] = confirm_duty(duty["id"], chair_id)
    short = propose_duty(
        regatta["id"], chair_id, roster["signals"]["id"], "SIGNALS",
        window_start_utc=AFTERNOON_ONLY[0], window_end_utc=AFTERNOON_ONLY[1],
    )
    duties["SIGNALS_SHORT"] = confirm_duty(short["id"], chair_id)
    duties["SIGNALS_FULL"] = propose_duty(
        regatta["id"], chair_id, understudy["id"], "SIGNALS",
        window_start_utc=FULL_DAY[0], window_end_utc=FULL_DAY[1],
    )
    race = schedule_race(regatta["id"], chair_id, 1, RACE_START)
    return {"regatta": regatta, "duties": duties, "race": race, "understudy": understudy}


def test_readiness_counts_only_confirmed_windows_that_span_the_whole_coverage_window(api, roster, headers):
    """PRD 3.6: "For a given race, the coverage window runs from half an hour before
    its `scheduled_start_utc` to two hours after it — that is, from 30 minutes before
    to 120 minutes after. An assignment counts as on station only if its `status` is
    `CONFIRMED`, its `regatta_id` is the race's regatta, its `race_id` is either that
    race or null, its `window_start_utc` is at or before the start of the coverage
    window, and its `window_end_utc` is at or after the end of it. A window that
    merely overlaps part of the coverage window contributes nothing at all; a window
    flush with both edges counts, because both comparisons are inclusive. `PROPOSED`
    and `RELEASED` assignments are ignored entirely."

    PRD 3.6 also fixes which positions this course and this safety category demand:
    "Three positions are always required, one of each: `PRO`, `TIMEKEEPER` and
    `SIGNALS`. A race whose `course_code` is `WINDWARD_LEEWARD` or `TRIANGLE`
    additionally requires one `MARK_BOAT_DRIVER`, since those courses have marks to be
    laid and shifted; a `DISTANCE_COASTAL` course does not. A regatta whose
    `safety_category` is `CAT_3` or `CAT_2` additionally requires one `SAFETY_BOAT`;
    `CAT_4` does not."

    Design: Corner/calculations/staffing_readiness_ignores_partially_covering_and_proposed_windows
    """
    world = _staffing_world(roster)
    race_id = world["race"]["id"]
    officer = make_race_officer_headers(roster["pro"]["id"])

    short_handed = validate_success(api.get_staffing(race_id, officer))

    assert short_handed["race_id"] == race_id
    assert short_handed["staffing_ready"] is False
    assert short_handed["staffed_position_codes"] == ["PRO", "TIMEKEEPER"], (
        "the SIGNALS window flush at 13:30 but two hours short at 16:00 counts for nothing"
    )
    assert short_handed["missing_position_codes"] == ["SIGNALS"]
    assert_same_instant(short_handed["coverage_window_start_utc"], "2026-08-05T13:30:00Z", "coverage_window_start_utc")
    assert_same_instant(short_handed["coverage_window_end_utc"], "2026-08-05T16:00:00Z", "coverage_window_end_utc")

    validate_success(
        api.confirm_duty_assignment(world["duties"]["SIGNALS_FULL"]["id"], headers["chair"])
    )

    on_station = validate_success(api.get_staffing(race_id, officer))

    assert on_station["staffing_ready"] is True
    assert on_station["staffed_position_codes"] == ["PRO", "SIGNALS", "TIMEKEEPER"]
    assert on_station["missing_position_codes"] == []
    assert read_duty(world["duties"]["SIGNALS_SHORT"]["id"])["status"] == "CONFIRMED", (
        "the short window was never rejected, it simply never counted"
    )
    spanning = read_duty(world["duties"]["SIGNALS_FULL"]["id"])
    assert spanning["status"] == "CONFIRMED"
    assert spanning["duty_minutes"] == 480


WIDE_ANY = {
    "code": "W",
    "boat_type_filter": "ANY",
    "rating_band_low": 160.0,
    "rating_band_high": 200.0,
    "min_entries": 2,
}
NARROW_MONOHULL = {
    "code": "N",
    "boat_type_filter": "MONOHULL",
    "rating_band_low": 165.0,
    "rating_band_high": 175.0,
    "min_entries": 2,
}
NARROWEST_MULTIHULL = {
    "code": "M",
    "boat_type_filter": "MULTIHULL",
    "rating_band_low": 170.0,
    "rating_band_high": 172.0,
    "min_entries": 2,
}
UNASSIGNED_MONOHULL = (
    {
        "key": "A",
        "helm": "helm_1",
        "measurement": MEASUREMENT_A,
        "crew": [],
        "inspect": None,
        "assign": False,
        "accept": False,
    },
)


def test_the_selector_takes_the_narrowest_band_that_survived_the_hull_filter(api):
    """PRD 3.5: "Eligible divisions are those of the entry's own regatta whose
    `status` is `PROVISIONAL` or `CONFIRMED` — a `MERGED` division is never eligible —
    whose `boat_type_filter` either equals the boat's `boat_type` or is `ANY`, and
    whose band contains the key, meaning `rating_band_low` is less than or equal to the
    key and the key is strictly less than `rating_band_high`. Among the eligible
    divisions the narrowest band wins: candidates are ordered by band width, that is
    `rating_band_high` minus `rating_band_low`, ascending; ties by `rating_band_low`
    ascending; and any remaining tie by `created_at` ascending, never by identifier."

    Design: Corner/calculations/assign_division_selects_narrowest_eligible_band_over_wider_and_wrong_type
    """
    world = build_racing_world(
        publish="nor",
        divisions=(WIDE_ANY, NARROW_MONOHULL, NARROWEST_MULTIHULL),
        entrants=UNASSIGNED_MONOHULL,
        confirm_division_codes=(),
    )

    assigned = validate_success(
        api.assign_division(world["entries"]["A"]["id"], world["h"]["chair"])
    )

    assert assigned["division_id"] == world["divisions"]["N"]["id"], (
        "the ten-point MONOHULL band beat the forty-point ANY band"
    )
    assert assigned["registration_status"] == "SUBMITTED", "assignment is not admission"
    assert assigned["version"] == 2

    chosen = read_division(world["divisions"]["N"]["id"])
    assert chosen["assigned_entry_count"] == 1
    assert chosen["accepted_entry_count"] == 0
    assert read_division(world["divisions"]["W"]["id"])["assigned_entry_count"] == 0, (
        "the wider eligible band lost the ranking"
    )
    assert read_division(world["divisions"]["M"]["id"])["assigned_entry_count"] == 0, (
        "the narrowest band of all was filtered out on hull type before ranking"
    )


BAND_A = {
    "code": "A",
    "boat_type_filter": "MONOHULL",
    "rating_band_low": 165.0,
    "rating_band_high": 175.0,
    "min_entries": 2,
}
BAND_B = {
    "code": "B",
    "boat_type_filter": "MONOHULL",
    "rating_band_low": 176.0,
    "rating_band_high": 200.0,
    "min_entries": 2,
}
BAND_C = {
    "code": "C",
    "boat_type_filter": "MONOHULL",
    "rating_band_low": 201.0,
    "rating_band_high": 230.0,
    "min_entries": 2,
}
ONE_ASSIGNED_MONOHULL = (
    {
        "key": "A",
        "helm": "helm_1",
        "measurement": MEASUREMENT_A,
        "crew": [],
        "inspect": None,
        "accept": False,
    },
)


def test_the_merge_target_is_the_nearest_band_midpoint_not_the_adjacent_band(api):
    """PRD 3.4: "Among the candidates the server computes each band's midpoint — the
    sum of `rating_band_low` and `rating_band_high` divided by two — and prefers the
    candidate whose midpoint is closest to the merging division's own midpoint,
    measured as an absolute difference. Ties are broken by the lower
    `rating_band_low`, and any remaining tie by the earlier `created_at`; the
    identifier is never used as a tie-breaker."

    PRD 3.4 also fixes that the absorbed entry follows the pointer regardless of its
    own key: "Hop two re-points every entry currently held by the merged division to
    the target division — only entries in `SUBMITTED` or `ACCEPTED` bear on any count,
    but the pointer itself moves for every entry of the merged division."

    Design: Corner/calculations/division_merge_selects_nearest_band_midpoint_target
    """
    world = build_racing_world(
        regatta_overrides={"fleet_minimum": 2},
        publish="nor",
        divisions=(BAND_A, BAND_B, BAND_C),
        entrants=ONE_ASSIGNED_MONOHULL,
        confirm_division_codes=(),
    )
    entry_id = world["entries"]["A"]["id"]
    assert read_entry(entry_id)["division_id"] == world["divisions"]["A"]["id"]

    merged = validate_success(
        api.merge_division(world["divisions"]["A"]["id"], world["h"]["chair"])
    )

    assert merged["status"] == "MERGED"
    assert merged["merged_into_division_id"] == world["divisions"]["B"]["id"], (
        "a midpoint distance of 18.0 beat one of 45.5"
    )
    assert merged["assigned_entry_count"] == 0, "the count followed the re-point"
    assert read_entry(entry_id)["division_id"] == world["divisions"]["B"]["id"], (
        "the entry followed the merge even though 171.3 lies outside the target band"
    )

    target = read_division(world["divisions"]["B"]["id"])
    assert target["assigned_entry_count"] == 1
    assert target["accepted_entry_count"] == 0
    assert target["status"] == "PROVISIONAL", "one absorbed entry is still under its floor"
    loser = read_division(world["divisions"]["C"]["id"])
    assert loser["assigned_entry_count"] == 0
    assert loser["status"] == "PROVISIONAL"
    assert read_regatta(world["regatta_id"])["confirmed_division_count"] == 0


RESULTS_CLOCK = "2026-08-05T15:00:00Z"
MIXED_RULE_FLEET = (
    {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A, "rule_code": "TOT_ORC"},
    {
        "key": "B",
        "helm": "helm_2",
        "measurement": MEASUREMENT_B,
        "rule_code": "TOD_PHRF",
        "crew": [],
        "inspect": None,
        "accept": False,
    },
)


def test_a_unified_basis_corrects_a_time_on_time_certificate_on_the_distance_scale(api):
    """PRD 3.8: "The **time-on-distance** variant applies when the regatta's
    `handicap_basis` is `UNIFIED_TOD`, whatever the certificate's `rule_code`, and also
    when `handicap_basis` is `PER_CERTIFICATE` while the pinned certificate's
    `rule_code` is `TOD_PHRF`. Its allowance in seconds per mile is the certificate's
    `rating_value` when `rule_code` is `TOD_PHRF`, and the certificate's `band_key_spm`
    when `rule_code` is `TOT_ORC` — which is how a unified-scale regatta scores a
    time-on-time certificate on the distance scale. Multiply that allowance by
    `course_distance_nm`, subtract the product from `elapsed_seconds`, and round
    half-up to one decimal place."

    PRD 3.8 names what the discarded branch would have produced: "The
    **time-on-time** variant applies in exactly one case: the regatta's
    `handicap_basis` is `PER_CERTIFICATE` and the pinned certificate's `rule_code` is
    `TOT_ORC`. Multiply `elapsed_seconds` by the certificate's `rating_value` and round
    half-up to one decimal place."

    Design: Corner/calculations/unified_tod_basis_scores_tot_certificate_on_band_key_allowance
    """
    world = build_started_race_world(
        regatta_overrides={"handicap_basis": "UNIFIED_TOD"},
        entrants=MIXED_RULE_FLEET,
    )
    pinned = read_certificate(world["certificates"]["A"]["id"])
    assert pinned["rule_code"] == "TOT_ORC"
    assert pinned["rating_value"] == 0.8582
    assert pinned["band_key_spm"] == 171.3
    race_id = world["races"][1]["id"]
    set_clock(RESULTS_CLOCK)

    recorded = validate_success(
        api.create_race_result(
            create_race_result_payload(
                race_id, world["entries"]["A"]["id"], elapsed_seconds=4800.0
            ),
            make_race_officer_headers(world["ids"]["pro"]),
        ),
        expected_status=201,
    )

    assert recorded["corrected_seconds"] == 3772.2, (
        "4800.0 less the band-key allowance of 171.3 over 6.0 miles"
    )
    assert recorded["corrected_seconds"] != 4119.4, (
        "which is what multiplying by the 0.8582 rating factor would have produced"
    )
    assert recorded["place"] is None, "places and points wait for the score run"
    assert recorded["points"] == 0
    assert recorded["voided"] is False
    assert recorded["discardable"] is True

    race = read_race(race_id)
    assert race["scoring_status"] == "PROVISIONAL"
    assert_same_instant(race["results_closed_utc"], RESULTS_CLOCK, "results_closed_utc")
    assert race["points_pool_total"] == 0
