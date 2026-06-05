"""Beneficiary posture state machine and the death voiding cascade.

Covers the FRAUD_HOLD cycle vs DECEASED terminal branch, the depth-2
death -> Part B VOIDED -> part_b_status NONE chain, the multi-entity death
cascade, and the activate-then-drop compensating invariant.
"""
from test_helpers import (
    validate_success, set_clock, create_beneficiary,
    setup_beneficiary_with_active_part_b, setup_confirmed_part_c, create_plan,
    create_period, read_beneficiary_version,
    create_part_d_enrollment_payload, TEST_USERS,
)

ADMIN = TEST_USERS["enrollment_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_beneficiary_fraud_hold_cycle_then_deceased_terminal(api):
    """PRD §3.1: "From ACTIVE, a ComplianceOfficer may place a fraud hold, moving status
    to FRAUD_HOLD; this requires the beneficiary to currently be ACTIVE"
    PRD §3.1: "The same officer may later clear the hold, moving FRAUD_HOLD back to
    ACTIVE (requiring the beneficiary to currently be in FRAUD_HOLD, else
    ERR_INVALID_STATE); clearing sets enrollment_lock back to false and increments
    version."
    PRD §3.2: "The transition moves status to DECEASED, which is terminal"

    Design: Difficulty/non_linear_state_machine/beneficiary_branching_fraud_hold_cycle_vs_deceased_terminal
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="Alan T")

    held = validate_success(api.fraud_hold(ben["id"], COMPLIANCE), 200)
    assert held["status"] == "FRAUD_HOLD"
    assert held["enrollment_lock"] is True

    cleared = validate_success(api.clear_hold(ben["id"], COMPLIANCE), 200)
    assert cleared["status"] == "ACTIVE"
    assert cleared["enrollment_lock"] is False

    dead = validate_success(api.record_death(ben["id"], ADMIN), 200)
    assert dead["status"] == "DECEASED"


def test_record_death_voids_part_b_and_resets_part_b_status(api):
    """PRD §3.2: "Every PartBEnrollment of this beneficiary currently in FILED or
    ACTIVE transitions to VOIDED. When a PartBEnrollment that was ACTIVE is voided this
    way, the beneficiary's part_b_status is reset to NONE."
    PRD §3.2: "The transition moves status to DECEASED, which is terminal"

    Design: Difficulty/transitive_cascade/record_death_voids_partb_which_resets_part_b_status_depth2
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben, _iep, pbe = setup_beneficiary_with_active_part_b()
    dead = validate_success(api.record_death(ben["id"], ADMIN), 200)
    assert dead["part_b_status"] == "NONE"
    assert dead["status"] == "DECEASED"

    pbe_after = validate_success(api.get_part_b_enrollment(pbe["id"], ADMIN), 200)
    assert pbe_after["status"] == "VOIDED"


def test_death_cascade_voids_active_part_c_and_part_d(api):
    """PRD §3.2: "Every PartCEnrollment of this beneficiary currently in PENDING or
    ACTIVE transitions to VOIDED, each incrementing its own version."
    PRD §3.2: "Every PartDEnrollment of this beneficiary currently in PENDING or ACTIVE
    transitions to VOIDED, each incrementing its own version."

    Design: Corner/cross_cutting_complexity_layers/death_cascade_voids_active_partc_and_partd
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben, iep, _ma, pce = setup_confirmed_part_c(
        plan_overrides={"name": "MA Only", "monthly_premium_cents": 0, "star_rating": 4.0})
    pdp = create_plan(name="PDP Cas", part_type="PART_D", monthly_premium_cents=2000,
                      star_rating=3.0, includes_drug_coverage=True)
    pde = validate_success(api.create_part_d_enrollment(
        create_part_d_enrollment_payload(ben["id"], pdp["id"], iep["id"]), ADMIN), 201)
    pde = validate_success(api.confirm_part_d_enrollment(pde["id"], ADMIN), 200)

    dead = validate_success(api.record_death(ben["id"], ADMIN), 200)
    assert dead["status"] == "DECEASED"
    assert validate_success(api.get_part_c_enrollment(pce["id"], ADMIN), 200)["status"] == "VOIDED"
    assert validate_success(api.get_part_d_enrollment(pde["id"], ADMIN), 200)["status"] == "VOIDED"


def test_part_b_activate_then_drop_restores_part_b_status(api):
    """PRD §3.5: "On success, activation sets the beneficiary's part_b_status to
    ENROLLED, copies the enrollment's effective_date onto the beneficiary's
    part_b_effective_date"
    PRD §3.5: "it moves the enrollment from ACTIVE to DROPPED, resets the beneficiary's
    part_b_status to NONE, and increments the PartBEnrollment.version."

    Design: Difficulty/compensating_invariant/partb_activate_then_drop_restores_part_b_coverage_count
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben, _iep, pbe = setup_beneficiary_with_active_part_b()
    after_activate = validate_success(api.get_beneficiary(ben["id"], ADMIN), 200)
    assert after_activate["part_b_status"] == "ENROLLED"

    dropped = validate_success(api.drop_part_b_enrollment(pbe["id"], ADMIN), 200)
    assert dropped["status"] == "DROPPED"
    after_drop = validate_success(api.get_beneficiary(ben["id"], ADMIN), 200)
    assert after_drop["part_b_status"] == "NONE"


def test_penalty_assess_then_waive_zeroes_penalty(api):
    """PRD §3.10: "The assessment is created with status ASSESSED and a computed
    monthly_penalty_cents."
    PRD §3.10: "A ComplianceOfficer may waive an ASSESSED penalty, which requires the
    assessment to currently be ASSESSED, moves status to WAIVED, sets
    monthly_penalty_cents to 0, and increments the version."

    Design: Difficulty/compensating_invariant/penalty_assess_then_waive_zeroes_total_penalty_burden
    """
    from test_helpers import create_penalty_assessment_payload
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="Vint C")
    pa = validate_success(api.create_penalty_assessment(
        create_penalty_assessment_payload(ben["id"], "PART_B", 12), COMPLIANCE), 201)
    assert pa["monthly_penalty_cents"] == 1747

    waived = validate_success(api.waive_penalty_assessment(pa["id"], COMPLIANCE), 200)
    assert waived["monthly_penalty_cents"] == 0
    assert waived["status"] == "WAIVED"
