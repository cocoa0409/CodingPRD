"""The two places this API computes the same quantity two different ways.

A capacity demonstration reports either the raw metered mean or the mean of the
per-interval weather-corrected figures, and an apprenticeship assessment either
pools every hour on the job or judges each payroll week on its own. Both
selectors are stored on the project or the test rather than passed at read time,
and both can flip a contractual outcome on identical underlying measurements.
"""

from test_helpers import validate_success
from test_helpers.assertions import (
    assert_commissioning_result,
    assert_compliance_run,
    assert_ratio,
)
from test_helpers.fixtures import (
    append_interval,
    create_payroll_week,
    create_project,
    energize_substation,
    finalize_test,
    post_labor_entry,
    read_commissioning_test,
    read_payroll_week,
    read_project,
    run_labor_compliance,
    schedule_commissioning_test,
    set_clock,
)
from test_helpers.test_users import LABOR_COMPLIANCE_OFFICER

# The three metered samples both capacity variants are computed from. The third
# sample is below the 600 W/m2 irradiance floor, so it is weather-invalid and
# takes no part in either result.
SAMPLE_ONE = {"sampled_at": "2026-08-10T03:00:00Z", "irradiance_w_m2": 850, "measured_kw_ac": 76.50, "ambient_c": 30, "wind_m_s": 3.0}
SAMPLE_TWO = {"sampled_at": "2026-08-10T03:15:00Z", "irradiance_w_m2": 900, "measured_kw_ac": 81.00, "ambient_c": 32, "wind_m_s": 4.0}
SAMPLE_INVALID = {"sampled_at": "2026-08-10T03:30:00Z", "irradiance_w_m2": 500, "measured_kw_ac": 40.00, "ambient_c": 20, "wind_m_s": 2.0}


def _metered_project(api):
    """A project whose substation is energized, so a test may be finalized."""
    set_clock(api, "2026-08-01T00:00:00Z")
    project = create_project(api, name="Solstice Ridge", guaranteed_capacity_kw_ac=100, dc_capacity_kw=130)
    energize_substation(api, project["id"])
    return project


def _run(api, project_id, variant, scheduled_at):
    """Schedule a capacity test under one variant, meter it and finalize it."""
    test = schedule_commissioning_test(
        api,
        project_id,
        test_type="CAPACITY",
        correction_variant=variant,
        scheduled_at=scheduled_at,
    )
    for sample in (SAMPLE_ONE, SAMPLE_TWO, SAMPLE_INVALID):
        append_interval(
            api,
            test["id"],
            sample["sampled_at"],
            sample["irradiance_w_m2"],
            sample["measured_kw_ac"],
            ambient_c=sample["ambient_c"],
            wind_m_s=sample["wind_m_s"],
        )
    return finalize_test(api, test["id"], note=f"{variant.lower()} run")


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/capacity_test_as_measured_fails_where_weather_corrected_passes
# ---------------------------------------------------------------------------
def test_as_measured_capacity_is_the_raw_metered_mean_and_falls_short(api):
    """AS_MEASURED averages the raw metered power and lands short of guarantee.

    PRD 3.7: "Under `AS_MEASURED` an interval's sample value is its raw
    `measured_kw_ac`, with no correction applied at all; the interval's
    `corrected_kw_ac` is still stored for reference but plays no part in the
    result."

    Design: Difficulty/dual_variant_calc/capacity_test_as_measured_fails_where_weather_corrected_passes
    """
    project = _metered_project(api)

    result = _run(api, project["id"], "AS_MEASURED", "2026-08-10T03:00:00Z")

    # (76.50 + 81.00) / 2 == 78.75, against 100 x 0.98 == 98.00.
    assert_commissioning_result(
        result,
        status="FAILED",
        interval_count=3,
        valid_interval_count=2,
        reported_kw_ac=78.75,
        pass_threshold_kw_ac=98.00,
    )
    assert result["reported_performance_ratio"] is None


def test_weather_corrected_capacity_passes_on_the_identical_samples(api):
    """The same three samples pass once each is corrected before averaging.

    PRD 3.7: "The same set of intervals can therefore yield a materially
    different `reported_kw_ac` under the two variants, and can flip the
    outcome."

    Design: Difficulty/dual_variant_calc/capacity_test_as_measured_fails_where_weather_corrected_passes
    """
    project = _metered_project(api)

    as_measured = _run(api, project["id"], "AS_MEASURED", "2026-08-10T03:00:00Z")
    corrected = _run(api, project["id"], "WEATHER_CORRECTED", "2026-08-10T03:45:00Z")

    # 99.11 and 100.36 are the two per-interval corrected figures; their mean
    # 99.735 rounds half up to 99.74, which clears the 98.00 threshold.
    assert_commissioning_result(
        corrected,
        status="PASSED",
        interval_count=3,
        valid_interval_count=2,
        reported_kw_ac=99.74,
        pass_threshold_kw_ac=98.00,
    )
    assert_ratio(
        corrected["reported_kw_ac"] - as_measured["reported_kw_ac"],
        20.99,
        "variant divergence",
    )


def test_per_interval_correction_is_stored_and_null_on_invalid_samples(api):
    """Each valid interval carries its own rounded corrected figure; invalid ones carry none.

    PRD 3.7: "Also computed at append time is `corrected_kw_ac`, the interval's
    weather-corrected power, which is null whenever `is_valid` is false."

    Design: Difficulty/dual_variant_calc/capacity_test_as_measured_fails_where_weather_corrected_passes
    """
    project = _metered_project(api)
    test = schedule_commissioning_test(
        api,
        project["id"],
        test_type="CAPACITY",
        correction_variant="WEATHER_CORRECTED",
        scheduled_at="2026-08-10T03:00:00Z",
    )

    first = append_interval(api, test["id"], SAMPLE_ONE["sampled_at"], 850, 76.50, ambient_c=30, wind_m_s=3.0)
    second = append_interval(api, test["id"], SAMPLE_TWO["sampled_at"], 900, 81.00, ambient_c=32, wind_m_s=4.0)
    third = append_interval(api, test["id"], SAMPLE_INVALID["sampled_at"], 500, 40.00, ambient_c=20, wind_m_s=2.0)

    assert first["is_valid"] is True
    assert_ratio(first["corrected_kw_ac"], 99.11, "corrected_kw_ac at 850 W/m2")
    assert second["is_valid"] is True
    assert_ratio(second["corrected_kw_ac"], 100.36, "corrected_kw_ac at 900 W/m2")
    assert third["is_valid"] is False
    assert third["corrected_kw_ac"] is None


def test_the_superseded_as_measured_test_is_voided_by_the_second_schedule(api):
    """A failed run of the same kind is voided when the next one is scheduled.

    PRD 3.7: "When a new test is created, every earlier test of the *same*
    `test_type` on the *same* project whose `status` is `SCHEDULED`,
    `IN_PROGRESS`, `FAILED` or `SUSPENDED` is driven to `VOID`, with
    `void_reason` set to `SUPERSEDED_BY_NEW_TEST`, `superseded` set to true and
    each voided test's `version` incremented by 1."

    Design: Difficulty/dual_variant_calc/capacity_test_as_measured_fails_where_weather_corrected_passes
    """
    project = _metered_project(api)

    as_measured = _run(api, project["id"], "AS_MEASURED", "2026-08-10T03:00:00Z")
    assert as_measured["status"] == "FAILED"

    _run(api, project["id"], "WEATHER_CORRECTED", "2026-08-10T03:45:00Z")

    voided = read_commissioning_test(api, as_measured["id"])
    assert voided["status"] == "VOID"
    assert voided["void_reason"] == "SUPERSEDED_BY_NEW_TEST"
    assert voided["superseded"] is True
    assert voided["version"] > as_measured["version"]


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/apprenticeship_project_aggregate_qualifies_where_weekly_worst_case_fails
# ---------------------------------------------------------------------------
def _two_week_payroll(api):
    """Two weeks whose apprentice shares are 30.00 and 5.00 percent."""
    project = create_project(
        api,
        name="Mesa Flats",
        prevailing_wage_election="REMEDIABLE",
        apprenticeship_basis="PROJECT_AGGREGATE",
        apprenticeship_min_pct=15.00,
    )
    strong = create_payroll_week(api, project["id"], week_start_date="2026-07-27")
    post_labor_entry(
        api,
        strong["id"],
        worker_ref="W-101",
        classification="ELECTRICIAN",
        is_apprentice=True,
        hours=30.00,
        paid_rate_cents=4200,
        fringe_rate_cents=800,
        prevailing_rate_cents=5000,
        work_date="2026-07-28",
    )
    post_labor_entry(
        api,
        strong["id"],
        worker_ref="W-102",
        classification="ELECTRICIAN",
        is_apprentice=False,
        hours=70.00,
        paid_rate_cents=4200,
        fringe_rate_cents=800,
        prevailing_rate_cents=5000,
        work_date="2026-07-29",
    )
    weak = create_payroll_week(api, project["id"], week_start_date="2026-08-03")
    post_labor_entry(
        api,
        weak["id"],
        worker_ref="W-103",
        classification="LABORER",
        is_apprentice=True,
        hours=5.00,
        paid_rate_cents=3500,
        fringe_rate_cents=700,
        prevailing_rate_cents=4200,
        work_date="2026-08-04",
    )
    post_labor_entry(
        api,
        weak["id"],
        worker_ref="W-104",
        classification="LABORER",
        is_apprentice=False,
        hours=95.00,
        paid_rate_cents=3500,
        fringe_rate_cents=700,
        prevailing_rate_cents=4200,
        work_date="2026-08-05",
    )
    return project, strong, weak


def test_project_aggregate_pools_hours_so_a_strong_week_carries_a_weak_one(api):
    """Pooled across the job the apprentice share is 17.50 percent and qualifies.

    PRD 3.8: "Under `PROJECT_AGGREGATE`, the weeks of the project are taken in
    `week_start_date` ascending order and treated as one pool:
    `apprentice_hours_pct` is the sum of `hours` over all posted apprentice
    lines, divided by the sum of `hours` over all posted lines, multiplied by
    100 and rounded half up to two decimal places — a single ratio across the
    whole job, in which a strong week can carry a weak one."

    Design: Difficulty/dual_variant_calc/apprenticeship_project_aggregate_qualifies_where_weekly_worst_case_fails
    """
    project, _strong, _weak = _two_week_payroll(api)

    run = run_labor_compliance(api, project["id"], basis_override="PROJECT_AGGREGATE")

    # 35.00 apprentice hours of 200.00 total == 17.50 percent, above 15.00.
    assert_compliance_run(
        run,
        apprentice_hours_pct=17.50,
        apprenticeship_basis_applied="PROJECT_AGGREGATE",
        wage_restitution_owed_cents=0,
        tax_credit_status="QUALIFIED",
    )


def test_weekly_worst_case_takes_the_minimum_and_disqualifies(api):
    """Judged week by week the worst share is 5.00 percent and disqualifies.

    PRD 3.8: "Under `WEEKLY_WORST_CASE`, each week is measured on its own: the
    week's `apprentice_hours` divided by its `total_hours`, multiplied by 100
    and rounded half up to two decimal places, and `apprentice_hours_pct` is
    the **smallest** of those per-week figures across the weeks whose
    `total_hours` is greater than zero."

    Design: Difficulty/dual_variant_calc/apprenticeship_project_aggregate_qualifies_where_weekly_worst_case_fails
    """
    project, strong, weak = _two_week_payroll(api)

    run_labor_compliance(api, project["id"], basis_override="PROJECT_AGGREGATE")
    weekly = run_labor_compliance(api, project["id"], basis_override="WEEKLY_WORST_CASE")

    assert_compliance_run(
        weekly,
        apprentice_hours_pct=5.00,
        apprenticeship_basis_applied="WEEKLY_WORST_CASE",
        wage_restitution_owed_cents=0,
        tax_credit_status="DISQUALIFIED",
    )
    assert_ratio(read_payroll_week(api, strong["id"])["apprentice_pct"], 30.00, "strong week apprentice_pct")
    assert_ratio(read_payroll_week(api, weak["id"])["apprentice_pct"], 5.00, "weak week apprentice_pct")


def test_a_basis_override_changes_the_run_but_not_the_project_selector(api):
    """The override is recorded per run while the project keeps its own basis.

    PRD 3.8: "Supplying `basis_override` changes only that one run — the
    project's own `apprenticeship_basis` is left exactly as it was."

    Design: Difficulty/dual_variant_calc/apprenticeship_project_aggregate_qualifies_where_weekly_worst_case_fails
    """
    project, _strong, _weak = _two_week_payroll(api)

    run_labor_compliance(api, project["id"], basis_override="PROJECT_AGGREGATE")
    run_labor_compliance(api, project["id"], basis_override="WEEKLY_WORST_CASE")

    after = read_project(api, project["id"])
    assert after["apprenticeship_basis_applied"] == "WEEKLY_WORST_CASE"
    assert after["apprenticeship_basis"] == "PROJECT_AGGREGATE"
    assert_ratio(after["total_labor_hours"], 200.00, "total_labor_hours")
    assert_ratio(after["apprentice_labor_hours"], 35.00, "apprentice_labor_hours")


def test_the_default_basis_is_used_when_no_override_is_supplied(api):
    """Without an override the project's stored basis is the one applied.

    PRD 3.8: "The applied basis is the `basis_override` when one is supplied
    and the project's stored `apprenticeship_basis` otherwise, and whichever it
    is, the run records it in `apprenticeship_basis_applied`."

    Design: Difficulty/dual_variant_calc/apprenticeship_project_aggregate_qualifies_where_weekly_worst_case_fails
    """
    project, _strong, _weak = _two_week_payroll(api)

    response = api.create_labor_compliance_run(project["id"], {}, LABOR_COMPLIANCE_OFFICER)
    run = validate_success(response, expected_status=200)

    assert_compliance_run(
        run,
        apprentice_hours_pct=17.50,
        apprenticeship_basis_applied="PROJECT_AGGREGATE",
        tax_credit_status="QUALIFIED",
    )
