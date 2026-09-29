"""The elective-deferral match, the compensation-cap accumulator and derived rollups."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents, assert_contribution_record_shape
from test_helpers.test_users import PAYROLL_HEADERS


def test_create_contribution_record_missing_required_field_rejected(client):
    """
    A payroll line without its deferral amount is not well formed.

    PRD: "Required body fields must be present, types correct and enum members
    valid; `amount_cents` must be greater than zero".

    PRD: "The payload carries `employee_id`, `payroll_period_id`,
    `eligible_compensation_cents` (plan-eligible compensation paid in the period,
    which must be zero or greater, with zero explicitly allowed for unpaid-leave
    periods) and `elective_deferral_cents` (the deferral withheld in the period,
    also zero or greater)."

    Design: Corner/entities/corner_create_contribution_record_missing_required_field_rejected
    """
    plan_year = fx.setup_open_plan_year(client)
    employee = fx.create_employee(client)
    period = fx.create_payroll_period(client, plan_year["id"], 3)

    payload = f.contribution_record_payload(
        employee["id"], period["id"], elective_deferral_cents=f.OMIT
    )
    assert "elective_deferral_cents" not in payload

    response = client.create_contribution_record(payload, PAYROLL_HEADERS)
    validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

    period_after = validate_success(client.get_payroll_period(period["id"], PAYROLL_HEADERS))
    assert_cents(period_after["total_eligible_compensation_cents"], 0, "period compensation")
    assert_cents(period_after["total_deferral_match_cents"], 0, "period deferral match")

    employee_after = fx.refresh_employee(client, employee["id"])
    assert_cents(employee_after["ytd_deferral_cents"], 0, "ytd_deferral_cents")


def test_deferral_match_cross_tier_straddle(client):
    """
    A deferral that overruns the first rung is matched across both rungs at their own rates.

    PRD: "The deferral dollars consumed at the first tier are the lesser of
    `elective_deferral_cents` and the first tier ceiling. The dollars consumed at
    the second tier are the lesser of the second tier ceiling and the excess of
    `elective_deferral_cents` over the first tier ceiling, that excess floored at
    zero."

    PRD: "`deferral_match_cents` is the first-tier consumption multiplied by
    `tier1_match_rate`, plus the second-tier consumption multiplied by
    `tier2_match_rate`, with the sum rounded half up to whole cents once."

    Design: Corner/calculations/corner_deferral_match_cross_tier_straddle
    """
    plan_year = fx.setup_open_plan_year(client)
    employee = fx.create_employee(client)
    period = fx.create_payroll_period(client, plan_year["id"], 3)

    record = fx.post_contribution_record(
        client, employee["id"], period["id"], 1_000_000, 45_000
    )

    assert_contribution_record_shape(record)
    assert_cents(record["counted_compensation_cents"], 1_000_000, "counted compensation")
    assert_cents(record["deferral_match_cents"], 37_500, "deferral_match_cents")
    assert_cents(record["qslp_space_tier1_cents"], 0, "qslp_space_tier1_cents")
    assert_cents(record["qslp_space_tier2_cents"], 5_000, "qslp_space_tier2_cents")

    period_after = validate_success(client.get_payroll_period(period["id"], PAYROLL_HEADERS))
    assert_cents(period_after["total_deferral_match_cents"], 37_500, "period deferral match")

    plan_year_after = fx.refresh_plan_year(client, plan_year["id"])
    assert_cents(
        plan_year_after["total_deferral_match_funded_cents"], 37_500, "plan year deferral match"
    )

    employee_after = fx.refresh_employee(client, employee["id"])
    assert_cents(employee_after["ytd_deferral_match_cents"], 37_500, "ytd deferral match")


def test_compensation_cap_accumulator_across_periods(client):
    """
    Counted compensation stops accumulating once the annual pay ceiling is reached.

    PRD: "`counted_compensation_cents` is the lesser of
    `eligible_compensation_cents` and the plan year's `compensation_cap_cents` less
    that prior counted amount, floored at zero."

    PRD: "The first tier ceiling is `counted_compensation_cents` multiplied by
    `tier1_pct`, and the second tier ceiling is `counted_compensation_cents`
    multiplied by `tier2_pct`."

    Design: Corner/calculations/corner_compensation_cap_accumulator_across_periods
    """
    scenario = fx.setup_multi_period_deferrals(
        client,
        period_specs=[
            {
                "period_number": 1,
                "start_date": "2026-01-01T00:00:00Z",
                "end_date": "2026-06-30T23:59:59Z",
                "pay_date": "2026-07-05T00:00:00Z",
                "eligible_compensation_cents": 20_000_000,
                "elective_deferral_cents": 0,
            },
            {
                "period_number": 2,
                "start_date": "2026-07-01T00:00:00Z",
                "end_date": "2026-12-31T23:59:59Z",
                "pay_date": "2027-01-05T00:00:00Z",
                "eligible_compensation_cents": 20_000_000,
                "elective_deferral_cents": 0,
            },
        ],
    )
    first, second = scenario["contribution_records"]

    assert_cents(first["counted_compensation_cents"], 20_000_000, "first counted compensation")
    assert_cents(first["deferral_match_cents"], 0, "first deferral match")
    assert_cents(first["qslp_space_tier1_cents"], 600_000, "first tier1 space")

    assert_cents(second["counted_compensation_cents"], 14_500_000, "second counted compensation")
    assert_cents(second["deferral_match_cents"], 0, "second deferral match")
    assert_cents(second["qslp_space_tier1_cents"], 435_000, "second tier1 space")

    employee_after = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(
        employee_after["ytd_eligible_compensation_cents"], 34_500_000, "ytd counted compensation"
    )

    plan_year_after = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(
        plan_year_after["total_deferral_match_funded_cents"], 0, "plan year deferral match"
    )


def test_duplicate_contribution_record_rejected(client):
    """
    An employee may carry only one payroll line per period.

    PRD: "Only one line may exist per employee and period; a second attempt is
    rejected with `ERR_DUPLICATE_CONTRIBUTION_RECORD`."

    Design: Corner/validations/corner_duplicate_contribution_record_rejected
    """
    plan_year = fx.setup_open_plan_year(client)
    employee = fx.create_employee(client)
    period = fx.create_payroll_period(client, plan_year["id"], 3)

    first = fx.post_contribution_record(client, employee["id"], period["id"])
    assert_cents(first["deferral_match_cents"], 20_000, "deferral_match_cents")

    response = client.create_contribution_record(
        f.contribution_record_payload(employee["id"], period["id"]), PAYROLL_HEADERS
    )
    validate_error(response, ApiErrorId.DUPLICATE_CONTRIBUTION_RECORD.value, 409)

    period_after = validate_success(client.get_payroll_period(period["id"], PAYROLL_HEADERS))
    assert_cents(
        period_after["total_eligible_compensation_cents"], 1_000_000, "period compensation"
    )
    assert_cents(period_after["total_deferral_match_cents"], 20_000, "period deferral match")

    listing = client.list_contribution_records(
        PAYROLL_HEADERS, {"payroll_period_id": period["id"]}
    )
    records, meta = validate_paginated(listing)
    assert len(records) == 1
    assert meta["total_count"] == 1


def test_derived_totals_reconcile_across_two_payroll_periods(client):
    """
    Period, plan-year and employee rollups agree after two lines in two periods.

    PRD: "`total_deferral_match_funded_cents` is the sum of `deferral_match_cents`
    across the contribution records of the plan year's payroll periods".

    PRD: "`ytd_deferral_cents` sums `elective_deferral_cents`;
    `ytd_deferral_match_cents` sums `deferral_match_cents`".

    Design: Corner/cross-cutting complexity layers/corner_derived_totals_reconcile_across_two_payroll_periods
    """
    scenario = fx.setup_multi_period_deferrals(
        client,
        period_specs=[
            {
                "period_number": 1,
                "eligible_compensation_cents": 1_000_000,
                "elective_deferral_cents": 20_000,
            },
            {
                "period_number": 2,
                "eligible_compensation_cents": 1_000_000,
                "elective_deferral_cents": 15_000,
            },
        ],
    )
    first, second = scenario["contribution_records"]
    first_period, second_period = scenario["periods"]

    assert_cents(first["deferral_match_cents"], 20_000, "first deferral match")
    assert_cents(first["qslp_space_tier1_cents"], 10_000, "first tier1 space")
    assert_cents(first["qslp_space_tier2_cents"], 20_000, "first tier2 space")
    assert_cents(second["deferral_match_cents"], 15_000, "second deferral match")

    first_after = validate_success(client.get_payroll_period(first_period["id"], PAYROLL_HEADERS))
    assert_cents(first_after["total_deferral_match_cents"], 20_000, "period one match")
    assert_cents(
        first_after["total_eligible_compensation_cents"], 1_000_000, "period one compensation"
    )

    second_after = validate_success(
        client.get_payroll_period(second_period["id"], PAYROLL_HEADERS)
    )
    assert_cents(second_after["total_deferral_match_cents"], 15_000, "period two match")

    plan_year_after = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(
        plan_year_after["total_deferral_match_funded_cents"], 35_000, "plan year deferral match"
    )

    employee_after = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(employee_after["ytd_deferral_match_cents"], 35_000, "ytd deferral match")
    assert_cents(employee_after["ytd_deferral_cents"], 35_000, "ytd deferral")
    assert_cents(employee_after["remaining_qslp_space_cents"], 2_265_000, "remaining space")
