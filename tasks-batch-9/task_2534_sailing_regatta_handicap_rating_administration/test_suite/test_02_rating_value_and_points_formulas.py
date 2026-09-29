"""Multi-input formulas: the rating pipeline with every multiplier live at once,
and the two rounding points of the series arithmetic.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    MEASUREMENT_A,
    MEASUREMENT_B,
    MEASUREMENT_D,
    build_accepted_fleet_world,
    decide_payload,
    evidence_payload,
    file_certificate,
    read_protest,
    read_result,
    read_standing,
    register_boat,
    sail_and_score_race,
    schedule_hearing_payload,
    set_clock,
)

MEASUREMENT_LONG = {
    "sail_area_m2": 88.0,
    "hull_length_m": 14.0,
    "displacement_kg": 6100,
    "draft_m": 2.05,
}
MEASUREMENT_MULTI = {
    "sail_area_m2": 95.0,
    "hull_length_m": 12.2,
    "displacement_kg": 2100,
    "draft_m": 1.10,
}


def _file_five_certificates(roster):
    """Five draft certificates that between them exercise the length-factor
    ceiling, the deep-draft penalty, two hull families and both rule branches."""
    measurer_id = roster["measurer"]["id"]
    owner_id = roster["helm_1"]["id"]
    baseline = register_boat(owner_id)
    long_boat = register_boat(owner_id)
    multi = register_boat(owner_id, boat_type="MULTIHULL")
    deep = register_boat(owner_id)
    return {
        "baseline": file_certificate(baseline["id"], measurer_id, measurement=MEASUREMENT_A),
        "long": file_certificate(long_boat["id"], measurer_id, measurement=MEASUREMENT_LONG),
        "multi": file_certificate(multi["id"], measurer_id, measurement=MEASUREMENT_MULTI),
        "deep_tod": file_certificate(deep["id"], measurer_id, measurement=MEASUREMENT_D),
        "deep_tot": file_certificate(
            deep["id"], measurer_id, measurement=MEASUREMENT_D, rule_code="TOT_ORC"
        ),
    }


def test_speed_index_combines_length_ceiling_draft_penalty_and_hull_family(api, roster):
    """PRD 3.2: "Multiply the base figure by the length factor, then by the draft
    multiplier, then by the hull-family multiplier, and round the product half-up
    to four decimal places."

    Four certificates pin the four multiplicative inputs: an 11.0 m hull inside
    the length band, a 14.0 m hull whose quotient of 1.75 is confined to the 1.60
    ceiling, a multihull carrying the 0.82 family multiplier, and a 2.35 m draft
    carrying the deep-draft 0.97.

    Design: Difficulty/combinatorial_formula/certificate_rating_value_nonlinear_clamp_penalty_and_rule_branch
    """
    certificates = _file_five_certificates(roster)

    assert certificates["baseline"]["raw_speed_index"] == 0.6545
    assert certificates["long"]["raw_speed_index"] == 0.8215, (
        "the length factor is confined to 1.60 even though 14.0 / 8.0 is 1.75"
    )
    assert certificates["multi"]["raw_speed_index"] == 0.9518
    assert certificates["deep_tod"]["raw_speed_index"] == 0.5767

    assert certificates["baseline"]["rating_value"] == 171.3
    assert certificates["long"]["rating_value"] == 107.8
    assert certificates["multi"]["rating_value"] == 58.3
    assert certificates["deep_tod"]["rating_value"] == 200.9
    for key, certificate in certificates.items():
        assert certificate["status"] == "DRAFT", f"{key} is filed in DRAFT"
        assert certificate["measured_by_member_id"] == roster["measurer"]["id"]


def test_rule_branch_splits_one_speed_index_into_two_ratings_and_two_band_keys(api, roster):
    """PRD 3.2: "Because divisions are banded on a single scale, a time-on-time
    certificate additionally gets a seconds-per-mile projection: subtract 0.4000
    from `rating_value`, multiply the difference by 542.8571, subtract that
    product from 420.0 and round half-up to one decimal place, and store the
    result as `band_key_spm`."

    The same 0.5767 speed index yields 200.9 seconds per mile under the
    time-on-distance branch, whose band key equals the rating, and 0.8037 under
    the time-on-time branch, whose projected band key is 200.8 — one tenth apart,
    because the projection is not the inverse of the rating line.

    Design: Difficulty/combinatorial_formula/certificate_rating_value_nonlinear_clamp_penalty_and_rule_branch
    """
    certificates = _file_five_certificates(roster)
    tod = certificates["deep_tod"]
    tot = certificates["deep_tot"]

    assert tod["raw_speed_index"] == tot["raw_speed_index"] == 0.5767, (
        "the branch consumes one and the same rounded speed index"
    )
    assert (tod["rule_code"], tod["rating_value"], tod["band_key_spm"]) == (
        "TOD_PHRF", 200.9, 200.9,
    )
    assert (tot["rule_code"], tot["rating_value"], tot["band_key_spm"]) == (
        "TOT_ORC", 0.8037, 200.8,
    )
    assert certificates["baseline"]["band_key_spm"] == 171.3
    assert certificates["long"]["band_key_spm"] == 107.8
    assert certificates["multi"]["band_key_spm"] == 58.3


ENTRANTS_D_A_B = (
    {"key": "D", "helm": "helm_3", "measurement": MEASUREMENT_D},
    {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
    {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_B},
)


def _bonus_world(race_starts):
    """A three-boat BONUS_POINT series that discards nothing, with one race
    scheduled at each supplied instant."""
    return build_accepted_fleet_world(
        regatta_overrides={"scoring_system": "BONUS_POINT", "discard_policy": "NONE"},
        entrants=ENTRANTS_D_A_B,
        panel=True,
        racing=True,
        staffing=True,
        races=tuple(
            {"race_number": number, "scheduled_start_utc": start}
            for number, start in enumerate(race_starts, start=1)
        ),
    )


def test_bonus_tie_group_average_is_rounded_once_per_race_before_the_series_sum(api):
    """PRD 2.5: "Series totals sum the already-rounded per-race `points` values;
    summing unrounded per-race values and rounding only the total is forbidden and
    can differ by a tenth of a point for every three fractional races."

    A two-boat tie across slots 2 and 3 averages 3.0 and 5.7 to 4.35, which is
    rounded once at group level to 4.4. Two such races therefore sum to 8.8, and
    never to the 8.7 that summing the unrounded 4.35 twice would produce.

    Design: Difficulty/combinatorial_formula/series_gross_rounds_per_race_before_summing_bonus_tie
    """
    world = _bonus_world(("2026-08-05T14:00:00Z", "2026-08-05T15:00:00Z"))
    plan = {"D": 5105.4, "A": 5027.8, "B": 5312.8}
    first = sail_and_score_race(world, 1, plan)
    second = sail_and_score_race(world, 2, plan)

    assert first["points_pool_total"] == 8.8
    assert second["points_pool_total"] == 8.8
    for race_number in (1, 2):
        rows = world["results"][race_number]
        assert read_result(rows["A"]["id"])["points"] == 4.4, (
            "the group average is rounded at group level, not per member"
        )
        assert read_result(rows["B"]["id"])["points"] == 4.4

    standing = read_standing(world["entries"]["A"]["id"])
    assert standing["gross_points"] == 8.8, (
        "two already-rounded 4.4 values sum to 8.8, not to the 8.7 of 4.35 twice"
    )
    assert standing["races_counted"] == 2


def test_no_discard_policy_leaves_the_gross_and_net_series_totals_equal(api):
    """PRD 3.9: "Under `NONE` nothing is ever discarded."

    Design: Difficulty/combinatorial_formula/series_gross_rounds_per_race_before_summing_bonus_tie
    """
    world = _bonus_world(("2026-08-05T14:00:00Z", "2026-08-05T15:00:00Z"))
    plan = {"D": 5105.4, "A": 5027.8, "B": 5312.8}
    sail_and_score_race(world, 1, plan)
    sail_and_score_race(world, 2, plan)

    leader = read_standing(world["entries"]["D"]["id"])
    assert (leader["gross_points"], leader["net_points"]) == (0.0, 0.0)
    assert leader["discarded_race_numbers"] == []
    assert leader["rank"] == 1

    for key in ("A", "B"):
        standing = read_standing(world["entries"][key]["id"])
        assert standing["discarded_race_numbers"] == []
        assert standing["net_points"] == standing["gross_points"] == 8.8


def _four_race_redress_world(api):
    """Four scored races in which the redress candidate finishes, retires, sails
    a slow third race and finally does not compete at all, then a protest carried
    all the way to a granted redress on the third race.
    """
    world = _bonus_world(
        (
            "2026-08-05T14:00:00Z",
            "2026-08-05T15:00:00Z",
            "2026-08-05T16:00:00Z",
            "2026-08-05T17:00:00Z",
        )
    )
    sail_and_score_race(world, 1, {"D": 5105.4, "A": 5027.8, "B": 5312.8})
    sail_and_score_race(
        world, 2, {"D": 5105.4, "B": 5312.8, "A": {"finish_status": "DNF"}}
    )
    sail_and_score_race(world, 3, {"D": 5105.4, "B": 5312.8, "A": 5127.8})
    sail_and_score_race(world, 4, {"D": 5105.4, "B": 5312.8})

    protest = validate_success(
        api.create_protest(
            {
                "race_id": world["races"][3]["id"],
                "protestor_entry_id": world["entries"]["A"]["id"],
                "protestee_entry_id": world["entries"]["B"]["id"],
                "rule_cited": "RRS_62",
                "incident_utc": "2026-08-05T16:15:00Z",
            },
            world["h"]["helm_1"],
        ),
        expected_status=201,
    )
    validate_success(
        api.file_evidence(
            protest["id"],
            evidence_payload(world["entries"]["A"]["id"]),
            world["h"]["helm_1"],
        )
    )
    validate_success(
        api.schedule_hearing(
            protest["id"],
            schedule_hearing_payload(world["panel"]["id"], "2026-08-05T19:00:00Z"),
            world["h"]["jury"],
        )
    )
    set_clock("2026-08-05T19:00:00Z")
    validate_success(api.hear_protest(protest["id"], world["h"]["jury"]))
    world["protest"] = protest
    return world


def test_redress_score_averages_only_the_qualifying_source_results(api):
    """PRD 3.10: "Second, gather the target entry's source results: its non-voided
    results in counted races other than the redress race whose `finish_status` is
    one of `FINISHED`, `DNF`, `DNS`, `RET` or `OCS`. Results with `finish_status`
    `DSQ` or `DNC`, and any other `RDG` result, are excluded from the average."

    The redress candidate carries 4.4 as a finisher, 4.0 as a retirement, 5.7 in
    the redress race itself and 5.0 as a did-not-compete. Only the first two
    qualify, so the average is 4.2 rather than any figure involving 5.0 or 5.7.

    Design: Difficulty/combinatorial_formula/redress_points_average_fixed_point_excludes_redress_race_and_dnc
    """
    world = _four_race_redress_world(api)

    decided = validate_success(
        api.decide_protest(
            world["protest"]["id"],
            decide_payload(
                "REDRESS_GRANTED",
                penalty_target_entry_id=world["entries"]["A"]["id"],
                redress_race_number=3,
            ),
            world["h"]["jury"],
        )
    )

    assert decided["status"] == "DECIDED" and decided["decision"] == "REDRESS_GRANTED"
    assert decided["redress_race_number"] == 3
    redressed = read_result(world["results"][3]["A"]["id"])
    assert redressed["finish_status"] == "RDG"
    assert redressed["points"] == 4.2, "the mean of 4.4 and 4.0 is 4.2"
    assert redressed["place"] is None
    assert redressed["corrected_seconds"] is None
    assert redressed["discardable"] is True


def test_redress_rescore_touches_only_the_redress_race_pool_and_the_series_totals(api):
    """PRD 3.10: "Fifth, the race points and places are re-run for the redress
    race, leaving the other rows of that race unchanged, and then the series
    standing is re-run for every `ACCEPTED` entry of the division. Sixth — and
    this is the load-bearing part — the redress score is **not** recomputed after
    that re-run, even though the discard set and the ranks it feeds may have
    moved."

    Design: Difficulty/combinatorial_formula/redress_points_average_fixed_point_excludes_redress_race_and_dnc
    """
    world = _four_race_redress_world(api)
    validate_success(
        api.decide_protest(
            world["protest"]["id"],
            decide_payload(
                "REDRESS_GRANTED",
                penalty_target_entry_id=world["entries"]["A"]["id"],
                redress_race_number=3,
            ),
            world["h"]["jury"],
        )
    )

    third = validate_success(api.get_race(world["races"][3]["id"], world["h"]["chair"]))
    assert third["scoring_status"] == "FINAL", "a re-score never leaves FINAL"
    assert third["rescore_count"] == 1
    assert third["points_pool_total"] == 7.2, "0.0 plus 3.0 plus the 4.2 redress"
    assert read_result(world["results"][3]["D"]["id"])["points"] == 0.0
    assert read_result(world["results"][3]["B"]["id"])["points"] == 3.0

    assert validate_success(
        api.get_race(world["races"][1]["id"], world["h"]["chair"])
    )["points_pool_total"] == 8.8
    assert validate_success(
        api.get_race(world["races"][2]["id"], world["h"]["chair"])
    )["points_pool_total"] == 7.0
    assert validate_success(
        api.get_race(world["races"][4]["id"], world["h"]["chair"])
    )["points_pool_total"] == 8.0

    assert read_standing(world["entries"]["A"]["id"])["gross_points"] == 17.6
    assert read_standing(world["entries"]["B"]["id"])["gross_points"] == 13.4
    assert read_standing(world["entries"]["D"]["id"])["gross_points"] == 0.0
    assert read_standing(world["entries"]["D"]["id"])["rank"] == 1
    assert read_standing(world["entries"]["B"]["id"])["rank"] == 2
    assert read_standing(world["entries"]["A"]["id"])["rank"] == 3
    assert read_protest(world["protest"]["id"])["reopen_count"] == 0
