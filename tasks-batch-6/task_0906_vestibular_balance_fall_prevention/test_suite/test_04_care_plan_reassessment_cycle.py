"""CarePlan cyclic reassessment: ACTIVE -> UNDER_REASSESSMENT -> ACTIVE with an
updated tier and recomputed visit target."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    setup_active_care_plan, setup_plan_under_reassessment,
)

INTAKE = TEST_USERS["intake_headers"]


def test_open_reassessment_moves_plan_under_reassessment(api):
    """PRD §3.9: "Opening a reassessment creates it in `DRAFT`, moves the plan from
    `ACTIVE` to `UNDER_REASSESSMENT`, and increments the plan's `version` by one."

    Design: Difficulty/non_linear_state_machine/care_plan_active_reassessment_cycle
    """
    ctx = setup_active_care_plan(api)
    before_version = ctx["care_plan"]["version"]
    re = get_success_data(
        api.create_reassessment(
            ctx["care_plan"]["id"],
            {"clinician_id": ctx["clinician"]["id"], "gait_speed_m_s": 1.20,
             "tug_seconds": 8.0, "berg_balance_score": 55, "medication_count": 0,
             "self_report_fall_count": 0},
            ctx["clinician_headers"],
        )
    )
    assert re["status"] == "DRAFT"
    plan = get_success_data(api.get_care_plan(ctx["care_plan"]["id"], INTAKE))
    assert plan["status"] == "UNDER_REASSESSMENT"
    assert plan["version"] == before_version + 1


def test_finalize_reassessment_returns_plan_active_with_new_tier(api):
    """PRD §3.9: "the plan's fall_risk_tier is overwritten with the reassessment's
    new tier, the plan's target_visits is recomputed from that new tier (twelve
    for HIGH, eight for MODERATE, four for LOW), and the plan returns from
    UNDER_REASSESSMENT to ACTIVE."

    Design: Difficulty/non_linear_state_machine/care_plan_active_reassessment_cycle
    """
    ctx = setup_plan_under_reassessment(api)  # low-risk re-measures by default
    re = validate_success(
        api.finalize_reassessment(ctx["reassessment"]["id"], ctx["clinician_headers"]), 200
    )
    assert re["status"] == "FINALIZED"
    assert re["clinical_score"] == 0
    plan = get_success_data(api.get_care_plan(ctx["care_plan"]["id"], INTAKE))
    assert plan["status"] == "ACTIVE"
    assert plan["fall_risk_tier"] == "LOW"
    assert plan["target_visits"] == 4
