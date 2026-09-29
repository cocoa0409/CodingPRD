"""The two warranty-accrual estimation variants on one identical cohort.

PRD §3.3: "A `MATURE` family that also carries an analogue basis may legally be
accrued under either variant on identical data, and the two variants will return
different figures".
"""

from test_helpers import (
    create_accrual,
    create_family,
    create_failure_mode,
    create_observation,
    create_period,
    create_vintage,
)


def _build_world(api):
    """FAM-A as the analogue predecessor and FAM-B as the accruing family."""
    create_period(api, "2026-Q2", "2026-04-01", "2026-06-30")
    period_q3 = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    period_q4 = create_period(api, "2026-Q4", "2026-10-01", "2026-12-31")

    analog_family = create_family(
        api,
        family_code="FAM-A",
        name="Legacy Compressor Platform",
        launch_date="2022-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=20000,
        reserve_cap_cents=100000000,
    )
    analog_vintage = create_vintage(
        api,
        analog_family["id"],
        vintage_code="A-MY2022",
        units_shipped=10000,
        ship_period_code="2022-Q1",
        warranty_expiry_date="2025-12-31",
    )
    analog_mode = create_failure_mode(
        api,
        analog_family["id"],
        mode_code="FM-A-CORE",
        description="Legacy compressor core wear",
        severity="FUNCTIONAL",
        cost_per_claim_cents=20000,
    )
    create_observation(
        api,
        analog_vintage["id"],
        analog_mode["id"],
        observation_period_code="2026-Q2",
        months_in_service_from=0,
        months_in_service_to=24,
        claim_count=300,
        paid_cost_cents=6000000,
    )

    family = create_family(
        api,
        family_code="FAM-B",
        name="Next Gen Compressor Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=30000,
        reserve_cap_cents=10000000,
        engineering_estimate_rate_ppm=4000,
        analog_family_id=analog_family["id"],
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="B-MY2024",
        units_shipped=8000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    mode_comp = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-COMP",
        description="Compressor valve plate fracture",
        severity="FUNCTIONAL",
        cost_per_claim_cents=25000,
    )
    mode_seal = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-SEAL",
        description="Door seal cosmetic delamination",
        severity="COSMETIC",
        cost_per_claim_cents=10000,
    )
    create_observation(
        api,
        vintage["id"],
        mode_comp["id"],
        observation_period_code="2026-Q2",
        months_in_service_from=0,
        months_in_service_to=12,
        claim_count=40,
        paid_cost_cents=1000000,
    )
    create_observation(
        api,
        vintage["id"],
        mode_seal["id"],
        observation_period_code="2026-Q2",
        months_in_service_from=0,
        months_in_service_to=12,
        claim_count=100,
        paid_cost_cents=900000,
    )
    return {
        "period_q3": period_q3,
        "period_q4": period_q4,
        "family": family,
        "vintage": vintage,
    }


def test_historical_rate_prices_each_failure_mode_from_the_cohorts_own_history(api):
    """HISTORICAL_RATE rounds a rate and an ultimate count per failure mode.

    PRD §3.3: "The rounding order here is pinned and observable: the rate and the
    ultimate claim count are each rounded **per failure mode, before any
    summation**, never summed as exact rationals and rounded once at the end."
    FM-COMP contributes a 5000 ppm rate and 100 ultimate claims at 25000 cents
    and FM-SEAL a 12500 ppm rate and 250 ultimate claims at 10000 cents, so the
    summed rate is 17500 ppm and the gross ultimate cost is 5000000 cents. The
    accrual is that gross less the cohort's 1900000 cents paid to date.

    Design: Difficulty/dual_variant_calc/warranty_accrual_historical_rate_vs_analog_blend_on_same_vintage
    """
    world = _build_world(api)

    accrual = create_accrual(
        api,
        world["period_q3"]["id"],
        world["vintage"]["id"],
        method="HISTORICAL_RATE",
        elapsed_exposure_bps=4000,
        expected_period_version=1,
    )

    assert accrual["expected_claim_rate_ppm"] == 17500
    assert accrual["paid_to_date_cents"] == 1900000
    assert accrual["accrued_amount_cents"] == 3100000
    assert accrual["cost_per_claim_basis_cents"] == 14286
    assert accrual["status"] == "DRAFT"


def test_analog_blend_prices_every_claim_at_the_family_standard_cost(api):
    """ANALOG_BLEND weights 60/40 and prices at one family-level figure.

    PRD §3.3: "multiply `engineering_estimate_rate_ppm` by 6000, multiply the
    developed analogue rate by 4000, add the two products as exact whole numbers,
    divide the sum by 10000, and round **once** to the nearest integer." The
    analogue's 30000 ppm observed rate develops to 75000 ppm, so the blend of the
    4000 ppm engineering estimate and that developed rate is 32400 ppm. PRD §3.3:
    "The accrual's `cost_per_claim_basis_cents` is simply the family's
    `standard_cost_per_claim_cents`".

    Design: Difficulty/dual_variant_calc/warranty_accrual_historical_rate_vs_analog_blend_on_same_vintage
    """
    world = _build_world(api)

    accrual = create_accrual(
        api,
        world["period_q4"]["id"],
        world["vintage"]["id"],
        method="ANALOG_BLEND",
        elapsed_exposure_bps=4000,
        expected_period_version=1,
    )

    assert accrual["expected_claim_rate_ppm"] == 32400
    assert accrual["cost_per_claim_basis_cents"] == 30000
    assert accrual["paid_to_date_cents"] == 1900000
    assert accrual["accrued_amount_cents"] == 5870000
    assert accrual["status"] == "DRAFT"


def test_the_two_variants_return_different_amounts_on_identical_data(api):
    """The same cohort accrued both ways diverges by 2770000 cents.

    PRD §3.3: "the two variants will return different figures; choosing between
    them is a deliberate accounting judgement, not a fallback." HISTORICAL_RATE
    prices each mode at its own `cost_per_claim_cents` and reaches 3100000 cents,
    while ANALOG_BLEND prices every claim at the family's 30000-cent standard cost
    and reaches 5870000 cents. PRD §3.3: "`paid_to_date_cents` is the sum of
    `paid_cost_cents` over every claim observation of this accrual's own cohort",
    so both variants subtract the same 1900000 cents.

    Design: Difficulty/dual_variant_calc/warranty_accrual_historical_rate_vs_analog_blend_on_same_vintage
    """
    world = _build_world(api)

    historical = create_accrual(
        api,
        world["period_q3"]["id"],
        world["vintage"]["id"],
        method="HISTORICAL_RATE",
        elapsed_exposure_bps=4000,
        expected_period_version=1,
    )
    analog = create_accrual(
        api,
        world["period_q4"]["id"],
        world["vintage"]["id"],
        method="ANALOG_BLEND",
        elapsed_exposure_bps=4000,
        expected_period_version=1,
    )

    assert historical["accrued_amount_cents"] == 3100000
    assert analog["accrued_amount_cents"] == 5870000
    assert analog["accrued_amount_cents"] - historical["accrued_amount_cents"] == 2770000
    assert historical["paid_to_date_cents"] == analog["paid_to_date_cents"] == 1900000
