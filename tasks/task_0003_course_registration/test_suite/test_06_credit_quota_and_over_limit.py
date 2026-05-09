"""Dynamic credit quota and OverLimitApplication lifecycle (PRD §3.6)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
    CREDIT_QUOTA_TIERS, make_student_headers, make_professor_headers,
    create_over_limit_application_payload,
)
from test_helpers.fixtures import (
    setup_basic_world, setup_open_offering, setup_offering_with_seat_taken,
    create_offering, create_course, create_student, create_professor,
    create_term_in_planning, create_campus, create_department, advance_clock,
    submit_enrollment, submit_enrollment_success, get_enrollment_request,
    create_over_limit_application, submit_application, sign_application,
    reject_application, revise_application, get_application,
    load_student_credits_via_approved,
)


# ─── Quota gate (PRD §3.6) ─────────────────────────────────────────────
def test_credit_quota_exceeded_at_year_two_boundary(api):
    """PRD §3.6: "The submission is rejected with ERR_CREDIT_QUOTA_EXCEEDED
    (402) when the candidate offering's Course.credits added to the
    provisional current load would strictly exceed the effective quota;
    equality is permitted."

    Claim: a year-2 student (base_quota=20.0) with 16.0 APPROVED credits
    cannot enroll in a 5.0-credit course (16+5=21 > 20). Equality at 20
    would be allowed; 21 strictly exceeds.
    """
    world = setup_basic_world(student_year=2)
    # Load 16 credits via four 4.0-credit courses on different days.
    load_student_credits_via_approved(world, target_credits=16.0,
                                       per_course_credits=4.0,
                                       meeting_start=540, meeting_end=600)
    # New course of 5.0 credits — 16+5 = 21 > 20 → reject.
    co = setup_open_offering(world, credits=5.0, base_capacity=5,
                              scheduled_meetings=[{"day_of_week": 5, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    res = submit_enrollment(world["student"], co["offering"]["id"])
    validate_error(res, "ERR_CREDIT_QUOTA_EXCEEDED")


def test_credit_quota_at_equality_is_permitted(api):
    """PRD §3.6: "equality is permitted."

    Claim: a year-1 student (base_quota=18.0) with 15.0 APPROVED credits
    can enroll in a 3.0-credit course (15+3=18, equal to quota).
    """
    world = setup_basic_world(student_year=1)
    # Load 15 credits via three 5.0-credit courses on different days.
    load_student_credits_via_approved(world, target_credits=15.0,
                                       per_course_credits=5.0,
                                       meeting_start=540, meeting_end=600)
    co = setup_open_offering(world, credits=3.0, base_capacity=5,
                              scheduled_meetings=[{"day_of_week": 4, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    assert er["academic_status"] == "APPROVED"


# ─── OverLimitApplication signer integrity (PRD §3.6) ──────────────────
def test_over_limit_application_signer_not_in_home_dept_rejected(api):
    """PRD §3.6: "At creation the system validates that both signers belong
    to the student's home program_department_id — that is, each signer's
    Professor.department_id matches program_department_id — otherwise it
    fails with ERR_SIGNER_NOT_IN_HOME_DEPARTMENT (422)."

    Claim: a primary signer from a different department → ERR_SIGNER_NOT_IN_HOME_DEPARTMENT.
    """
    world = setup_basic_world()
    foreign_dept = create_department(world["campus"]["id"], code_prefix="FOREIGN")
    foreign_prof = create_professor(foreign_dept["id"], is_chair=False, rank="ASSOCIATE")
    payload = create_over_limit_application_payload(
        student_id=world["student"]["id"],
        term_id=world["term"]["id"],
        requested_extension_credits=4.0,
        primary_signer_id=foreign_prof["id"],
        secondary_signer_id=world["chair"]["id"],
    )
    res = api.create_over_limit_application(
        payload, make_student_headers(world["student"]["id"])
    )
    validate_error(res, "ERR_SIGNER_NOT_IN_HOME_DEPARTMENT")


def test_over_limit_application_primary_is_chair_rejected(api):
    """PRD §3.6: "It further requires that the primary signer is not the chair
    of that department — a primary signer with is_chair true fails with
    ERR_PRIMARY_SIGNER_IS_CHAIR (422)."

    Claim: primary signer with is_chair=true → ERR_PRIMARY_SIGNER_IS_CHAIR.
    """
    world = setup_basic_world()
    payload = create_over_limit_application_payload(
        student_id=world["student"]["id"],
        term_id=world["term"]["id"],
        requested_extension_credits=4.0,
        primary_signer_id=world["chair"]["id"],   # chair as primary
        secondary_signer_id=world["chair"]["id"],
    )
    res = api.create_over_limit_application(
        payload, make_student_headers(world["student"]["id"])
    )
    validate_error(res, "ERR_PRIMARY_SIGNER_IS_CHAIR")


def test_over_limit_application_secondary_not_chair_rejected(api):
    """PRD §3.6: "...and that the secondary signer is the chair, that is, has
    is_chair true; otherwise the application fails with
    ERR_SECONDARY_SIGNER_NOT_CHAIR (422)."

    Claim: secondary signer with is_chair=false → ERR_SECONDARY_SIGNER_NOT_CHAIR.
    """
    world = setup_basic_world()
    payload = create_over_limit_application_payload(
        student_id=world["student"]["id"],
        term_id=world["term"]["id"],
        requested_extension_credits=4.0,
        primary_signer_id=world["professor"]["id"],
        secondary_signer_id=world["professor"]["id"],   # not a chair
    )
    res = api.create_over_limit_application(
        payload, make_student_headers(world["student"]["id"])
    )
    validate_error(res, "ERR_SECONDARY_SIGNER_NOT_CHAIR")


# ─── OverLimitApplication state machine (PRD §3.6) ─────────────────────
def test_submit_outside_registration_open_rejected(api):
    """PRD §3.6: "The Student submits the draft, transitioning DRAFT →
    AWAITING_PRIMARY. The submission is rejected unless the parent Term is
    in REGISTRATION_OPEN (ERR_TERM_NOT_OPEN_FOR_REGISTRATION)..."

    Claim: submitting a draft application on a term still in PLANNING →
    ERR_TERM_NOT_OPEN_FOR_REGISTRATION.

    # difficulty: cross_entity_state_dependency/cross_entity_overlimit_application_depends_on_term
    """
    campus = create_campus()
    dept = create_department(campus["id"])
    chair = create_professor(dept["id"], is_chair=True, rank="FULL")
    professor = create_professor(dept["id"], is_chair=False, rank="ASSOCIATE")
    student = create_student(dept["id"], campus["id"], year_in_program=2)
    # Create a term whose registration_open_at is far in the future.
    future_term = create_term_in_planning()
    # Do not advance the clock — the term remains in PLANNING.
    app = create_over_limit_application(
        student=student, term_id=future_term["id"],
        primary_signer=professor, secondary_signer=chair,
        requested_extension_credits=4.0,
    )
    res = api.submit_over_limit_application(app["id"], make_student_headers(student["id"]))
    validate_error(res, "ERR_TERM_NOT_OPEN_FOR_REGISTRATION")


def test_full_approval_chain_grants_credits(api):
    """PRD §3.6: "The secondary signer signs, transitioning AWAITING_SECONDARY
    → APPROVED. The request is rejected unless X-User-ID matches
    secondary_signer_id (ERR_NOT_DESIGNATED_SIGNER). On entering APPROVED,
    the system populates granted_credits to equal requested_extension_credits,
    and emits an OVER_LIMIT_GRANTED SyncEvent to ACADEMIC_AFFAIRS and FINANCE."

    Claim: full submit→sign→sign chain yields APPROVED with granted_credits ==
    requested_extension_credits.
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


def test_revision_cycle_returns_to_draft_then_resubmits(api):
    """PRD §3.6: "The Student may revise a REJECTED application back to DRAFT,
    allowing a fresh submission with new justification or a new requested
    extension. The cycle is permitted only while the parent Term is still in
    REGISTRATION_OPEN and only by the application's own student. Previous
    granted_credits remains zero across the cycle."

    Claim: a REJECTED → DRAFT → AWAITING_PRIMARY cycle leaves
    granted_credits at 0.

    # difficulty: non_linear_state_machine/non_linear_overlimit_application_revision_cycle
    """
    world = setup_basic_world(student_year=2)
    app = create_over_limit_application(
        student=world["student"], term_id=world["term"]["id"],
        primary_signer=world["professor"], secondary_signer=world["chair"],
        requested_extension_credits=4.0,
    )
    submit_application(world["student"], app["id"])
    after_submit = get_application(app["id"])
    assert after_submit["status"] == "AWAITING_PRIMARY"

    rejected = reject_application(world["professor"], app["id"], version=after_submit["version"])
    assert rejected["status"] == "REJECTED"

    revised = revise_application(world["student"], app["id"])
    assert revised["status"] == "DRAFT"
    assert float(revised["granted_credits"]) == 0

    # Re-submit; cycle complete.
    re_submitted = submit_application(world["student"], app["id"])
    assert re_submitted["status"] == "AWAITING_PRIMARY"
    assert float(re_submitted["granted_credits"]) == 0


def test_sign_by_wrong_professor_rejected(api):
    """PRD §3.6: "The primary signer signs, transitioning AWAITING_PRIMARY →
    AWAITING_SECONDARY. The request is rejected unless X-User-ID matches
    primary_signer_id (ERR_NOT_DESIGNATED_SIGNER)."

    Claim: a Professor who is not the designated primary signer attempting
    to sign an AWAITING_PRIMARY application → ERR_NOT_DESIGNATED_SIGNER.
    """
    world = setup_basic_world(student_year=2)
    app = create_over_limit_application(
        student=world["student"], term_id=world["term"]["id"],
        primary_signer=world["professor"], secondary_signer=world["chair"],
        requested_extension_credits=4.0,
    )
    submitted = submit_application(world["student"], app["id"])
    assert submitted["status"] == "AWAITING_PRIMARY"

    # Use the chair (designated as secondary, not primary) to sign primary step.
    res = api.sign_over_limit_application(
        app["id"], {}, make_professor_headers(world["chair"]["id"])
    )
    validate_error(res, "ERR_NOT_DESIGNATED_SIGNER")
