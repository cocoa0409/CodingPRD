"""Nutritional-risk reconciliation (provisional vs reconciled), meal-compliance
rate aggregation, and the refused-event rule.
"""
from test_helpers import (
    validate_success,
    DIETITIAN,
    INTAKE,
    fixtures as fx,
)


def test_nutritional_risk_provisional_vs_reconciled_diverge(api):
    """PRD §3.3: "The provisional figure is then frozen: it is computed once and
    is never touched by meal events or holds for the rest of the stay."
    PRD §3.6: "the credit subtracted is 40 multiplied by the plan's
    meal-compliance rate, rounded half-up to two decimal places. The running
    `nutritional_risk_score` becomes its prior value minus that credit, clamped to
    lie within 0 and 100".

    Design: Difficulty/dual_variant_calc/nutritional_risk_provisional_vs_reconciled
    """
    # provisional 44 (composite 37 + bmi 17 bonus 7); meal rate 0.95 ->
    # credit round(40*0.95,2)=38 -> reconciled 44-38=6.0.
    ctx = fx.setup_admitted_admission()
    mp = fx.create_meal_plan_with_events(
        ctx["admission"]["id"], ctx["facility"]["id"], [1.0, 1.0, 0.9, 0.9]
    )
    assert mp["meal_compliance_rate"] == 0.95, (
        f"precondition meal rate 0.95, got {mp['meal_compliance_rate']}"
    )
    validate_success(api.close_meal_plan(mp["id"], DIETITIAN))
    patient = validate_success(api.get_patient(ctx["patient"]["id"], INTAKE))
    assert patient["provisional_nutritional_risk_score"] == 44.0, (
        f"provisional must stay frozen at 44.0, got "
        f"{patient['provisional_nutritional_risk_score']}"
    )
    assert patient["nutritional_risk_score"] == 6.0, (
        f"expected reconciled 6.0, got {patient['nutritional_risk_score']}"
    )
    assert patient["medical_stability_posture"] == "STABLE", (
        f"expected STABLE, got {patient['medical_stability_posture']}"
    )


def test_meal_plan_close_reconciles_to_stable_posture(api):
    """PRD §3.6: "after which the `medical_stability_posture` is recomputed from
    the new score."

    Design: Difficulty/dual_variant_calc/nutritional_risk_provisional_vs_reconciled
    """
    ctx = fx.setup_admitted_admission()
    mp = fx.create_meal_plan_with_events(
        ctx["admission"]["id"], ctx["facility"]["id"], [1.0, 1.0, 0.9, 0.9]
    )
    validate_success(api.close_meal_plan(mp["id"], DIETITIAN))
    patient = validate_success(api.get_patient(ctx["patient"]["id"], INTAKE))
    assert patient["medical_stability_posture"] == "STABLE"


def test_meal_event_refused_forces_zero_completion(api):
    """PRD §3.6: "Each event's **effective fraction** is 0.0 when the event is
    `refused`, and otherwise is the `completion_fraction` clamped into the
    0.0-to-1.0 range."
    PRD §3.6: "The plan's `meal_compliance_rate` is then recomputed as the
    accumulated completion points divided by the number of events logged, rounded
    half-up to four decimal places".

    Design: Corner/entities/meal_event_refused_forces_zero_completion
    """
    ctx = fx.setup_admitted_admission()
    mp = fx.create_meal_plan(ctx["admission"]["id"], ctx["facility"]["id"])
    # One full event (1.0) then one refused event with completion_fraction 1.0.
    validate_success(
        api.create_meal_event(
            {"meal_plan_id": mp["id"], "admission_id": ctx["admission"]["id"],
             "meal_type": "BREAKFAST", "completion_fraction": 1.0},
            DIETITIAN,
        ),
        expected_status=201,
    )
    validate_success(
        api.create_meal_event(
            {"meal_plan_id": mp["id"], "admission_id": ctx["admission"]["id"],
             "meal_type": "LUNCH", "completion_fraction": 1.0, "refused": True},
            DIETITIAN,
        ),
        expected_status=201,
    )
    data = validate_success(api.get_meal_plan(mp["id"], DIETITIAN))
    assert data["meals_logged"] == 2, f"expected 2, got {data['meals_logged']}"
    assert data["completion_points"] == 1.0, (
        f"expected 1.0, got {data['completion_points']}"
    )
    assert data["meal_compliance_rate"] == 0.5, (
        f"expected 0.5, got {data['meal_compliance_rate']}"
    )
