"""Derived figures: which rows feed them, which constants apply, which variant wins.

Every number in this program is recomputed from a declared input set with a
declared rounding rule, and the interesting failures are input-set failures: a
MIDDAY session that should not be summed, a survey that should not be adopted, a
tie-break key consulted in the wrong order. These tests pin the input sets, the
speed-multiplier tier boundary, both mode-share variants and the substitute
ranking, and close with the consistency model that makes all of it visible in
the response that caused it.
"""
from test_helpers import validate_success
from test_helpers.assertions import (
    assert_clock_response,
    assert_guard,
    assert_same_instant,
    assert_school,
)
from test_helpers.factories import (
    create_crash_record_payload,
    create_mode_share_survey_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    CANONICAL_AM_SESSION,
    CANONICAL_PM_SESSION,
    ENGINEER,
    SUPERVISOR,
    advance_clock,
    append_survey,
    create_school,
    dispatch,
    file_absence,
    read_guard,
    read_school,
    setup_certified_guard,
    setup_staffed_post,
    setup_study_ready_to_analyze,
)
from test_helpers.test_users import make_school_liaison_headers

MIDDAY_SESSION = {
    "session_date": "2026-09-10",
    "period": "MIDDAY",
    "observed_minutes": 60,
    "child_count": 40,
    "adult_count": 6,
    "vehicle_count": 300,
    "adequate_gaps": 30,
}
FALL_SURVEY = {
    "term_code": "2026FA",
    "survey_date": "2026-10-01",
    "classrooms_reporting": 24,
    "enrollment_at_survey": 640,
    "walk_count": 120,
    "bike_count": 40,
    "bus_count": 150,
    "car_count": 160,
    "other_count": 30,
}
SPRING_SURVEY = {
    "term_code": "2027SP",
    "survey_date": "2027-02-02",
    "classrooms_reporting": 22,
    "enrollment_at_survey": 600,
    "walk_count": 100,
    "bike_count": 20,
    "bus_count": 150,
    "car_count": 200,
    "other_count": 30,
}
SUMMER_SURVEY = {
    "term_code": "2026SU",
    "survey_date": "2026-09-15",
    "classrooms_reporting": 20,
    "enrollment_at_survey": 500,
    "walk_count": 200,
    "bike_count": 100,
    "bus_count": 100,
    "car_count": 80,
    "other_count": 20,
}


def test_a_midday_session_is_stored_yet_touches_no_term_of_the_score(api):
    """The included set is the two commute periods only, so a third session that
    would flatter the gap ratio and inflate exposure changes nothing.

    PRD: "The **included set** consists of exactly those `count_sessions` entries
    whose `voided` is false and whose `period` is `AM_ARRIVAL` or `PM_DISMISSAL`;
    `MIDDAY` sessions are stored and returned but excluded from every term, and
    voided sessions are excluded whatever their period."

    Design: Corner/calculations/corner_midday_sessions_excluded_from_every_warrant_term
    """
    scenario = setup_study_ready_to_analyze(
        sessions=[CANONICAL_AM_SESSION, CANONICAL_PM_SESSION, MIDDAY_SESSION])

    study = validate_success(
        api.analyze_warrant_study(scenario["study"]["id"], ENGINEER))

    assert study["included_child_count"] == 120
    assert study["included_adequate_gaps"] == 48
    assert study["included_vehicle_count"] == 880
    assert study["pedestrian_crash_count_3yr"] == 2
    assert study["severe_pedestrian_crash_count_3yr"] == 1
    assert study["warrant_score"] == 66.19
    assert study["warrant_score"] != 71.23
    assert study["determination"] == "WARRANTED"
    assert study["scoring_variant"] == "GAP_ADEQUACY"
    assert len(study["count_sessions"]) == 3
    midday = [s for s in study["count_sessions"] if s["period"] == "MIDDAY"]
    assert len(midday) == 1
    assert midday[0]["voided"] is False


def test_twenty_nine_miles_per_hour_misses_the_middle_speed_tier(api):
    """The tier comparison is inclusive at 30, so one mile per hour below it the
    multiplier drops to 1.00 and the crossing crosses two decision boundaries.

    PRD: "A **speed multiplier** is 1.30 when the intersection's `speed_limit_mph`
    is 35 or more, 1.15 when it is 30 or more but below 35, and 1.00 otherwise."

    Design: Corner/calculations/corner_speed_multiplier_tier_excludes_twenty_nine_mph
    """
    scenario = setup_study_ready_to_analyze(speed_limit_mph=29)

    study = validate_success(
        api.analyze_warrant_study(scenario["study"]["id"], ENGINEER))

    assert study["included_child_count"] == 120
    assert study["included_adequate_gaps"] == 48
    assert study["included_vehicle_count"] == 880
    assert study["warrant_score"] == 57.56
    assert study["warrant_score"] != 66.19
    assert study["determination"] == "CONDITIONAL"
    assert study["determination"] != "NOT_WARRANTED"
    assert study["scoring_variant"] == "GAP_ADEQUACY"
    assert study["pedestrian_crash_count_3yr"] == 2


def test_one_survey_writes_both_shares_and_the_trend_in_the_same_body(api):
    """Two denominators, one tally: the seven-point gap between the raw and weighted
    shares is the non-response inflation, and it is visible immediately.

    PRD: "`walk_bike_mode_share_pct` is the raw-tally variant: 100 multiplied by the
    sum of `walk_count` and `bike_count`, divided by the sum of all five buckets,
    rounded half up to two decimal places." ... "`walk_bike_mode_share_weighted_pct`
    is the enrollment-weighted variant: 100 multiplied by the same walk-plus-bike
    numerator, but divided by `enrollment_at_survey`, again rounded half up to two
    decimal places."

    Design: Corner/calculations/corner_mode_share_survey_computes_both_variants_and_trend
    """
    school = create_school()
    assert school["baseline_walk_bike_mode_share_pct"] == 18.50
    assert school["mode_share_surveys"] == []
    assert school["walk_bike_mode_share_pct"] is None

    updated = validate_success(api.create_mode_share_survey(
        school["id"], create_mode_share_survey_payload(**FALL_SURVEY),
        make_school_liaison_headers(school["id"])))

    assert_school(updated)
    assert updated["walk_bike_mode_share_pct"] == 32.00
    assert updated["walk_bike_mode_share_weighted_pct"] == 25.00
    assert round(updated["walk_bike_mode_share_pct"]
                 - updated["walk_bike_mode_share_weighted_pct"], 2) == 7.00
    assert updated["mode_share_trend_pct"] == 13.50
    assert updated["latest_survey_term_code"] == "2026FA"
    assert len(updated["mode_share_surveys"]) == 1
    assert_same_instant(updated["mode_share_surveys"][0]["recorded_at"],
                        "2026-08-01T00:00:00Z", "ModeShareSurvey.recorded_at")
    assert updated["version"] == school["version"] + 1
    assert read_school(school["id"]) == updated


def test_the_trend_follows_the_raw_tally_of_the_latest_survey_only(api):
    """Two selections at once: the trend is built from the raw variant, and the
    latest survey is chosen by date rather than by order of arrival.

    PRD: "`mode_share_trend_pct` is the raw-tally share less the school's
    `baseline_walk_bike_mode_share_pct`, rounded half up to two decimal places — and
    it is built from the raw-tally variant only, deliberately **not** from the
    weighted one, because the raw tally is comparable across terms with differing
    participation." ... "The latest survey is selected by `survey_date` descending,
    then by `recorded_at` descending as the tie-break"

    Design: Corner/calculations/corner_trend_reads_raw_tally_and_latest_survey_only
    """
    school = create_school()
    append_survey(school["id"], **FALL_SURVEY)
    append_survey(school["id"], **SPRING_SURVEY)

    before = read_school(school["id"])
    assert before["walk_bike_mode_share_pct"] == 24.00
    assert before["walk_bike_mode_share_weighted_pct"] == 20.00
    assert before["mode_share_trend_pct"] == 5.50
    assert before["mode_share_trend_pct"] != 1.50
    assert before["latest_survey_term_code"] == "2027SP"

    after = validate_success(api.create_mode_share_survey(
        school["id"], create_mode_share_survey_payload(**SUMMER_SURVEY),
        make_school_liaison_headers(school["id"])))

    assert len(after["mode_share_surveys"]) == 3
    assert after["walk_bike_mode_share_pct"] == 24.00
    assert after["walk_bike_mode_share_weighted_pct"] == 20.00
    assert after["mode_share_trend_pct"] == 5.50
    assert after["latest_survey_term_code"] == "2027SP"
    assert after["walk_bike_mode_share_pct"] != 60.00
    terms = [survey["term_code"] for survey in after["mode_share_surveys"]]
    assert terms == ["2026FA", "2027SP", "2026SU"]


def test_a_zone_match_outranks_an_earlier_created_candidate(api):
    """Both substitutes sit at 100.00, so the reliability key ties and the zone
    preference decides before `created_at` is ever consulted.

    PRD: "The eligible pool is then ranked by three keys applied in order:
    `reliability_score_season_to_date` descending, compared at its stored two-decimal
    precision without re-rounding; then a zone-match preference descending, where a
    guard whose `home_zone_code` equals the post's `zone_code` sorts ahead of one
    whose does not; then the guard's `created_at` ascending as the terminal
    tie-break."

    Design: Corner/calculations/corner_substitute_selector_zone_match_outranks_created_at
    """
    scenario = setup_staffed_post(substitute_pool_optin=False)
    nia = setup_certified_guard(full_name="Nia Brandt", home_zone_code="Z-SOUTH",
                                substitute_pool_optin=True)
    advance_clock("2026-08-02T00:00:00Z")
    sam = setup_certified_guard(full_name="Sam Okafor", home_zone_code="Z-NORTH",
                                substitute_pool_optin=True)
    assert nia["created_at"] < sam["created_at"]
    assert scenario["post"]["zone_code"] == "Z-NORTH"
    advance_clock("2026-09-16T01:00:00Z")
    absence = file_absence(scenario["assignment"]["id"])

    report = dispatch(absence["id"])

    assert report["status"] == "OFFER_OUT"
    assert report["current_offer_guard_id"] == sam["id"]
    assert report["current_offer_guard_id"] != nia["id"]
    assert report["current_offer_guard_id"] != scenario["guard"]["id"]
    assert report["dispatch_attempt_count"] == 1
    assert len(report["dispatch_offers"]) == 1
    assert report["dispatch_offers"][0]["offer_status"] == "OPEN"
    assert_same_instant(report["current_offer_expires_at"], "2026-09-16T01:45:00Z",
                        "AbsenceReport.current_offer_expires_at")
    assert read_guard(nia["id"])["reliability_score_season_to_date"] == 100.00
    assert read_guard(sam["id"])["reliability_score_season_to_date"] == 100.00


def test_every_derived_figure_is_current_in_the_response_that_moved_it(api):
    """The crash append answers with the recomputed aggregates already in its own
    body, and the clock advance ages one reliability variant out while the other,
    which never consults the clock, holds still.

    PRD: "Appending refreshes two rolling aggregates on the intersection over a
    **1095-day window — three years — ending at the logical clock's date, with both
    ends inclusive**." ... "`reliability_score_rolling_90d` counts absences whose
    `created_at` falls in the closed 90-day window ending at the current logical
    clock — anchored on when the report was filed, not on the day being missed, so a
    report filed for a future school day counts immediately and ages out 90 days
    after filing."

    Design: Corner/consistency_model/corner_derived_fields_are_visible_in_the_same_response
    """
    scenario = setup_staffed_post()
    file_absence(scenario["assignment"]["id"], absence_date="2026-09-16",
                 reason="UNEXCUSED", note="No call, no show.")

    filed = validate_success(api.get_guard(scenario["guard"]["id"], SUPERVISOR))
    assert_guard(filed)
    assert filed["reliability_score_rolling_90d"] == 93.00
    assert filed["reliability_score_season_to_date"] == 93.00

    appended = validate_success(api.create_crash_record(
        scenario["intersection"]["id"],
        create_crash_record_payload(crash_date="2026-05-02", severity="FATAL"),
        ENGINEER))
    assert appended["crash_severity_points"] == 48
    assert appended["pedestrian_crash_count_window"] == 3
    assert len(appended["crash_history"]) == 3

    swept = validate_success(
        api.set_clock("2026-10-31T00:00:00Z", ADMIN))
    assert_clock_response(swept, "2026-10-31T00:00:00Z", activated=1, ended=1)

    aged = validate_success(api.get_guard(scenario["guard"]["id"], SUPERVISOR))
    assert aged["reliability_score_rolling_90d"] == 100.00
    assert aged["reliability_score_season_to_date"] == 93.00
    assert aged["certification_status"] == "CERTIFIED"
    assert aged["suspension_reason"] is None
    assert read_guard(scenario["guard"]["id"])["reliability_score_rolling_90d"] == 100.00
