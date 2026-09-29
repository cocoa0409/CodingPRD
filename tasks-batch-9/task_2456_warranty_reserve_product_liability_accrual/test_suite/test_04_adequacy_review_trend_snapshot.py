"""Reserve adequacy: the pinned seven-step order and the frozen snapshot.

PRD §3.4: "The evaluation order above is pinned to break an apparent circularity,
and implementations must not 'improve' it."
"""

from test_helpers import (
    ANALYST_HEADERS,
    apply_true_up,
    create_accrual,
    create_adequacy_review,
    create_failure_mode,
    create_family,
    create_observation,
    create_period,
    create_vintage,
    lock_period,
    post_accrual,
    propose_accrual,
    read_family,
    success_data,
)


def _build_world(api):
    """FAM-Z with one POSTED historical-rate accrual of 3100000 cents."""
    create_period(api, "2026-Q2", "2026-04-01", "2026-06-30")
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")

    family = create_family(
        api,
        family_code="FAM-Z",
        name="Upright Freezer Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=20000,
        reserve_cap_cents=10000000,
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="Z-MY2024",
        units_shipped=8000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    mode_a = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-Z-A",
        description="Evaporator leak",
        severity="FUNCTIONAL",
        cost_per_claim_cents=25000,
    )
    mode_b = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-Z-B",
        description="Handle trim discolouration",
        severity="COSMETIC",
        cost_per_claim_cents=10000,
    )
    create_observation(
        api,
        vintage["id"],
        mode_a["id"],
        observation_period_code="2026-Q2",
        months_in_service_from=0,
        months_in_service_to=12,
        claim_count=40,
        paid_cost_cents=1000000,
    )
    create_observation(
        api,
        vintage["id"],
        mode_b["id"],
        observation_period_code="2026-Q2",
        months_in_service_from=0,
        months_in_service_to=12,
        claim_count=100,
        paid_cost_cents=900000,
    )

    accrual = create_accrual(
        api,
        period["id"],
        vintage["id"],
        method="HISTORICAL_RATE",
        elapsed_exposure_bps=4000,
        expected_period_version=1,
    )
    propose_accrual(api, accrual["id"])
    lock_period(api, period["id"])
    posted = post_accrual(api, accrual["id"])
    assert posted["accrued_amount_cents"] == 3100000

    return {"period": period, "family": family, "vintage": vintage, "accrual": posted}


def test_adequacy_review_selects_the_trend_tier_from_the_pre_true_up_ratio(api):
    """Steps one to four run against the posted-accrual base as it stands.

    PRD §3.4: "For each accrual in the working set, multiply its
    `accrued_amount_cents` by its `elapsed_exposure_bps`, divide by 10000, and
    round to the nearest integer to obtain that accrual's earned portion" — 4000
    bps of 3100000 cents is 1240000. PRD §3.4: "the review's `actual_paid_cents` is
    the sum of `paid_cost_cents` over every claim observation whose cohort belongs
    to the family under review and whose `observation_period_code` is lexically
    less than or equal to the review period's `period_code`" — 1900000 cents. PRD
    §3.4: "Any higher ratio sets `trend_adjustment_bps` to 3000 and
    `adequacy_status` to `DEFICIENT`", and 15323 basis points is above the 15000
    boundary.

    Design: Difficulty/combinatorial_formula/adequacy_review_pins_trend_tier_against_pre_true_up_base_snapshot
    """
    world = _build_world(api)

    review = create_adequacy_review(api, world["period"]["id"], world["family"]["id"])

    assert review["expected_to_date_cents"] == 1240000
    assert review["actual_paid_cents"] == 1900000
    assert review["ave_ratio_bps"] == 15323
    assert review["trend_adjustment_bps"] == 3000
    assert review["adequacy_status"] == "DEFICIENT"


def test_recommendation_combines_the_tier_shift_with_the_paid_divergence(api):
    """Step seven adds the remaining-base movement to the actual-versus-expected gap.

    PRD §3.4: "`remaining_base_cents` is the sum, over the same working set, of each
    accrual's `accrued_amount_cents` less that accrual's earned portion — reusing
    the *rounded* earned figure computed in step one rather than recomputing it" —
    3100000 less 1240000 is 1860000. PRD §3.4: "`adjusted_remaining_cents` is
    `remaining_base_cents` multiplied by the quantity 10000 plus
    `trend_adjustment_bps`, divided by 10000, rounded to the nearest integer" —
    2418000. PRD §3.4: "`recommended_true_up_cents` is the amount by which step six
    moved the remaining base ... plus the amount by which actuals have already
    diverged from expectation" — 558000 plus 660000 is 1218000.

    Design: Difficulty/combinatorial_formula/adequacy_review_pins_trend_tier_against_pre_true_up_base_snapshot
    """
    world = _build_world(api)

    review = create_adequacy_review(api, world["period"]["id"], world["family"]["id"])

    assert review["remaining_base_cents"] == 1860000
    assert review["adjusted_remaining_cents"] == 2418000
    assert review["recommended_true_up_cents"] == 1218000
    assert review["true_up_applied"] is False


def test_applying_the_true_up_moves_the_balance_without_re_running_the_analysis(api):
    """The review's intermediates stay frozen while the family ledger moves.

    PRD §3.4: "applying its true-up later changes the family's
    `warranty_reserve_balance_cents`, but it must not re-run any of the seven
    steps, and the review's stored intermediates never move again." PRD §2.10: "The
    balance is the posted accrual total plus the approved campaign total plus the
    applied true-up total, minus the completed execution total", so 3100000 plus
    1218000 is 4318000; against the 10000000-cent cap PRD §2.10 leaves the posture
    at `NORMAL` because the ratio is under 8000 basis points.

    Design: Difficulty/combinatorial_formula/adequacy_review_pins_trend_tier_against_pre_true_up_base_snapshot
    """
    world = _build_world(api)
    review = create_adequacy_review(api, world["period"]["id"], world["family"]["id"])

    applied = apply_true_up(api, review["id"])

    assert applied["true_up_applied"] is True
    assert applied["ave_ratio_bps"] == 15323
    assert applied["expected_to_date_cents"] == 1240000
    assert applied["remaining_base_cents"] == 1860000
    assert applied["recommended_true_up_cents"] == 1218000

    reread = success_data(api.get_adequacy_review(ANALYST_HEADERS, review["id"]))
    assert reread["recommended_true_up_cents"] == 1218000
    assert reread["adjusted_remaining_cents"] == 2418000

    family = read_family(api, world["family"]["id"])
    assert family["warranty_reserve_balance_cents"] == 4318000
    assert family["reserve_posture"] == "NORMAL"
