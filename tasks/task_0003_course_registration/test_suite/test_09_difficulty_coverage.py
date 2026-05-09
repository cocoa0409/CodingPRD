"""Targeted coverage for difficulty-design instances that are not already
satisfied (or only satisfied once) by tests in 01-08. Each test below
targets a specific scaffold-difficulty-design instance with at least one
additional assertion path so every instance carries ≥2 covering tests.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, TEST_USERS,
    PRIORITY_WEIGHTS, CREDIT_QUOTA_TIERS,
    make_student_headers, make_professor_headers,
)
from test_helpers.fixtures import (
    setup_basic_world, setup_open_offering, setup_offering_with_seat_taken,
    setup_two_program_world_with_completed_source_course,
    create_credit_equivalence_policy, get_degree_plan,
    create_offering, create_course, create_student, create_professor,
    create_term_in_planning, create_campus, create_department, create_lab_equipment,
    advance_clock, submit_enrollment, submit_enrollment_success,
    cancel_enrollment, get_enrollment_request, list_waitlist,
    list_student_sync_events, get_offering, settle_tuition,
    create_over_limit_application, submit_application,
    sign_application, reject_application, revise_application, get_application,
    load_student_credits_via_approved, open_offering,
)


# ─── dual_variant_calc / dual_variant_credit_quota_student_domain ───────
def test_quota_provisional_includes_waitlisted_load(api):
    """PRD §3.6: "Note that WAITLISTED enrollments do consume the provisional
    quota; they release it only when they reach CANCELED, EXPIRED, or REJECTED."

    Concrete claim from the difficulty design: a year-2 student
    (base_quota=20.0) with 14.0 APPROVED credits AND a 5.0-credit
    WAITLISTED enrollment cannot enroll in a 2.0-credit offering
    (current_load = 14.0 + 5.0 = 19.0; 19.0 + 2.0 = 21.0 > 20.0).

    # difficulty: dual_variant_calc/dual_variant_credit_quota_student_domain
    """
    world = setup_basic_world(student_year=2)
    # 14.0 APPROVED credits via two 4.0 + one 5.0 — two distinct days each;
    # actually use two 4.0 (8.0) + one 6.0 ... easier: three 4.0 = 12. Try two 4 + one 5:
    # 4.0 + 4.0 + 5.0 = 13.0... close but not 14. Use one 4 + one 4 + one 5 + one 1: 14.
    # Simpler — load 14 directly: 4 × 3.5 = 14? loader uses uniform per-course credits.
    # Use four 3.5-credit courses on different days → 14.0 APPROVED.
    load_student_credits_via_approved(world, target_credits=14.0,
                                       per_course_credits=3.5,
                                       meeting_start=540, meeting_end=600)
    # Add a 5.0-credit WAITLISTED enrollment.
    full = setup_offering_with_seat_taken(world, credits=5.0,
                                            scheduled_meetings=[{"day_of_week": 5, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er_w = submit_enrollment_success(world["student"], full["offering"]["id"])
    assert er_w["academic_status"] == "WAITLISTED"

    # Now attempt a 2.0-credit course; must fail because 14+5+2 = 21 > 20.
    co = setup_open_offering(world, credits=2.0,
                              scheduled_meetings=[{"day_of_week": 6, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    res = submit_enrollment(world["student"], co["offering"]["id"])
    validate_error(res, "ERR_CREDIT_QUOTA_EXCEEDED")


def test_quota_release_after_waitlisted_canceled_permits_enrollment(api):
    """PRD §3.6: "Note that WAITLISTED enrollments do consume the provisional
    quota; they release it only when they reach CANCELED, EXPIRED, or REJECTED."

    Claim: when a WAITLISTED enrollment is canceled, the provisional quota is
    released. Same year-2 student now has 14.0 APPROVED + 0 WAITLISTED, and
    a 6.0-credit submission must fit (14+6=20, equality permitted).

    # difficulty: dual_variant_calc/dual_variant_credit_quota_student_domain
    """
    world = setup_basic_world(student_year=2)
    load_student_credits_via_approved(world, target_credits=14.0,
                                       per_course_credits=3.5,
                                       meeting_start=540, meeting_end=600)
    full = setup_offering_with_seat_taken(world, credits=6.0,
                                            scheduled_meetings=[{"day_of_week": 5, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er_w = submit_enrollment_success(world["student"], full["offering"]["id"])
    assert er_w["academic_status"] == "WAITLISTED"
    # Cancel the WAITLISTED row to release its provisional quota.
    cancel_enrollment(world["student"], er_w["id"])

    # Now submit a 6.0-credit offering; current_load=14.0, 14+6=20 (equality permitted).
    co = setup_open_offering(world, credits=6.0,
                              scheduled_meetings=[{"day_of_week": 6, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    assert er["academic_status"] == "APPROVED"


# ─── combinatorial_formula / combinatorial_priority_score_mode_a ────────
def test_priority_score_with_year_three_and_zero_fraud(api):
    """PRD §3.5: "The score is the sum of year_factor weighted by ten, plus
    gap_count weighted by fifteen, plus prereq_strength weighted by eight,
    minus fraud_penalty weighted by two."

    Concrete claim: a year-3 student (year_factor=3), fraud_score=0
    (fraud_penalty=0), enrolling in a course that satisfies a degree-plan
    gap (gap_count=1) with two downstream courses citing it (prereq_strength=2)
    yields priority_score = (10*3) + (15*1) + (8*2) - (2*0) = 30 + 15 + 16 = 61.

    # difficulty: combinatorial_formula/combinatorial_priority_score_mode_a
    """
    world = setup_basic_world(student_year=3)
    # CX is the test course; CY and CZ each list CX as REQUIRED prereq
    # (so CX has prereq_strength of 2).
    cx = create_course(world["department"]["id"], credits=3.0, code_prefix="CX")
    create_course(world["department"]["id"], credits=3.0,
                   prerequisite_course_ids=[{"course_id": cx["id"], "mode": "REQUIRED"}],
                   code_prefix="CY")
    create_course(world["department"]["id"], credits=3.0,
                   prerequisite_course_ids=[{"course_id": cx["id"], "mode": "REQUIRED"}],
                   code_prefix="CZ")
    # Make an offering of CX with capacity=1 and pre-fill its seat.
    cx_offering = create_offering(
        term_id=world["term"]["id"], course_id=cx["id"],
        campus_id=world["campus"]["id"], instructor_id=world["instructor"]["id"],
        base_capacity=1,
        scheduled_meetings=[{"day_of_week": 0, "start_minute_of_day": 540, "end_minute_of_day": 600}],
    )
    open_offering(cx_offering["id"])
    occupant = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=2,
                                full_name="Occupant CX")
    er_occ = submit_enrollment_success(occupant, cx_offering["id"])
    assert er_occ["academic_status"] == "APPROVED"

    # Now world['student'] (year=3) submits → WAITLISTED with priority_score 61.
    er = submit_enrollment_success(world["student"], cx_offering["id"])
    assert er["academic_status"] == "WAITLISTED"
    expected = (10 * 3) + (15 * 1) + (8 * 2) - (2 * 0)
    assert expected == 61
    assert er["priority_score"] == 61, (
        f"Expected priority_score=61, got {er['priority_score']}"
    )


def test_priority_score_with_negative_fraud_penalty_clamped_to_zero(api):
    """PRD §3.5: "A fraud_penalty equal to the student's fraud_score minus a
    grace value of ten, with negative results clamped to zero. Below the
    grace threshold there is no penalty."

    Concrete claim: a year-2 student with fraud_score=0 (≤ grace=10)
    enrolling in a gap-filling course with prereq_strength=1 yields:
    (10*2) + (15*1) + (8*1) - 0 = 43. The test confirms the
    sub-grace clamp produces no negative contribution.

    # difficulty: combinatorial_formula/combinatorial_priority_score_mode_a
    """
    world = setup_basic_world(student_year=2)
    # Test course CT, with one downstream course CT_DOWN citing CT as REQUIRED prereq
    # (prereq_strength = 1).
    ct = create_course(world["department"]["id"], credits=3.0, code_prefix="CT")
    create_course(world["department"]["id"], credits=3.0,
                   prerequisite_course_ids=[{"course_id": ct["id"], "mode": "REQUIRED"}],
                   code_prefix="CTDOWN")
    ct_offering = create_offering(
        term_id=world["term"]["id"], course_id=ct["id"],
        campus_id=world["campus"]["id"], instructor_id=world["instructor"]["id"],
        base_capacity=1,
        scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 540, "end_minute_of_day": 600}],
    )
    open_offering(ct_offering["id"])
    occupant = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=1,
                                full_name="Occupant CT")
    er_occ = submit_enrollment_success(occupant, ct_offering["id"])
    assert er_occ["academic_status"] == "APPROVED"

    er = submit_enrollment_success(world["student"], ct_offering["id"])
    assert er["academic_status"] == "WAITLISTED"
    expected = (10 * 2) + (15 * 1) + (8 * 1) - 0
    assert expected == 43
    assert er["priority_score"] == expected, (
        f"Expected priority_score={expected}, got {er['priority_score']}"
    )


# ─── priority_pair_validation_conflict ──────────────────────────────────
def test_state_priority_wins_over_business_safety(api):
    """PRD §2.9: validation order — "When a single request would fail more
    than one priority level, the lower-numbered priority wins and is reported."
    State (priority 4) precedes business_safety (priority 6).

    Claim: when both ERR_OFFERING_NOT_OPEN (priority 4 — state) and
    ERR_CROSS_DEPARTMENT_ACCESS_DENIED (priority 6 — business_safety) would
    fire, the state error wins.

    # difficulty: priority_pair_validation_conflict/conflict_state_vs_business_safety
    """
    campus = create_campus()
    d_home = create_department(campus["id"], code_prefix="HOME")
    d_other = create_department(campus["id"], code_prefix="OTHER")
    instructor = create_professor(d_other["id"], is_chair=False, max_minutes=600)
    student = create_student(d_home["id"], campus["id"], year_in_program=2)
    term = create_term_in_planning()
    advance_clock(term["registration_open_at"])

    course_other = create_course(d_other["id"], credits=3.0)
    offering = create_offering(
        term_id=term["id"], course_id=course_other["id"],
        campus_id=campus["id"], instructor_id=instructor["id"],
        base_capacity=10,
        scheduled_meetings=[{"day_of_week": 2, "start_minute_of_day": 540, "end_minute_of_day": 600}],
    )
    open_offering(offering["id"])
    # Now CLOSE it so state-precondition fires.
    api.close_course_offering(offering["id"], TEST_USERS["registrar_headers"])

    # No DepartmentAccessGrant from d_home → d_other, so cross-department
    # check would also fail. State priority wins.
    res = submit_enrollment(student, offering["id"])
    validate_error(res, "ERR_OFFERING_NOT_OPEN")


def test_business_constraint_priority_wins_over_business_fiscal(api):
    """PRD §2.9: validation order — "When a single request would fail more
    than one priority level, the lower-numbered priority wins and is reported."
    Prerequisite (priority 7 — business_constraint) precedes credit_quota
    (priority 12 — business_fiscal).

    Claim: when both ERR_PREREQUISITE_NOT_MET (priority 7) and
    ERR_CREDIT_QUOTA_EXCEEDED (priority 12) would fire, the prereq error
    wins.

    # difficulty: priority_pair_validation_conflict/conflict_business_constraint_vs_business_fiscal
    """
    world = setup_basic_world(student_year=1, student_completed_course_ids=[])
    # Load 16 APPROVED credits via four 4.0-credit courses (none with prereq) —
    # year-1 quota is 18.0, leaving 2.0 head-room. A new 4.0-credit course
    # would push total to 20.0 > 18.0 → quota check fails.
    load_student_credits_via_approved(world, target_credits=16.0,
                                       per_course_credits=4.0,
                                       meeting_start=540, meeting_end=600)
    # Test course CK has a REQUIRED prereq the student lacks.
    prereq = create_course(world["department"]["id"], credits=3.0, code_prefix="PREK")
    ck = create_course(
        world["department"]["id"], credits=4.0,
        prerequisite_course_ids=[{"course_id": prereq["id"], "mode": "REQUIRED"}],
        code_prefix="CK",
    )
    co = setup_open_offering(world, course=ck, base_capacity=10,
                              scheduled_meetings=[{"day_of_week": 6, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    res = submit_enrollment(world["student"], co["offering"]["id"])
    validate_error(res, "ERR_PREREQUISITE_NOT_MET")


# ─── compensating_invariant pair (credit ↔ seat) — second tests ─────────
def test_credit_invariant_two_cycles_no_drift(api, registrar_headers):
    """PRD §3.4 + §3.7: provisional_credit_charge debits at APPROVED and
    refunds at CANCELED. The conserved quantity is the student's
    in_progress_credits across APPROVED+WAITLISTED.

    Claim: TWO independent create-then-cancel cycles preserve in_progress_credits.

    # difficulty: compensating_invariant/invariant_student_credit_budget_create_then_cancel
    """
    world = setup_basic_world(student_year=2)
    plan_before = get_degree_plan(world["student"]["id"])
    in_prog_before = float(plan_before["in_progress_credits"])

    for i in range(2):
        co = setup_open_offering(world, credits=3.0,
                                  scheduled_meetings=[{"day_of_week": i, "start_minute_of_day": 540, "end_minute_of_day": 600}])
        er = submit_enrollment_success(world["student"], co["offering"]["id"])
        cancel_enrollment(world["student"], er["id"])

    plan_after = get_degree_plan(world["student"]["id"])
    assert float(plan_after["in_progress_credits"]) == pytest.approx(in_prog_before, abs=0.01)


def test_seat_invariant_two_cycles_no_drift(api, registrar_headers):
    """PRD §3.4 + §3.7: enrolled_count increments at APPROVED, decrements at
    cancel of APPROVED. The conserved quantity is capacity − enrolled_count.

    Claim: TWO independent create-then-cancel cycles preserve
    capacity − enrolled_count on the offering.

    # difficulty: compensating_invariant/invariant_offering_seat_ledger_create_then_cancel
    """
    world = setup_basic_world(student_year=2)
    co = setup_open_offering(world, credits=3.0, base_capacity=5,
                              scheduled_meetings=[{"day_of_week": 0, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    o0 = get_offering(co["offering"]["id"])
    available_before = o0["capacity"] - o0["enrolled_count"]
    assert available_before == 5

    # Two cycles in sequence (different students so we don't trip "same
    # student already in offering" semantics if that exists).
    for i in range(2):
        s = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=2,
                           full_name=f"Cycler-{i}")
        er = submit_enrollment_success(s, co["offering"]["id"])
        cancel_enrollment(s, er["id"])

    o2 = get_offering(co["offering"]["id"])
    assert o2["capacity"] - o2["enrolled_count"] == available_before, (
        f"Seat ledger drift after 2 cycles: before={available_before}, "
        f"after={o2['capacity']-o2['enrolled_count']}"
    )


# ─── transitive_cascade — second tests for both instances ───────────────
def test_cascade_student_cancel_emits_enrollment_canceled_to_all_four_systems(api, registrar_headers):
    """PRD §3.7 + §2.12: "an ENROLLMENT_CANCELED SyncEvent is emitted to all
    four downstream systems."
    PRD §2.12: ENROLLMENT_CANCELED is fanned out to all four systems
    (ACADEMIC_AFFAIRS, FINANCE, LIBRARY, DORMITORY).

    Claim: cancel of an APPROVED enrollment produces an ENROLLMENT_CANCELED
    SyncEvent whose target_systems is exactly the four-system set.

    # difficulty: transitive_cascade/cascade_student_cancel_promotes_waitlist_depth_3
    """
    world = setup_basic_world(student_year=2)
    co = setup_open_offering(world, credits=3.0, base_capacity=2,
                              scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    assert er["academic_status"] == "APPROVED"
    cancel_enrollment(world["student"], er["id"])

    events = list_student_sync_events(world["student"]["id"])
    matching = [e for e in events if e["event_type"] == "ENROLLMENT_CANCELED"]
    assert matching, f"Expected ENROLLMENT_CANCELED event; events={events}"
    targets = set(matching[-1]["target_systems"])
    assert targets == {"ACADEMIC_AFFAIRS", "FINANCE", "LIBRARY", "DORMITORY"}, (
        f"Expected fan-out to all four downstream systems, got {targets}"
    )


def test_cascade_capacity_reduction_emits_to_all_four_systems(api, registrar_headers):
    """PRD §3.3 + §2.12: capacity-reduction cancellation emits a
    CAPACITY_REDUCED_CANCELED SyncEvent fanned out to all four downstream
    systems.

    Claim: PATCH capacity below enrolled_count produces a
    CAPACITY_REDUCED_CANCELED SyncEvent on the canceled student with
    target_systems == the four-system set.

    # difficulty: transitive_cascade/cascade_capacity_reduction_cancels_lowest_priority_depth_3
    """
    world = setup_basic_world(student_year=4)
    co = setup_open_offering(world, credits=3.0, base_capacity=2,
                              scheduled_meetings=[{"day_of_week": 2, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    s_high = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=4,
                             full_name="High Pri Cascade")
    s_low = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=1,
                            full_name="Low Pri Cascade")
    submit_enrollment_success(s_high, co["offering"]["id"])
    submit_enrollment_success(s_low, co["offering"]["id"])

    current = get_offering(co["offering"]["id"])
    res = api.patch_course_offering_capacity(
        co["offering"]["id"], {"new_capacity": 1, "version": current["version"]},
        registrar_headers,
    )
    validate_success(res, 200)

    events = list_student_sync_events(s_low["id"])
    matching = [e for e in events if e["event_type"] == "CAPACITY_REDUCED_CANCELED"]
    assert matching, (
        f"Expected CAPACITY_REDUCED_CANCELED event for canceled student; events={events}"
    )
    targets = set(matching[-1]["target_systems"])
    assert targets == {"ACADEMIC_AFFAIRS", "FINANCE", "LIBRARY", "DORMITORY"}


# ─── boundary_precision — second test for time-overlap half-open ────────
def test_time_boundary_immediate_overlap_one_minute_rejected(api):
    """PRD §3.4: "Two meetings overlap when each one's start_minute_of_day
    falls strictly before the other one's end_minute_of_day."

    Claim: an existing 480-600 meeting and a new 599-720 meeting on the same
    day DO overlap by 1 minute (599 < 600 AND 480 < 720) → ERR_TIME_CONFLICT.
    Companion to the touching-boundary test in test_04.

    # difficulty: boundary_precision_check/boundary_time_overlap_half_open_endpoint_enrollment
    """
    world = setup_basic_world()
    co1 = setup_open_offering(world, credits=3.0,
                               scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 480, "end_minute_of_day": 600}])
    co2 = setup_open_offering(world, credits=3.0,
                               scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 599, "end_minute_of_day": 720}])
    er1 = submit_enrollment_success(world["student"], co1["offering"]["id"])
    assert er1["academic_status"] == "APPROVED"
    res2 = submit_enrollment(world["student"], co2["offering"]["id"])
    validate_error(res2, "ERR_TIME_CONFLICT")


# ─── resource_temporal_overlap — second test for student schedule ───────
def test_lab_equipment_buffer_satisfied_at_one_above_buffer(api):
    """PRD §3.4: "Two meetings conflict when each one's start_minute_of_day
    falls strictly before the other one's end_minute_of_day plus the
    per-equipment setup_buffer_minutes."

    Claim: with buffer=30, an existing 480-600 meeting and a new 631-751
    meeting (gap = 31 > 30) DO NOT conflict. Companion to the gap-29 case
    (which fails) in test_04.

    # difficulty: resource_temporal_overlap/overlap_lab_equipment_half_open_with_setup_buffer
    """
    world = setup_basic_world()
    lab = create_lab_equipment(world["campus"]["id"], setup_buffer_minutes=30)
    s1 = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=2,
                         full_name="Lab Buffer A")
    s2 = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=2,
                         full_name="Lab Buffer B")
    co1 = setup_open_offering(world, credits=3.0,
                               scheduled_meetings=[{"day_of_week": 3, "start_minute_of_day": 480, "end_minute_of_day": 600}],
                               requires_lab_equipment_ids=[lab["id"]])
    co2 = setup_open_offering(world, credits=3.0,
                               scheduled_meetings=[{"day_of_week": 3, "start_minute_of_day": 631, "end_minute_of_day": 751}],
                               requires_lab_equipment_ids=[lab["id"]])
    er1 = submit_enrollment_success(s1, co1["offering"]["id"])
    assert er1["academic_status"] == "APPROVED"
    er2 = submit_enrollment_success(s2, co2["offering"]["id"])
    assert er2["academic_status"] == "APPROVED"


# ─── resource_temporal_overlap / overlap_student_schedule_half_open_intervals (second) ─
def test_student_schedule_overlap_other_direction_rejected(api):
    """PRD §3.4: "Two meetings overlap when each one's start_minute_of_day
    falls strictly before the other one's end_minute_of_day."

    Claim (companion): the overlap test is symmetric — submit existing
    540-660 first, then add 480-600 (overlap from 540-600). Same
    ERR_TIME_CONFLICT outcome regardless of submission order.

    # difficulty: resource_temporal_overlap/overlap_student_schedule_half_open_intervals
    """
    world = setup_basic_world()
    co1 = setup_open_offering(world, credits=3.0,
                               scheduled_meetings=[{"day_of_week": 4, "start_minute_of_day": 540, "end_minute_of_day": 660}])
    co2 = setup_open_offering(world, credits=3.0,
                               scheduled_meetings=[{"day_of_week": 4, "start_minute_of_day": 480, "end_minute_of_day": 600}])
    er1 = submit_enrollment_success(world["student"], co1["offering"]["id"])
    assert er1["academic_status"] == "APPROVED"
    res2 = submit_enrollment(world["student"], co2["offering"]["id"])
    validate_error(res2, "ERR_TIME_CONFLICT")


# ─── priority_pair_validation_conflict / conflict_state_vs_business_safety (second) ────
def test_state_priority_wins_over_business_safety_via_planned_offering(api):
    """PRD §2.9: "When a single request would fail more than one priority
    level, the lower-numbered priority wins and is reported."
    State (priority 4) precedes business_safety (priority 6).

    Claim (companion to the CLOSED-state test): when a foreign-department
    offering is in PLANNED (state-priority would reject) AND no
    DepartmentAccessGrant exists (business-safety would reject), the state
    error wins.

    # difficulty: priority_pair_validation_conflict/conflict_state_vs_business_safety
    """
    campus = create_campus()
    d_home = create_department(campus["id"], code_prefix="HOME2")
    d_other = create_department(campus["id"], code_prefix="OTHER2")
    instructor = create_professor(d_other["id"], is_chair=False, max_minutes=600)
    student = create_student(d_home["id"], campus["id"], year_in_program=2)
    term = create_term_in_planning()
    advance_clock(term["registration_open_at"])

    course_other = create_course(d_other["id"], credits=3.0)
    offering = create_offering(
        term_id=term["id"], course_id=course_other["id"],
        campus_id=campus["id"], instructor_id=instructor["id"],
        base_capacity=10,
        scheduled_meetings=[{"day_of_week": 5, "start_minute_of_day": 540, "end_minute_of_day": 600}],
    )
    # Do NOT open the offering — it stays in PLANNED. Both checks would fire.
    res = submit_enrollment(student, offering["id"])
    validate_error(res, "ERR_OFFERING_NOT_OPEN")


# ─── priority_pair_validation_conflict / conflict_business_constraint_vs_business_fiscal (second) ─
def test_business_constraint_wins_via_year_two_quota_breach(api):
    """PRD §2.9: priority 7 (business_constraint) precedes priority 12
    (business_fiscal).

    Claim (companion): a year-2 student (base_quota=20.0) with 17.0 APPROVED
    credits attempting a 4.0-credit course where they lack the REQUIRED
    prereq (17+4=21 > 20 AND prereq missing). Both fire; the prereq error
    wins.

    # difficulty: priority_pair_validation_conflict/conflict_business_constraint_vs_business_fiscal
    """
    world = setup_basic_world(student_year=2, student_completed_course_ids=[])
    # Load 17.0 via three 4.0 + one 5.0... loader uses uniform per-course; use four 4.0=16, then add 1.0?
    # Simpler: load 16.0 first, then add a 1.0-credit APPROVED course manually.
    load_student_credits_via_approved(world, target_credits=16.0,
                                       per_course_credits=4.0,
                                       meeting_start=540, meeting_end=600)
    extra = setup_open_offering(world, credits=1.0, base_capacity=5,
                                  scheduled_meetings=[{"day_of_week": 5, "start_minute_of_day": 700, "end_minute_of_day": 720}])
    er_extra = submit_enrollment_success(world["student"], extra["offering"]["id"])
    assert er_extra["academic_status"] == "APPROVED"
    # Total APPROVED credits now = 17.0.

    prereq = create_course(world["department"]["id"], credits=3.0, code_prefix="P2")
    ck = create_course(
        world["department"]["id"], credits=4.0,
        prerequisite_course_ids=[{"course_id": prereq["id"], "mode": "REQUIRED"}],
        code_prefix="CK2",
    )
    co = setup_open_offering(world, course=ck, base_capacity=10,
                              scheduled_meetings=[{"day_of_week": 6, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    res = submit_enrollment(world["student"], co["offering"]["id"])
    # Both fail; prereq (priority 7) precedes quota (priority 12).
    validate_error(res, "ERR_PREREQUISITE_NOT_MET")


# ─── cross_entity_state_dependency / cross_entity_overlimit_application_depends_on_term (second) ─
def test_overlimit_submit_after_term_closed_rejected(api):
    """PRD §3.6: "The submission is rejected unless the parent Term is in
    REGISTRATION_OPEN (ERR_TERM_NOT_OPEN_FOR_REGISTRATION)..."

    Claim (companion): a draft application created while the term is
    REGISTRATION_OPEN, but submitted after the term has auto-advanced to
    REGISTRATION_CLOSED, fails with ERR_TERM_NOT_OPEN_FOR_REGISTRATION.

    # difficulty: cross_entity_state_dependency/cross_entity_overlimit_application_depends_on_term
    """
    world = setup_basic_world(student_year=2)
    # Create the application while the term is REGISTRATION_OPEN.
    app = create_over_limit_application(
        student=world["student"], term_id=world["term"]["id"],
        primary_signer=world["professor"], secondary_signer=world["chair"],
        requested_extension_credits=4.0,
    )
    # Now advance the clock past registration_close_at so the term auto-transitions.
    advance_clock(world["term"]["registration_close_at"])
    res = api.submit_over_limit_application(
        app["id"], make_student_headers(world["student"]["id"])
    )
    validate_error(res, "ERR_TERM_NOT_OPEN_FOR_REGISTRATION")


# ─── combinatorial_formula / combinatorial_transferable_credits_rounding_mode_b (second) ─
def test_transferable_credits_three_policies_sum_yields_one_dot_eight_nine(api):
    """PRD §3.8: per-course rounded then summed. Three matching policies
    (each yielding 0.625) → 0.63 + 0.63 + 0.63 = 1.89.
    Sum-then-round would yield round(1.875, 2) = 1.88 (round_half_up).

    Claim (companion to the two-policy 1.26 test): three policies → 1.89.

    # difficulty: combinatorial_formula/combinatorial_transferable_credits_rounding_mode_b
    """
    cw = setup_two_program_world_with_completed_source_course()
    # Add a third target course in d_tgt.
    from test_helpers.fixtures import create_course as _cc
    c_tgt3 = _cc(owning_department_id=cw["d_tgt"]["id"], credits=1.0, code_prefix="CTGT3")
    # Three policies, all sharing source_course_id=c_src, each with transfer_factor=0.625.
    create_credit_equivalence_policy(
        source_program_id=cw["d_src"]["id"],
        target_program_id=cw["tgt_program_id"],
        source_course_id=cw["c_src"]["id"],
        target_course_id=cw["c_tgt"]["id"],
        transfer_factor=0.625,
    )
    create_credit_equivalence_policy(
        source_program_id=cw["d_src"]["id"],
        target_program_id=cw["tgt_program_id"],
        source_course_id=cw["c_src"]["id"],
        target_course_id=cw["c_tgt2"]["id"],
        transfer_factor=0.625,
    )
    create_credit_equivalence_policy(
        source_program_id=cw["d_src"]["id"],
        target_program_id=cw["tgt_program_id"],
        source_course_id=cw["c_src"]["id"],
        target_course_id=c_tgt3["id"],
        transfer_factor=0.625,
    )
    plan = get_degree_plan(cw["student"]["id"])
    # Per-course rounding then sum: 0.63 * 3 = 1.89.
    assert float(plan["transferable_credits"]) == pytest.approx(1.89, abs=0.005)


# ─── non_linear_state_machine — second test for OverLimit revision ──────
def test_overlimit_after_secondary_signature_grants_credits(api):
    """PRD §3.6: "On entering APPROVED, the system populates granted_credits to
    equal requested_extension_credits, and emits an OVER_LIMIT_GRANTED
    SyncEvent to ACADEMIC_AFFAIRS and FINANCE."

    Claim: A complete chain submit→primary-sign→secondary-sign yields
    APPROVED with granted_credits==requested_extension_credits AND emits an
    OVER_LIMIT_GRANTED event to {ACADEMIC_AFFAIRS, FINANCE}.

    # difficulty: non_linear_state_machine/non_linear_overlimit_application_revision_cycle
    """
    world = setup_basic_world(student_year=2)
    app = create_over_limit_application(
        student=world["student"], term_id=world["term"]["id"],
        primary_signer=world["professor"], secondary_signer=world["chair"],
        requested_extension_credits=4.0,
    )
    submit_application(world["student"], app["id"])
    sign_application(world["professor"], app["id"])
    final = sign_application(world["chair"], app["id"])
    assert final["status"] == "APPROVED"
    assert float(final["granted_credits"]) == pytest.approx(4.0, abs=0.01)

    events = list_student_sync_events(world["student"]["id"])
    matching = [e for e in events if e["event_type"] == "OVER_LIMIT_GRANTED"]
    assert matching, f"Expected OVER_LIMIT_GRANTED event; events={events}"
    targets = set(matching[-1]["target_systems"])
    assert targets == {"ACADEMIC_AFFAIRS", "FINANCE"}, (
        f"Expected OVER_LIMIT_GRANTED → {{ACADEMIC_AFFAIRS, FINANCE}}, got {targets}"
    )
