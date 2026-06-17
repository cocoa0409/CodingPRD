"""Enrollment and clearance claims: the two parallel clearance gates at
activation, the minimum-deposit gate, invalid clearance decisions, the
medical-EXPIRED cascade that suspends an active enrollment, and the
hours-not-met completion gate.
"""
from test_helpers import (
    validate_error,
    ADMIN,
    ApiErrorId,
    create_student, create_syllabus, create_enrollment,
    clear_medical, clear_tsa, get_enrollment, get_student, get_booking,
    setup_active_enrollment,
    setup_confirmed_booking,
)


def test_activate_blocked_when_tsa_still_pending(api):
    """PRD §3.2: "Activation requires both clearance axes to be satisfied:
    `medical_status` must be `CLEARED` or the request fails with
    `ERR_MEDICAL_NOT_CLEARED`, and `tsa_status` must be `CLEARED` or it fails with
    `ERR_TSA_NOT_CLEARED`."

    Design: Corner/state_machines/enrollment_activate_blocked_until_both_clearances
    """
    student = create_student(deposit_cents=60000)
    syllabus = create_syllabus(min_deposit_cents=50000)
    enrollment = create_enrollment(student["id"], syllabus["id"])
    clear_medical(enrollment["id"])  # medical CLEARED, TSA still PENDING
    validate_error(api.activate_enrollment(enrollment["id"], ADMIN), ApiErrorId.ERR_TSA_NOT_CLEARED.value)
    enr = get_enrollment(enrollment["id"])
    assert enr["status"] == "PENDING_CLEARANCE"
    assert enr["medical_status"] == "CLEARED"
    assert enr["tsa_status"] == "PENDING"


def test_activate_below_minimum_deposit_rejected(api):
    """PRD §3.2: "The student's spendable balance, `deposit_balance_cents`, must be
    at least the syllabus's `min_deposit_cents`, failing with
    `ERR_DEPOSIT_BELOW_MINIMUM` (HTTP 402) otherwise."

    Design: Corner/validations/activate_below_minimum_deposit_rejected
    """
    student = create_student(deposit_cents=30000)
    syllabus = create_syllabus(min_deposit_cents=50000)
    enrollment = create_enrollment(student["id"], syllabus["id"])
    clear_medical(enrollment["id"])
    clear_tsa(enrollment["id"])
    validate_error(api.activate_enrollment(enrollment["id"], ADMIN), ApiErrorId.ERR_DEPOSIT_BELOW_MINIMUM.value)
    assert get_enrollment(enrollment["id"])["status"] == "PENDING_CLEARANCE"


def test_invalid_clearance_decision_tsa_expired_rejected(api):
    """PRD §3.2: "A decision that does not fit its axis — for example a medical
    decision of `DENIED`, or a TSA decision of `EXPIRED` — is rejected with
    `ERR_INVALID_CLEARANCE_DECISION` (HTTP 400)."

    Design: Corner/validations/invalid_clearance_decision_rejected
    """
    student = create_student()
    syllabus = create_syllabus()
    enrollment = create_enrollment(student["id"], syllabus["id"])
    validate_error(
        api.record_clearance(enrollment["id"], {"clearance_type": "TSA", "decision": "EXPIRED"}, ADMIN),
        ApiErrorId.ERR_INVALID_CLEARANCE_DECISION.value,
    )


def test_medical_expired_cascades_active_enrollment_to_suspended(api):
    """PRD §3.2: "Recording a medical decision of `EXPIRED` on an enrollment that is
    currently `ACTIVE` cascades the enrollment from `ACTIVE` to `SUSPENDED`."
    PRD §2.6: "When an enrollment leaves `ACTIVE` for `SUSPENDED` or `WITHDRAWN`,
    its `REQUESTED` and `CONFIRMED` bookings are likewise cancelled (with hold
    release for the confirmed ones)."

    Design: Corner/state_machines/medical_expired_cascades_active_enrollment_to_suspended
    """
    ctx = setup_confirmed_booking(deposit_cents=100000, estimated_hours=2.0, lesson_type="DUAL",
                                  aircraft_overrides={"rental_rate_cents_per_hour": 15000})
    api.record_clearance(ctx["enrollment"]["id"], {"clearance_type": "MEDICAL", "decision": "EXPIRED"}, ADMIN)

    enr = get_enrollment(ctx["enrollment"]["id"])
    assert enr["medical_status"] == "EXPIRED"
    assert enr["status"] == "SUSPENDED"
    assert get_booking(ctx["booking"]["id"])["status"] == "CANCELLED"
    stu = get_student(ctx["student"]["id"])
    assert stu["deposit_held_cents"] == 0
    assert stu["deposit_balance_cents"] == 100000


def test_complete_blocked_when_hours_not_met(api):
    """PRD §3.2: "The accumulated `logged_dual_hours` must be at least the syllabus's
    `required_dual_hours`, and `logged_solo_hours` at least `required_solo_hours`; a
    shortfall on either yields `ERR_HOURS_NOT_MET`."

    Design: Corner/state_machines/enrollment_complete_blocked_when_hours_not_met
    """
    base = setup_active_enrollment(deposit_cents=60000)  # required_dual_hours 40, logged 0
    validate_error(api.complete_enrollment(base["enrollment"]["id"], ADMIN), ApiErrorId.ERR_HOURS_NOT_MET.value)
    assert get_enrollment(base["enrollment"]["id"])["status"] == "ACTIVE"
