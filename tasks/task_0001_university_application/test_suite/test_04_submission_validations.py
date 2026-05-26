"""Application submission validations: deadline, incomplete bundle, ED
exclusivity, word-count tolerance, validation priority ordering.

Covers Difficulty Rule 5 (priority_pair_validation_conflict), Rule 6 (boundary
word-count), Rule 8 (resource_temporal_overlap ED exclusivity) plus related
Corner validation triggers.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_applicant,
    create_application_payload,
    create_essay_payload,
    create_financial_aid_profile,
    create_school,
    make_applicant_headers,
    set_clock,
    setup_aid_finalized,
    setup_admitted_application,
    setup_ready_to_submit_application,
    setup_submitted_application,
    setup_under_review_application,
    validate_error,
    validate_success,
)


# ─── Deadline / Incomplete (Corner validations) ────────────────────────────

def test_deadline_passed_blocks_submit(api):
    """PRD §3.5: "the platform's logical clock (see §2.10) reads a value no
    later than the target school's deadline_iso".
    PRD §3.5: "A deadline miss yields ERR_DEADLINE_PASSED".

    Design: Corner/validations/deadline_passed_blocks_submit
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, app = setup_ready_to_submit_application(
        email_suffix="dl",
        school_overrides={
            "name": "U Dl", "state_code": "OK",
            "deadline_iso": "2026-10-01T00:00:00Z",
        },
    )
    set_clock("2026-10-02T00:00:00Z")  # past deadline
    res = api.submit_application(app["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_DEADLINE_PASSED")
    after = validate_success(
        api.get_application(app["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert after["status"] == "DRAFT"


def test_application_incomplete_missing_two_recs(api):
    """PRD §3.5: "at least two RecommendationRequest rows exist where the
    applicant_id and school_id match this application and the status is
    SUBMITTED".
    PRD §3.5: "missing essays, recommendations, or financial-aid profile yield
    the bundled ERR_APPLICATION_INCOMPLETE."

    Design: Corner/validations/application_incomplete_missing_two_recs
    """
    set_clock("2026-09-01T00:00:00Z")
    # Build a draft app with 2 completed essays, FAP, but only 1 SUBMITTED rec.
    applicant, school, app = setup_ready_to_submit_application(
        email_suffix="inc",
        num_recommendations=1,
        rec_ratings=[4],
    )
    res = api.submit_application(app["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_APPLICATION_INCOMPLETE")


# ─── Essay word-count boundary (Difficulty Rule 6 instance 2) ──────────────

_TEXT_500_WORDS = " ".join(["word"] * 500)


def test_essay_word_count_delta_5_words_inclusive_succeeds(api):
    """PRD §3.3: "The server independently re-counts the words in text and
    rejects the create or update with ERR_WORD_COUNT_MISMATCH whenever the
    declared word_count differs from the server count by more than 5 words in
    either direction."

    Design: Difficulty/boundary_precision_check/essay_word_count_exact_5_word_delta_passes_6_word_delta_fails
    """
    set_clock("2026-09-01T00:00:00Z")
    school = create_school(name="U Wc", state_code="AZ")
    applicant = create_applicant(email="wc@u.edu", gpa_unweighted=3.50, sat_total=1300,
                                 residency="IN_STATE")
    app = validate_success(
        api.create_application(
            create_application_payload(applicant["id"], school["id"]),
            make_applicant_headers(applicant["id"]),
        ),
        expected_status=201,
    )
    # declared word_count = 505, actual = 500 → delta 5, boundary inclusive
    payload = create_essay_payload(
        app["id"], prompt_code="P_PASS", word_count=505, text=_TEXT_500_WORDS, completed=True,
    )
    essay = validate_success(
        api.create_essay(payload, make_applicant_headers(applicant["id"])),
        expected_status=201,
    )
    assert essay["word_count"] == 505


def test_essay_word_count_delta_6_words_exceeds_tolerance_fails(api):
    """PRD §3.3: "The server independently re-counts the words in text and
    rejects the create or update with ERR_WORD_COUNT_MISMATCH whenever the
    declared word_count differs from the server count by more than 5 words in
    either direction."

    Design: Difficulty/boundary_precision_check/essay_word_count_exact_5_word_delta_passes_6_word_delta_fails
    """
    set_clock("2026-09-01T00:00:00Z")
    school = create_school(name="U WcF", state_code="AZ")
    applicant = create_applicant(email="wcf@u.edu", gpa_unweighted=3.50, sat_total=1300,
                                 residency="IN_STATE")
    app = validate_success(
        api.create_application(
            create_application_payload(applicant["id"], school["id"]),
            make_applicant_headers(applicant["id"]),
        ),
        expected_status=201,
    )
    payload = create_essay_payload(
        app["id"], prompt_code="P_FAIL", word_count=506, text=_TEXT_500_WORDS, completed=True,
    )
    res = api.create_essay(payload, make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_WORD_COUNT_MISMATCH")


# ─── Essay word_count out-of-bounds (Corner errors) ────────────────────────

def test_essay_word_count_zero_returns_invalid_request(api):
    """PRD §3.3: "an integer word_count between 1 and 650 inclusive".
    PRD §2.6: "generic input validation (ERR_INVALID_REQUEST) for missing
    required fields, type mismatches, and out-of-bounds numerics."

    Design: Corner/errors/err_invalid_request_essay_word_count_negative
    """
    school = create_school(name="U EE", state_code="SC")
    applicant = create_applicant(email="ee_e@u.edu", gpa_unweighted=3.0, residency="IN_STATE")
    app = validate_success(
        api.create_application(
            create_application_payload(applicant["id"], school["id"]),
            make_applicant_headers(applicant["id"]),
        ),
        expected_status=201,
    )
    payload = {
        "application_id": app["id"],
        "prompt_code": "P1",
        "word_count": 0,
        "text": "x",
        "completed": True,
    }
    res = api.create_essay(payload, make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── ED exclusivity (Difficulty Rule 8 instance 1 + Corner stale-link) ─────

def test_ed_exclusivity_blocks_second_ed_submit(api):
    """PRD §3.5: "If the school's admission_track is EARLY_DECISION, one
    further constraint applies: the applicant must not already have another
    Application whose admission_track_snapshot is EARLY_DECISION and whose
    status is any of SUBMITTED, UNDER_REVIEW, ADMITTED, WAITLISTED, or
    ENROLLED — only one Early-Decision commitment may live at a time,
    enforced by ERR_ED_EXCLUSIVITY_VIOLATED."

    Design: Difficulty/resource_temporal_overlap/ed_exclusivity_aggregate_capacity_one_over_closed_window
    """
    set_clock("2026-09-01T00:00:00Z")
    school_a = create_school(
        name="U ED A", state_code="MA", admission_track="EARLY_DECISION",
        deadline_iso="2026-11-01T00:00:00Z",
        decision_release_iso="2026-12-15T00:00:00Z",
        target_class_size=50, assumed_yield_rate=0.90,
    )
    school_b = create_school(
        name="U ED B", state_code="CT", admission_track="EARLY_DECISION",
        deadline_iso="2026-11-15T00:00:00Z",
        decision_release_iso="2026-12-30T00:00:00Z",
        target_class_size=50, assumed_yield_rate=0.90,
    )
    # First ED app fully ready and submitted at school_a
    applicant, _, _ = setup_submitted_application(
        submit_clock_iso="2026-10-15T00:00:00Z",
        school=school_a, email_suffix="eda",
        gpa=3.80, sat_total=1400,
    )
    # Second ED app at school_b, ALSO fully eligible (so only ED-exclusivity can fail)
    _, _, app_b = setup_ready_to_submit_application(
        school=school_b, applicant=applicant, email_suffix="edb",
    )
    res = api.submit_application(app_b["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_ED_EXCLUSIVITY_VIOLATED")
    after = validate_success(
        api.get_application(app_b["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert after["status"] == "DRAFT"


def test_ed_exclusivity_aggregate_capacity_closed_window(api):
    """PRD §3.5: "only one Early-Decision commitment may live at a time,
    enforced by ERR_ED_EXCLUSIVITY_VIOLATED."

    Design: Difficulty/resource_temporal_overlap/ed_exclusivity_aggregate_capacity_one_over_closed_window
    """
    set_clock("2026-09-01T00:00:00Z")
    s1 = create_school(
        name="U EDX1", state_code="MA", admission_track="EARLY_DECISION",
        deadline_iso="2026-11-01T00:00:00Z",
        decision_release_iso="2026-12-15T00:00:00Z",
        target_class_size=50, assumed_yield_rate=0.90,
    )
    s2 = create_school(
        name="U EDX2", state_code="CT", admission_track="EARLY_DECISION",
        deadline_iso="2026-11-15T00:00:00Z",
        decision_release_iso="2026-12-30T00:00:00Z",
        target_class_size=50, assumed_yield_rate=0.90,
    )
    applicant, _, _ = setup_submitted_application(
        submit_clock_iso="2026-10-15T00:00:00Z",
        school=s1, email_suffix="edx",
        gpa=3.80, sat_total=1400,
    )
    # Second ED draft remains DRAFT after a rejected submit
    _, _, app2 = setup_ready_to_submit_application(
        school=s2, applicant=applicant, email_suffix="edx2",
    )
    res = api.submit_application(app2["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_ED_EXCLUSIVITY_VIOLATED")


# ─── ED-binding violation on decline ────────────────────────────────────────

def test_ed_binding_violation_blocks_decline_of_admitted_ed(api):
    """PRD §3.9: "A decline from ADMITTED is rejected when the application's
    admission_track_snapshot is EARLY_DECISION — Early-Decision admits are
    binding, and the attempt surfaces ERR_ED_BINDING_VIOLATION."

    Design: Corner/validations/ed_binding_violation_blocks_decline
    """
    set_clock("2026-09-01T00:00:00Z")
    school = create_school(
        name="U EDB", state_code="VT", admission_track="EARLY_DECISION",
        deadline_iso="2026-11-01T00:00:00Z",
        decision_release_iso="2026-12-15T00:00:00Z",
        target_class_size=50, assumed_yield_rate=0.90,
    )
    applicant, _, admitted = setup_admitted_application(
        submit_clock_iso="2026-10-15T00:00:00Z",
        review_clock_iso="2026-11-15T00:00:00Z",
        school=school, email_suffix="edb",
        gpa=3.80, sat_total=1400,
    )
    res = api.decline_application(admitted["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_ED_BINDING_VIOLATION")
    after = validate_success(
        api.get_application(admitted["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert after["status"] == "ADMITTED"


# ─── Validation priority pair: ED-exclusivity outranks incomplete ─────────

def test_ed_exclusivity_outranks_application_incomplete(api):
    """PRD §2.6: "then the Early-Decision exclusivity check at submit
    (ERR_ED_EXCLUSIVITY_VIOLATED); then the application-submit completeness
    bundle (ERR_APPLICATION_INCOMPLETE)".

    Design: Difficulty/priority_pair_validation_conflict/ed_exclusivity_safety_outranks_incomplete_constraint
    """
    set_clock("2026-09-01T00:00:00Z")
    s_ed1 = create_school(
        name="U EDP1", state_code="MA", admission_track="EARLY_DECISION",
        deadline_iso="2026-11-01T00:00:00Z",
        decision_release_iso="2026-12-15T00:00:00Z",
        target_class_size=50, assumed_yield_rate=0.90,
    )
    s_ed2 = create_school(
        name="U EDP2", state_code="CT", admission_track="EARLY_DECISION",
        deadline_iso="2026-11-15T00:00:00Z",
        decision_release_iso="2026-12-30T00:00:00Z",
        target_class_size=50, assumed_yield_rate=0.90,
    )
    applicant, _, _ = setup_submitted_application(
        submit_clock_iso="2026-10-15T00:00:00Z",
        school=s_ed1, email_suffix="edp1", gpa=3.80, sat_total=1400,
    )
    # Second ED draft with ONLY 1 recommendation (so incomplete fires alongside ED-exclusivity)
    app2 = validate_success(
        api.create_application(
            create_application_payload(applicant["id"], s_ed2["id"]),
            make_applicant_headers(applicant["id"]),
        ),
        expected_status=201,
    )
    validate_success(
        api.create_essay(
            create_essay_payload(app2["id"], prompt_code="P1"),
            make_applicant_headers(applicant["id"]),
        ),
        expected_status=201,
    )
    inv = validate_success(
        api.create_recommendation_request(
            {
                "applicant_id": applicant["id"],
                "school_id": s_ed2["id"],
                "recommender_email": "rp2@x.edu",
            },
            make_applicant_headers(applicant["id"]),
        ),
        expected_status=201,
    )
    validate_success(
        api.submit_recommendation_request(
            inv["id"], 5, TEST_USERS["platform_admin_headers"]
        ),
        expected_status=200,
    )
    res = api.submit_application(app2["id"], make_applicant_headers(applicant["id"]))
    # Priority 7 (ED-exclusivity) wins over priority 8 (incomplete)
    validate_error(res, "ERR_ED_EXCLUSIVITY_VIOLATED")


def test_state_check_outranks_aid_exceeds_tuition(api):
    """PRD §2.6: "then state-machine eligibility (ERR_INVALID_STATE); ...
    then the aid-package tuition cap (ERR_AID_EXCEEDS_TUITION)".

    Design: Difficulty/priority_pair_validation_conflict/aid_state_outranks_aid_exceeds_tuition_constraint
    """
    set_clock("2026-09-01T00:00:00Z")
    school = create_school(
        name="U AS", state_code="VT", admission_track="REGULAR",
        deadline_iso="2026-10-01T00:00:00Z",
        decision_release_iso="2027-03-15T00:00:00Z",
        target_class_size=100, assumed_yield_rate=0.50,
        in_state_tuition_cents=1_500_000,
        out_of_state_tuition_cents=3_000_000,
        international_tuition_cents=5_000_000,
    )
    # Admitted + Drafted AidPackage that EXCEEDS tuition
    from test_helpers import setup_aid_drafted
    applicant, _, admitted, aid_pkg = setup_aid_drafted(
        grant_cents=1_000_000, loan_cents=500_000, work_study_cents=200_000,
        school=school, email_suffix="as", residency="IN_STATE",
    )
    # Applicant declines (REGULAR track allows decline). PRD §3.9 scopes the
    # aid-cascade to FINALIZED AidPackages only, so the DRAFT package stays
    # DRAFT; the application moves to DECLINED.
    validate_success(
        api.decline_application(admitted["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    # Finalize attempt: state-precondition (linked application in ADMITTED) fails
    # AND grant+loan+ws > tuition; state error must win per §2.6 priority order.
    res = api.finalize_aid_package(aid_pkg["id"], TEST_USERS["financial_aid_headers"])
    validate_error(res, "ERR_INVALID_STATE")
