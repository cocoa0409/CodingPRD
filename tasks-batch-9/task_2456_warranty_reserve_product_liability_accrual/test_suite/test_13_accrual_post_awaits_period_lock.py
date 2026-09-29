"""Posting an accrual depends on the state of a row the request never names.

PRD §2.9 rung 12: "The target row occupies a state from which the requested transition
is declared, which includes every cross-entity state precondition".
"""

from test_helpers import (
    CONTROLLER_HEADERS,
    ERR_INVALID_STATE_TRANSITION,
    RESERVE_CONTROLLER_USER_ID,
    create_accrual,
    create_failure_mode,
    create_family,
    create_observation,
    create_period,
    create_vintage,
    lock_period,
    post_accrual,
    propose_accrual,
    read_accrual,
    read_family,
    read_period,
    validate_error,
)


def _build_world(api):
    """FAM-T has a PROPOSED 2910000-cent accrual scoped by an OPEN period."""
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
        family_code="FAM-T",
        name="Tower Fridge Freezer",
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
        vintage_code="T-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    create_failure_mode(
        api,
        family["id"],
        mode_code="FM-T-ICE",
        description="Ice maker solenoid failure",
        severity="FUNCTIONAL",
        cost_per_claim_cents=19000,
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

    return {"period": period, "family": family, "accrual": proposed}


def test_posting_is_refused_while_the_scoping_period_is_still_open(api):
    """The accrual is in its own legal from-state and the ceiling is generous.

    PRD §3.3: "The accrual must be in `PROPOSED`. The scoping period must be precisely
    in `ANALYSIS_LOCKED` — not merely non-closed — and a period still `OPEN`, already in
    `ACTUARIAL_REVIEW`, or `CLOSED` answers `ERR_INVALID_STATE_TRANSITION`." Nothing
    else is wrong: PRD §3.3 adds "if it would, the post is refused with
    `ERR_RESERVE_CAP_EXCEEDED` and nothing is written", and 2910000 is comfortably
    inside the 10000000-cent cap.

    Design: Difficulty/cross_entity_state_dependency/accrual_post_blocked_until_its_accrual_period_is_analysis_locked
    """
    world = _build_world(api)
    assert read_period(api, world["period"]["id"])["status"] == "OPEN"

    response = api.post_accrual(CONTROLLER_HEADERS, world["accrual"]["id"])
    validate_error(response, ERR_INVALID_STATE_TRANSITION, expected_status=409)

    assert read_accrual(api, world["accrual"]["id"])["status"] == "PROPOSED"
    assert read_family(api, world["family"]["id"])["warranty_reserve_balance_cents"] == 0


def test_locking_the_period_unlocks_the_identical_post(api):
    """Moving a different row lets the unchanged request through.

    PRD §3.1: "Locking analysis moves it from `OPEN` to `ANALYSIS_LOCKED`". PRD §3.3 then
    admits the post and describes its effect: "A successful post records the
    controller's identifier as `posted_by_user_id` ... That balance is then recomputed
    in full as described in §2.10, and immediately afterwards the family's
    `reserve_posture` is re-derived from the new balance." At 2910 basis points of the
    cap PRD §2.10 leaves the posture at `NORMAL`.

    Design: Difficulty/cross_entity_state_dependency/accrual_post_blocked_until_its_accrual_period_is_analysis_locked
    """
    world = _build_world(api)

    locked = lock_period(api, world["period"]["id"])
    assert locked["status"] == "ANALYSIS_LOCKED"

    posted = post_accrual(api, world["accrual"]["id"])
    assert posted["status"] == "POSTED"
    assert posted["posted_by_user_id"] == RESERVE_CONTROLLER_USER_ID

    family = read_family(api, world["family"]["id"])
    assert family["warranty_reserve_balance_cents"] == 2910000
    assert family["reserve_posture"] == "NORMAL"
