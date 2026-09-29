"""Values sitting exactly on a threshold, and the nearest value that is not.

The apprenticeship comparison is inclusive, so a payroll landing on precisely
fifteen percent qualifies while fourteen and nine tenths does not, on the same
hundred hours. The weather filters are inclusive too, so 600 watts per square
metre and 8.0 metres per second admit a sample that 599 and 8.1 reject.
"""

from test_helpers import validate_error
from test_helpers.api_errors import ERR_NO_VALID_TEST_INTERVALS
from test_helpers.assertions import (
    assert_commissioning_result,
    assert_compliance_run,
    assert_week_totals,
)
from test_helpers.fixtures import (
    append_interval,
    create_payroll_week,
    create_project,
    energize_substation,
    finalize_test,
    post_labor_entry,
    read_commissioning_test,
    read_labor_entry,
    read_payroll_week,
    read_project,
    run_labor_compliance,
    schedule_commissioning_test,
    set_clock,
    void_labor_entry,
)
from test_helpers.test_users import COMMISSIONING_ENGINEER

AT_SCALE = {"paid_rate_cents": 4500, "fringe_rate_cents": 500, "prevailing_rate_cents": 5000}


def _week_at_the_threshold(api):
    """Fifteen apprentice hours against eighty-five journeyworker hours."""
    project = create_project(
        api,
        name="Cinder Cone",
        prevailing_wage_election="REMEDIABLE",
        apprenticeship_basis="PROJECT_AGGREGATE",
        apprenticeship_min_pct=15.00,
    )
    week = create_payroll_week(api, project["id"], week_start_date="2026-08-03")
    apprentice = post_labor_entry(
        api,
        week["id"],
        worker_ref="W-401",
        classification="ELECTRICIAN",
        is_apprentice=True,
        hours=15.00,
        work_date="2026-08-03",
        **AT_SCALE,
    )
    post_labor_entry(
        api,
        week["id"],
        worker_ref="W-402",
        classification="ELECTRICIAN",
        is_apprentice=False,
        hours=85.00,
        work_date="2026-08-04",
        **AT_SCALE,
    )
    return project, week, apprentice


def _reclassify_a_tenth_of_an_hour(api, week_id, apprentice_id):
    """Void the apprentice line and repost it a tenth of an hour lighter."""
    void_labor_entry(api, apprentice_id, void_reason="reclassified to journeyworker overtime")
    post_labor_entry(
        api,
        week_id,
        worker_ref="W-401",
        classification="ELECTRICIAN",
        is_apprentice=True,
        hours=14.90,
        work_date="2026-08-03",
        **AT_SCALE,
    )
    post_labor_entry(
        api,
        week_id,
        worker_ref="W-403",
        classification="LABORER",
        is_apprentice=False,
        hours=0.10,
        work_date="2026-08-05",
        **AT_SCALE,
    )


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/apprentice_percentage_qualifies_exactly_at_fifteen_percent
# ---------------------------------------------------------------------------
def test_a_payroll_landing_exactly_on_the_minimum_qualifies(api):
    """Fifteen percent of a hundred hours meets a fifteen percent floor.

    PRD 3.8: "Apprenticeship qualification is then a single comparison: the run's
    `apprentice_hours_pct` must be **at least** the project's
    `apprenticeship_min_pct`, so a project landing exactly on its threshold
    qualifies."

    Design: Difficulty/boundary_precision_check/apprentice_percentage_qualifies_exactly_at_fifteen_percent
    """
    project, _week, _apprentice = _week_at_the_threshold(api)

    run = run_labor_compliance(api, project["id"])

    assert_compliance_run(
        run,
        apprentice_hours_pct=15.00,
        wage_restitution_owed_cents=0,
        tax_credit_status="QUALIFIED",
    )


def test_a_tenth_of_an_hour_below_the_minimum_disqualifies(api):
    """The same hundred hours split 14.90 to 85.10 falls under the floor.

    PRD 3.8: "It is `QUALIFIED` when apprenticeship qualification holds *and*
    `wage_restitution_owed_cents` is exactly 0; in every other case it is
    `DISQUALIFIED`."

    Design: Difficulty/boundary_precision_check/apprentice_percentage_qualifies_exactly_at_fifteen_percent
    """
    project, week, apprentice = _week_at_the_threshold(api)
    run_labor_compliance(api, project["id"])

    _reclassify_a_tenth_of_an_hour(api, week["id"], apprentice["id"])
    below = run_labor_compliance(api, project["id"])

    assert_compliance_run(
        below,
        apprentice_hours_pct=14.90,
        wage_restitution_owed_cents=0,
        tax_credit_status="DISQUALIFIED",
    )


def test_the_week_holds_a_hundred_hours_on_both_sides_of_the_threshold(api):
    """Only the apprentice share moves; the total is a hundred hours throughout.

    PRD 3.8: "The hour ledger is a conserved quantity: at every instant
    `apprentice_hours` plus `journeyworker_hours` equals `total_hours`."

    Design: Difficulty/boundary_precision_check/apprentice_percentage_qualifies_exactly_at_fifteen_percent
    """
    _project, week, apprentice = _week_at_the_threshold(api)

    at_threshold = read_payroll_week(api, week["id"])
    assert_week_totals(
        at_threshold,
        total_hours=100.00,
        journeyworker_hours=85.00,
        apprentice_hours=15.00,
        apprentice_pct=15.00,
    )

    _reclassify_a_tenth_of_an_hour(api, week["id"], apprentice["id"])

    below = read_payroll_week(api, week["id"])
    assert_week_totals(
        below,
        total_hours=100.00,
        journeyworker_hours=85.10,
        apprentice_hours=14.90,
        apprentice_pct=14.90,
    )


def test_the_voided_line_leaves_the_ledger_and_carries_no_restitution(api):
    """A voided line contributes nothing to any later computation.

    PRD 3.8: "Voided lines leave the ledger entirely and contribute nothing to any
    later computation."

    Design: Difficulty/boundary_precision_check/apprentice_percentage_qualifies_exactly_at_fifteen_percent
    """
    project, week, apprentice = _week_at_the_threshold(api)

    _reclassify_a_tenth_of_an_hour(api, week["id"], apprentice["id"])
    run_labor_compliance(api, project["id"])

    voided = read_labor_entry(api, apprentice["id"])
    assert voided["status"] == "VOIDED"
    assert voided["restitution_cents"] == 0
    assert read_project(api, project["id"])["wage_restitution_owed_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/capacity_finalization_at_weather_filter_endpoints
# ---------------------------------------------------------------------------
def _test_with_two_rejected_samples(api):
    """An energized plant whose only two samples each miss one filter by a hair."""
    set_clock(api, "2026-08-01T00:00:00Z")
    project = create_project(api, name="Thistle Draw")
    energize_substation(api, project["id"])
    test = schedule_commissioning_test(
        api,
        project["id"],
        test_type="CAPACITY",
        correction_variant="AS_MEASURED",
        scheduled_at="2026-08-10T02:30:00Z",
    )
    dim = append_interval(api, test["id"], "2026-08-10T02:35:00Z", 599, 58.70, ambient_c=30, wind_m_s=3.0)
    windy = append_interval(api, test["id"], "2026-08-10T02:40:00Z", 700, 65.00, ambient_c=30, wind_m_s=8.1)
    return project, test, dim, windy


def test_a_sample_one_unit_outside_either_filter_is_invalid(api):
    """599 W/m2 and 8.1 m/s each fail one of the three weather filters.

    PRD 3.7: "Validity is decided at append time by three weather filters that
    must all hold: `irradiance_w_m2` must be at least 600 watts per square metre,
    `wind_m_s` must be at most 8.0 metres per second, and `ambient_c` must lie
    between -10 and 45 degrees Celsius inclusive on both ends."

    Design: Difficulty/boundary_precision_check/capacity_finalization_at_weather_filter_endpoints
    """
    _project, _test, dim, windy = _test_with_two_rejected_samples(api)

    assert dim["is_valid"] is False
    assert windy["is_valid"] is False


def test_finalization_is_refused_while_every_sample_is_invalid(api):
    """With no weather-valid interval the test cannot close and stays IN_PROGRESS.

    PRD 3.7: "And at least one interval of the test must have cleared all three
    weather filters, or the request is refused with
    `ERR_NO_VALID_TEST_INTERVALS`."

    Design: Difficulty/boundary_precision_check/capacity_finalization_at_weather_filter_endpoints
    """
    _project, test, _dim, _windy = _test_with_two_rejected_samples(api)

    response = api.finalize_commissioning_test(test["id"], {}, COMMISSIONING_ENGINEER)

    validate_error(response, ERR_NO_VALID_TEST_INTERVALS, expected_status=422)
    still_open = read_commissioning_test(api, test["id"])
    assert still_open["status"] == "IN_PROGRESS"
    assert still_open["finalized_at"] is None
    assert still_open["reported_kw_ac"] is None


def test_a_sample_sitting_on_all_three_inclusive_endpoints_is_valid(api):
    """600 W/m2, 8.0 m/s and 45 C are all admitted at their endpoints.

    PRD 3.7: "Validity is decided at append time by three weather filters that
    must all hold: `irradiance_w_m2` must be at least 600 watts per square metre,
    `wind_m_s` must be at most 8.0 metres per second, and `ambient_c` must lie
    between -10 and 45 degrees Celsius inclusive on both ends."

    Design: Difficulty/boundary_precision_check/capacity_finalization_at_weather_filter_endpoints
    """
    _project, test, _dim, _windy = _test_with_two_rejected_samples(api)

    endpoint = append_interval(
        api, test["id"], "2026-08-10T02:45:00Z", 600, 58.80, ambient_c=45, wind_m_s=8.0
    )

    assert endpoint["is_valid"] is True


def test_the_result_averages_only_the_single_admitted_sample(api):
    """Two invalid samples neither drag the mean down nor dilute it.

    PRD 3.7: "For a `CAPACITY` test the calculation runs over exactly the
    intervals whose three weather filters passed, taken in `created_at` ascending
    order; invalid samples are excluded from both the numerator and the
    denominator, so they neither drag the average down nor dilute it."

    Design: Difficulty/boundary_precision_check/capacity_finalization_at_weather_filter_endpoints
    """
    _project, test, _dim, _windy = _test_with_two_rejected_samples(api)
    api.finalize_commissioning_test(test["id"], {}, COMMISSIONING_ENGINEER)
    append_interval(api, test["id"], "2026-08-10T02:45:00Z", 600, 58.80, ambient_c=45, wind_m_s=8.0)

    result = finalize_test(api, test["id"])

    assert_commissioning_result(
        result,
        status="FAILED",
        interval_count=3,
        valid_interval_count=1,
        reported_kw_ac=58.80,
        pass_threshold_kw_ac=98.00,
    )
