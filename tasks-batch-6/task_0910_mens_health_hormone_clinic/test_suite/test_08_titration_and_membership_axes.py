"""Cyclic titration loop and Membership's two independent state axes."""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    create_patient, create_membership_plan, create_membership,
    setup_active_plan, make_plan_titration_pending, get_plan,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def test_titration_cycle_returns_plan_to_active_with_new_dose(api):
    """PRD §3.5: "Confirming a pending titration moves the plan from `TITRATION_PENDING`
    back to `ACTIVE`".
    PRD §3.5: "On confirmation the titration's `status` becomes `CONFIRMED` and its
    `applied` flag becomes true, the plan's `current_dose_mg` is set to the titration's
    `proposed_dose_mg`, the plan's `round_index` is set to the titration's
    `round_index`, and the plan's `version` is incremented by one."

    Design: Difficulty/non_linear_state_machine/treatment_plan_titration_cycle
    """
    ctx = setup_active_plan(starting_dose_mg=100)
    make_plan_titration_pending(ctx, proposed_dose_mg=120)
    get_success_data(api.confirm_titration(ctx["plan_id"], ctx["titration_id"], ctx["clinician_headers"]))
    plan = get_plan(ctx["plan_id"])
    assert plan["status"] == "ACTIVE"
    assert plan["current_dose_mg"] == 120
    assert plan["round_index"] == 1


def test_titration_confirm_marks_titration_confirmed_and_applied(api):
    """PRD §3.5: "On confirmation the titration's `status` becomes `CONFIRMED` and its
    `applied` flag becomes true".

    Design: Difficulty/non_linear_state_machine/treatment_plan_titration_cycle
    """
    ctx = setup_active_plan(starting_dose_mg=100)
    make_plan_titration_pending(ctx, proposed_dose_mg=120)
    titration = validate_success(
        api.confirm_titration(ctx["plan_id"], ctx["titration_id"], ctx["clinician_headers"]), 200
    )
    assert titration["status"] == "CONFIRMED"
    assert titration["applied"] is True


def _active_membership():
    patient = create_patient()
    plan = create_membership_plan(tier="CORE")
    return create_membership(patient["id"], plan["id"], activate=True)


def test_failed_payment_delinquents_without_touching_subscription(api):
    """PRD §3.2: "an `outcome` of `FAILED` moves a `CURRENT` membership to `DELINQUENT`".
    PRD §3.2: "The two axes never interact: a membership may be `ACTIVE` and
    `DELINQUENT` at once."

    Design: Difficulty/non_linear_state_machine/membership_parallel_dimensions_independent
    """
    membership = _active_membership()
    data = validate_success(api.record_payment(membership["id"], {"outcome": "FAILED"}, ADMIN), 200)
    assert data["subscription_status"] == "ACTIVE"
    assert data["payment_status"] == "DELINQUENT"


def test_succeeded_payment_returns_current_subscription_unchanged(api):
    """PRD §3.2: "while an `outcome` of `SUCCEEDED` moves a `DELINQUENT` membership back
    to `CURRENT`".
    PRD §3.2: "The two axes never interact: a membership may be `ACTIVE` and
    `DELINQUENT` at once."

    Design: Difficulty/non_linear_state_machine/membership_parallel_dimensions_independent
    """
    membership = _active_membership()
    get_success_data(api.record_payment(membership["id"], {"outcome": "FAILED"}, ADMIN))
    data = validate_success(api.record_payment(membership["id"], {"outcome": "SUCCEEDED"}, ADMIN), 200)
    assert data["payment_status"] == "CURRENT"
    assert data["subscription_status"] == "ACTIVE"
