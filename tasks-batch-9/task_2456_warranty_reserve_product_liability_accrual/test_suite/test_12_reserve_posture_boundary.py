"""The utilisation ratio landed exactly on both of its inclusive thresholds.

PRD §2.10: "Both comparisons are inclusive, so a balance exactly equal to the cap
yields `CONSTRAINED` and a balance exactly eighty percent of the cap yields
`ELEVATED`."
"""

from test_helpers import (
    create_accrual,
    create_failure_mode,
    create_family,
    create_observation,
    create_period,
    create_vintage,
    lock_period,
    patch_family,
    post_accrual,
    propose_accrual,
    read_family,
)


def _build_world(api):
    """FAM-Q's 2910000-cent estimate sits at exactly 8000 bps of a 3637500-cent cap."""
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")

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
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=24,
        claim_count=300,
        paid_cost_cents=6000000,
    )

    family = create_family(
        api,
        family_code="FAM-Q",
        name="Quiet Series Cooktop",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=30000,
        reserve_cap_cents=3637500,
        engineering_estimate_rate_ppm=4000,
        analog_family_id=analog_family["id"],
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="Q-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    create_failure_mode(
        api,
        family["id"],
        mode_code="FM-Q-CTRL",
        description="Touch control unresponsive",
        severity="FUNCTIONAL",
        cost_per_claim_cents=17000,
    )
    accrual = create_accrual(
        api,
        period["id"],
        vintage["id"],
        method="ANALOG_BLEND",
        elapsed_exposure_bps=2000,
        expected_period_version=1,
    )
    proposed = propose_accrual(api, accrual["id"])
    assert proposed["accrued_amount_cents"] == 2910000
    lock_period(api, period["id"])

    return {"period": period, "family": family, "accrual": proposed}


def test_a_balance_at_exactly_eighty_percent_of_the_cap_is_elevated_not_constrained(api):
    """8000 basis points exactly clears the middle threshold and no further.

    PRD §2.10: "If that ratio is at least 10000 basis points, `reserve_posture` becomes
    `CONSTRAINED`; otherwise, if it is at least 8000 basis points, `reserve_posture`
    becomes `ELEVATED`; otherwise it becomes `NORMAL`." A balance of 2910000 against a
    3637500-cent cap is exactly 8000 basis points. PRD §3.3 also confirms the post itself
    is admissible, since the ceiling only bars a post where "the family reserve balance that
    would result from counting this accrual as posted" would "exceed the family's
    `reserve_cap_cents`".

    Design: Difficulty/boundary_precision_check/reserve_posture_boundary_exactly_eighty_and_one_hundred_percent_of_cap
    """
    world = _build_world(api)

    posted = post_accrual(api, world["accrual"]["id"])
    assert posted["status"] == "POSTED"

    family = read_family(api, world["family"]["id"])
    assert family["warranty_reserve_balance_cents"] == 2910000
    assert family["reserve_posture"] == "ELEVATED"


def test_lowering_the_cap_to_the_balance_makes_the_ratio_exactly_one_hundred_percent(api):
    """Re-pointing the ceiling at the balance itself tips the posture over.

    PRD §2.10: "a balance exactly equal to the cap yields `CONSTRAINED` ... and
    re-pointing the cap through a family update re-derives the posture against the new
    ceiling without touching the balance." PRD §3.2 lists `reserve_cap_cents` among the
    updatable attributes and says the update "re-derives its `reserve_posture` against
    whatever ceiling `reserve_cap_cents` now holds".

    Design: Difficulty/boundary_precision_check/reserve_posture_boundary_exactly_eighty_and_one_hundred_percent_of_cap
    """
    world = _build_world(api)
    post_accrual(api, world["accrual"]["id"])

    patch_family(api, world["family"]["id"], {"reserve_cap_cents": 2910000})

    family = read_family(api, world["family"]["id"])
    assert family["reserve_cap_cents"] == 2910000
    assert family["reserve_posture"] == "CONSTRAINED"
    assert family["warranty_reserve_balance_cents"] == 2910000
