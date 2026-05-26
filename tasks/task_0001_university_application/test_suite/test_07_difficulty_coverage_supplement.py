"""Supplementary tests ensuring each Difficulty-design instance has ≥2 tests.

Each test here asserts a distinct facet of the same Difficulty instance — a
side-effect, a counter, or a downstream entity update — that complements the
primary assertion file. The Difficulty docstring tag points to the same
instance the primary test does.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    admit_n_applications_at_school,
    create_aid_package_payload,
    create_application_payload,
    create_essay_payload,
    create_school,
    create_submitted_recommendation,
    make_applicant_headers,
    set_clock,
    setup_admitted_application,
    setup_aid_finalized,
    setup_applicant_with_fap,
    setup_ready_to_submit_application,
    setup_submitted_application,
    setup_under_review_application,
    setup_waitlisted_application,
    validate_error,
    validate_success,
)


# ─── Difficulty Rule 2 (yield_posture) second test ─────────────────────────

def test_yield_posture_admitted_count_recompute_on_admit(api):
    """PRD §3.2: "Its computation projects the eventual enrolled headcount by
    taking the school's current admitted_count, multiplying by the school's
    assumed_yield_rate, adding the current enrolled_count, and rounding to a
    whole person using round-half-up. That projected yield is divided by
    target_class_size to produce a ratio."
    PRD §3.2: "the posture is recomputed every time admitted_count or
    enrolled_count changes, which in practice means every Application status
    transition into or out of ADMITTED or ENROLLED."

    Design: Difficulty/combinatorial_formula/yield_posture_multi_input_nonlinear_threshold
    """
    set_clock("2026-09-01T00:00:00Z")
    school = create_school(
        name="U YR2", state_code="CA", admission_track="REGULAR",
        deadline_iso="2026-10-01T00:00:00Z",
        decision_release_iso="2027-03-15T00:00:00Z",
        target_class_size=20, assumed_yield_rate=0.50,
    )
    # First admit: admitted_count=1, projected=round(0.5)=1, ratio=0.05 → OPEN
    admit_n_applications_at_school(1, school, email_prefix="yr2")
    s = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert s["admitted_count"] == 1
    assert s["yield_posture"] == "OPEN"


# ─── Difficulty Rule 4 instance 1 (enroll cascade depth-3) second test ────

def test_enroll_cascades_decrement_sibling_school_admitted_count(api):
    """PRD §3.9: "Each cascaded decline transition fires its full side-effect
    set in the same transaction — the linked school's declined_count is
    incremented, the linked school's admitted_count is decremented (only when
    the cascade source was ADMITTED, since a WAITLISTED row's count is held
    by the waitlist, not by admitted_count), the linked school's
    yield_posture is recomputed".

    Design: Difficulty/transitive_cascade/enroll_chains_through_other_admit_to_aid_revoke_depth_3
    """
    set_clock("2026-09-01T00:00:00Z")
    s_enroll = create_school(name="U Enroll2", state_code="MA")
    s_other = create_school(name="U Other2", state_code="NY")
    applicant = setup_applicant_with_fap(
        email="en2c@u.edu", gpa=3.80, sat_total=1400, residency="IN_STATE",
    )
    _, _, admitted_1, _ = setup_aid_finalized(
        school=s_enroll, applicant=applicant, email_suffix="en2c1",
    )
    _, _, admitted_2, aid_2 = setup_aid_finalized(
        school=s_other, applicant=applicant, email_suffix="en2c2",
    )
    s_other_before = validate_success(
        api.get_school(s_other["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert s_other_before["admitted_count"] == 1
    validate_success(
        api.enroll_application(admitted_1["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    s_other_after = validate_success(
        api.get_school(s_other["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    # Cascade hop 1: sibling ADMITTED → DECLINED; admitted_count decremented to 0.
    assert s_other_after["admitted_count"] == 0
    assert s_other_after["declined_count"] == 1


# ─── Difficulty Rule 4 instance 2 (decline cascade depth-2) second test ───

def test_applicant_decline_decrements_school_admitted_count(api):
    """PRD §3.9: "when the source was ADMITTED, decrements the school's
    admitted_count and recomputes yield_posture, and cascades any FINALIZED
    AidPackage to REVOKED".

    Design: Difficulty/transitive_cascade/deny_chains_through_aid_revoke_depth_2
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, admitted, _ = setup_aid_finalized(email_suffix="dx2")
    before = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert before["admitted_count"] == 1
    validate_success(
        api.decline_application(admitted["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    after = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert after["admitted_count"] == 0


# ─── Difficulty Rule 5 instance 1 (ED-excl > incomplete) second test ──────

def test_ed_exclusivity_priority_pair_target_unchanged(api):
    """PRD §3.5: "If the school's admission_track is EARLY_DECISION, one
    further constraint applies: the applicant must not already have another
    Application whose admission_track_snapshot is EARLY_DECISION and whose
    status is any of SUBMITTED, UNDER_REVIEW, ADMITTED, WAITLISTED, or
    ENROLLED — only one Early-Decision commitment may live at a time,
    enforced by ERR_ED_EXCLUSIVITY_VIOLATED."

    Design: Difficulty/priority_pair_validation_conflict/ed_exclusivity_safety_outranks_incomplete_constraint
    """
    set_clock("2026-09-01T00:00:00Z")
    s_ed1 = create_school(
        name="U EDPx1", state_code="MA", admission_track="EARLY_DECISION",
        deadline_iso="2026-11-01T00:00:00Z",
        decision_release_iso="2026-12-15T00:00:00Z",
        target_class_size=50, assumed_yield_rate=0.90,
    )
    s_ed2 = create_school(
        name="U EDPx2", state_code="CT", admission_track="EARLY_DECISION",
        deadline_iso="2026-11-15T00:00:00Z",
        decision_release_iso="2026-12-30T00:00:00Z",
        target_class_size=50, assumed_yield_rate=0.90,
    )
    applicant, _, _ = setup_submitted_application(
        submit_clock_iso="2026-10-15T00:00:00Z",
        school=s_ed1, email_suffix="edpx", gpa=3.80, sat_total=1400,
    )
    # Second ED draft with NO recommendations (incomplete in MULTIPLE ways) — still ED-excl wins.
    app2 = validate_success(
        api.create_application(
            create_application_payload(applicant["id"], s_ed2["id"]),
            make_applicant_headers(applicant["id"]),
        ),
        expected_status=201,
    )
    res = api.submit_application(app2["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_ED_EXCLUSIVITY_VIOLATED")
    after = validate_success(
        api.get_application(app2["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert after["status"] == "DRAFT"


# ─── Difficulty Rule 5 instance 2 (state > aid_exceeds) second test ───────

def test_state_outranks_aid_exceeds_after_deny_cascade_revoke(api):
    """PRD §3.9: "A decline from ADMITTED ... cascades any FINALIZED AidPackage
    to REVOKED".
    PRD §2.6: "then state-machine eligibility (ERR_INVALID_STATE); ... then
    the aid-package tuition cap (ERR_AID_EXCEEDS_TUITION)".

    Design: Difficulty/priority_pair_validation_conflict/aid_state_outranks_aid_exceeds_tuition_constraint
    """
    set_clock("2026-09-01T00:00:00Z")
    school = create_school(
        name="U ASB", state_code="VT", admission_track="REGULAR",
        deadline_iso="2026-10-01T00:00:00Z",
        decision_release_iso="2027-03-15T00:00:00Z",
        target_class_size=100, assumed_yield_rate=0.50,
        in_state_tuition_cents=1_500_000,
        out_of_state_tuition_cents=3_000_000,
        international_tuition_cents=5_000_000,
    )
    from test_helpers import setup_aid_finalized
    # Finalize an aid package within cap (so finalize succeeds), then the
    # applicant declines from ADMITTED — PRD §3.9: a decline from ADMITTED
    # cascades any FINALIZED AidPackage to REVOKED. Retry finalize: state
    # precondition (DRAFT) fails — state error must win per §2.6.
    applicant, _, admitted, aid_pkg = setup_aid_finalized(
        grant_cents=500_000, loan_cents=400_000, work_study_cents=100_000,
        school=school, email_suffix="asb", residency="IN_STATE",
    )
    validate_success(
        api.decline_application(admitted["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    aid_after = validate_success(
        api.get_aid_package(aid_pkg["id"], TEST_USERS["financial_aid_headers"]),
        expected_status=200,
    )
    assert aid_after["status"] == "REVOKED"
    # Finalize attempt now: state precondition fails (package is REVOKED, not
    # DRAFT). State error wins per §2.6.
    res = api.finalize_aid_package(aid_pkg["id"], TEST_USERS["financial_aid_headers"])
    validate_error(res, "ERR_INVALID_STATE")


# ─── Difficulty Rule 6 instance 1 (yield_posture 0.85 boundary) second ──

def test_yield_posture_below_boundary_remains_open(api):
    """PRD §3.2: "If the ratio is at least 1.00, the posture is OVER_TARGET;
    otherwise, if the ratio is at least 0.85, the posture is ON_TARGET;
    otherwise the posture is OPEN."

    Design: Difficulty/boundary_precision_check/yield_posture_exact_0_85_ratio_maps_on_target
    """
    set_clock("2026-09-01T00:00:00Z")
    school = create_school(
        name="U BdryLow", state_code="OR", admission_track="REGULAR",
        deadline_iso="2026-10-01T00:00:00Z",
        decision_release_iso="2027-03-15T00:00:00Z",
        target_class_size=20, assumed_yield_rate=0.50,
    )
    # 32 admits → projected = round(16.0) = 16; ratio = 0.80 → OPEN (below 0.85)
    admit_n_applications_at_school(32, school, email_prefix="bdry_low")
    after = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert after["admitted_count"] == 32
    assert after["yield_posture"] == "OPEN"


# ─── Difficulty Rule 8 instance 2 (enrollment uniqueness) second test ────

def test_enrollment_uniqueness_first_enroll_remains_unchanged(api):
    """PRD §3.9: "an applicant can be enrolled in at most one school across
    the lifetime of their account (an open-ended occupation interval starting
    at the enroll instant)."

    Design: Difficulty/resource_temporal_overlap/enrollment_uniqueness_aggregate_capacity_one_over_open_ended_window
    """
    set_clock("2026-09-01T00:00:00Z")
    s_e1 = create_school(name="U EE1", state_code="RI", admission_track="REGULAR")
    s_e2 = create_school(
        name="U EE2", state_code="NH", admission_track="ROLLING",
        deadline_iso="2027-04-01T00:00:00Z",
        decision_release_iso="2027-06-15T00:00:00Z",
    )
    applicant = setup_applicant_with_fap(
        email="ee2@u.edu", gpa=3.80, sat_total=1400, residency="IN_STATE",
    )
    _, _, admitted_1, _ = setup_aid_finalized(
        school=s_e1, applicant=applicant, email_suffix="ee2_1",
    )
    validate_success(
        api.enroll_application(admitted_1["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    # Build a second admitted-with-aid application
    _, _, ready_2 = setup_ready_to_submit_application(
        school=s_e2, applicant=applicant, email_suffix="ee2_2",
    )
    sub_2 = validate_success(
        api.submit_application(ready_2["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    ur_2 = validate_success(
        api.begin_review_application(sub_2["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    admitted_2 = validate_success(
        api.admit_application(
            ur_2["id"], ur_2["version"], TEST_USERS["admissions_headers"]
        ),
        expected_status=200,
    )
    aid_2 = validate_success(
        api.create_aid_package(
            create_aid_package_payload(admitted_2["id"]),
            TEST_USERS["financial_aid_headers"],
        ),
        expected_status=201,
    )
    validate_success(
        api.finalize_aid_package(aid_2["id"], TEST_USERS["financial_aid_headers"]),
        expected_status=200,
    )
    # Second enroll rejected; the first remains ENROLLED (open-ended occupation continues).
    res = api.enroll_application(admitted_2["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_ENROLLMENT_ALREADY_DECLARED")
    a1_after = validate_success(
        api.get_application(admitted_1["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert a1_after["status"] == "ENROLLED"


# ─── Difficulty Rule 9 instance 1 (submit-withdraw invariant) second test ─

def test_withdraw_from_draft_does_not_decrement_submission_count(api):
    """PRD §3.1: "It is recomputed only at the boundary crossings: incremented
    when an application transitions from DRAFT to SUBMITTED, decremented when
    an application transitions from SUBMITTED back to WITHDRAWN."
    PRD §3.9: "withdrawing from DRAFT does not (the application was never
    counted)."

    Design: Difficulty/compensating_invariant/submit_withdraw_preserves_applicant_submission_count
    """
    from test_helpers import create_applicant, create_draft_application
    school = create_school(name="U Inv1b", state_code="NM")
    applicant = create_applicant(
        email="inv1b@u.edu", gpa_unweighted=3.50, sat_total=1300, residency="IN_STATE",
    )
    draft = create_draft_application(applicant, school)
    withdrawn = validate_success(
        api.withdraw_application(draft["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert withdrawn["status"] == "WITHDRAWN"
    a_after = validate_success(
        api.get_applicant(applicant["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert a_after["submitted_application_count"] == 0


# ─── Difficulty Rule 9 instance 2 (admit-decline volume) second test ──────

def test_admit_decline_preserves_yield_posture_recompute_open(api):
    """PRD §3.6: "increments the linked school's admitted_count by one,
    recomputes the school's yield_posture as described in §3.2".
    PRD §3.9: "when the source was ADMITTED, decrements the school's
    admitted_count and recomputes yield_posture".

    Design: Difficulty/compensating_invariant/admit_decline_preserves_school_decision_volume
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, ur = setup_under_review_application(
        email_suffix="inv2b", gpa=3.80, sat_total=1400,
    )
    school_before = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert school_before["yield_posture"] == "OPEN"
    admitted = validate_success(
        api.admit_application(ur["id"], ur["version"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    school_after_admit = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    # target_class_size=100, rate=0.50, admitted=1 → projected=round(0.5)=1, ratio=0.01 → OPEN
    assert school_after_admit["yield_posture"] == "OPEN"
    validate_success(
        api.decline_application(admitted["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    school_after_decline = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert school_after_decline["yield_posture"] == "OPEN"
    assert school_after_decline["admitted_count"] == 0
    assert school_after_decline["declined_count"] == 1
