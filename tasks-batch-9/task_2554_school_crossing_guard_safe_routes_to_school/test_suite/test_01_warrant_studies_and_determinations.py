"""Warrant scoring, determinations and the study calendar.

The warrant study is where engineering judgement about a crossing is turned
into a number, and the number decides whether a guard post may ever be
activated there. These tests exercise the two scoring variants, the exact
threshold that separates a warranted crossing from an unwarranted one, and the
buffered calendar that keeps two count windows from crowding each other.
"""
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_warrant_study
from test_helpers.factories import create_warrant_study_payload
from test_helpers.fixtures import (
    ENGINEER,
    CANONICAL_CRASHES,
    create_school,
    read_intersection,
    read_study,
    setup_study_ready_to_analyze,
    setup_warranted_intersection,
)

# The primary boundary study: 60 + 40 children, 24 + 16 adequate gaps and
# 1800 + 1500 vehicles over a 25 mph crossing with no crash history.
BOUNDARY_AM_SESSION = {
    "session_date": "2026-09-08",
    "period": "AM_ARRIVAL",
    "observed_minutes": 60,
    "child_count": 60,
    "adult_count": 5,
    "vehicle_count": 1800,
    "adequate_gaps": 24,
}
BOUNDARY_PM_SESSION = {
    "session_date": "2026-09-09",
    "period": "PM_DISMISSAL",
    "observed_minutes": 60,
    "child_count": 40,
    "adult_count": 4,
    "vehicle_count": 1500,
    "adequate_gaps": 16,
}
# The control study differs only in the afternoon vehicle tally.
CONTROL_PM_SESSION = dict(BOUNDARY_PM_SESSION, vehicle_count=1400)


def test_uncontrolled_and_controlled_crossings_score_differently_on_identical_counts(api):
    """Two crossings that differ only in `control_type` diverge on the same field data.

    PRD: "Identical count sessions and identical crash history therefore yield
    materially different scores at an uncontrolled crossing and at a signalized
    one; the divergence is the intended behaviour, not an artifact."

    Design: Difficulty/dual_variant_calc/warrant_score_gap_adequacy_vs_exposure_index_divergence
    """
    school = create_school()
    uncontrolled = setup_study_ready_to_analyze(
        school=school, control_type="UNCONTROLLED",
        cross_streets="Maple St & 3rd Ave")
    controlled = setup_study_ready_to_analyze(
        school=school, control_type="STOP_SIGN",
        cross_streets="Birch St & 4th Ave")

    gap_study = validate_success(
        api.analyze_warrant_study(uncontrolled["study"]["id"], ENGINEER))
    exposure_study = validate_success(
        api.analyze_warrant_study(controlled["study"]["id"], ENGINEER))

    assert_warrant_study(gap_study)
    assert_warrant_study(exposure_study)
    assert gap_study["scoring_variant"] == "GAP_ADEQUACY"
    assert gap_study["warrant_score"] == 66.19
    assert gap_study["determination"] == "WARRANTED"
    assert exposure_study["scoring_variant"] == "EXPOSURE_INDEX"
    assert exposure_study["warrant_score"] == 51.98
    assert exposure_study["determination"] == "CONDITIONAL"
    assert round(gap_study["warrant_score"] - exposure_study["warrant_score"], 2) == 14.21


def test_both_scoring_variants_report_the_same_included_aggregates(api):
    """The two variants weigh the same tallies differently but count them identically.

    PRD: "Over that included set, `included_child_count` is the sum of
    `child_count`, `included_adequate_gaps` is the sum of `adequate_gaps`, and
    `included_vehicle_count` is the sum of `vehicle_count`."

    Design: Difficulty/dual_variant_calc/warrant_score_gap_adequacy_vs_exposure_index_divergence
    """
    school = create_school()
    uncontrolled = setup_study_ready_to_analyze(
        school=school, control_type="UNCONTROLLED",
        cross_streets="Maple St & 3rd Ave")
    controlled = setup_study_ready_to_analyze(
        school=school, control_type="STOP_SIGN",
        cross_streets="Birch St & 4th Ave")

    gap_study = validate_success(
        api.analyze_warrant_study(uncontrolled["study"]["id"], ENGINEER))
    exposure_study = validate_success(
        api.analyze_warrant_study(controlled["study"]["id"], ENGINEER))

    for study in (gap_study, exposure_study):
        assert study["included_child_count"] == 120
        assert study["included_adequate_gaps"] == 48
        assert study["included_vehicle_count"] == 880
        assert study["pedestrian_crash_count_3yr"] == len(CANONICAL_CRASHES)
        assert study["severe_pedestrian_crash_count_3yr"] == 1
        assert study["status"] == "ANALYZED"


def test_warrant_score_of_exactly_sixty_is_warranted(api):
    """Equality with the warrant threshold resolves upward, not downward.

    PRD: "A `warrant_score` of 60.00 or more yields `WARRANTED` — exactly 60.00
    qualifies."

    Design: Difficulty/boundary_precision_check/warrant_score_exactly_at_threshold_is_warranted
    """
    scenario = setup_study_ready_to_analyze(
        speed_limit_mph=25, crashes=[],
        sessions=[BOUNDARY_AM_SESSION, BOUNDARY_PM_SESSION])

    study = validate_success(api.analyze_warrant_study(scenario["study"]["id"], ENGINEER))

    assert study["scoring_variant"] == "GAP_ADEQUACY"
    assert study["included_child_count"] == 100
    assert study["included_adequate_gaps"] == 40
    assert study["included_vehicle_count"] == 3300
    assert study["pedestrian_crash_count_3yr"] == 0
    assert study["severe_pedestrian_crash_count_3yr"] == 0
    assert study["warrant_score"] == 60.00
    assert study["determination"] == "WARRANTED"
    assert study["determination"] != "CONDITIONAL"
    assert study["determination"] != "NOT_WARRANTED"
    assert study["status"] == "ANALYZED"


def test_warrant_score_one_point_below_the_threshold_is_not_warranted(api):
    """A crossing with no crash history and a score under 60.00 falls all the way
    through to the negative determination.

    PRD: "Anything else yields `NOT_WARRANTED`; so 59.99 with one pedestrian
    crash is `CONDITIONAL`, while 59.99 with no pedestrian crashes is
    `NOT_WARRANTED`."

    Design: Difficulty/boundary_precision_check/warrant_score_exactly_at_threshold_is_warranted
    """
    scenario = setup_study_ready_to_analyze(
        speed_limit_mph=25, crashes=[],
        sessions=[BOUNDARY_AM_SESSION, CONTROL_PM_SESSION])

    study = validate_success(api.analyze_warrant_study(scenario["study"]["id"], ENGINEER))

    assert study["included_vehicle_count"] == 3200
    assert study["warrant_score"] == 59.00
    assert study["determination"] == "NOT_WARRANTED"
    assert study["pedestrian_crash_count_3yr"] == 0


def test_count_window_starting_twenty_nine_days_after_a_finalized_window_is_refused(api):
    """The cool-off buffer extends a prior window forward by thirty days, and a
    finalized study still occupies the calendar.

    PRD: "A new study is refused with `ERR_COUNT_WINDOW_OVERLAP` (HTTP 409) when
    the intersection already carries a study"

    Design: Difficulty/resource_temporal_overlap/warrant_count_window_half_open_overlap_with_thirty_day_cooloff
    """
    scenario = setup_warranted_intersection()
    before = read_intersection(scenario["intersection"]["id"])
    assert before["warrant_status"] == "WARRANTED"
    assert read_study(scenario["study"]["id"])["status"] == "WARRANTED"

    response = api.create_warrant_study(
        create_warrant_study_payload(before["id"], before["version"],
                                     count_window_start="2026-10-29",
                                     count_window_end="2026-11-20"),
        ENGINEER)

    validate_error(response, ApiErrorId.ERR_COUNT_WINDOW_OVERLAP.value)
    after = read_intersection(before["id"])
    assert after["warrant_status"] == "WARRANTED"
    assert after["version"] == before["version"]


def test_count_window_starting_exactly_thirty_days_after_a_prior_window_is_accepted(api):
    """The leading edge of the buffered window is half-open, so day thirty is free.

    PRD: "Half-open comparison at the leading edge and the buffer at the trailing
    edge together mean that a new window starting exactly 30 days after a prior
    window's end is accepted, while one starting 29 days after is rejected."

    Design: Difficulty/resource_temporal_overlap/warrant_count_window_half_open_overlap_with_thirty_day_cooloff
    """
    scenario = setup_warranted_intersection()
    intersection = read_intersection(scenario["intersection"]["id"])

    response = api.create_warrant_study(
        create_warrant_study_payload(intersection["id"], intersection["version"],
                                     count_window_start="2026-10-30",
                                     count_window_end="2026-11-20"),
        ENGINEER)

    recount = validate_success(response, 201)
    assert_warrant_study(recount)
    assert recount["status"] == "DRAFT"
    assert recount["recount_round"] == 0
    assert recount["determination"] is None
    assert read_intersection(intersection["id"])["warrant_status"] == "UNDER_STUDY"
    assert read_study(scenario["study"]["id"])["status"] == "WARRANTED"
