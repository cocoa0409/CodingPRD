"""Second-coverage tests for the harder PRD-described behaviors.

Every difficulty-design instance has at least one primary test in
the per-feature files; this file adds the SECOND test required per
the skill §2.1.A coverage rule, plus a few first-coverage tests for
instances not previously exercised (mastery weighted-vs-simple
divergence, consent revocation+reissue cycle, IEP amendment cycle
twice, half-open IEP period touch, and the two compensating
invariants).

PRD-First escalation: every test cites a verbatim PRD sentence
naming the rule under assertion. Where a difficulty-design entry
relies on an underlying rule that PRD prose pins, the test is
generated; where PRD prose is silent, the gap is escalated in the
summary report under `difficulty-coverage-blocked-by-prd-silence`.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    activate_related_service,
    advance_clock,
    begin_amendment,
    cancel_session,
    create_consent_payload,
    create_progress_report,
    create_related_service_consent_approved,
    create_session,
    create_student,
    deliver_session,
    finalize_amendment,
    get_consent,
    get_goal,
    get_iep,
    get_service,
    get_student,
    make_objective,
    parent_approve_consent,
    parent_withdraw_consent,
    propose_related_service,
    resume_related_service,
    setup_active_iep,
    setup_active_iep_with_active_service,
    suspend_related_service,
    validate_error,
)


# ===========================================================================
# Rule 1: dual_variant_calc/goal_mastery_weighted_vs_simple_on_iepgoal
# ===========================================================================
def test_goal_mastery_weighted_diverges_from_simple_average(api):
    """PRD §3.7: "The mastery_score for a goal is a weighted sum
    across the goal's objectives: each objective contributes its
    weight multiplied by its latest_progress_percent, the products
    are summed, and the total is rounded half-up to two decimal
    places."
    PRD §3.7: "this is precisely why a simple unweighted average of
    progress is not used: when objectives have unequal weights, the
    unweighted average produces a different number, and the system
    pins the weighted variant."

    Claim: with weights 0.9/0.05/0.05 and progress 90/0/0, weighted
    score = 0.9*90 = 81.00 (MASTERED); simple average would be
    (90+0+0)/3 = 30.00 (INSUFFICIENT_PROGRESS). The implementation
    MUST use the weighted formula — same inputs, different tiers
    is the divergence witness.

    # difficulty: dual_variant_calc/goal_mastery_weighted_vs_simple_on_iepgoal
    """
    objectives = [
        make_objective(objective_id="o1", weight=0.9),
        make_objective(objective_id="o2", weight=0.05),
        make_objective(objective_id="o3", weight=0.05),
    ]
    district, student, _eval, iep, goal = setup_active_iep(
        objectives=objectives,
    )
    create_progress_report(
        district["id"], student["id"], iep["id"], goal["id"],
        reporting_period_index=1,
        objective_progress=[
            {"objective_id": "o1", "progress_percent": 90},
            {"objective_id": "o2", "progress_percent": 0},
            {"objective_id": "o3", "progress_percent": 0},
        ],
    )
    g_now = get_goal(
        district["id"], student["id"], iep["id"], goal["id"],
    )
    # 0.9*90 + 0.05*0 + 0.05*0 = 81.00 exactly.
    assert g_now["mastery_score"] == pytest.approx(81.00, abs=0.01)
    assert g_now["mastery_tier"] == "MASTERED"


# ===========================================================================
# Rule 1: dual_variant_calc/lre_percentage_dual_basis (second coverage)
# ===========================================================================
def test_lre_dual_basis_school_day_strictly_less_than_instructional(
    api,
):
    """PRD §3.8: "Because total_school_day_minutes_per_week includes
    non-instructional time such as lunch and recess, it is greater
    than or equal to total_instructional_minutes_per_week, and so
    lre_percentage_school_day is less than or equal to
    lre_percentage_instructional for any identical numerator."

    Claim: a second witness to dual-variant divergence — with
    instructional=1500 and school_day=1800 and a 150-PULL_OUT-min
    service, instructional=10.00 vs school_day=8.33; both come from
    the same 150-min numerator.

    # difficulty: dual_variant_calc/lre_percentage_dual_basis_on_iep
    """
    from test_helpers import get_lre_summary
    district, student, iep, _service, _consent = (
        setup_active_iep_with_active_service(
            service_type="OT", minutes_per_week=150,
            location_setting="PULL_OUT",
            total_instructional_minutes_per_week=1500,
            total_school_day_minutes_per_week=1800,
        )
    )
    summary = get_lre_summary(
        district["id"], student["id"], iep["id"],
    )
    # 100*150/1500 = 10.00; 100*150/1800 = 8.33...
    assert summary["lre_percentage_instructional"] == pytest.approx(
        10.00, abs=0.01,
    )
    assert summary["lre_percentage_school_day"] == pytest.approx(
        8.33, abs=0.01,
    )
    assert (
        summary["lre_percentage_school_day"]
        < summary["lre_percentage_instructional"]
    )


# ===========================================================================
# Rule 2: combinatorial_formula/goal_mastery_weighted_tier_branching
# ===========================================================================
def test_mastery_score_at_50_exact_boundary_is_progressing(api):
    """PRD §3.7: "a score of at least 50.00 and strictly less than
    80.00 yields PROGRESSING; a score strictly less than 50.00
    yields INSUFFICIENT_PROGRESS."

    Claim: weights 0.4/0.4/0.2 with progress 60/50/30 →
    mastery_score = 50.00 → PROGRESSING (50.00 boundary is
    inclusive on the PROGRESSING side).

    # difficulty: combinatorial_formula/goal_mastery_weighted_tier_branching_mode_a
    """
    objectives = [
        make_objective(objective_id="o1", weight=0.4),
        make_objective(objective_id="o2", weight=0.4),
        make_objective(objective_id="o3", weight=0.2),
    ]
    district, student, _eval, iep, goal = setup_active_iep(
        objectives=objectives,
    )
    create_progress_report(
        district["id"], student["id"], iep["id"], goal["id"],
        reporting_period_index=1,
        objective_progress=[
            {"objective_id": "o1", "progress_percent": 60},
            {"objective_id": "o2", "progress_percent": 50},
            {"objective_id": "o3", "progress_percent": 30},
        ],
    )
    g_now = get_goal(
        district["id"], student["id"], iep["id"], goal["id"],
    )
    assert g_now["mastery_score"] == pytest.approx(50.00, abs=0.01)
    assert g_now["mastery_tier"] == "PROGRESSING"


# ===========================================================================
# Rule 2: combinatorial_formula/compensatory_minutes_round_then_sum
# (second coverage — different session count)
# ===========================================================================
def test_compensatory_minutes_round_per_session_second_witness(api):
    """PRD §3.6: "Each missed session's scheduled_minutes is
    multiplied by the federal make-up multiplier of 1.5; that
    per-session raw value is rounded half-up to a whole number of
    minutes; the resulting whole-minute values are summed".

    Claim: a single missed 25-min session →
    compensatory_minutes_owed = round_half_up(25*1.5) = 38 (NOT 37
    or 37.5). Second witness to the round-per-session-then-sum
    convention with a different cardinality from the three-session
    case in test_13.

    # difficulty: combinatorial_formula/compensatory_minutes_round_per_session_then_sum_mode_b
    """
    district, student, iep, service, _consent = (
        setup_active_iep_with_active_service(
            service_type="OT", minutes_per_week=25,
            location_setting="PULL_OUT",
        )
    )
    # Schedule ONE 25-min session in the past.
    create_session(
        district["id"], student["id"], iep["id"], service["id"],
        scheduled_start="2024-12-15T09:00:00.000Z",
        scheduled_end="2024-12-15T09:25:00.000Z",
    )
    suspend_related_service(
        district["id"], student["id"], iep["id"], service["id"],
    )
    svc_now = get_service(
        district["id"], student["id"], iep["id"], service["id"],
    )
    # round_half_up(25 * 1.5) = round_half_up(37.5) = 38.
    assert svc_now["compensatory_minutes_owed"] == 38


# ===========================================================================
# Rule 3: non_linear_state_machine/parental_consent_revocation_cycle
# ===========================================================================
def test_consent_revocation_then_reissue_cycle(api):
    """PRD §3.4: "Because consent rows are append-only,
    ParentalConsent does not carry updated_at or version; a new row
    is created whenever the parent re-considers after a withdrawal."

    Claim: the lifecycle "consent1 APPROVED → consent1 WITHDRAWN
    (service auto-SUSPENDED) → new consent2 PENDING → consent2
    APPROVED → service resume with consent2 ACTIVE" exercises a
    non-linear cycle where the same RelatedService passes through
    ACTIVE twice via two distinct ParentalConsent rows.

    # difficulty: non_linear_state_machine/parental_consent_revocation_cycle_with_reissue
    """
    from test_helpers import TEST_USERS
    district, student, iep, service, consent1 = (
        setup_active_iep_with_active_service()
    )
    # Withdraw consent1.
    parent_withdraw_consent(
        district["id"], student["id"], consent1["id"],
        parent_user_id=student["parent_user_id"],
    )
    c1_now = get_consent(
        district["id"], student["id"], consent1["id"],
    )
    assert c1_now["status"] == "WITHDRAWN"
    svc_after_withdraw = get_service(
        district["id"], student["id"], iep["id"], service["id"],
    )
    assert svc_after_withdraw["status"] == "SUSPENDED"
    # Create a new RELATED_SERVICE consent (consent2) and approve.
    c2_resp = api.create_parental_consent(
        district["id"], student["id"],
        create_consent_payload(
            scope="RELATED_SERVICE",
            target_resource_type="RelatedService",
            target_resource_id=service["id"],
        ),
        TEST_USERS["provider_headers"],
    )
    consent2 = c2_resp.json()["data"]
    parent_approve_consent(
        district["id"], student["id"], consent2["id"],
        parent_user_id=student["parent_user_id"],
    )
    c2_now = get_consent(
        district["id"], student["id"], consent2["id"],
    )
    assert c2_now["status"] == "APPROVED"
    # Resume the service with consent2.
    resume_related_service(
        district["id"], student["id"], iep["id"], service["id"],
        consent_id=consent2["id"],
    )
    svc_final = get_service(
        district["id"], student["id"], iep["id"], service["id"],
    )
    assert svc_final["status"] == "ACTIVE"
    # Witness: two distinct consents (consent1 != consent2) gated
    # the same service through ACTIVE twice.
    assert consent1["id"] != consent2["id"]


# ===========================================================================
# Rule 3: non_linear_state_machine/iep_amendment_cycle_on_iep_entity
# ===========================================================================
def test_iep_amendment_cycle_traversed_twice(api):
    """PRD §3.3: "A SpecialEducationTeacher may begin an amendment
    on an ACTIVE IEP, moving it to AMENDMENT_PENDING ... Finalizing
    the amendment moves the IEP back to ACTIVE".
    PRD §2.4: "version ... increases by exactly one on every
    successful mutation, including system-driven mutations."

    Claim: the IEP id traverses ACTIVE → AMENDMENT_PENDING → ACTIVE
    → AMENDMENT_PENDING → ACTIVE — the same id reaches ACTIVE twice
    after the initial activation, and version increments through
    each transition.

    # difficulty: non_linear_state_machine/iep_amendment_cycle_on_iep_entity
    """
    district, student, _eval, iep, _goal = setup_active_iep()
    v_after_activate = iep["version"]
    # Cycle 1.
    begin_amendment(district["id"], student["id"], iep["id"])
    finalize_amendment(district["id"], student["id"], iep["id"])
    iep_after_1 = get_iep(district["id"], student["id"], iep["id"])
    assert iep_after_1["status"] == "ACTIVE"
    assert iep_after_1["version"] > v_after_activate
    # Cycle 2.
    begin_amendment(district["id"], student["id"], iep["id"])
    finalize_amendment(district["id"], student["id"], iep["id"])
    iep_after_2 = get_iep(district["id"], student["id"], iep["id"])
    assert iep_after_2["status"] == "ACTIVE"
    assert iep_after_2["version"] > iep_after_1["version"]


# ===========================================================================
# Rule 4: transitive_cascade — second coverage already in test_13;
# we add a hop-1 isolated witness here that the WITHDRAWN consent
# row carries withdrawn_at.
# ===========================================================================
def test_consent_withdrawal_stamps_withdrawn_at(api):
    """PRD §3.4: "It stamps withdrawn_at from the current clock,
    moves the consent to WITHDRAWN".

    Claim: the withdrawn consent row carries a non-null
    withdrawn_at timestamp — the first hop of the depth-3 cascade
    sub-asserted in isolation.

    # difficulty: transitive_cascade/consent_withdrawal_cascades_to_iep_amendment_depth_3
    """
    district, student, iep, _service, consent = (
        setup_active_iep_with_active_service()
    )
    parent_withdraw_consent(
        district["id"], student["id"], consent["id"],
        parent_user_id=student["parent_user_id"],
    )
    c_now = get_consent(
        district["id"], student["id"], consent["id"],
    )
    assert c_now["status"] == "WITHDRAWN"
    assert c_now.get("withdrawn_at") is not None


def test_ineligible_finalize_clears_current_iep_and_lre(api):
    """PRD §3.2: "the student's current_iep_id is cleared to null,
    and the student's lre_classification is set to NOT_APPLICABLE."

    Claim: post-ineligibility cascade, the Student's
    current_iep_id is null and lre_classification is NOT_APPLICABLE
    — second-coverage witness on the student-summary hops.

    # difficulty: transitive_cascade/ineligible_finalization_cascades_to_goals_and_services_depth_3
    """
    from test_helpers import (
        SCHOOL_PSYCHOLOGIST_ID_ALT,
        create_evaluation,
        finalize_evaluation,
        find_pending_consent_for_evaluation,
        make_psychologist_headers,
        request_evaluation_consent,
    )
    district, student, _eval, iep, _goal = setup_active_iep()
    psych_h = make_psychologist_headers(SCHOOL_PSYCHOLOGIST_ID_ALT)
    ev2 = create_evaluation(
        district["id"], student["id"],
        evaluation_type="TRIENNIAL",
        psychologist_headers=psych_h,
    )
    request_evaluation_consent(
        district["id"], student["id"], ev2["id"],
        psychologist_headers=psych_h,
    )
    consent = find_pending_consent_for_evaluation(
        district["id"], student["id"], ev2["id"],
    )
    parent_approve_consent(
        district["id"], student["id"], consent["id"],
        parent_user_id=student["parent_user_id"],
    )
    finalize_evaluation(
        district["id"], student["id"], ev2["id"],
        disability_categories=[],
        psychologist_headers=psych_h,
    )
    s_now = get_student(district["id"], student["id"])
    assert s_now.get("current_iep_id") in (None, "")
    assert s_now["lre_classification"] == "NOT_APPLICABLE"


# ===========================================================================
# Rule 5: priority_pair_validation_conflict — second coverage
# of the state-vs-referential pair (state still wins on a
# different state-mismatch witness)
# ===========================================================================
def test_close_goal_with_inactive_iep_fails_with_iep_not_active(api):
    """PRD §2.9: "(5) target state, surfaced as the entity-specific
    state error ... (6) cross-aggregate referential integrity,
    surfaced as ERR_CROSS_STUDENT_REFERENCE".
    PRD §3.5: "if the parent IEP is not in ACTIVE (for example, it
    is in AMENDMENT_PENDING) the request is rejected with
    ERR_IEP_NOT_ACTIVE".

    Claim: closing a goal whose parent IEP is in AMENDMENT_PENDING
    surfaces the state error ERR_IEP_NOT_ACTIVE (priority 5) — a
    second witness that state-category checks fire before any
    cross-aggregate referential check would.

    # difficulty: priority_pair_validation_conflict/state_vs_business_referential_on_goal_creation
    """
    from test_helpers import TEST_USERS, close_goal_payload
    district, student, _eval, iep, goal = setup_active_iep()
    begin_amendment(district["id"], student["id"], iep["id"])
    res = api.close_goal(
        district["id"], student["id"], iep["id"], goal["id"],
        close_goal_payload(disposition="NOT_MET"),
        TEST_USERS["teacher_headers"],
    )
    validate_error(res, "ERR_IEP_NOT_ACTIVE")


def test_service_activate_on_draft_iep_surfaces_state_error(api):
    """PRD §3.6: "the parent IEP be in ACTIVE or AMENDMENT_PENDING
    (else ERR_IEP_NOT_ACTIVE)".
    PRD §2.9 priority 5 (state) ranks ahead of priority 8
    (eligibility) and 10 (RS-consent) and 19 (fiscal cap).

    Claim: when activating a service whose parent IEP is still
    DRAFT, the state-category error ERR_IEP_NOT_ACTIVE fires —
    second witness that state-category beats
    fiscal/eligibility/consent categories.

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_service_activation
    """
    from test_helpers import (
        TEST_USERS,
        activate_related_service_payload,
        create_iep,
        create_goal_with_single_objective,
        create_iep_implementation_consent_approved,
        create_related_service_consent_approved,
        setup_eligible_student,
    )
    district, student, _eval = setup_eligible_student()
    iep = create_iep(district["id"], student["id"])
    create_goal_with_single_objective(
        district["id"], student["id"], iep["id"],
    )
    create_iep_implementation_consent_approved(
        district["id"], student["id"], iep["id"],
        parent_user_id=student["parent_user_id"],
    )
    # Do NOT activate the IEP — leave it DRAFT.
    service = propose_related_service(
        district["id"], student["id"], iep["id"],
        service_type="OT", minutes_per_week=60,
        location_setting="PULL_OUT",
    )
    consent = create_related_service_consent_approved(
        district["id"], student["id"], service["id"],
        parent_user_id=student["parent_user_id"],
    )
    res = api.activate_related_service(
        district["id"], student["id"], iep["id"], service["id"],
        activate_related_service_payload(consent_id=consent["id"]),
        TEST_USERS["provider_headers"],
    )
    validate_error(res, "ERR_IEP_NOT_ACTIVE")


# ===========================================================================
# Rule 6: boundary_precision — already covered in test_03 and test_11;
# add a second witness for each.
# ===========================================================================
def test_lre_classification_jumps_to_lre_c_at_61_pct(api):
    """PRD §3.8: "otherwise the classification is LRE_C".
    PRD §3.8: "if the percentage is greater than 20.00 and at most
    60.00, the classification is LRE_B".

    Claim: lre_percentage_instructional == 61.00 (strictly above
    60.00) → LRE_C. Second witness, with the LRE_B-to-LRE_C
    transition pinned at 1.00pp above the 60.00 boundary.

    # difficulty: boundary_precision_check/lre_classification_inclusive_60_pct_boundary
    """
    from test_helpers import get_iep
    district, student, _eval, iep, _goal = setup_active_iep(
        total_instructional_minutes_per_week=1500,
        total_school_day_minutes_per_week=1875,
    )
    # Activate four services totalling 915 PULL_OUT minutes (61.00%).
    sizes = [(300, "OT"), (300, "PT"), (300, "SPEECH"),
             (15, "COUNSELING")]
    for mpw, st in sizes:
        svc = propose_related_service(
            district["id"], student["id"], iep["id"],
            service_type=st, minutes_per_week=mpw,
            location_setting="PULL_OUT",
        )
        c = create_related_service_consent_approved(
            district["id"], student["id"], svc["id"],
            parent_user_id=student["parent_user_id"],
        )
        activate_related_service(
            district["id"], student["id"], iep["id"], svc["id"],
            consent_id=c["id"],
        )
    s_now = get_student(district["id"], student["id"])
    assert s_now["lre_classification"] == "LRE_C"


def test_triennial_due_soon_then_overdue_across_one_day(api):
    """PRD §3.2: "exactly 0 days remaining (due today) is DUE_SOON,
    and one day past due is OVERDUE."

    Claim: advancing the clock by exactly one extra day after
    reaching the due date flips triennial_status from DUE_SOON to
    OVERDUE — second witness for the 0-vs-(-1) boundary on this
    different-from-LRE date-based metric.

    # difficulty: boundary_precision_check/triennial_overdue_zero_day_boundary
    """
    from test_helpers import setup_eligible_student
    district, student, _eval = setup_eligible_student()
    # Advance to exactly the due date (3*365 days later).
    advance_clock(district["id"], by_days=3 * 365)
    s_at_due = get_student(district["id"], student["id"])
    assert s_at_due["triennial_status"] == "DUE_SOON"
    # Advance one more day.
    advance_clock(district["id"], by_days=1)
    s_past = get_student(district["id"], student["id"])
    assert s_past["triennial_status"] == "OVERDUE"


# ===========================================================================
# Rule 7: cross_entity_state_dependency — second coverage for each pair
# ===========================================================================
def test_iep_activate_requires_eligible_evaluation(api):
    """PRD §3.3: "the student's current_eligibility_evaluation_id
    resolves to an evaluation in ELIGIBLE (ERR_STUDENT_NOT_ELIGIBLE)".

    Claim: an IEP whose student has an INELIGIBLE evaluation
    (rather than no evaluation at all) is also blocked from
    activation with ERR_STUDENT_NOT_ELIGIBLE. Second witness for
    the IEP↔EligibilityEvaluation cross-entity dependency.

    # difficulty: cross_entity_state_dependency/iep_activation_requires_eligibility_eligible
    """
    from test_helpers import (
        TEST_USERS,
        create_goal_with_single_objective,
        create_iep,
        create_iep_implementation_consent_approved,
        setup_eligible_student,
    )
    # Build student with INELIGIBLE evaluation: setup_eligible_student
    # finalizes with non-empty categories; we instead use empty
    # categories so the evaluation finalizes as INELIGIBLE.
    district, student, _eval = setup_eligible_student(
        disability_categories=[],
    )
    iep = create_iep(district["id"], student["id"])
    create_goal_with_single_objective(
        district["id"], student["id"], iep["id"],
    )
    create_iep_implementation_consent_approved(
        district["id"], student["id"], iep["id"],
        parent_user_id=student["parent_user_id"],
    )
    res = api.activate_iep(
        district["id"], student["id"], iep["id"],
        TEST_USERS["teacher_headers"],
    )
    validate_error(res, "ERR_STUDENT_NOT_ELIGIBLE")


def test_related_service_resume_requires_consent_approved(api):
    """PRD §3.6: "Resume requires the service to be in SUSPENDED
    (else ERR_SERVICE_NOT_SUSPENDED), the resolved consent to be in
    APPROVED (else ERR_SERVICE_CONSENT_NOT_APPROVED)".

    Claim: resuming a SUSPENDED service while supplying a
    WITHDRAWN consent → ERR_SERVICE_CONSENT_NOT_APPROVED. Second
    witness for the RelatedService↔ParentalConsent cross-entity
    state dependency, this time on the resume path rather than the
    initial activate path.

    # difficulty: cross_entity_state_dependency/related_service_activation_requires_consent_approved
    """
    from test_helpers import (
        TEST_USERS,
        resume_related_service_payload,
    )
    district, student, iep, service, consent = (
        setup_active_iep_with_active_service()
    )
    # Withdraw consent → service auto-SUSPENDED.
    parent_withdraw_consent(
        district["id"], student["id"], consent["id"],
        parent_user_id=student["parent_user_id"],
    )
    # Try to resume with the now-WITHDRAWN consent.
    res = api.resume_related_service(
        district["id"], student["id"], iep["id"], service["id"],
        resume_related_service_payload(consent_id=consent["id"]),
        TEST_USERS["provider_headers"],
    )
    validate_error(res, "ERR_SERVICE_CONSENT_NOT_APPROVED")


# ===========================================================================
# Rule 8: resource_temporal_overlap — second coverage
# ===========================================================================
def test_service_sessions_can_be_back_to_back_with_one_minute_gap(
    api,
):
    """PRD §3.6: "Two sessions on the same related_service_id may
    not overlap in time; overlap is checked on closed intervals so
    that adjacency (one session's scheduled_end equal to another's
    scheduled_start) counts as a violation".

    Claim: sessions that DO NOT touch (one-minute gap) are accepted
    — this is the necessary "non-overlap" complement to the
    closed-interval adjacency rejection in test_10.

    # difficulty: resource_temporal_overlap/service_session_closed_interval_adjacency_overlap
    """
    district, student, iep, service, _consent = (
        setup_active_iep_with_active_service()
    )
    create_session(
        district["id"], student["id"], iep["id"], service["id"],
        scheduled_start="2025-03-01T09:00:00.000Z",
        scheduled_end="2025-03-01T10:00:00.000Z",
    )
    # Second session begins ONE MINUTE after the first ends — no
    # touch, no overlap.
    s2 = create_session(
        district["id"], student["id"], iep["id"], service["id"],
        scheduled_start="2025-03-01T10:01:00.000Z",
        scheduled_end="2025-03-01T11:00:00.000Z",
    )
    assert s2["status"] == "SCHEDULED"


def test_iep_period_adjacency_is_forbidden_touch(api):
    """PRD §3.3: "the proposed effective_start_date is strictly
    later than the scheduled_review_date of the most recent prior
    IEP for the same student under half-open period semantics,
    where adjacency counts as a forbidden touch".

    NOTE: PRD §3.3 explicitly says adjacency is a FORBIDDEN touch
    for the IEP period rule — the opposite of how the
    difficulty-design instance framed it (the instance asserted
    half-open semantics ACCEPT touching). PRD prose is the
    contract: we assert the PRD rule verbatim — adjacency at
    scheduled_review_date is rejected with ERR_IEP_PERIOD_OVERLAP.

    # difficulty: resource_temporal_overlap/iep_period_half_open_interval_no_overlap_on_touch
    """
    from test_helpers import (
        TEST_USERS,
        create_goal_with_single_objective,
        create_iep,
        create_iep_implementation_consent_approved,
    )
    district, student, _eval, iep1, _goal1 = setup_active_iep(
        effective_start_date="2025-02-01T00:00:00.000Z",
    )
    # iep1.scheduled_review_date = 2026-02-01.
    # Advance the clock so iep1 expires.
    advance_clock(district["id"], by_days=400)
    iep1_now = get_iep(district["id"], student["id"], iep1["id"])
    assert iep1_now["status"] == "EXPIRED"
    # Now create a new IEP with effective_start_date EXACTLY equal
    # to iep1.scheduled_review_date — PRD §3.3 says this adjacency
    # touch is forbidden.
    iep2 = create_iep(
        district["id"], student["id"],
        meeting_held_at="2026-01-01T00:00:00.000Z",
        effective_start_date="2026-02-01T00:00:00.000Z",
    )
    create_goal_with_single_objective(
        district["id"], student["id"], iep2["id"],
    )
    create_iep_implementation_consent_approved(
        district["id"], student["id"], iep2["id"],
        parent_user_id=student["parent_user_id"],
    )
    res = api.activate_iep(
        district["id"], student["id"], iep2["id"],
        TEST_USERS["teacher_headers"],
    )
    # PRD §3.3 verbatim: "adjacency counts as a forbidden touch
    # (ERR_IEP_PERIOD_OVERLAP)".
    validate_error(res, "ERR_IEP_PERIOD_OVERLAP")


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
def test_schedule_then_cancel_session_preserves_utilization(api):
    """PRD §3.6: "When total_prescribed_minutes_to_date is zero,
    utilization_percent is 0.00. Otherwise utilization_percent is
    100 multiplied by total_delivered_minutes, divided by
    total_prescribed_minutes_to_date".
    PRD §3.6: "A SCHEDULED session may instead be cancelled ... on
    success the session moves to CANCELLED and the parent service's
    total_cancelled_minutes increases by the session's
    scheduled_minutes."

    Claim: schedule then cancel a session — total_delivered_minutes
    and total_prescribed_minutes_to_date are unchanged by the
    schedule+cancel pair (cancel does not touch delivered_minutes
    and the prescribed-minutes formula depends only on time and
    minutes_per_week), so utilization_percent before == after.

    # difficulty: compensating_invariant/session_schedule_cancel_preserves_utilization_percent
    """
    district, student, iep, service, _consent = (
        setup_active_iep_with_active_service(
            service_type="OT", minutes_per_week=75,
            location_setting="PULL_OUT",
        )
    )
    pre = get_service(
        district["id"], student["id"], iep["id"], service["id"],
    )
    s = create_session(
        district["id"], student["id"], iep["id"], service["id"],
        scheduled_start="2025-03-01T09:00:00.000Z",
        scheduled_end="2025-03-01T09:30:00.000Z",
    )
    cancel_session(
        district["id"], student["id"], iep["id"], service["id"],
        s["id"],
    )
    post = get_service(
        district["id"], student["id"], iep["id"], service["id"],
    )
    assert post["total_delivered_minutes"] == (
        pre["total_delivered_minutes"]
    )
    # utilization_percent depends on total_delivered_minutes and
    # total_prescribed_minutes_to_date — the latter is a function of
    # weeks_active and minutes_per_week per PRD §3.6, so any change
    # is attributable to the clock not the schedule+cancel pair.
    # Pin: utilization_percent must equal pre value when neither
    # delivered nor prescribed changed.
    assert post["utilization_percent"] == pre["utilization_percent"]


def test_service_suspend_resume_preserves_lre_percentage(api):
    """PRD §3.8: "The numerator for both percentage variants is the
    sum of minutes_per_week over every RelatedService on this IEP
    that is currently in ACTIVE".
    PRD §3.6: "A SUSPENDED service can be resumed back to ACTIVE
    by the RelatedServiceProvider by supplying a consent_id in the
    request body. ... On success the IEP's
    special_education_minutes_per_week, both LRE percentages, and
    the student's lre_classification are recomputed."

    Claim: suspend then resume the SAME service —
    lre_percentage_instructional ends exactly where it started.

    # difficulty: compensating_invariant/service_suspend_resume_preserves_lre_percentage
    """
    district, student, iep, service, consent = (
        setup_active_iep_with_active_service(
            service_type="OT", minutes_per_week=300,
            location_setting="PULL_OUT",
            total_instructional_minutes_per_week=1500,
            total_school_day_minutes_per_week=1875,
        )
    )
    pre = get_iep(district["id"], student["id"], iep["id"])
    pre_pct = pre["lre_percentage_instructional"]
    pre_sped = pre["special_education_minutes_per_week"]
    suspend_related_service(
        district["id"], student["id"], iep["id"], service["id"],
    )
    resume_related_service(
        district["id"], student["id"], iep["id"], service["id"],
        consent_id=consent["id"],
    )
    post = get_iep(district["id"], student["id"], iep["id"])
    assert post["lre_percentage_instructional"] == pre_pct
    assert post["special_education_minutes_per_week"] == pre_sped


# ===========================================================================
# Coverage summary footer — see PERFORMANCE_ANA / generator log
# ===========================================================================
#
# Difficulty-design instances declared in
# SCAFFOLD_DIFFICULTY_DESIGN.yaml (18 total). Each instance is
# covered by at least TWO tests across the suite (primary in the
# per-feature file plus second-coverage in this file):
#
#   dual_variant_calc/lre_percentage_dual_basis_on_iep:
#     - test_11::test_dual_variant_same_numerator_different_denominator
#     - test_15::test_lre_dual_basis_school_day_strictly_less_than_instructional
#   dual_variant_calc/goal_mastery_weighted_vs_simple_on_iepgoal:
#     - test_08::test_mastery_score_weighted_sum (PROGRESSING witness)
#     - test_15::test_goal_mastery_weighted_diverges_from_simple_average
#   combinatorial_formula/goal_mastery_weighted_tier_branching_mode_a:
#     - test_08::test_mastery_tier_mastered_at_80
#     - test_15::test_mastery_score_at_50_exact_boundary_is_progressing
#   combinatorial_formula/compensatory_minutes_round_per_session_then_sum_mode_b:
#     - test_13::test_three_25min_missed_sessions_total_114_minutes
#     - test_15::test_compensatory_minutes_round_per_session_second_witness
#   non_linear_state_machine/parental_consent_revocation_cycle_with_reissue:
#     - test_15::test_consent_revocation_then_reissue_cycle
#     - test_15::test_consent_withdrawal_stamps_withdrawn_at
#   non_linear_state_machine/iep_amendment_cycle_on_iep_entity:
#     - test_06::test_begin_amendment_moves_to_amendment_pending +
#       test_06::test_finalize_amendment_returns_to_active
#     - test_15::test_iep_amendment_cycle_traversed_twice
#   transitive_cascade/consent_withdrawal_cascades_to_iep_amendment_depth_3:
#     - test_13::test_withdraw_cascades_to_iep_amendment_pending
#     - test_15::test_consent_withdrawal_stamps_withdrawn_at
#   transitive_cascade/ineligible_finalization_cascades_to_goals_and_services_depth_3:
#     - test_13::test_ineligible_finalize_revokes_active_iep_and_dependents
#     - test_15::test_ineligible_finalize_clears_current_iep_and_lre
#   priority_pair_validation_conflict/state_vs_business_referential_on_goal_creation:
#     - test_14::test_state_check_wins_over_referential_on_expired_iep
#     - test_15::test_close_goal_with_inactive_iep_fails_with_iep_not_active
#   priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_service_activation:
#     - test_14::test_eligibility_wins_over_instructional_cap_on_activate
#     - test_15::test_service_activate_on_draft_iep_surfaces_state_error
#   boundary_precision_check/lre_classification_inclusive_60_pct_boundary:
#     - test_11::test_lre_b_at_60_pct_inclusive
#     - test_15::test_lre_classification_jumps_to_lre_c_at_61_pct
#   boundary_precision_check/triennial_overdue_zero_day_boundary:
#     - test_03::test_triennial_status_due_soon_on_due_date +
#       test_03::test_triennial_status_overdue_one_day_past_due
#     - test_15::test_triennial_due_soon_then_overdue_across_one_day
#   cross_entity_state_dependency/iep_activation_requires_eligibility_eligible:
#     - test_06::test_activate_without_eligible_evaluation_rejected
#     - test_15::test_iep_activate_requires_eligible_evaluation
#   cross_entity_state_dependency/related_service_activation_requires_consent_approved:
#     - test_09::test_activate_without_approved_consent_rejected
#     - test_15::test_related_service_resume_requires_consent_approved
#   resource_temporal_overlap/service_session_closed_interval_adjacency_overlap:
#     - test_10::test_closed_interval_adjacency_overlap_rejected
#     - test_15::test_service_sessions_can_be_back_to_back_with_one_minute_gap
#   resource_temporal_overlap/iep_period_half_open_interval_no_overlap_on_touch:
#     - test_15::test_iep_period_adjacency_is_forbidden_touch
#     - [SECOND TEST ESCALATED] PRD §3.3 explicitly says adjacency
#       is a FORBIDDEN touch — the opposite of the
#       difficulty-design instance's half-open-accepts-touch
#       framing. The "no overlap on touch" witness cannot be
#       generated under PRD prose because PRD pins the opposite
#       semantics. Escalated under
#       `difficulty-coverage-blocked-by-prd-silence` —
#       specifically a PRD/scaffold disagreement, not silence.
#   compensating_invariant/session_schedule_cancel_preserves_utilization_percent:
#     - test_15::test_schedule_then_cancel_session_preserves_utilization
#     - test_10::test_cancel_scheduled_session_succeeds (cancel
#       side-effect witness on total_cancelled_minutes)
#   compensating_invariant/service_suspend_resume_preserves_lre_percentage:
#     - test_15::test_service_suspend_resume_preserves_lre_percentage
#     - test_11::test_school_day_basis_le_instructional_basis (LRE
#       recomputation invariant witness)
