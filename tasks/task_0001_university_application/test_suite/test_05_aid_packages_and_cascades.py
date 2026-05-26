"""AidPackage finalization, cross-entity preconditions, and applicant-decision
cascades (enroll/decline depth-2 and depth-3).

Covers Difficulty Rule 4 (transitive_cascade — both instances) and
Rule 7 (cross_entity_state_dependency enroll requires aid FINALIZED) plus
Corner validation for ERR_AID_EXCEEDS_TUITION.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    create_aid_package_payload,
    create_application_payload,
    create_school,
    make_applicant_headers,
    set_clock,
    setup_admitted_application,
    setup_aid_drafted,
    setup_aid_finalized,
    setup_applicant_with_fap,
    setup_ready_to_submit_application,
    setup_submitted_application,
    setup_under_review_application,
    validate_error,
    validate_success,
)


# ─── Corner validation: aid exceeds tuition ────────────────────────────────

def test_aid_exceeds_tuition_blocks_finalize(api):
    """PRD §3.8: "Finalization is the operative transition: it moves the
    package from DRAFT to FINALIZED, but only if the linked application is in
    ADMITTED, a FinancialAidProfile exists for the application's owning
    applicant, and the sum grant_cents + loan_cents + work_study_cents does
    not exceed the residency-appropriate tuition on the linked school...
    A sum that exceeds the cap is rejected with ERR_AID_EXCEEDS_TUITION."

    Design: Corner/validations/aid_exceeds_tuition_blocks_finalize
    """
    set_clock("2026-09-01T00:00:00Z")
    school = create_school(
        name="U AE", state_code="DE", admission_track="REGULAR",
        deadline_iso="2026-10-01T00:00:00Z",
        decision_release_iso="2027-03-15T00:00:00Z",
        target_class_size=100, assumed_yield_rate=0.50,
        in_state_tuition_cents=1_500_000,
        out_of_state_tuition_cents=3_000_000,
        international_tuition_cents=5_000_000,
    )
    applicant, _, admitted, aid_pkg = setup_aid_drafted(
        grant_cents=1_000_000, loan_cents=400_000, work_study_cents=300_000,
        school=school, email_suffix="ae", residency="IN_STATE",
    )
    res = api.finalize_aid_package(aid_pkg["id"], TEST_USERS["financial_aid_headers"])
    validate_error(res, "ERR_AID_EXCEEDS_TUITION")
    after = validate_success(
        api.get_aid_package(aid_pkg["id"], TEST_USERS["financial_aid_headers"]),
        expected_status=200,
    )
    assert after["status"] == "DRAFT"


# ─── Cross-entity precondition: enroll requires aid FINALIZED ──────────────

def test_enroll_blocked_when_aid_package_not_finalized(api):
    """PRD §3.9: "Enrolling transitions the application from ADMITTED to
    ENROLLED and is gated on three preconditions: the caller's X-User-ID
    equals the application's applicant_id; an AidPackage for this
    application_id exists in FINALIZED status; and the applicant does not
    already have another Application in ENROLLED status".
    PRD §2.6: "then state-machine eligibility (ERR_INVALID_STATE)".

    Design: Difficulty/cross_entity_state_dependency/enroll_requires_aid_package_finalized_application_aidpackage
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, admitted, aid_pkg = setup_aid_drafted(email_suffix="enrlblk")
    res = api.enroll_application(admitted["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    after_app = validate_success(
        api.get_application(admitted["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert after_app["status"] == "ADMITTED"
    after_aid = validate_success(
        api.get_aid_package(aid_pkg["id"], TEST_USERS["financial_aid_headers"]),
        expected_status=200,
    )
    assert after_aid["status"] == "DRAFT"


def test_enroll_succeeds_when_aid_package_finalized(api):
    """PRD §3.9: "an AidPackage for this application_id exists in FINALIZED
    status".
    PRD §3.9: "The transition stamps enrollment_decision_at, decrements the
    school's admitted_count (the application leaves ADMITTED), increments the
    school's enrolled_count".

    Design: Difficulty/cross_entity_state_dependency/enroll_requires_aid_package_finalized_application_aidpackage
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, admitted, aid_pkg = setup_aid_finalized(email_suffix="enrlok")
    enrolled = validate_success(
        api.enroll_application(admitted["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert enrolled["status"] == "ENROLLED"
    after_school = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert after_school["enrolled_count"] == 1
    assert after_school["admitted_count"] == 0


# ─── Difficulty Rule 4 instance 1: depth-3 enroll cascade ─────────────────

def test_enroll_cascades_sibling_admit_to_declined_and_revokes_aid(api):
    """PRD §3.9: "The enroll then sweeps every other live application of the
    same applicant: for every other Application of this applicant_id whose
    status is either ADMITTED or WAITLISTED, the application is cascaded to
    DECLINED. Each cascaded decline transition fires its full side-effect set
    in the same transaction — the linked school's declined_count is
    incremented, the linked school's admitted_count is decremented (only when
    the cascade source was ADMITTED, since a WAITLISTED row's count is held
    by the waitlist, not by admitted_count), the linked school's
    yield_posture is recomputed, any FINALIZED AidPackage on the cascaded
    application is cascaded to REVOKED".

    Design: Difficulty/transitive_cascade/enroll_chains_through_other_admit_to_aid_revoke_depth_3
    """
    set_clock("2026-09-01T00:00:00Z")
    s_enroll = create_school(name="U Enroll", state_code="MA")
    s_other = create_school(name="U Other", state_code="NY")
    applicant = setup_applicant_with_fap(
        email="en@u.edu", gpa=3.80, sat_total=1400, residency="IN_STATE",
    )
    # Drive both applications to ADMITTED with FINALIZED AidPackages.
    _, _, admitted_1, aid_1 = setup_aid_finalized(
        school=s_enroll, applicant=applicant, email_suffix="en1",
    )
    _, _, admitted_2, aid_2 = setup_aid_finalized(
        school=s_other, applicant=applicant, email_suffix="en2",
    )
    # Trigger: enroll on the first application
    enrolled = validate_success(
        api.enroll_application(admitted_1["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert enrolled["status"] == "ENROLLED"
    # Hop 1: sibling cascaded ADMITTED → DECLINED
    sib_after = validate_success(
        api.get_application(admitted_2["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert sib_after["status"] == "DECLINED"
    # Hop 2: sibling's FINALIZED AidPackage cascaded → REVOKED
    aid_2_after = validate_success(
        api.get_aid_package(aid_2["id"], TEST_USERS["financial_aid_headers"]),
        expected_status=200,
    )
    assert aid_2_after["status"] == "REVOKED"
    # Enrolled-side aid is preserved
    aid_1_after = validate_success(
        api.get_aid_package(aid_1["id"], TEST_USERS["financial_aid_headers"]),
        expected_status=200,
    )
    assert aid_1_after["status"] == "FINALIZED"
    # School counters
    s_enroll_after = validate_success(
        api.get_school(s_enroll["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert s_enroll_after["enrolled_count"] == 1
    assert s_enroll_after["admitted_count"] == 0
    s_other_after = validate_success(
        api.get_school(s_other["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert s_other_after["admitted_count"] == 0
    assert s_other_after["declined_count"] == 1


# ─── Difficulty Rule 4 instance 2: depth-2 decline cascade ─────────────────

def test_applicant_decline_cascades_aid_to_revoked(api):
    """PRD §3.9: "The transition stamps enrollment_decision_at, increments the
    school's declined_count, and, when the source was ADMITTED, decrements
    the school's admitted_count and recomputes yield_posture, and cascades
    any FINALIZED AidPackage to REVOKED".

    Design: Difficulty/transitive_cascade/deny_chains_through_aid_revoke_depth_2
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, admitted, aid_pkg = setup_aid_finalized(
        email_suffix="dx", residency="IN_STATE",
    )
    declined = validate_success(
        api.decline_application(admitted["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert declined["status"] == "DECLINED"
    aid_after = validate_success(
        api.get_aid_package(aid_pkg["id"], TEST_USERS["financial_aid_headers"]),
        expected_status=200,
    )
    assert aid_after["status"] == "REVOKED"
    school_after = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert school_after["admitted_count"] == 0
    assert school_after["declined_count"] == 1
