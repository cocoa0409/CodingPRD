"""Cascade chains and seat conservation invariants (PRD §3.7, §3.8, §3.9).

Difficulty queue: transitive_cascade (contract-close depth3, withdraw->promote depth2),
                  compensating_invariant (cohort seat conservation, contract seat conservation).
Corner queue: withdraw releases seat, withdraw-last-enrollment visa probation cascade.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS, set_clock,
    create_contract, create_cohort, create_placed_student, create_enrollment, confirm,
    setup_capacity1_with_waitlist, setup_active_international,
    close_contract_payload, terminate_enrollment_payload,
    latest_contract_version,
)

REG = TEST_USERS["registrar_headers"]
DSO = TEST_USERS["dso_headers"]


# =====================================================================
# Difficulty / transitive_cascade / contract_close_cascade_depth3_terminate_release_void
# =====================================================================
def test_contract_close_cascade_terminates_sponsored_enrollment(api):
    """PRD §3.9: "Closing cascades: every currently ENROLLED enrollment sponsored by
    the contract is terminated with termination_reason CONTRACT_REVOKED (releasing
    each cohort seat and each contract seat and promoting waitlists exactly as a
    termination does), and the contract's version is incremented by one."

    Design: Difficulty/transitive_cascade/contract_close_cascade_depth3_terminate_release_void
    """
    contract = create_contract(contracted_seats=2, discount_tier="BRONZE", company_name="Casc")
    cohort = create_cohort(level="B1", track="GENERAL", capacity=5, weekly_hours=18,
                           base_tuition_cents=100000, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL", corporate_contract_id=contract["id"])
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    cversion = latest_contract_version(contract["id"])
    closed = validate_success(api.close_corporate_contract(
        contract["id"], close_contract_payload(cversion), REG))
    assert closed["status"] == "CLOSED"
    enr_after = validate_success(api.get_enrollment(enr["id"], REG))
    assert enr_after["status"] == "TERMINATED"
    assert enr_after["termination_reason"] == "CONTRACT_REVOKED"


def test_contract_close_cascade_releases_seats(api):
    """PRD §3.9: "every currently ENROLLED enrollment sponsored by the contract is
    terminated with termination_reason CONTRACT_REVOKED (releasing each cohort seat
    and each contract seat ...)"

    Design: Difficulty/transitive_cascade/contract_close_cascade_depth3_terminate_release_void
    """
    contract = create_contract(contracted_seats=2, discount_tier="BRONZE")
    cohort = create_cohort(level="B1", track="GENERAL", capacity=5, weekly_hours=18,
                           base_tuition_cents=100000, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL", corporate_contract_id=contract["id"])
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    cversion = latest_contract_version(contract["id"])
    api.close_corporate_contract(contract["id"], close_contract_payload(cversion), REG)
    cohort_after = validate_success(api.get_cohort(cohort["id"], REG))
    contract_after = validate_success(api.get_corporate_contract(contract["id"], REG))
    assert cohort_after["seats_taken"] == 0, "cohort seat released by the cascaded termination"
    assert contract_after["seats_consumed"] == 0, "contract seat drawn down by the cascaded termination"


# =====================================================================
# Difficulty / transitive_cascade / withdraw_cascade_depth2_seat_release_promotes_waitlist
# =====================================================================
def test_withdraw_promotes_earliest_waitlisted(api):
    """PRD §3.7: "On withdrawal the system computes refund_cents, decrements the
    cohort's seats_taken by one ... and promotes the earliest waitlisted enrollment
    on that cohort if any exists."
    PRD §3.7: "the system promotes the earliest WAITLISTED enrollment on that cohort
    — the one with the smallest created_at — by transitioning it WAITLISTED → ENROLLED.
    Promotion stamps the promoted enrollment's enrolled_at with the current logical clock"

    Design: Difficulty/transitive_cascade/withdraw_cascade_depth2_seat_release_promotes_waitlist
    """
    cohort, stu_a, enr_a, stu_b, enr_b = setup_capacity1_with_waitlist()
    assert enr_b["status"] == "WAITLISTED"
    api.withdraw_enrollment(enr_a["id"], REG)
    promoted = validate_success(api.get_enrollment(enr_b["id"], REG))
    assert promoted["status"] == "ENROLLED", "waitlisted B promoted by the seat-release link"
    assert promoted["enrolled_at"] is not None, "promotion stamps enrolled_at"


def test_withdraw_seat_net_unchanged_after_promotion(api):
    """PRD §3.7: "Whenever a seat frees on a cohort, the system promotes the earliest
    WAITLISTED enrollment on that cohort ... increments the cohort's seats_taken by one"

    Design: Difficulty/transitive_cascade/withdraw_cascade_depth2_seat_release_promotes_waitlist
    """
    cohort, stu_a, enr_a, stu_b, enr_b = setup_capacity1_with_waitlist()
    api.withdraw_enrollment(enr_a["id"], REG)
    after = validate_success(api.get_cohort(cohort["id"], REG))
    # Seat moved A -> B; net seats_taken stays 1 on a capacity-1 cohort.
    assert after["seats_taken"] == 1, f"seat moved A->B, net unchanged, got {after['seats_taken']}"


# =====================================================================
# Difficulty / compensating_invariant / cohort_seat_conservation_enroll_then_withdraw
# =====================================================================
def test_cohort_seat_conservation_enroll_then_withdraw(api):
    """PRD §2.6: "A Cohort exposes seats_taken, the count of enrollments currently in
    ENROLLED state, and a derived status of OPEN while seats_taken is below capacity
    or FULL once seats_taken equals capacity."
    PRD §3.7: "decrements the cohort's seats_taken by one and flips the cohort's
    status from FULL back to OPEN if it was full"

    Design: Difficulty/compensating_invariant/cohort_seat_conservation_enroll_then_withdraw
    """
    cohort = create_cohort(level="B1", track="GENERAL", capacity=3, weekly_hours=18,
                           base_tuition_cents=100000, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    api.withdraw_enrollment(enr["id"], REG)
    after = validate_success(api.get_cohort(cohort["id"], REG))
    assert after["seats_taken"] == 0, f"seat released, no drift, got {after['seats_taken']}"
    assert after["capacity"] == 3, "capacity unchanged"


def test_cohort_full_then_open_after_withdraw(api):
    """PRD §2.6: "a derived status of OPEN while seats_taken is below capacity or FULL
    once seats_taken equals capacity."
    PRD §3.7: "decrements the cohort's seats_taken by one and flips the cohort's status
    from FULL back to OPEN if it was full"

    Design: Difficulty/compensating_invariant/cohort_seat_conservation_enroll_then_withdraw
    """
    # Second angle on the seat-conservation invariant: a capacity-1 cohort goes FULL on
    # enroll and returns to OPEN with seats_taken 0 after the compensating withdraw.
    cohort = create_cohort(level="B1", track="GENERAL", capacity=1, weekly_hours=18,
                           base_tuition_cents=100000, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    full = validate_success(api.get_cohort(cohort["id"], REG))
    assert full["status"] == "FULL" and full["seats_taken"] == 1
    api.withdraw_enrollment(enr["id"], REG)
    after = validate_success(api.get_cohort(cohort["id"], REG))
    assert after["seats_taken"] == 0 and after["status"] == "OPEN", "seat released, no drift"


# =====================================================================
# Difficulty / compensating_invariant / contract_seat_conservation_enroll_then_terminate
# =====================================================================
def test_contract_seat_conservation_enroll_then_terminate(api):
    """PRD §2.6: "A CorporateContract exposes seats_consumed, the count of currently
    ENROLLED enrollments whose student it sponsors"
    PRD §3.7: "On termination the system records the termination_reason, sets
    refund_cents to 0 (no refund is ever paid on a termination) ... decrements the
    sponsoring contract's seats_consumed by one if sponsored"

    Design: Difficulty/compensating_invariant/contract_seat_conservation_enroll_then_terminate
    """
    contract = create_contract(contracted_seats=2, discount_tier="BRONZE", company_name="Inv2")
    cohort = create_cohort(level="B1", track="GENERAL", capacity=5, weekly_hours=18,
                           base_tuition_cents=100000, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL", corporate_contract_id=contract["id"])
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    terminated = validate_success(api.terminate_enrollment(
        enr["id"], terminate_enrollment_payload("ATTENDANCE_FAILURE"), DSO))
    after = validate_success(api.get_corporate_contract(contract["id"], REG))
    assert after["seats_consumed"] == 0, f"contract seat released, no drift, got {after['seats_consumed']}"
    assert after["contracted_seats"] == 2, "contracted_seats unchanged"
    assert terminated["refund_cents"] == 0, "termination yields no refund"


def test_contract_returns_to_active_after_terminate_frees_seat(api):
    """PRD §2.6: "a derived status that is ACTIVE while seats remain, EXHAUSTED once
    seats_consumed equals contracted_seats"
    PRD §3.9: "automatically returns to ACTIVE when a sponsored enrollment leaves
    ENROLLED and frees a seat."

    Design: Difficulty/compensating_invariant/contract_seat_conservation_enroll_then_terminate
    """
    # Second angle: a 1-seat contract goes EXHAUSTED on enroll, then the compensating
    # terminate frees the seat and the contract returns to ACTIVE with seats_consumed 0.
    contract = create_contract(contracted_seats=1, discount_tier="BRONZE", company_name="Inv1")
    cohort = create_cohort(level="B1", track="GENERAL", capacity=5, weekly_hours=18,
                           base_tuition_cents=100000, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL", corporate_contract_id=contract["id"])
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    exhausted = validate_success(api.get_corporate_contract(contract["id"], REG))
    assert exhausted["status"] == "EXHAUSTED" and exhausted["seats_consumed"] == 1
    api.terminate_enrollment(enr["id"], terminate_enrollment_payload("ATTENDANCE_FAILURE"), DSO)
    after = validate_success(api.get_corporate_contract(contract["id"], REG))
    assert after["seats_consumed"] == 0 and after["status"] == "ACTIVE", "contract seat released, no drift"


# =====================================================================
# Corner / cross_cutting / withdraw_releases_seat_derived_field_reconciles
# =====================================================================
def test_withdraw_reconciles_cohort_seats_taken(api):
    """PRD §2.6: "A Cohort exposes seats_taken, the count of enrollments currently in
    ENROLLED state, and a derived status of OPEN while seats_taken is below capacity"

    Design: Corner/cross_cutting_complexity_layers/withdraw_releases_seat_derived_field_reconciles
    """
    cohort = create_cohort(level="B1", track="GENERAL", capacity=5, weekly_hours=18,
                           base_tuition_cents=100000, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    set_clock("2026-05-07T00:00:00Z")
    api.withdraw_enrollment(enr["id"], REG)
    after = validate_success(api.get_cohort(cohort["id"], REG))
    assert after["seats_taken"] == 0
    assert after["status"] == "OPEN"


# =====================================================================
# Corner / cross_cutting / withdraw_last_enrollment_triggers_visa_probation_cascade
# =====================================================================
def test_withdraw_last_enrollment_triggers_visa_probation(api):
    """PRD §3.7: "If the student is_international and, after this withdrawal, the
    student has zero remaining ENROLLED enrollments, the system sets the student's
    visa_status to PROBATION and appends a ComplianceEvent of type PROBATION_PLACED;
    this is the visa-dimension cascade of a withdrawal that empties a student's course load."

    Design: Corner/cross_cutting_complexity_layers/withdraw_last_enrollment_triggers_visa_probation_cascade
    """
    stu, cohort, enr = setup_active_international(weekly_hours=18)
    assert stu["visa_status"] == "ACTIVE"
    set_clock("2026-05-07T00:00:00Z")
    api.withdraw_enrollment(enr["id"], REG)
    after = validate_success(api.get_student(stu["id"], REG))
    assert after["visa_status"] == "PROBATION", (
        f"empty course load -> PROBATION, got {after['visa_status']}")
