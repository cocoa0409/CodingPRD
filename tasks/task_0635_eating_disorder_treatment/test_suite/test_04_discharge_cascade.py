"""Discharge and its multi-hop cascade: meal-plan close -> risk reconcile ->
posture recompute, bed/cohort release and conservation, and waitlist promotion.
"""
from test_helpers import (
    validate_success,
    CLINICIAN,
    INTAKE,
    fixtures as fx,
)


def test_discharge_cascade_depth3_mealplan_risk_posture(api):
    """PRD §3.9: "Any `ACTIVE` meal plan associated with the admission moves to
    `CLOSED` (cascade hop 1), that meal-plan close reconciles the patient's
    `nutritional_risk_score` from the compliance rate exactly as in §3.6 (hop 2),
    and the patient's `medical_stability_posture` is recomputed from the
    reconciled score (hop 3)."

    Design: Difficulty/transitive_cascade/discharge_cascade_depth3_mealplan_risk_posture
    """
    # provisional 44 (composite 37 from 5,5,4,6 + bmi 17 bonus 7);
    # rate 0.95 -> credit round(40*0.95,2)=38 -> reconciled 44-38=6.0 -> STABLE.
    ctx = fx.setup_discharge_pending(
        bed_capacity=5, meal_fractions=(1.0, 1.0, 0.9, 0.9), with_meal_plan=True
    )
    aid = ctx["admission"]["id"]
    mp_id = ctx["meal_plan"]["id"]
    pid = ctx["patient"]["id"]
    discharged = validate_success(api.discharge_admission(aid, CLINICIAN))
    assert discharged["clinical_status"] == "DISCHARGED", (
        f"expected DISCHARGED, got {discharged['clinical_status']}"
    )
    mp = validate_success(api.get_meal_plan(mp_id, CLINICIAN))
    assert mp["status"] == "CLOSED", f"expected CLOSED meal plan, got {mp['status']}"
    patient = validate_success(api.get_patient(pid, INTAKE))
    assert patient["nutritional_risk_score"] == 6.0, (
        f"expected 6.0, got {patient['nutritional_risk_score']}"
    )
    assert patient["medical_stability_posture"] == "STABLE", (
        f"expected STABLE, got {patient['medical_stability_posture']}"
    )


def test_discharge_closes_active_meal_plan(api):
    """PRD §3.9: "Any `ACTIVE` meal plan associated with the admission moves to
    `CLOSED` (cascade hop 1)".

    Design: Difficulty/transitive_cascade/discharge_cascade_depth3_mealplan_risk_posture
    """
    ctx = fx.setup_discharge_pending(
        meal_fractions=(1.0, 1.0, 0.9, 0.9), with_meal_plan=True
    )
    validate_success(api.discharge_admission(ctx["admission"]["id"], CLINICIAN))
    mp = validate_success(api.get_meal_plan(ctx["meal_plan"]["id"], CLINICIAN))
    assert mp["status"] == "CLOSED", f"expected CLOSED, got {mp['status']}"


def test_bed_conservation_admit_then_discharge(api):
    """PRD §2.8: "From these two it derives `beds_available` as the bed capacity
    minus the occupied count, floored at zero so it never goes negative."
    PRD §3.9: "The program's `beds_occupied` decrements by one and its
    `beds_available` and `occupancy_posture` recompute".

    Design: Difficulty/compensating_invariant/bed_conservation_admit_then_discharge
    """
    ctx = fx.setup_discharge_pending(bed_capacity=5, with_meal_plan=False)
    pgid = ctx["program"]["id"]
    # Before discharge: 1 occupied / 4 available, invariant sums to 5.
    before = validate_success(api.get_program(pgid, INTAKE))
    assert before["beds_occupied"] + before["beds_available"] == 5
    validate_success(api.discharge_admission(ctx["admission"]["id"], CLINICIAN))
    after = validate_success(api.get_program(pgid, INTAKE))
    assert after["beds_occupied"] == 0, (
        f"expected 0 occupied, got {after['beds_occupied']}"
    )
    assert after["beds_available"] == 5, (
        f"expected 5 available, got {after['beds_available']}"
    )
    assert after["occupancy_posture"] == "OPEN", (
        f"expected OPEN, got {after['occupancy_posture']}"
    )
    assert after["beds_occupied"] + after["beds_available"] == 5, (
        "bed pool invariant beds_occupied + beds_available == bed_capacity drifted"
    )


def test_waitlist_promotion_on_discharge_from_full_program(api):
    """PRD §3.9: "if and only if the program's occupancy posture flips from `FULL`
    to `OPEN` as a result of releasing the bed, the platform promotes the
    earliest-created (by `created_at` ascending) `WAITLISTED` admission in that
    same program to `PENDING_ADMISSION` and sets that admission's
    `waitlist_promoted` flag true."

    Design: Corner/cross_cutting_complexity_layers/waitlist_promotion_cascade_on_discharge_from_full_program
    """
    # Capacity-1 program: admission X admitted (FULL), admission Y WAITLISTED.
    ctx = fx.setup_admitted_admission(bed_capacity=1)
    facility = ctx["facility"]
    program = ctx["program"]
    cohort = ctx["cohort"]
    aidx = ctx["admission"]["id"]
    patient_y = fx.create_patient(facility["id"], full_name="Pat Y")
    admission_y = fx.create_admission(
        patient_y["id"], facility["id"], program["id"], cohort["id"]
    )
    # Carry X to DISCHARGE_PENDING (waive family + finalize discharge plan).
    fx.create_waived_family_program(aidx, facility["id"])
    fx.create_finalized_discharge_plan(aidx, facility["id"])
    validate_success(api.begin_discharge_admission(aidx, CLINICIAN))
    discharged = validate_success(api.discharge_admission(aidx, CLINICIAN))
    assert discharged["clinical_status"] == "DISCHARGED"
    program_after = validate_success(api.get_program(program["id"], INTAKE))
    assert program_after["occupancy_posture"] == "OPEN", (
        f"expected OPEN after release, got {program_after['occupancy_posture']}"
    )
    promoted = validate_success(api.get_admission(admission_y["id"], INTAKE))
    assert promoted["clinical_status"] == "PENDING_ADMISSION", (
        f"expected PENDING_ADMISSION, got {promoted['clinical_status']}"
    )
    assert promoted["waitlist_promoted"] is True, (
        f"expected waitlist_promoted True, got {promoted['waitlist_promoted']}"
    )
