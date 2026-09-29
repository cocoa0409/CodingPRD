"""The two integer maturity thresholds probed exactly at and just below the line.

PRD §3.2: "Both comparisons are inclusive, so exactly one year of observed
development on exactly five thousand shipped units already classifies as `MATURE`."
"""

from test_helpers import (
    ANALYST_HEADERS,
    ERR_INSUFFICIENT_CLAIM_HISTORY,
    create_failure_mode,
    create_family,
    create_observation,
    create_period,
    create_vintage,
    factories,
    read_family,
    success_data,
    validate_error,
)


def _cohort(api, family_code, name, units_shipped, months_to, mode_code):
    """One family with a single vintage and a single development bucket."""
    family = create_family(
        api,
        family_code=family_code,
        name=name,
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=20000,
        reserve_cap_cents=10000000,
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code=f"{family_code[-1]}-MY2024",
        units_shipped=units_shipped,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code=mode_code,
        description="Drum belt slip",
        severity="FUNCTIONAL",
        cost_per_claim_cents=20000,
    )
    create_observation(
        api,
        vintage["id"],
        mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=months_to,
        claim_count=25,
        paid_cost_cents=200000,
    )
    return family, vintage


def _build_world(api):
    """Three near-identical cohorts straddling the 12-month and 5000-unit lines."""
    periods = [
        create_period(api, "2026-Q3", "2026-07-01", "2026-09-30"),
        create_period(api, "2026-Q4", "2026-10-01", "2026-12-31"),
        create_period(api, "2027-Q1", "2027-01-01", "2027-03-31"),
    ]
    on_both = _cohort(api, "FAM-F", "Tumble Dryer Platform F", 5000, 12, "FM-F-BELT")
    one_unit_short = _cohort(api, "FAM-G", "Tumble Dryer Platform G", 4999, 12, "FM-G-BELT")
    one_month_short = _cohort(api, "FAM-H", "Tumble Dryer Platform H", 5000, 11, "FM-H-BELT")
    return {
        "periods": periods,
        "on_both": on_both,
        "one_unit_short": one_unit_short,
        "one_month_short": one_month_short,
    }


def test_the_three_cohorts_classify_at_exactly_the_inclusive_thresholds(api):
    """Twelve months on five thousand units is MATURE; one short either way is LIMITED.

    PRD §3.2: "The family's `history_maturity_status` is then `MATURE` when
    `observed_history_months` is at least 12 **and** `observed_exposure_units` is at
    least 5000; in every other case it is `LIMITED`." PRD §3.2 also fixes the two
    metrics: `observed_history_months` "is the largest `months_in_service_to` found
    across all such observations", and `observed_exposure_units` "is the sum of
    `units_shipped` over every production vintage of the family".

    Design: Difficulty/boundary_precision_check/history_maturity_boundary_exact_twelve_months_and_five_thousand_units
    """
    world = _build_world(api)

    on_both = read_family(api, world["on_both"][0]["id"])
    assert on_both["observed_history_months"] == 12
    assert on_both["observed_exposure_units"] == 5000
    assert on_both["history_maturity_status"] == "MATURE"

    one_unit_short = read_family(api, world["one_unit_short"][0]["id"])
    assert one_unit_short["observed_history_months"] == 12
    assert one_unit_short["observed_exposure_units"] == 4999
    assert one_unit_short["history_maturity_status"] == "LIMITED"

    one_month_short = read_family(api, world["one_month_short"][0]["id"])
    assert one_month_short["observed_history_months"] == 11
    assert one_month_short["observed_exposure_units"] == 5000
    assert one_month_short["history_maturity_status"] == "LIMITED"


def test_the_cohort_sitting_on_both_thresholds_may_be_accrued_historically(api):
    """Landing exactly on the line admits the HISTORICAL_RATE variant.

    PRD §3.3: "`HISTORICAL_RATE` is permitted only when the family's
    `history_maturity_status` is `MATURE`". The single mode's observed rate is 25
    claims per 5000 units, or 5000 parts per million, and PRD §3.3 develops it: "multiply
    that rounded rate by `units_shipped`, multiply by the lifetime development factor of
    25000 basis points ... divide by the product of one million and ten thousand, and
    round to the nearest integer", giving 63 ultimate claims at 20000 cents each less
    the 200000 cents already paid.

    Design: Difficulty/boundary_precision_check/history_maturity_boundary_exact_twelve_months_and_five_thousand_units
    """
    world = _build_world(api)
    _, vintage = world["on_both"]

    payload = factories.accrual_payload(
        world["periods"][0]["id"], vintage["id"], 1, method="HISTORICAL_RATE",
        elapsed_exposure_bps=3000,
    )
    accrual = success_data(api.create_accrual_raw(ANALYST_HEADERS, payload), expected_status=201)

    assert accrual["expected_claim_rate_ppm"] == 5000
    assert accrual["cost_per_claim_basis_cents"] == 20000
    assert accrual["accrued_amount_cents"] == 1060000


def test_missing_either_threshold_by_one_refuses_the_historical_variant(api):
    """One unit short and one month short are both refused for the same reason.

    PRD §2.9 rung 24: "When the accrual `method` is `HISTORICAL_RATE`, the vintage's
    family has `history_maturity_status` equal to `MATURE` — guarding
    `POST /warranty/accruals` — otherwise `ERR_INSUFFICIENT_CLAIM_HISTORY` (HTTP 422)."
    PRD §3.3 repeats it: "attempting it on a family still classified `LIMITED` answers
    `ERR_INSUFFICIENT_CLAIM_HISTORY`."

    Design: Difficulty/boundary_precision_check/history_maturity_boundary_exact_twelve_months_and_five_thousand_units
    """
    world = _build_world(api)

    _, short_units_vintage = world["one_unit_short"]
    response = api.create_accrual_raw(
        ANALYST_HEADERS,
        factories.accrual_payload(
            world["periods"][1]["id"], short_units_vintage["id"],
            1, method="HISTORICAL_RATE", elapsed_exposure_bps=3000,
        ),
    )
    validate_error(response, ERR_INSUFFICIENT_CLAIM_HISTORY, expected_status=422)

    _, short_months_vintage = world["one_month_short"]
    response = api.create_accrual_raw(
        ANALYST_HEADERS,
        factories.accrual_payload(
            world["periods"][2]["id"], short_months_vintage["id"],
            1, method="HISTORICAL_RATE", elapsed_exposure_bps=3000,
        ),
    )
    validate_error(response, ERR_INSUFFICIENT_CLAIM_HISTORY, expected_status=422)
