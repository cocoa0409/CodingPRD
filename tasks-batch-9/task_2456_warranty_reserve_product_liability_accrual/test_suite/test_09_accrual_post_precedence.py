"""Posting an accrual: the state precondition outranks the reserve ceiling.

PRD §2.9: "When a request violates more than one rule, the response is determined by
the **first** violated rule in the ordering below, and no later rule is evaluated."
"""

from test_helpers import (
    CONTROLLER_HEADERS,
    ERR_INVALID_STATE_TRANSITION,
    ERR_RESERVE_CAP_EXCEEDED,
    create_accrual,
    create_failure_mode,
    create_family,
    create_observation,
    create_period,
    create_vintage,
    lock_period,
    propose_accrual,
    read_accrual,
    read_family,
    validate_error,
)


def _build_world(api):
    """FAM-D has a PROPOSED accrual of 2910000 cents against a 1000000-cent cap."""
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
        family_code="FAM-D",
        name="Downdraft Hob Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=30000,
        reserve_cap_cents=1000000,
        engineering_estimate_rate_ppm=4000,
        analog_family_id=analog_family["id"],
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="D-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    create_failure_mode(
        api,
        family["id"],
        mode_code="FM-D-FAN",
        description="Extraction fan bearing noise",
        severity="FUNCTIONAL",
        cost_per_claim_cents=14000,
    )
    accrual = create_accrual(
        api,
        period["id"],
        vintage["id"],
        method="ANALOG_BLEND",
        elapsed_exposure_bps=2500,
        expected_period_version=1,
    )
    proposed = propose_accrual(api, accrual["id"])
    assert proposed["accrued_amount_cents"] == 2910000

    return {"period": period, "family": family, "accrual": proposed}


def test_posting_into_an_open_period_answers_the_state_error_not_the_cap_error(api):
    """Both rules are violated at once and the earlier rung wins.

    PRD §3.3: "The scoping period must be precisely in `ANALYSIS_LOCKED` — not merely
    non-closed — and a period still `OPEN`, already in `ACTUARIAL_REVIEW`, or `CLOSED`
    answers `ERR_INVALID_STATE_TRANSITION`." The same request would also breach PRD
    §3.3's ceiling, "the family reserve balance that would result from counting this
    accrual as posted must not exceed the family's `reserve_cap_cents`", but PRD §2.9
    places the state rung at 12 and the ceiling at 36.

    Design: Difficulty/priority_pair_validation_conflict/accrual_post_state_error_outranks_reserve_cap_exceeded
    """
    world = _build_world(api)

    response = api.post_accrual(CONTROLLER_HEADERS, world["accrual"]["id"])
    validate_error(response, ERR_INVALID_STATE_TRANSITION, expected_status=409)

    accrual = read_accrual(api, world["accrual"]["id"])
    assert accrual["status"] == "PROPOSED"
    assert accrual["posted_by_user_id"] is None


def test_locking_the_period_flips_the_identical_post_to_the_cap_error(api):
    """With the state rung satisfied the ceiling rung finally answers.

    PRD §3.3: "if it would, the post is refused with `ERR_RESERVE_CAP_EXCEEDED` and
    nothing is written." Posting the 2910000-cent estimate would take the family
    balance far past its 1000000-cent cap. PRD §2.10: "A freshly registered family
    sits at a balance of zero and therefore at `NORMAL`", and the refused post leaves
    it there.

    Design: Difficulty/priority_pair_validation_conflict/accrual_post_state_error_outranks_reserve_cap_exceeded
    """
    world = _build_world(api)
    lock_period(api, world["period"]["id"])

    response = api.post_accrual(CONTROLLER_HEADERS, world["accrual"]["id"])
    validate_error(response, ERR_RESERVE_CAP_EXCEEDED, expected_status=422)

    accrual = read_accrual(api, world["accrual"]["id"])
    assert accrual["status"] == "PROPOSED"
    assert accrual["posted_by_user_id"] is None
    assert accrual["accrued_amount_cents"] == 2910000

    family = read_family(api, world["family"]["id"])
    assert family["warranty_reserve_balance_cents"] == 0
    assert family["reserve_posture"] == "NORMAL"
