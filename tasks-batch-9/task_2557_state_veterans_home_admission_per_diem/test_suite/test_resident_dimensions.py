"""A resident's occupancy and billing dimensions advance independently.

Occupancy tracks where the resident physically is; billing tracks how far the
month's money has been settled. Neither dimension may drag the other along, so
the combined state of a readmitted resident who has already been finalised is
only reachable when the two are genuinely separate.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx


def _hospitalized_resident_with_verified_income(api):
    """A resident with fifteen materialised census days who is then hospitalised.

    Income is declared and verified before the month is half over, the checkpoint
    runs through the fifteenth, and the hospitalisation on the sixteenth moves the
    occupancy dimension only.
    """
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    fx.declare_income(api, scenario.resident_id, "SSA", 114000, "2026-08", verify=True)
    fx.set_clock(api, "2026-08-15T00:00:00Z")
    fx.census_run(api, "2026-08-15", scenario.home_id)
    fx.hospitalize(api, scenario.resident_id, "2026-08-16", clock="2026-08-16T00:00:00Z")
    return scenario


def test_billing_dimension_advances_while_occupancy_stays_hospitalized(api):
    """A hospitalised resident may be finalised without leaving hospital.

    Per the PRD: "Note that this dimension moves independently of occupancy: a
    `HOSPITALIZED` resident can be moved to `FINAL_COST_SHARE` exactly as an
    `ADMITTED` one can." The determination writes the billing dimension and leaves
    the occupancy dimension untouched.

    Design: Difficulty/non_linear_state_machine/resident_parallel_occupancy_and_billing_dimensions
    """
    scenario = _hospitalized_resident_with_verified_income(api)

    validate_success(
        fx.determine_cost_share(
            api,
            scenario.resident_id,
            variant="FINAL",
            declared_medical_expense_cents=20000,
        ),
        201,
    )

    resident = fx.read_resident(api, scenario.resident_id)
    assert resident["occupancy_status"] == "HOSPITALIZED"
    assert resident["billing_status"] == "FINAL_COST_SHARE"


def test_final_day_count_is_read_from_census_rows_not_from_the_occupancy_flag(api):
    """The finalised month counts the fifteen materialised resident days.

    Per the PRD: "For `FINAL` it is the number of the resident's census days
    classified `RESIDENT_DAY` whose `service_date` falls inside `effective_month`."
    Only half the month has been materialised, so the day count and the federal
    offset both follow the census rather than the calendar.

    Design: Difficulty/non_linear_state_machine/resident_parallel_occupancy_and_billing_dimensions
    """
    scenario = _hospitalized_resident_with_verified_income(api)

    determination = validate_success(
        fx.determine_cost_share(
            api,
            scenario.resident_id,
            variant="FINAL",
            declared_medical_expense_cents=20000,
        ),
        201,
    )

    assert determination["resident_day_count"] == 15
    assert determination["income_tier"] == "TIER_2"
    assert determination["tiered_share_cents"] == 36000
    assert determination["federal_per_diem_offset_cents"] == 8893
    assert determination["monthly_cost_share_cents"] == 27107


def test_readmission_restores_occupancy_without_resetting_billing(api):
    """Coming back from hospital returns occupancy to ADMITTED and leaves billing finalised.

    Per the PRD: "A resident already in `FINAL_COST_SHARE` may receive further
    `FINAL` determinations for the same or a later `effective_month`, each of
    which stays in `FINAL_COST_SHARE`, supersedes the prior governing row for that
    month and records its `delta_from_prior_cents`." Nothing about the occupancy
    move rewinds that, and the four days away are folded into the bed-hold total.

    Design: Difficulty/non_linear_state_machine/resident_parallel_occupancy_and_billing_dimensions
    """
    scenario = _hospitalized_resident_with_verified_income(api)
    validate_success(
        fx.determine_cost_share(
            api,
            scenario.resident_id,
            variant="FINAL",
            declared_medical_expense_cents=20000,
        ),
        201,
    )

    fx.readmit(api, scenario.resident_id, "2026-08-20", clock="2026-08-20T00:00:00Z")

    resident = fx.read_resident(api, scenario.resident_id)
    assert resident["occupancy_status"] == "ADMITTED"
    assert resident["billing_status"] == "FINAL_COST_SHARE"
    assert resident["bed_hold_days_used"] == 4
    assert resident["readmission_count"] == 1
    assert resident["monthly_cost_share_cents"] == 27107
