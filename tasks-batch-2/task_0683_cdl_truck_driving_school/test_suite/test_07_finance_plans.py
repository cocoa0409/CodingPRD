"""Tuition finance plans: the tiered down-payment and floor-installment schedule, the
optimistic-concurrency guard on creation, supersession, and withdrawal cancellation.

Translates queue A (combinatorial_formula/finance_schedule_floor_installment_remainder_to_final)
and queue B (calculations, cross_cutting_complexity_layers) instances.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_program, create_enrollment,
    setup_enrollment_for_finance, create_finance_plan,
)

ADMIN = TEST_USERS["school_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# ---- Queue A: combinatorial_formula / finance_schedule_floor_installment_remainder_to_final ----

def test_finance_schedule_floor_installment_remainder_to_final():
    """PRD §3.7: "The installment_cents ... is the total repayment amount divided by
    term_months, taking the floor (rounding down to a whole number of cents). The
    final_installment_cents is then the total repayment amount minus installment_cents
    multiplied by term_months minus one, so that the last installment absorbs the entire
    leftover-cents remainder."

    Design: Difficulty/combinatorial_formula/finance_schedule_floor_installment_remainder_to_final
    """
    ctx = setup_enrollment_for_finance(tuition_cents=700000)
    enr = ctx["enrollment"]
    # tuition 700000 >= 600000 -> 20% down = 140000; financed 560000;
    # interest = 560000 * 0.01 * 6 = 33600; total_repay = 593600;
    # installment = floor(593600 / 6) = 98933; final = 593600 - 98933*5 = 98935.
    plan = create_finance_plan(enr["id"], 6, enr["version"])
    assert plan["down_payment_cents"] == 140000
    assert plan["financed_cents"] == 560000
    assert plan["total_interest_cents"] == 33600
    assert plan["installment_cents"] == 98933
    assert plan["final_installment_cents"] == 98935


def test_finance_schedule_high_tier_down_payment_twenty_percent():
    """PRD §3.7: "when the snapshotted tuition is at least 600000 cents (that is, six
    thousand dollars), the down payment is twenty percent of tuition; otherwise it is ten
    percent. The down_payment_cents is that percentage of the snapshotted tuition, rounded
    half-up. The financed_cents is the snapshotted tuition minus the down payment."

    Design: Difficulty/combinatorial_formula/finance_schedule_floor_installment_remainder_to_final
    """
    ctx = setup_enrollment_for_finance(tuition_cents=700000)
    enr = ctx["enrollment"]
    plan = create_finance_plan(enr["id"], 6, enr["version"])
    assert plan["down_payment_cents"] == 140000  # 20% of 700000
    assert plan["financed_cents"] == 560000


# ---- Queue B: calculations / finance_schedule_default_down_payment_tier ----

def test_finance_schedule_low_tier_down_payment_ten_percent():
    """PRD §3.7: "when the snapshotted tuition is at least 600000 cents ... the down
    payment is twenty percent of tuition; otherwise it is ten percent." PRD §3.7:
    "Interest is simple interest accrued at one percent of the financed principal per
    month: the total_interest_cents is the financed amount multiplied by one percent and
    by the number of term_months, rounded half-up."

    Design: Corner/calculations/finance_schedule_default_down_payment_tier
    """
    ctx = setup_enrollment_for_finance(tuition_cents=550000)  # < 600000 -> 10% tier
    enr = ctx["enrollment"]
    plan = create_finance_plan(enr["id"], 6, enr["version"])
    assert plan["down_payment_cents"] == 55000     # 10% of 550000
    assert plan["financed_cents"] == 495000        # 550000 - 55000
    assert plan["total_interest_cents"] == 29700   # round_half_up(495000 * 0.01 * 6)
    assert plan["installment_cents"] == 87450      # floor((495000 + 29700) / 6)


# ---- Queue B: cross_cutting_complexity_layers / finance_plan_stale_version_returns_412 ----

def test_finance_plan_stale_version_returns_412():
    """PRD §2.9: "If expected_enrollment_version does not equal the enrollment's current
    version at the time the create is processed, the request is rejected with
    ERR_STALE_VERSION and HTTP status 412." PRD §3.7: "Creating a plan increments the
    enrollment's version by one".

    Design: Corner/cross_cutting_complexity_layers/finance_plan_stale_version_returns_412
    """
    ctx = setup_enrollment_for_finance()
    enr = ctx["enrollment"]
    ev0 = enr["version"]
    # First create succeeds and bumps the enrollment version.
    create_finance_plan(enr["id"], 6, ev0)
    # Second create still carries the pre-bump version.
    resp = api_client.create_finance_plan(
        enr["id"], {"term_months": 12, "expected_enrollment_version": ev0}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_finance_plan_supersede_with_fresh_version_succeeds():
    """PRD §3.7: "any prior ACTIVE finance plan for the same enrollment is moved to
    SUPERSEDED, leaving exactly one active plan governing tuition." PRD §2.9: "If
    expected_enrollment_version does not equal the enrollment's current version at the
    time the create is processed, the request is rejected with ERR_STALE_VERSION".

    Design: Corner/cross_cutting_complexity_layers/finance_plan_supersede_with_fresh_version_succeeds
    """
    ctx = setup_enrollment_for_finance()
    enr = ctx["enrollment"]
    plan1 = create_finance_plan(enr["id"], 6, enr["version"])
    # Re-read the enrollment to pick up the bumped version.
    refreshed = validate_success(api_client.get_enrollment(enr["id"], REGISTRAR))
    plan2 = create_finance_plan(enr["id"], 12, refreshed["version"])
    assert plan2["status"] == "ACTIVE"
    superseded = validate_success(api_client.get_finance_plan(plan1["id"], REGISTRAR))
    assert superseded["status"] == "SUPERSEDED"


# ---- Queue B: cross_cutting_complexity_layers / withdraw_cancels_active_finance_plan_cascade ----

def test_withdraw_cancels_active_finance_plan_cascade():
    """PRD §3.9: "Any ACTIVE finance plan for the enrollment is moved to CANCELLED." PRD
    §3.7: "A finance plan is also moved to CANCELLED automatically when its owning
    enrollment is withdrawn."

    Design: Corner/cross_cutting_complexity_layers/withdraw_cancels_active_finance_plan_cascade
    """
    ctx = setup_enrollment_for_finance()
    enr = ctx["enrollment"]
    plan = create_finance_plan(enr["id"], 6, enr["version"])
    validate_success(api_client.withdraw_enrollment(enr["id"], REGISTRAR))
    final_enr = validate_success(api_client.get_enrollment(enr["id"], REGISTRAR))
    assert final_enr["status"] == "WITHDRAWN"
    final_plan = validate_success(api_client.get_finance_plan(plan["id"], REGISTRAR))
    assert final_plan["status"] == "CANCELLED"
