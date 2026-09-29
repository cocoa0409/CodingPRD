"""Measurement cycles and the identification of full-time months.

The look-back average projected over a stability period against the monthly
actual test on identical hours, the empty look-back denominator that follows
from special unpaid leave, and the closed-interval adjacency rule that keeps two
stability periods from touching.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_employee,
    assert_hours_record,
    assert_measurement_cycle,
    factories,
    fixtures,
    get_success_data,
    make_benefits_admin_headers,
    make_compliance_officer_headers,
    validate_error,
    validate_success,
)

CO = make_compliance_officer_headers()
BA = make_benefits_admin_headers()

# The cycle every look-back recipe below shares: the prior calendar year is
# measured, the administrative period closes with it and the whole reporting
# year is the stability period the verdict is projected onto.
CYCLE_DATES = {
    "measurement_start_date": "2025-01-01",
    "measurement_end_date": "2025-12-31",
    "admin_period_end_date": "2025-12-31",
    "stability_start_date": "2026-01-01",
    "stability_end_date": "2026-12-31",
    "hours_threshold_monthly": 130,
}


# ---------------------------------------------------------------------------
# Local composition over test_helpers.fixtures
# ---------------------------------------------------------------------------
def _look_back_member_with_standard_cycle(api):
    """A season, a determined controlled group, one member defaulting to
    look-back measurement and the member's standard measurement cycle."""
    ctx = fixtures.determined_ale_group(api, member_measurement_method="LOOK_BACK")
    ctx["cycle"] = fixtures.create_measurement_cycle(
        api, ctx["member"]["id"], cycle_type="STANDARD", **CYCLE_DATES
    )
    return ctx


def _employees_with_identical_hours(api, ctx):
    """Two employees of the same member with byte-identical hours rows: one
    inheriting the member's look-back method, one overriding it to monthly."""
    employee_look_back = fixtures.create_employee(
        api,
        ctx["member"]["id"],
        full_name="Lena Ortiz",
        ssn_last4="4321",
        hire_date="2025-01-01",
        employment_type="VARIABLE_HOUR",
        is_hourly=True,
        hourly_rate_cents=1500,
        w2_box1_wages_cents=2400000,
    )
    employee_monthly = fixtures.create_employee(
        api,
        ctx["member"]["id"],
        full_name="Marco Diaz",
        ssn_last4="8765",
        hire_date="2025-01-01",
        employment_type="VARIABLE_HOUR",
        is_hourly=True,
        hourly_rate_cents=1500,
        w2_box1_wages_cents=2400000,
        measurement_method_override="MONTHLY",
    )
    for employee in (employee_look_back, employee_monthly):
        fixtures.record_hours(api, employee["id"], 2025, [1, 2, 3, 4, 5, 6], hours_of_service=160)
        fixtures.record_hours(
            api, employee["id"], 2025, [7, 8, 9, 10, 11, 12], hours_of_service=100
        )
        fixtures.record_hours(
            api, employee["id"], 2026, list(range(1, 13)), hours_of_service=100
        )
    return employee_look_back, employee_monthly


def _recompute(api, employee_id):
    return validate_success(api.recompute_employee_full_time(employee_id, BA), 200)


def _hours_rows(api, employee_id, measurement_year):
    """Hours rows are reachable only through the filtered list read."""
    return get_success_data(
        api.list_hours_records(
            BA,
            params={
                "employee_id": employee_id,
                "measurement_year": measurement_year,
                "limit": 100,
            },
        )
    )


def _cycles_of_member(api, member_id):
    return get_success_data(
        api.list_measurement_cycles(CO, params={"group_member_id": member_id, "limit": 100})
    )


# ---------------------------------------------------------------------------
# Look-back stability against monthly actual on identical hours
# ---------------------------------------------------------------------------
def test_look_back_average_projects_full_time_over_the_whole_stability_period(api):
    """PRD §3.5: "Otherwise `measured_average_hours` is the sum of
    `counted_hours` across the surviving rows divided by the number of surviving
    rows, rounded half up to two decimal places, and the single stability verdict
    is that this average is at least the cycle's `hours_threshold_monthly`."
    PRD §3.5: "Then, for each of the twelve months of the tax year: a month whose
    first day falls within the cycle's stability start and end dates inclusive
    takes that single verdict with `ft_source` of `LOOK_BACK_STABILITY`; any
    other month falls back to the monthly test against 130 counted hours with
    `ft_source` of `MONTHLY_ACTUAL`."
    PRD §3.5: "`full_time_months` is the ascending list of the months that
    survive as full time, `full_time_month_count` is its length, and
    `ft_source_by_month` is the twelve source labels in calendar order starting
    with January, each one of `LOOK_BACK_STABILITY`, `MONTHLY_ACTUAL`, `LNAP` or
    `NOT_EMPLOYED`."

    Design: Difficulty/dual_variant_calc/look_back_stability_vs_monthly_actual_ft_months
    """
    ctx = _look_back_member_with_standard_cycle(api)
    employee_look_back, employee_monthly = _employees_with_identical_hours(api, ctx)

    _recompute(api, employee_look_back["id"])
    _recompute(api, employee_monthly["id"])

    reread = fixtures.read_employee(api, employee_look_back["id"])
    assert_employee(
        reread,
        effective_measurement_method="LOOK_BACK",
        full_time_month_count=12,
        full_time_months=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        ft_source_by_month=["LOOK_BACK_STABILITY"] * 12,
    )
    assert reread["measured_average_hours"] == pytest.approx(130.00, abs=0.01), (
        f"six months of 160 and six of 100 average 130.00, got "
        f"{reread['measured_average_hours']}"
    )


def test_monthly_override_reads_each_reporting_year_month_on_its_own(api):
    """PRD §3.3: "The resolved value is exposed as
    `effective_measurement_method` — the override when set, otherwise the
    member's `measurement_method` — and it is recomputed whenever the override
    changes or the employee moves to another member."
    PRD §3.5: "The input set is the employee's hours rows whose
    `measurement_year` equals the season's `tax_year`; the month is full time
    exactly when that month's `counted_hours` is at least 130, and `ft_source`
    for the month is `MONTHLY_ACTUAL`."
    PRD §3.5: "`measured_average_hours` stays null under this method."

    Design: Difficulty/dual_variant_calc/look_back_stability_vs_monthly_actual_ft_months
    """
    ctx = _look_back_member_with_standard_cycle(api)
    employee_look_back, employee_monthly = _employees_with_identical_hours(api, ctx)

    _recompute(api, employee_look_back["id"])
    _recompute(api, employee_monthly["id"])

    reread = fixtures.read_employee(api, employee_monthly["id"])
    assert_employee(
        reread,
        effective_measurement_method="MONTHLY",
        full_time_month_count=0,
        full_time_months=[],
        ft_source_by_month=["MONTHLY_ACTUAL"] * 12,
    )
    assert reread["measured_average_hours"] is None, (
        f"the monthly method leaves measured_average_hours null, got "
        f"{reread['measured_average_hours']}"
    )


# ---------------------------------------------------------------------------
# The look-back denominator at its empty-set boundary
# ---------------------------------------------------------------------------
def test_special_unpaid_leave_at_130_hours_drops_the_month_from_the_denominator(api):
    """PRD §3.3: "`counted_hours` is `hours_of_service` plus `paid_leave_hours` —
    special unpaid leave is *never* added to the numerator."
    PRD §3.3: "`excluded_from_denominator` is true exactly when
    `special_unpaid_leave_hours` is at least 130, and a month so marked drops out
    of the look-back average altogether, from numerator and denominator alike."

    Design: Difficulty/boundary_precision_check/look_back_denominator_empty_after_leave_exclusion
    """
    ctx = _look_back_member_with_standard_cycle(api)
    employee = fixtures.create_employee(
        api,
        ctx["member"]["id"],
        full_name="Bo Halvorsen",
        ssn_last4="1414",
        hire_date="2025-01-01",
        employment_type="VARIABLE_HOUR",
        is_hourly=True,
        hourly_rate_cents=1500,
    )
    fixtures.record_hours(
        api,
        employee["id"],
        2025,
        list(range(1, 12)),
        hours_of_service=0,
        special_unpaid_leave_hours=160,
    )
    fixtures.record_hours(
        api,
        employee["id"],
        2025,
        [12],
        hours_of_service=130,
        special_unpaid_leave_hours=129,
    )

    rows = {row["month"]: row for row in _hours_rows(api, employee["id"], 2025)}
    assert len(rows) == 12, f"expected twelve hours rows for 2025, got {len(rows)}"
    for month in range(1, 12):
        assert_hours_record(
            rows[month],
            special_unpaid_leave_hours=160,
            counted_hours=0,
            excluded_from_denominator=True,
        )
    assert_hours_record(
        rows[12],
        special_unpaid_leave_hours=129,
        counted_hours=130,
        excluded_from_denominator=False,
    )


def test_single_surviving_month_is_the_whole_look_back_denominator(api):
    """PRD §3.5: "The measurement months are those months whose first day falls
    within the cycle's measurement start and end dates inclusive, and the input
    set is the employee's hours rows for those months whose
    `excluded_from_denominator` is false."
    PRD §3.5: "Otherwise `measured_average_hours` is the sum of `counted_hours`
    across the surviving rows divided by the number of surviving rows, rounded
    half up to two decimal places, and the single stability verdict is that this
    average is at least the cycle's `hours_threshold_monthly`."

    Design: Difficulty/boundary_precision_check/look_back_denominator_empty_after_leave_exclusion
    """
    ctx = _look_back_member_with_standard_cycle(api)
    employee = fixtures.create_employee(
        api,
        ctx["member"]["id"],
        full_name="Bo Halvorsen",
        ssn_last4="1414",
        hire_date="2025-01-01",
        employment_type="VARIABLE_HOUR",
        is_hourly=True,
        hourly_rate_cents=1500,
    )
    fixtures.record_hours(
        api,
        employee["id"],
        2025,
        list(range(1, 12)),
        hours_of_service=0,
        special_unpaid_leave_hours=160,
    )
    fixtures.record_hours(
        api,
        employee["id"],
        2025,
        [12],
        hours_of_service=130,
        special_unpaid_leave_hours=129,
    )

    _recompute(api, employee["id"])

    reread = fixtures.read_employee(api, employee["id"])
    assert reread["measured_average_hours"] == pytest.approx(130.00, abs=0.01), (
        f"one surviving month of 130 counted hours averages 130.00, got "
        f"{reread['measured_average_hours']}"
    )
    assert_employee(
        reread,
        effective_measurement_method="LOOK_BACK",
        full_time_month_count=12,
        full_time_months=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        ft_source_by_month=["LOOK_BACK_STABILITY"] * 12,
    )


def test_recompute_refused_when_every_measurement_month_is_excluded(api):
    """PRD §3.5: "The measurement months are those months whose first day falls
    within the cycle's measurement start and end dates inclusive, and the input
    set is the employee's hours rows for those months whose
    `excluded_from_denominator` is false."
    PRD §3.5: "If that filtered set is empty the recompute is refused with
    `ERR_NO_HOURS_DATA`."
    PRD §3.3: "A new hire starts `ACTIVE` with a null `termination_date`, a null
    `open_leave_type`, `full_time_month_count` of 0, empty `full_time_months`, a
    null `measured_average_hours` and a null `last_recomputed_at`."

    Design: Difficulty/boundary_precision_check/look_back_denominator_empty_after_leave_exclusion
    """
    ctx = _look_back_member_with_standard_cycle(api)
    employee = fixtures.create_employee(
        api,
        ctx["member"]["id"],
        full_name="Ada Nkemi",
        ssn_last4="1313",
        hire_date="2025-01-01",
        employment_type="VARIABLE_HOUR",
        is_hourly=True,
        hourly_rate_cents=1500,
    )
    fixtures.record_hours(
        api,
        employee["id"],
        2025,
        list(range(1, 13)),
        hours_of_service=0,
        special_unpaid_leave_hours=160,
    )

    response = api.recompute_employee_full_time(employee["id"], BA)
    validate_error(response, ApiErrorId.ERR_NO_HOURS_DATA, 422)

    for row in _hours_rows(api, employee["id"], 2025):
        assert_hours_record(row, counted_hours=0, excluded_from_denominator=True)

    reread = fixtures.read_employee(api, employee["id"])
    assert reread["measured_average_hours"] is None, (
        f"a refused recompute must write nothing, got measured_average_hours "
        f"{reread['measured_average_hours']}"
    )
    assert reread["last_recomputed_at"] is None, (
        f"a refused recompute must leave last_recomputed_at null, got "
        f"{reread['last_recomputed_at']}"
    )
    assert reread["full_time_month_count"] == 0, (
        f"a refused recompute must leave full_time_month_count at 0, got "
        f"{reread['full_time_month_count']}"
    )


# ---------------------------------------------------------------------------
# Stability periods are closed at both ends
# ---------------------------------------------------------------------------
def _member_with_one_cycle(api):
    """A member whose stability period already runs 2026-01-01 through
    2026-12-31."""
    season = fixtures.create_filing_season(api)
    group = fixtures.create_controlled_group(api, season["id"], name="Closed Interval Group")
    member = fixtures.create_group_member(
        api,
        group["id"],
        ein="222222221",
        legal_name="Closed Interval Co",
        measurement_method="LOOK_BACK",
    )
    cycle = fixtures.create_measurement_cycle(
        api, member["id"], cycle_type="STANDARD", **CYCLE_DATES
    )
    return member, cycle


def test_stability_period_starting_on_an_existing_end_date_is_rejected(api):
    """PRD §3.3: "For the same employee — or, for a standard cycle, for the same
    member with a null `employee_id` — the interval running from
    `stability_start_date` through `stability_end_date` is treated as **closed at
    both ends**, so a new cycle is refused with `ERR_STABILITY_PERIOD_OVERLAP`
    whenever its start falls on or before an existing period's end and its end
    falls on or after that period's start."
    PRD §3.3: "Touching endpoints therefore collide: a new period may begin only
    strictly after the previous one ends."

    Design: Difficulty/resource_temporal_overlap/stability_period_closed_interval_touching_end_rejected
    """
    member, cycle = _member_with_one_cycle(api)

    touching = factories.measurement_cycle_payload(
        member["id"],
        cycle_type="STANDARD",
        measurement_start_date="2026-01-01",
        measurement_end_date="2026-11-30",
        admin_period_end_date="2026-12-30",
        stability_start_date="2026-12-31",
        stability_end_date="2027-12-31",
        hours_threshold_monthly=130,
    )
    validate_error(
        api.create_measurement_cycle(touching, CO),
        ApiErrorId.ERR_STABILITY_PERIOD_OVERLAP,
        409,
    )

    surviving = _cycles_of_member(api, member["id"])
    assert len(surviving) == 1, (
        f"the rejected cycle must not be persisted, found {len(surviving)} cycles"
    )
    assert_measurement_cycle(
        surviving[0],
        stability_start_date="2026-01-01",
        stability_end_date="2026-12-31",
    )
    assert surviving[0]["id"] == cycle["id"], "the surviving cycle must be the original"


def test_stability_period_starting_strictly_after_the_existing_end_is_accepted(api):
    """PRD §3.3: "Touching endpoints therefore collide: a new period may begin
    only strictly after the previous one ends."
    PRD §3.3: "`hours_threshold_monthly` defaults to 130 and is the monthly
    average at or above which the employee is full time for the whole stability
    period."

    Design: Difficulty/resource_temporal_overlap/stability_period_closed_interval_touching_end_rejected
    """
    member, cycle = _member_with_one_cycle(api)

    adjacent = factories.measurement_cycle_payload(
        member["id"],
        cycle_type="STANDARD",
        measurement_start_date="2026-01-01",
        measurement_end_date="2026-11-30",
        admin_period_end_date="2026-12-31",
        stability_start_date="2027-01-01",
        stability_end_date="2027-12-31",
        hours_threshold_monthly=130,
    )
    created = validate_success(api.create_measurement_cycle(adjacent, CO), 201)

    assert_measurement_cycle(
        created,
        group_member_id=member["id"],
        cycle_type="STANDARD",
        stability_start_date="2027-01-01",
        stability_end_date="2027-12-31",
        hours_threshold_monthly=130,
    )

    cycles = _cycles_of_member(api, member["id"])
    assert len(cycles) == 2, f"expected two cycles for the member, found {len(cycles)}"
    original = get_success_data(api.get_measurement_cycle(cycle["id"], CO))
    assert_measurement_cycle(
        original,
        stability_start_date="2026-01-01",
        stability_end_date="2026-12-31",
    )
