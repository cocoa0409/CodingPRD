"""Cohort scheduling/membership windows, practice validation, analytics, and RBAC.

Covers difficulty queue (A): resource_temporal_overlap (membership half-open,
session 30-min buffer), priority_pair_validation_conflict (cohort referential vs
window), boundary_precision_check (empty session); and corner queue (B): cohort
full/transition, practice validations, analytics read, RBAC and auth.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, build_user_headers,
    setup_active_enrollment,
    create_program, create_published_program, create_plan, create_learner,
    create_enrollment, create_cohort, activate, get_enrollment, join_cohort,
    create_practice_session_payload, create_cohort_session_payload,
    create_cohort_membership_payload, create_license_program_payload,
    make_learner_headers,
)

ADMIN = TEST_USERS["content_admin_headers"]
PROCTOR = TEST_USERS["exam_proctor_headers"]


# ==========================================================================
# resource_temporal_overlap / membership_window_half_open_abutting_allowed_overlap_rejected
# ==========================================================================
def test_membership_abutting_window_allowed(api):
    """A membership window abutting an existing one ([12:00,14:00) after [10:00,12:00)) is accepted.

    PRD §3.8: "the new window `[new_start, new_end)` conflicts with an existing window
    `[existing_start, existing_end)` exactly when the new start is before the existing end
    and the existing start is before the new end. Abutting windows, where one ends precisely
    as the next begins, do not conflict."

    Design: Difficulty/resource_temporal_overlap/membership_window_half_open_abutting_allowed_overlap_rejected
    """
    ctx = setup_active_enrollment(license_code="OVL-1", learner_email="ovl@x.com")
    enr, learner, prog = ctx["enrollment"], ctx["learner"], ctx["program"]
    c1 = create_cohort(prog["id"], title="Cohort A", capacity=5)
    c2 = create_cohort(prog["id"], title="Cohort B", capacity=5)
    join_cohort(c1["id"], enr["id"], learner["id"],
                session_start_utc="2026-06-04T10:00:00Z", session_end_utc="2026-06-04T12:00:00Z")
    abutting = validate_success(api.create_cohort_membership(
        c2["id"],
        create_cohort_membership_payload(enr["id"], session_start_utc="2026-06-04T12:00:00Z",
                                          session_end_utc="2026-06-04T14:00:00Z"),
        make_learner_headers(learner["id"])), 201)
    assert abutting["status"] == "JOINED"


def test_membership_overlapping_window_rejected(api):
    """A membership window overlapping an existing one returns ERR_SESSION_WINDOW_CONFLICT.

    PRD §3.8: "the new window `[new_start, new_end)` conflicts with an existing window
    `[existing_start, existing_end)` exactly when the new start is before the existing end
    and the existing start is before the new end. Abutting windows, where one ends precisely
    as the next begins, do not conflict. A conflicting window is rejected with
    `ERR_SESSION_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/membership_window_half_open_abutting_allowed_overlap_rejected
    """
    ctx = setup_active_enrollment(license_code="OVL-1B", learner_email="ovlb@x.com")
    enr, learner, prog = ctx["enrollment"], ctx["learner"], ctx["program"]
    c1 = create_cohort(prog["id"], title="Cohort A", capacity=5)
    c3 = create_cohort(prog["id"], title="Cohort C", capacity=5)
    join_cohort(c1["id"], enr["id"], learner["id"],
                session_start_utc="2026-06-04T10:00:00Z", session_end_utc="2026-06-04T12:00:00Z")
    resp = api.create_cohort_membership(
        c3["id"],
        create_cohort_membership_payload(enr["id"], session_start_utc="2026-06-04T11:00:00Z",
                                          session_end_utc="2026-06-04T13:00:00Z"),
        make_learner_headers(learner["id"]))
    validate_error(resp, ApiErrorId.ERR_SESSION_WINDOW_CONFLICT.value)


# ==========================================================================
# resource_temporal_overlap / cohort_session_closed_interval_30min_buffer_boundary
# ==========================================================================
def test_cohort_session_exact_30min_gap_allowed(api):
    """A session [11:30,12:30] exactly 30 minutes after [10:00,11:00] is accepted.

    PRD §3.8: "A gap of exactly thirty minutes is allowed; any gap of less than thirty
    minutes — including a true overlap — is rejected with `ERR_SESSION_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/cohort_session_closed_interval_30min_buffer_boundary
    """
    prog = create_program("OVL-2", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    cohort = create_cohort(prog["id"], title="Sessioned", capacity=10)
    validate_success(api.create_cohort_session(
        cohort["id"], create_cohort_session_payload(topic="Intro",
                                                    session_start_utc="2026-06-05T10:00:00Z",
                                                    session_end_utc="2026-06-05T11:00:00Z"), ADMIN), 201)
    ok = validate_success(api.create_cohort_session(
        cohort["id"], create_cohort_session_payload(topic="Exactly30",
                                                    session_start_utc="2026-06-05T11:30:00Z",
                                                    session_end_utc="2026-06-05T12:30:00Z"), ADMIN), 201)
    assert ok["topic"] == "Exactly30"


def test_cohort_session_15min_gap_rejected(api):
    """A session [11:15,12:00] only 15 minutes after [10:00,11:00] returns ERR_SESSION_BUFFER_CONFLICT.

    PRD §3.8: "A gap of exactly thirty minutes is allowed; any gap of less than thirty
    minutes — including a true overlap — is rejected with `ERR_SESSION_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/cohort_session_closed_interval_30min_buffer_boundary
    """
    prog = create_program("OVL-2B", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    cohort = create_cohort(prog["id"], title="Sessioned2", capacity=10)
    validate_success(api.create_cohort_session(
        cohort["id"], create_cohort_session_payload(topic="Intro",
                                                    session_start_utc="2026-06-05T10:00:00Z",
                                                    session_end_utc="2026-06-05T11:00:00Z"), ADMIN), 201)
    resp = api.create_cohort_session(
        cohort["id"], create_cohort_session_payload(topic="TooClose",
                                                    session_start_utc="2026-06-05T11:15:00Z",
                                                    session_end_utc="2026-06-05T12:00:00Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_SESSION_BUFFER_CONFLICT.value)


# ==========================================================================
# priority_pair_validation_conflict / cohort_join_referential_beats_window_conflict
# ==========================================================================
def test_cohort_join_wrong_program_returns_referential_over_window(api):
    """Joining a wrong-program cohort with an overlapping window returns ERR_REFERENCE_INCOMPATIBLE.

    PRD §3.8: "The cohort's `license_program_id` must match the program of the joining
    enrollment, or the join is rejected as a referential mismatch with
    `ERR_REFERENCE_INCOMPATIBLE`."
    PRD §2.5: "the system evaluates them in a fixed priority order and returns the first
    failure encountered."

    Design: Difficulty/priority_pair_validation_conflict/cohort_join_referential_beats_window_conflict
    """
    p1 = create_published_program("P1-CODE", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    p2 = create_published_program("P2-CODE", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="BASIC", total_price_cents=30000)
    c1 = create_cohort(p1["id"], title="P1 Cohort", capacity=5)
    c2 = create_cohort(p2["id"], title="P2 Cohort", capacity=5)
    learner = create_learner(email="ref@x.com", full_name="RefTemp")
    enr = create_enrollment(learner, p1["id"], plan["id"], financed=False)
    activate(enr["id"], learner["id"])
    join_cohort(c1["id"], enr["id"], learner["id"],
                session_start_utc="2026-06-03T10:00:00Z", session_end_utc="2026-06-03T12:00:00Z")
    # join c2 (wrong program P2) with an OVERLAPPING window [11:00,13:00)
    resp = api.create_cohort_membership(
        c2["id"],
        create_cohort_membership_payload(enr["id"], session_start_utc="2026-06-03T11:00:00Z",
                                          session_end_utc="2026-06-03T13:00:00Z"),
        make_learner_headers(learner["id"]))
    err = validate_error(resp, ApiErrorId.ERR_REFERENCE_INCOMPATIBLE.value)
    assert err["error_id"] != ApiErrorId.ERR_SESSION_WINDOW_CONFLICT.value


def test_cohort_join_wrong_program_referential_with_identical_overlapping_window(api):
    """A wrong-program join whose window exactly duplicates an existing one still returns referential.

    PRD §3.8: "The cohort's `license_program_id` must match the program of the joining
    enrollment, or the join is rejected as a referential mismatch with
    `ERR_REFERENCE_INCOMPATIBLE`."
    PRD §2.5: "the system evaluates them in a fixed priority order and returns the first
    failure encountered."

    Design: Difficulty/priority_pair_validation_conflict/cohort_join_referential_beats_window_conflict
    """
    p1 = create_published_program("PR1", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    p2 = create_published_program("PR2", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="BASIC", total_price_cents=30000)
    c1 = create_cohort(p1["id"], title="P1 Cohort", capacity=5)
    c2 = create_cohort(p2["id"], title="P2 Cohort", capacity=5)
    learner = create_learner(email="ref2@x.com", full_name="Ref2")
    enr = create_enrollment(learner, p1["id"], plan["id"], financed=False)
    activate(enr["id"], learner["id"])
    join_cohort(c1["id"], enr["id"], learner["id"],
                session_start_utc="2026-07-01T10:00:00Z", session_end_utc="2026-07-01T12:00:00Z")
    # join wrong-program c2 with the SAME window as the existing membership (a true overlap)
    resp = api.create_cohort_membership(
        c2["id"],
        create_cohort_membership_payload(enr["id"], session_start_utc="2026-07-01T10:00:00Z",
                                          session_end_utc="2026-07-01T12:00:00Z"),
        make_learner_headers(learner["id"]))
    err = validate_error(resp, ApiErrorId.ERR_REFERENCE_INCOMPATIBLE.value)
    assert err["error_id"] != ApiErrorId.ERR_SESSION_WINDOW_CONFLICT.value


# ==========================================================================
# boundary_precision_check / practice_session_zero_answered_empty_set_boundary
# ==========================================================================
def test_practice_session_zero_answered_rejected(api):
    """A practice session with answered_count == 0 returns ERR_EMPTY_SESSION; counter unchanged.

    PRD §3.4: "A batch with an `answered_count` of zero has no defined percentage and is
    rejected with `ERR_EMPTY_SESSION`."

    Design: Difficulty/boundary_precision_check/practice_session_zero_answered_empty_set_boundary
    """
    ctx = setup_active_enrollment(license_code="BND-2", learner_email="empty@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    lh = make_learner_headers(learner["id"])
    resp = api.create_practice_session(enr["id"], create_practice_session_payload(domain_code="A", answered_count=0, correct_count=0), lh)
    validate_error(resp, ApiErrorId.ERR_EMPTY_SESSION.value)
    enr = get_enrollment(enr["id"], learner["id"])
    assert enr["questions_answered_total"] == 0, "rejected empty session must not change the counter"


def test_practice_session_one_answered_succeeds(api):
    """A practice session with answered_count == 1 is accepted (the boundary above empty).

    PRD §3.4: "the system computes the batch percentage `batch_pct` as one hundred times the
    correct count divided by the answered count, rounded half up to an integer."

    Design: Difficulty/boundary_precision_check/practice_session_zero_answered_empty_set_boundary
    """
    ctx = setup_active_enrollment(license_code="BND-2B", learner_email="onefn@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    lh = make_learner_headers(learner["id"])
    data = validate_success(api.create_practice_session(
        enr["id"], create_practice_session_payload(domain_code="A", answered_count=1, correct_count=1), lh), 201)
    assert data["batch_pct"] == 100


# ==========================================================================
# Corner / state_machines / cohort_open_to_full_then_full_to_open_compound
# ==========================================================================
def test_cohort_full_then_open_on_join_and_drop(api):
    """Joining a capacity-1 cohort flips it FULL; dropping flips it back OPEN.

    PRD §3.8: "as soon as a join brings `seats_taken` up to `capacity`, the cohort flips
    from `OPEN` to `FULL`; when a drop later brings `seats_taken` back below `capacity`, it
    flips from `FULL` back to `OPEN`."

    Design: Corner/state_machines/cohort_open_to_full_then_full_to_open_compound
    """
    ctx = setup_active_enrollment(license_code="CFL", learner_email="cfl@x.com")
    enr, learner, prog = ctx["enrollment"], ctx["learner"], ctx["program"]
    cohort = create_cohort(prog["id"], title="Cap1", capacity=1)
    mem = join_cohort(cohort["id"], enr["id"], learner["id"],
                      session_start_utc="2026-06-10T10:00:00Z", session_end_utc="2026-06-10T12:00:00Z")
    after_join = validate_success(api.get_cohort(cohort["id"], ADMIN))
    assert after_join["status"] == "FULL" and after_join["seats_taken"] == 1
    dropped = validate_success(api.drop_cohort_membership(cohort["id"], mem["id"], make_learner_headers(learner["id"])))
    assert dropped["status"] == "DROPPED"
    after_drop = validate_success(api.get_cohort(cohort["id"], ADMIN))
    assert after_drop["status"] == "OPEN" and after_drop["seats_taken"] == 0


# ==========================================================================
# Corner / validations / cohort_join_when_full_returns_cohort_full
# ==========================================================================
def test_cohort_join_when_full_returns_cohort_full(api):
    """A second JOIN to a capacity-1 cohort already at capacity returns ERR_COHORT_FULL.

    PRD §3.8: "a join is rejected with `ERR_COHORT_FULL` when `seats_taken` is already at or
    above `capacity`, or when the cohort status is `CLOSED`."

    Design: Corner/validations/cohort_join_when_full_returns_cohort_full
    """
    prog = create_published_program("FULLJ", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="BASIC", total_price_cents=30000)
    cohort = create_cohort(prog["id"], title="Cap1", capacity=1)
    l1 = create_learner(email="e1@x.com", full_name="E1")
    l2 = create_learner(email="e2@x.com", full_name="E2")
    e1 = create_enrollment(l1, prog["id"], plan["id"], financed=False)
    e2 = create_enrollment(l2, prog["id"], plan["id"], financed=False)
    activate(e1["id"], l1["id"])
    activate(e2["id"], l2["id"])
    join_cohort(cohort["id"], e1["id"], l1["id"],
                session_start_utc="2026-06-11T10:00:00Z", session_end_utc="2026-06-11T12:00:00Z")
    resp = api.create_cohort_membership(
        cohort["id"],
        create_cohort_membership_payload(e2["id"], session_start_utc="2026-06-11T13:00:00Z",
                                          session_end_utc="2026-06-11T15:00:00Z"),
        make_learner_headers(l2["id"]))
    validate_error(resp, ApiErrorId.ERR_COHORT_FULL.value)


# ==========================================================================
# Corner / validations / practice_session_domain_not_in_plan_rejected
# ==========================================================================
def test_practice_session_domain_not_in_plan_rejected(api):
    """A practice session whose domain is not a study-plan domain returns ERR_REFERENCE_INCOMPATIBLE.

    PRD §3.4: "The targeted `domain_code` must match a study-plan domain of the enrollment,
    or the session is rejected with `ERR_REFERENCE_INCOMPATIBLE`."

    Design: Corner/validations/practice_session_domain_not_in_plan_rejected
    """
    ctx = setup_active_enrollment(license_code="PDOM",
                                  domain_weights=[{"domain_code": "A", "weight": 1.00}],
                                  learner_email="pdom@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    resp = api.create_practice_session(
        enr["id"], create_practice_session_payload(domain_code="B", answered_count=10, correct_count=8),
        make_learner_headers(learner["id"]))
    validate_error(resp, ApiErrorId.ERR_REFERENCE_INCOMPATIBLE.value)


# ==========================================================================
# Corner / validations / practice_correct_exceeds_answered_invalid_request
# ==========================================================================
def test_practice_correct_exceeds_answered_invalid_request(api):
    """correct_count > answered_count violates the field constraint -> ERR_INVALID_REQUEST.

    PRD §3.4: "a `correct_count` of those answered correctly (at least zero and no greater
    than the answered count)."

    Design: Corner/validations/practice_correct_exceeds_answered_invalid_request
    """
    ctx = setup_active_enrollment(license_code="CGT", learner_email="cgt@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    resp = api.create_practice_session(
        enr["id"], create_practice_session_payload(domain_code="A", answered_count=10, correct_count=11),
        make_learner_headers(learner["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ==========================================================================
# Corner / endpoints / analytics_computed_read_matches_components
# ==========================================================================
def test_analytics_reflects_activity_counters(api):
    """Analytics surfaces questions_answered_total and completed_mock_count after activity.

    PRD §3.4: "Both scores, the per-domain mastery, the activity counters, and the financing
    figures are surfaced together on the enrollment's analytics view."
    PRD §3.4: "The enrollment's `questions_answered_total` is increased by the batch's
    `answered_count` (it is, equivalently, the sum of `answered_count` over all completed
    sessions), the readiness scores are recomputed, and the enrollment is re-versioned."

    Design: Corner/endpoints/analytics_computed_read_matches_components
    """
    ctx = setup_active_enrollment(license_code="ANA", learner_email="ana@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    lh = make_learner_headers(learner["id"])
    validate_success(api.create_practice_session(
        enr["id"], create_practice_session_payload(domain_code="A", answered_count=40, correct_count=30), lh), 201)
    validate_success(api.create_mock_exam(enr["id"], {"raw_score": 60, "item_count": 100}, lh), 201)
    data = validate_success(api.get_enrollment_analytics(enr["id"], lh))
    assert data["questions_answered_total"] == 40
    assert data["completed_mock_count"] == 1


# ==========================================================================
# Corner / rbac
# ==========================================================================
def test_learner_cannot_create_license_program(api):
    """A Learner calling POST /license-programs returns ERR_FORBIDDEN_ROLE.

    PRD §2.1: "When the headers are present and well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/learner_cannot_create_license_program
    """
    learner = create_learner(email="rb1@x.com", full_name="RB1")
    resp = api.create_license_program(
        create_license_program_payload(license_code="RB1", title="RB1", passing_scaled_score=70,
                                       domain_weights=[{"domain_code": "A", "weight": 1.00}]),
        make_learner_headers(learner["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_learner_cannot_certify_exam(api):
    """A Learner calling certify-exam (an ExamProctor exclusive) returns ERR_FORBIDDEN_ROLE.

    PRD §2.1: "When the headers are present and well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/learner_cannot_certify_exam
    """
    ctx = setup_active_enrollment(license_code="RB2", learner_email="rb2@x.com")
    enr, learner = ctx["enrollment"], ctx["learner"]
    resp = api.certify_exam(enr["id"], {"outcome": "PASS"}, make_learner_headers(learner["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_learner_cannot_act_on_other_learners_enrollment(api):
    """Learner B activating Learner A's enrollment returns ERR_NOT_RESOURCE_OWNER.

    PRD §2.1: "for any learner-scoped action on an enrollment or on resources nested beneath
    it — installments, practice sessions, mock exams, CE awards, cohort memberships — the
    `learner_id` of the owning `Enrollment` (or the `id` of the `Learner` itself for
    learner-record reads) must equal `X-User-ID`; otherwise the request is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/learner_cannot_act_on_other_learners_enrollment
    """
    prog = create_published_program("RB3", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="BASIC", total_price_cents=30000)
    la = create_learner(email="ra@x.com", full_name="RA")
    lb = create_learner(email="rbx@x.com", full_name="RBX")
    enr = create_enrollment(la, prog["id"], plan["id"], financed=False)
    resp = api.activate_enrollment(enr["id"], make_learner_headers(lb["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    enr = get_enrollment(enr["id"], la["id"])
    assert enr["status"] == "DRAFT"


def test_missing_auth_headers_returns_unauthenticated(api):
    """A request with no auth headers returns ERR_UNAUTHENTICATED.

    PRD §2.1: "A request missing either header, or carrying a malformed value, is rejected
    with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_license_programs({})  # no X-User-ID / X-User-Role
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
