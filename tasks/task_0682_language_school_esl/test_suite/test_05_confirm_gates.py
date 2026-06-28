"""Confirm-time validation gates and their fixed ordering (PRD §3.3, §3.4, §2.8).

Difficulty queue: priority_pair_validation_conflict (placement>visa, state>contract-seats),
                  cross_entity_state_dependency (visa gate, contract-seats gate),
                  resource_temporal_overlap (schedule conflict, different-block no-conflict).
Corner queue: cohort-full on require_seat, placement mismatch on track.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, set_clock,
    create_contract, create_cohort, create_student, create_placed_student,
    create_enrollment, confirm, confirm_enrollment_payload,
    setup_pending_enrollment, issue_i20, activate_status, place_probation,
    latest_cohort_version,
)

REG = TEST_USERS["registrar_headers"]
DSO = TEST_USERS["dso_headers"]


# =====================================================================
# Difficulty / priority_pair_validation_conflict / placement_mismatch_beats_visa_noncompliant
# =====================================================================
def test_placement_mismatch_beats_visa_noncompliant(api):
    """PRD §3.4: "the confirm-specific checks are evaluated in this order: first the
    placement gate (ERR_PLACEMENT_MISMATCH), then the F-1 visa gate for international
    students (ERR_VISA_NONCOMPLIANT), then the schedule-conflict check
    (ERR_SCHEDULE_CONFLICT) ..."
    PRD §3.3: "a student whose status is NONE, PROBATION, or TERMINATED cannot be
    confirmed into an ENROLLED seat and the confirm is rejected with
    ERR_VISA_NONCOMPLIANT (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/placement_mismatch_beats_visa_noncompliant
    """
    # International student driven to PROBATION (visa gate would fire), then attempts a
    # confirm into a cohort whose level mismatches the student's placement_level
    # (placement gate would also fire). The placement gate is evaluated first.
    #
    # Reach PROBATION: place B1, issue I-20, ENROLL into an 18h B1 cohort, activate to
    # ACTIVE, then place-probation. The student's placement_level is B1 throughout.
    course_cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=18,
                                  schedule_block="MORNING", name="Course")
    stu = create_placed_student(level="B1", track="GENERAL", is_international=True)
    issue_i20(stu["id"])
    course_enr = create_enrollment(stu["id"], course_cohort["id"])
    confirm(course_enr["id"], course_cohort["version"], require_seat=True)
    activate_status(stu["id"])
    place_probation(stu["id"], reason="concern")  # now PROBATION
    # Now attempt a confirm into a cohort at a DIFFERENT level (A1 != B1 placement_level).
    mismatch_cohort = create_cohort(level="A1", track="GENERAL", weekly_hours=18,
                                    schedule_block="AFTERNOON", name="Mismatch")
    enr = create_enrollment(stu["id"], mismatch_cohort["id"])
    validate_error(
        api.confirm_enrollment(enr["id"], confirm_enrollment_payload(mismatch_cohort["version"], require_seat=True), REG),
        ApiErrorId.ERR_PLACEMENT_MISMATCH.value)
    after = validate_success(api.get_enrollment(enr["id"], REG))
    assert after["status"] == "PLACEMENT_PENDING", "enrollment unchanged after a rejected confirm"


def test_placement_mismatch_reported_not_visa_when_both_violated(api):
    """PRD §3.4: "first the placement gate (ERR_PLACEMENT_MISMATCH), then the F-1 visa
    gate for international students (ERR_VISA_NONCOMPLIANT)"
    PRD §3.3: "a student whose status is NONE, PROBATION, or TERMINATED cannot be
    confirmed into an ENROLLED seat and the confirm is rejected with
    ERR_VISA_NONCOMPLIANT (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/placement_mismatch_beats_visa_noncompliant
    """
    # Second angle: assert the reported error is NOT the visa error even though the
    # student's visa is non-compliant (PROBATION) and placement also mismatches.
    course_cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=18,
                                  schedule_block="MORNING", name="Course2")
    stu = create_placed_student(level="B1", track="GENERAL", is_international=True)
    issue_i20(stu["id"])
    course_enr = create_enrollment(stu["id"], course_cohort["id"])
    confirm(course_enr["id"], course_cohort["version"], require_seat=True)
    activate_status(stu["id"])
    place_probation(stu["id"], reason="concern")
    mismatch_cohort = create_cohort(level="A1", track="GENERAL", weekly_hours=18,
                                    schedule_block="AFTERNOON", name="Mismatch2")
    enr = create_enrollment(stu["id"], mismatch_cohort["id"])
    err = api.confirm_enrollment(
        enr["id"], confirm_enrollment_payload(mismatch_cohort["version"], require_seat=True), REG)
    body = err.json()["data"]
    assert body["error_id"] == "ERR_PLACEMENT_MISMATCH", (
        f"placement gate (p6) must preempt visa gate (p7), got {body['error_id']}")


# =====================================================================
# Difficulty / priority_pair_validation_conflict / invalid_state_beats_contract_seats_exhausted
# =====================================================================
def test_invalid_state_beats_contract_seats_exhausted(api):
    """PRD §2.8: "fifth, that the target resource is in a state from which the
    requested transition is legal (ERR_INVALID_STATE, 409). Only after these five
    gates pass does the system evaluate the endpoint-specific business rules
    described in §3"

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_contract_seats_exhausted
    """
    # 1-seat contract fully consumed by one ENROLLED student (contract EXHAUSTED);
    # re-confirm the SAME already-ENROLLED enrollment -> state precondition fails first.
    contract = create_contract(contracted_seats=1, discount_tier="BRONZE", company_name="OneSeat")
    cohort = create_cohort(level="B1", track="GENERAL", capacity=5, weekly_hours=18,
                           base_tuition_cents=100000, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL", corporate_contract_id=contract["id"])
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)  # now ENROLLED, contract EXHAUSTED
    cv2 = latest_cohort_version(cohort["id"])
    validate_error(
        api.confirm_enrollment(enr["id"], confirm_enrollment_payload(cv2, require_seat=True), REG),
        ApiErrorId.ERR_INVALID_STATE.value)


def test_invalid_state_on_reconfirm_leaves_enrollment_enrolled(api):
    """PRD §2.8: "Only after these five gates pass does the system evaluate the
    endpoint-specific business rules described in §3"
    PRD §3.3: "A Registrar confirms a PLACEMENT_PENDING enrollment by supplying
    expected_cohort_version and an optional require_seat flag."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_contract_seats_exhausted
    """
    # Second angle: re-confirming an ENROLLED enrollment is rejected (state gate) and
    # the enrollment remains ENROLLED — confirming an already-ENROLLED target is illegal.
    contract = create_contract(contracted_seats=1, discount_tier="BRONZE", company_name="OneSeat2")
    cohort = create_cohort(level="B1", track="GENERAL", capacity=5, weekly_hours=18,
                           base_tuition_cents=100000, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL", corporate_contract_id=contract["id"])
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    cv2 = latest_cohort_version(cohort["id"])
    validate_error(
        api.confirm_enrollment(enr["id"], confirm_enrollment_payload(cv2, require_seat=True), REG),
        ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_enrollment(enr["id"], REG))
    assert after["status"] == "ENROLLED", "enrollment stays ENROLLED after a rejected re-confirm"


# =====================================================================
# Difficulty / cross_entity_state_dependency / enrollment_confirm_gated_by_student_visa_status
# =====================================================================
def test_confirm_blocked_when_student_in_probation(api):
    """PRD §3.3: "If the student is_international, their visa_status must be either
    INITIAL or ACTIVE; a student whose status is NONE, PROBATION, or TERMINATED cannot
    be confirmed into an ENROLLED seat and the confirm is rejected with
    ERR_VISA_NONCOMPLIANT (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/enrollment_confirm_gated_by_student_visa_status
    """
    # International student placed B1, ENROLLED into an 18h cohort, activated, then
    # placed on PROBATION; a fresh confirm into a matching cohort is blocked.
    cohort1 = create_cohort(level="B1", track="GENERAL", weekly_hours=18, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL", is_international=True)
    issue_i20(stu["id"])
    enr1 = create_enrollment(stu["id"], cohort1["id"])
    confirm(enr1["id"], cohort1["version"], require_seat=True)
    activate_status(stu["id"])
    place_probation(stu["id"], reason="attendance concern")
    cohort2 = create_cohort(level="B1", track="GENERAL", weekly_hours=18, schedule_block="AFTERNOON")
    enr2 = create_enrollment(stu["id"], cohort2["id"])
    validate_error(
        api.confirm_enrollment(enr2["id"], confirm_enrollment_payload(cohort2["version"], require_seat=True), REG),
        ApiErrorId.ERR_VISA_NONCOMPLIANT.value)
    after = validate_success(api.get_enrollment(enr2["id"], REG))
    assert after["status"] == "PLACEMENT_PENDING"


def test_confirm_blocked_when_visa_status_none(api):
    """PRD §3.3: "If the student is_international, their visa_status must be either
    INITIAL or ACTIVE; a student whose status is NONE, PROBATION, or TERMINATED cannot
    be confirmed into an ENROLLED seat and the confirm is rejected with
    ERR_VISA_NONCOMPLIANT (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/enrollment_confirm_gated_by_student_visa_status
    """
    # Second angle, different visa state: an international student with NO I-20 issued
    # (visa_status NONE) cannot take an ENROLLED seat.
    cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=18, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL", is_international=True)  # visa NONE
    enr = create_enrollment(stu["id"], cohort["id"])
    validate_error(
        api.confirm_enrollment(enr["id"], confirm_enrollment_payload(cohort["version"], require_seat=True), REG),
        ApiErrorId.ERR_VISA_NONCOMPLIANT.value)


# =====================================================================
# Difficulty / cross_entity_state_dependency / enrollment_confirm_gated_by_contract_seats_exhausted
# =====================================================================
def test_confirm_blocked_when_contract_seats_exhausted(api):
    """PRD §3.6: "a sponsored student can only take an ENROLLED seat while the
    contract has capacity, meaning seats_consumed is strictly below contracted_seats
    and the contract is neither EXHAUSTED nor CLOSED. A sponsored ENROLLED confirm
    against a contract with no remaining seats is rejected with
    ERR_CONTRACT_SEATS_EXHAUSTED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/enrollment_confirm_gated_by_contract_seats_exhausted
    """
    contract = create_contract(contracted_seats=1, discount_tier="BRONZE", company_name="Solo")
    cohort = create_cohort(level="B1", track="GENERAL", capacity=5, weekly_hours=18,
                           base_tuition_cents=100000, schedule_block="MORNING")
    # First sponsored student fills the only contract seat.
    stu1 = create_placed_student(level="B1", track="GENERAL", corporate_contract_id=contract["id"])
    enr1 = create_enrollment(stu1["id"], cohort["id"])
    confirm(enr1["id"], cohort["version"], require_seat=True)  # contract now EXHAUSTED
    # Second sponsored student into a cohort with free seats — blocked by contract gate.
    stu2 = create_placed_student(level="B1", track="GENERAL", corporate_contract_id=contract["id"])
    enr2 = create_enrollment(stu2["id"], cohort["id"])
    cv1 = latest_cohort_version(cohort["id"])
    validate_error(
        api.confirm_enrollment(enr2["id"], confirm_enrollment_payload(cv1, require_seat=True), REG),
        ApiErrorId.ERR_CONTRACT_SEATS_EXHAUSTED.value)
    after = validate_success(api.get_enrollment(enr2["id"], REG))
    assert after["status"] == "PLACEMENT_PENDING"


def test_contract_exhausted_leaves_second_enrollment_pending(api):
    """PRD §3.6: "a sponsored student can only take an ENROLLED seat while the contract
    has capacity, meaning seats_consumed is strictly below contracted_seats and the
    contract is neither EXHAUSTED nor CLOSED."
    PRD §2.6: "a derived status that is ACTIVE while seats remain, EXHAUSTED once
    seats_consumed equals contracted_seats"

    Design: Difficulty/cross_entity_state_dependency/enrollment_confirm_gated_by_contract_seats_exhausted
    """
    # Second angle: confirm the contract is EXHAUSTED after the first seat and the
    # blocked second enrollment is unchanged.
    contract = create_contract(contracted_seats=1, discount_tier="BRONZE", company_name="Solo2")
    cohort = create_cohort(level="B1", track="GENERAL", capacity=5, weekly_hours=18,
                           base_tuition_cents=100000, schedule_block="MORNING")
    stu1 = create_placed_student(level="B1", track="GENERAL", corporate_contract_id=contract["id"])
    enr1 = create_enrollment(stu1["id"], cohort["id"])
    confirm(enr1["id"], cohort["version"], require_seat=True)
    contract_after = validate_success(api.get_corporate_contract(contract["id"], REG))
    assert contract_after["status"] == "EXHAUSTED", "contract becomes EXHAUSTED at full seats"
    stu2 = create_placed_student(level="B1", track="GENERAL", corporate_contract_id=contract["id"])
    enr2 = create_enrollment(stu2["id"], cohort["id"])
    cv1 = latest_cohort_version(cohort["id"])
    validate_error(
        api.confirm_enrollment(enr2["id"], confirm_enrollment_payload(cv1, require_seat=True), REG),
        ApiErrorId.ERR_CONTRACT_SEATS_EXHAUSTED.value)


# =====================================================================
# Difficulty / resource_temporal_overlap / student_double_booking_closed_interval_term_overlap
# =====================================================================
def test_schedule_conflict_closed_interval_boundary_touch(api):
    """PRD §3.4: "A confirm into the ENROLLED state is rejected with
    ERR_SCHEDULE_CONFLICT (HTTP 409) when the student already holds another ENROLLED
    enrollment whose cohort shares the same schedule_block as the target cohort and
    whose term overlaps the target cohort's term. Overlap is evaluated as a
    closed-interval test on the two [term_start, term_end] ranges: the two terms
    conflict whenever the earlier term's term_end is on or after the later term's
    term_start, so that even terms that merely touch at a shared boundary date are
    treated as overlapping."

    Design: Difficulty/resource_temporal_overlap/student_double_booking_closed_interval_term_overlap
    """
    stu = create_placed_student(level="B1", track="GENERAL")
    cohort1 = create_cohort(level="B1", track="GENERAL", weekly_hours=9, schedule_block="MORNING",
                            term_start="2026-05-04T00:00:00Z", term_end="2026-06-01T00:00:00Z",
                            total_sessions=20, name="AM-1")
    enr1 = create_enrollment(stu["id"], cohort1["id"])
    confirm(enr1["id"], cohort1["version"], require_seat=True)
    # Second MORNING cohort touching at the boundary 2026-06-01.
    cohort2 = create_cohort(level="B1", track="GENERAL", weekly_hours=9, schedule_block="MORNING",
                            term_start="2026-06-01T00:00:00Z", term_end="2026-07-01T00:00:00Z",
                            total_sessions=20, name="AM-2")
    enr2 = create_enrollment(stu["id"], cohort2["id"])
    validate_error(
        api.confirm_enrollment(enr2["id"], confirm_enrollment_payload(cohort2["version"], require_seat=True), REG),
        ApiErrorId.ERR_SCHEDULE_CONFLICT.value)
    after = validate_success(api.get_enrollment(enr2["id"], REG))
    assert after["status"] == "PLACEMENT_PENDING"


def test_schedule_conflict_interior_term_overlap(api):
    """PRD §3.4: "A confirm into the ENROLLED state is rejected with
    ERR_SCHEDULE_CONFLICT (HTTP 409) when the student already holds another ENROLLED
    enrollment whose cohort shares the same schedule_block as the target cohort and
    whose term overlaps the target cohort's term."

    Design: Difficulty/resource_temporal_overlap/student_double_booking_closed_interval_term_overlap
    """
    # Second angle: a strict interior overlap (not just a boundary touch) on the same block.
    stu = create_placed_student(level="B1", track="GENERAL")
    cohort1 = create_cohort(level="B1", track="GENERAL", weekly_hours=9, schedule_block="MORNING",
                            term_start="2026-05-04T00:00:00Z", term_end="2026-08-01T00:00:00Z",
                            total_sessions=40, name="AM-Wide")
    enr1 = create_enrollment(stu["id"], cohort1["id"])
    confirm(enr1["id"], cohort1["version"], require_seat=True)
    cohort2 = create_cohort(level="B1", track="GENERAL", weekly_hours=9, schedule_block="MORNING",
                            term_start="2026-06-01T00:00:00Z", term_end="2026-06-20T00:00:00Z",
                            total_sessions=10, name="AM-Inside")
    enr2 = create_enrollment(stu["id"], cohort2["id"])
    validate_error(
        api.confirm_enrollment(enr2["id"], confirm_enrollment_payload(cohort2["version"], require_seat=True), REG),
        ApiErrorId.ERR_SCHEDULE_CONFLICT.value)


# =====================================================================
# Difficulty / resource_temporal_overlap / cohort_seat_capacity_overlap_no_block_difference
# =====================================================================
def test_overlapping_terms_different_block_no_conflict(api):
    """PRD §3.4: "Only ENROLLED enrollments sharing the same schedule_block can
    conflict; differing blocks never collide."

    Design: Difficulty/resource_temporal_overlap/cohort_seat_capacity_overlap_no_block_difference
    """
    stu = create_placed_student(level="B1", track="GENERAL")
    cohort1 = create_cohort(level="B1", track="GENERAL", weekly_hours=9, schedule_block="MORNING",
                            term_start="2026-05-04T00:00:00Z", term_end="2026-08-01T00:00:00Z",
                            total_sessions=40, name="AM-X")
    enr1 = create_enrollment(stu["id"], cohort1["id"])
    confirm(enr1["id"], cohort1["version"], require_seat=True)
    # Same overlapping term but EVENING block -> no conflict, confirms to ENROLLED.
    cohort2 = create_cohort(level="B1", track="GENERAL", weekly_hours=9, schedule_block="EVENING",
                            term_start="2026-05-04T00:00:00Z", term_end="2026-08-01T00:00:00Z",
                            total_sessions=40, name="PM-X")
    enr2 = create_enrollment(stu["id"], cohort2["id"])
    data = validate_success(api.confirm_enrollment(
        enr2["id"], confirm_enrollment_payload(cohort2["version"], require_seat=True), REG))
    assert data["status"] == "ENROLLED", "different schedule_block => no conflict despite overlap"


def test_different_block_second_enrollment_computes_tuition(api):
    """PRD §3.4: "Only ENROLLED enrollments sharing the same schedule_block can
    conflict; differing blocks never collide."
    PRD §3.3: "computes and pins tuition_invoice_cents per §3.6"

    Design: Difficulty/resource_temporal_overlap/cohort_seat_capacity_overlap_no_block_difference
    """
    # Second angle: the non-conflicting second enrollment (AFTERNOON vs MORNING, same
    # overlapping term) confirms to ENROLLED and pins its tuition (proving it truly entered).
    stu = create_placed_student(level="B1", track="GENERAL")
    cohort1 = create_cohort(level="B1", track="GENERAL", weekly_hours=9, schedule_block="MORNING",
                            term_start="2026-05-04T00:00:00Z", term_end="2026-08-01T00:00:00Z",
                            total_sessions=40, base_tuition_cents=100000, name="AM-T")
    enr1 = create_enrollment(stu["id"], cohort1["id"])
    confirm(enr1["id"], cohort1["version"], require_seat=True)
    cohort2 = create_cohort(level="B1", track="GENERAL", weekly_hours=9, schedule_block="AFTERNOON",
                            term_start="2026-05-04T00:00:00Z", term_end="2026-08-01T00:00:00Z",
                            total_sessions=40, base_tuition_cents=200000, name="PM-T")
    enr2 = create_enrollment(stu["id"], cohort2["id"])
    data = validate_success(api.confirm_enrollment(
        enr2["id"], confirm_enrollment_payload(cohort2["version"], require_seat=True), REG))
    assert data["status"] == "ENROLLED"
    assert data["tuition_invoice_cents"] == 200000, "self-pay tuition pinned to base on the ENROLLED branch"


# =====================================================================
# Corner / endpoints / confirm_require_seat_on_full_cohort_returns_cohort_full
# =====================================================================
def test_confirm_require_seat_on_full_cohort_returns_cohort_full(api):
    """PRD §3.3: "With require_seat set, a confirm against a cohort whose seats_taken
    is at or above capacity is treated as an error rather than a waitlist, and is
    rejected with ERR_COHORT_FULL (HTTP 409)."

    Design: Corner/endpoints/confirm_require_seat_on_full_cohort_returns_cohort_full
    """
    cohort = create_cohort(level="B1", track="GENERAL", capacity=1, schedule_block="MORNING")
    stu_a = create_placed_student(level="B1", track="GENERAL")
    enr_a = create_enrollment(stu_a["id"], cohort["id"])
    confirm(enr_a["id"], cohort["version"], require_seat=True)  # fills the seat
    stu_b = create_placed_student(level="B1", track="GENERAL")
    enr_b = create_enrollment(stu_b["id"], cohort["id"])
    cv1 = latest_cohort_version(cohort["id"])
    validate_error(
        api.confirm_enrollment(enr_b["id"], confirm_enrollment_payload(cv1, require_seat=True), REG),
        ApiErrorId.ERR_COHORT_FULL.value)


# =====================================================================
# Corner / errors / confirm_placement_mismatch_track_returns_conflict
# =====================================================================
def test_confirm_placement_mismatch_on_track(api):
    """PRD §3.3: "The confirm always demands that the student's placement_level
    exactly equal the cohort's level and the student's track exactly equal the
    cohort's track; a mismatch on either is rejected with ERR_PLACEMENT_MISMATCH
    (HTTP 409)."

    Design: Corner/errors/confirm_placement_mismatch_track_returns_conflict
    """
    # B1/GENERAL student into a B1/ACADEMIC cohort: level matches, track mismatches.
    stu = create_placed_student(level="B1", track="GENERAL")
    cohort = create_cohort(level="B1", track="ACADEMIC", weekly_hours=18, schedule_block="MORNING")
    enr = create_enrollment(stu["id"], cohort["id"])
    validate_error(
        api.confirm_enrollment(enr["id"], confirm_enrollment_payload(cohort["version"], require_seat=True), REG),
        ApiErrorId.ERR_PLACEMENT_MISMATCH.value)
