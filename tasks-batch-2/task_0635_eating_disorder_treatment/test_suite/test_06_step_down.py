"""Level-of-care step-down: the combinatorial readiness formula, the separate
meal-compliance and readiness gates, the ACTIVE-treatment-plan dependency, and
the already-lowest-rung guard. The level-of-care dimension is orthogonal to the
clinical status.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    CLINICIAN,
    INTAKE,
    fixtures as fx,
)


def test_step_down_readiness_clears_threshold_advances_loc(api):
    """PRD §3.8: "The readiness is 100 multiplied by the sum of 0.45 times the
    goal ratio, plus 0.35 times the meal factor, plus 0.20 times the stability
    factor; that result is rounded half-up to two decimal places and then
    constrained to lie within 0 and 100. Step-down is permitted only when this
    readiness is at least 75."

    Design: Difficulty/combinatorial_formula/step_down_readiness_nonlinear_three_inputs
    """
    # goals 5/5, meal rate 0.85, STABLE -> 100*(0.45*1 + 0.35*0.85 + 0.20*1.0)
    # = 94.75 >= 75. (patient at provisional 44 -> STABLE.)
    ctx = fx.setup_step_down_ready(
        level_of_care="RESIDENTIAL", goals_total=5, goals_met=5,
        meal_fractions=(0.9, 0.9, 0.8, 0.8),
    )
    assert ctx["patient"]["medical_stability_posture"] == "STABLE", (
        f"precondition STABLE, got {ctx['patient']['medical_stability_posture']}"
    )
    assert ctx["meal_plan"]["meal_compliance_rate"] == 0.85, (
        f"precondition meal rate 0.85, got {ctx['meal_plan']['meal_compliance_rate']}"
    )
    stepped = validate_success(api.step_down_admission(ctx["admission"]["id"], CLINICIAN))
    assert stepped["level_of_care"] == "PHP", (
        f"expected PHP, got {stepped['level_of_care']}"
    )
    assert stepped["clinical_status"] == "ADMITTED", (
        f"clinical_status must stay ADMITTED, got {stepped['clinical_status']}"
    )


def test_step_down_keeps_clinical_status_admitted(api):
    """PRD §3.8: "The admission's clinical status stays `ADMITTED` throughout —
    step-down only changes the level-of-care dimension."

    Design: Difficulty/combinatorial_formula/step_down_readiness_nonlinear_three_inputs
    """
    ctx = fx.setup_step_down_ready(
        level_of_care="RESIDENTIAL", goals_total=5, goals_met=5,
        meal_fractions=(0.9, 0.9, 0.8, 0.8),
    )
    stepped = validate_success(api.step_down_admission(ctx["admission"]["id"], CLINICIAN))
    assert stepped["clinical_status"] == "ADMITTED"


def test_step_down_readiness_below_threshold_rejected(api):
    """PRD §3.8: "the computed step-down readiness must be at least 75, else
    `ERR_STEP_DOWN_NOT_READY`."

    Design: Corner/calculations/step_down_readiness_below_threshold_rejected
    """
    # goals 2/5, meal rate 0.80 over 3 events, GUARDED ->
    # 100*(0.45*0.4 + 0.35*0.8 + 0.20*0.6) = 58.0 < 75.
    # patient (6,6,5,5) composite: 0.40*60+0.30*60+0.20*50-0.10*50 = 47;
    # bmi 17 -> +7 -> provisional 54 -> GUARDED.
    ctx = fx.setup_step_down_ready(
        level_of_care="RESIDENTIAL", goals_total=5, goals_met=2,
        meal_fractions=(0.8, 0.8, 0.8), med=6, beh=6, psy=5, mot=5,
    )
    assert ctx["patient"]["medical_stability_posture"] == "GUARDED", (
        f"precondition GUARDED, got {ctx['patient']['medical_stability_posture']}"
    )
    assert ctx["meal_plan"]["meal_compliance_rate"] == 0.8, (
        f"precondition meal rate 0.8, got {ctx['meal_plan']['meal_compliance_rate']}"
    )
    resp = api.step_down_admission(ctx["admission"]["id"], CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_STEP_DOWN_NOT_READY.value)


def test_step_down_empty_meal_plan_blocks_on_compliance(api):
    """PRD §3.8: "the admission's meal plan must show a `meal_compliance_rate` of
    at least 0.80 with at least 3 meals logged, else
    `ERR_INSUFFICIENT_MEAL_COMPLIANCE`".

    Design: Difficulty/boundary_precision_check/meal_compliance_floor_empty_set_blocks_step_down
    """
    ctx = fx.setup_admitted_admission(level_of_care="RESIDENTIAL")
    fx.create_active_treatment_plan(
        ctx["admission"]["id"], ctx["facility"]["id"], goals_total=5
    )
    # Meal plan with ZERO events: meals_logged 0, rate 0 -> fails the floor.
    mp = fx.create_meal_plan(ctx["admission"]["id"], ctx["facility"]["id"])
    mp_read = validate_success(api.get_meal_plan(mp["id"], CLINICIAN))
    assert mp_read["meals_logged"] == 0
    assert mp_read["meal_compliance_rate"] == 0
    resp = api.step_down_admission(ctx["admission"]["id"], CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MEAL_COMPLIANCE.value)


def test_step_down_without_active_treatment_plan_rejected(api):
    """PRD §3.8: "a treatment plan for this admission must exist in `ACTIVE`
    status, else `ERR_TREATMENT_PLAN_NOT_ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/step_down_blocked_without_active_treatment_plan
    """
    ctx = fx.setup_admitted_admission(level_of_care="RESIDENTIAL")
    # DRAFT treatment plan (never activated).
    tp = validate_success(
        api.create_treatment_plan(
            {"admission_id": ctx["admission"]["id"],
             "facility_id": ctx["facility"]["id"], "goals_total": 5},
            CLINICIAN,
        ),
        expected_status=201,
    )
    # Meal plan at 0.85 over 4 events would otherwise pass compliance.
    fx.create_meal_plan_with_events(
        ctx["admission"]["id"], ctx["facility"]["id"], [0.9, 0.9, 0.8, 0.8]
    )
    resp = api.step_down_admission(ctx["admission"]["id"], CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_TREATMENT_PLAN_NOT_ACTIVE.value)
    data = validate_success(api.get_treatment_plan(tp["id"], CLINICIAN))
    assert data["status"] == "DRAFT"


def test_step_down_empty_meal_plan_meals_logged_zero(api):
    """PRD §3.6: "with no events the rate is zero."
    PRD §3.8: "the admission's meal plan must show a `meal_compliance_rate` of at
    least 0.80 with at least 3 meals logged, else
    `ERR_INSUFFICIENT_MEAL_COMPLIANCE`".

    Design: Difficulty/boundary_precision_check/meal_compliance_floor_empty_set_blocks_step_down
    """
    ctx = fx.setup_admitted_admission(level_of_care="RESIDENTIAL")
    fx.create_active_treatment_plan(
        ctx["admission"]["id"], ctx["facility"]["id"], goals_total=5
    )
    mp = fx.create_meal_plan(ctx["admission"]["id"], ctx["facility"]["id"])
    read = validate_success(api.get_meal_plan(mp["id"], CLINICIAN))
    assert read["meals_logged"] == 0, f"expected 0 logged, got {read['meals_logged']}"
    assert read["meal_compliance_rate"] == 0, (
        f"expected rate 0, got {read['meal_compliance_rate']}"
    )
    resp = api.step_down_admission(ctx["admission"]["id"], CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MEAL_COMPLIANCE.value)


def test_step_down_draft_plan_keeps_loc_residential(api):
    """PRD §3.8: "a treatment plan for this admission must exist in `ACTIVE`
    status, else `ERR_TREATMENT_PLAN_NOT_ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/step_down_blocked_without_active_treatment_plan
    """
    ctx = fx.setup_admitted_admission(level_of_care="RESIDENTIAL")
    validate_success(
        api.create_treatment_plan(
            {"admission_id": ctx["admission"]["id"],
             "facility_id": ctx["facility"]["id"], "goals_total": 5},
            CLINICIAN,
        ),
        expected_status=201,
    )
    fx.create_meal_plan_with_events(
        ctx["admission"]["id"], ctx["facility"]["id"], [0.9, 0.9, 0.8, 0.8]
    )
    resp = api.step_down_admission(ctx["admission"]["id"], CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_TREATMENT_PLAN_NOT_ACTIVE.value)
    # The level-of-care dimension is unchanged by the rejected step-down.
    admission = validate_success(api.get_admission(ctx["admission"]["id"], CLINICIAN))
    assert admission["level_of_care"] == "RESIDENTIAL", (
        f"level_of_care must stay RESIDENTIAL, got {admission['level_of_care']}"
    )


def test_step_down_from_op_already_lowest(api):
    """PRD §3.8: "the current level of care must not already be `OP`, because a
    lower rung must exist, else `ERR_ALREADY_LOWEST_LOC`".

    Design: Corner/state_machines/step_down_from_op_returns_already_lowest_loc
    """
    # Admit into an OP program (level_of_care OP), STABLE, ACTIVE plan, meals ok.
    # patient (3,3,2,8) composite: 0.40*30+0.30*30+0.20*20-0.10*80 = 17; bmi 19 -> +0
    # -> provisional 17 -> STABLE.
    ctx = fx.setup_step_down_ready(
        level_of_care="OP", goals_total=2, goals_met=2,
        meal_fractions=(0.9, 0.9, 0.9), med=3, beh=3, psy=2, mot=8, bmi=19.0,
    )
    assert ctx["admission"]["level_of_care"] == "OP", (
        f"precondition OP, got {ctx['admission']['level_of_care']}"
    )
    resp = api.step_down_admission(ctx["admission"]["id"], CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_ALREADY_LOWEST_LOC.value)
