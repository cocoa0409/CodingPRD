"""Course credits: hour-conversion boundaries, transcript audit variants, GPA,
and the post/revoke round-trip invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_course_credit,
    assert_transcript,
    complete_credit,
    create_planned_credit,
    create_posted_credit,
    create_open_year,
    get_success_data,
    setup_active_enrollment,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]


def _setup_senior(api, family_name="Fam Cred", district_code="D-02",
                  date_of_birth="2008-05-05"):
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 12, family_name=family_name,
                                  district_code=district_code,
                                  student_name="Senior", date_of_birth=date_of_birth)
    return ctx


def _setup_mixed_credit_states(api):
    """ENGLISH 120h A POSTED; MATH 120h B VERIFIED; SCIENCE 60h A COMPLETED;
    ELECTIVE left PLANNED."""
    ctx = _setup_senior(api)
    enr, fam = ctx["enrollment"], ctx["family"]

    create_posted_credit(enr, fam, "ENGLISH", "English 12", 120, "A")

    c2 = create_planned_credit(enr, fam, subject="MATH", course_title="Algebra II",
                               planned_hours=120)
    get_success_data(complete_credit(c2, fam, 120, "B"))
    get_success_data(api.verify_course_credit(c2["id"], {"decision": "APPROVE"}, REGISTRAR))

    c3 = create_planned_credit(enr, fam, subject="SCIENCE", course_title="Biology",
                               planned_hours=60, is_lab=True)
    get_success_data(complete_credit(c3, fam, 60, "A"))

    create_planned_credit(enr, fam, subject="ELECTIVE", course_title="Robotics",
                          planned_hours=120)
    return ctx


def test_transcript_official_counts_posted_only(api):
    """PRD §3.8: "It reports `official_credits_total`, the sum over the
    student's `POSTED` credits across all enrollments; `projected_credits_total`,
    the same sum over `POSTED`, `VERIFIED`, and `COMPLETED` credits;
    `subject_credits_official`, the per-subject official bucket totals; and
    `gpa_official`, the grade-point average over `POSTED` credits — `A` worth 4
    points, `B` 3, `C` 2, `D` 1, `F` 0 — computed as the sum of each credit's
    points times its `credit_value`, divided by the sum of those credit values,
    rounded half-up to two decimal places, and null when no posted credits
    exist."

    Design: Difficulty/dual_variant_calc/graduation_official_vs_projected_credit_audit
    """
    ctx = _setup_mixed_credit_states(api)
    transcript = validate_success(api.get_transcript(ctx["student"]["id"], REGISTRAR))
    assert_transcript(transcript)
    assert transcript["official_credits_total"] == 1.0, "POSTED only"
    assert transcript["gpa_official"] == 4.0, "single POSTED A on 1.0 credit"
    assert transcript["subject_credits_official"]["ENGLISH"] == 1.0


def test_transcript_projected_includes_verified_and_completed(api):
    """PRD §3.8: "It reports `official_credits_total`, the sum over the
    student's `POSTED` credits across all enrollments; `projected_credits_total`,
    the same sum over `POSTED`, `VERIFIED`, and `COMPLETED` credits;
    `subject_credits_official`, the per-subject official bucket totals; and
    `gpa_official`, the grade-point average over `POSTED` credits — `A` worth 4
    points, `B` 3, `C` 2, `D` 1, `F` 0 — computed as the sum of each credit's
    points times its `credit_value`, divided by the sum of those credit values,
    rounded half-up to two decimal places, and null when no posted credits
    exist."

    Design: Difficulty/dual_variant_calc/graduation_official_vs_projected_credit_audit
    """
    ctx = _setup_mixed_credit_states(api)
    transcript = validate_success(api.get_transcript(ctx["student"]["id"], REGISTRAR))
    # POSTED 1.0 + VERIFIED 1.0 + COMPLETED 0.5; the PLANNED credit is excluded.
    assert transcript["projected_credits_total"] == 2.5
    assert transcript["official_credits_total"] != transcript["projected_credits_total"]


def test_course_credit_hour_conversion_boundaries(api):
    """PRD §3.8: "Completion requires at least 60 reported hours — 59 is refused
    with `ERR_CREDIT_HOURS_INSUFFICIENT` — and an enrollment in `ACTIVE` or
    `COMPLETED` status (else `ERR_ENROLLMENT_NOT_ACTIVE`). The earned
    `credit_value` is the number of whole sixty-hour blocks in the reported
    hours, multiplied by one-half credit, with no cap: 60 hours earns 0.5
    credits, 119 hours still 0.5, 120 hours earns 1.0, and 240 hours earns 2.0."

    Design: Corner/calculations/course_credit_hour_conversion_boundaries
    """
    ctx = _setup_senior(api, family_name="Fam H", district_code="D-42",
                        date_of_birth="2008-01-01")
    enr, fam = ctx["enrollment"], ctx["family"]

    c59 = create_planned_credit(enr, fam, course_title="TooShort", planned_hours=59)
    resp = complete_credit(c59, fam, 59, "A")
    validate_error(resp, ApiErrorId.ERR_CREDIT_HOURS_INSUFFICIENT)

    cases = [(60, 0.5), (119, 0.5), (120, 1.0), (240, 2.0)]
    for hours, expected_value in cases:
        credit = create_planned_credit(enr, fam, course_title=f"C{hours}",
                                       planned_hours=hours)
        completed = validate_success(complete_credit(credit, fam, hours, "A"))
        assert_course_credit(completed)
        assert completed["status"] == "COMPLETED"
        assert completed["credit_value"] == pytest.approx(expected_value), (
            f"{hours} hours -> {expected_value} credits"
        )


def test_gpa_weighted_rounding(api):
    """PRD §3.8: "`gpa_official`, the grade-point average over `POSTED` credits
    — `A` worth 4 points, `B` 3, `C` 2, `D` 1, `F` 0 — computed as the sum of
    each credit's points times its `credit_value`, divided by the sum of those
    credit values, rounded half-up to two decimal places, and null when no
    posted credits exist."

    Design: Corner/calculations/gpa_weighted_rounding
    """
    ctx = _setup_senior(api, family_name="Fam G", district_code="D-43",
                        date_of_birth="2008-02-02")
    enr, fam = ctx["enrollment"], ctx["family"]
    create_posted_credit(enr, fam, "ENGLISH", "English 12", 120, "A")    # 1.0 @ 4
    create_posted_credit(enr, fam, "FINE_ARTS", "Studio Art", 60, "B")   # 0.5 @ 3

    transcript = validate_success(api.get_transcript(ctx["student"]["id"], REGISTRAR))
    assert transcript["official_credits_total"] == 1.5
    # (4*1.0 + 3*0.5) / 1.5 = 3.6666... -> round-half-up 2dp = 3.67
    assert transcript["gpa_official"] == 3.67


def test_credit_post_roundtrip_sets_transcript(api):
    """PRD §3.8: "Posting — `VERIFIED` → `POSTED` — writes the credit to the
    transcript, stamps `posted_at`, and recomputes the transcript's derived
    values; it is possible only while the student's transcript remains unsealed,
    a sealed transcript refusing with `ERR_TRANSCRIPT_SEALED`."

    Design: Difficulty/compensating_invariant/credit_post_revoke_roundtrip_invariant
    """
    ctx = _setup_senior(api, family_name="Fam Rev", district_code="D-25",
                        date_of_birth="2008-01-12")
    credit = create_posted_credit(ctx["enrollment"], ctx["family"],
                                  "ENGLISH", "English 12", 120, "A")
    assert credit["status"] == "POSTED"
    assert credit["posted_at"] is not None

    transcript = validate_success(api.get_transcript(ctx["student"]["id"], REGISTRAR))
    assert transcript["official_credits_total"] == 1.0
    assert transcript["gpa_official"] == 4.0
    assert transcript["transcript_sealed"] is False


def test_credit_revoke_restores_transcript_invariant(api):
    """PRD §3.8: "A posted credit can still be revoked — `POSTED` → `REVOKED`,
    terminal — with the supplied `reason` stored as `revoked_reason`; revocation
    is likewise blocked by a sealed transcript with `ERR_TRANSCRIPT_SEALED`, and
    revoked credits are excluded from every transcript derivation, which is
    recomputed on the spot."

    Design: Difficulty/compensating_invariant/credit_post_revoke_roundtrip_invariant
    """
    ctx = _setup_senior(api, family_name="Fam Rev", district_code="D-25",
                        date_of_birth="2008-01-12")
    credit = create_posted_credit(ctx["enrollment"], ctx["family"],
                                  "ENGLISH", "English 12", 120, "A")
    revoked = validate_success(
        api.revoke_course_credit(credit["id"], {"reason": "hours documentation lost"},
                                 REGISTRAR)
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_reason"] == "hours documentation lost"

    transcript = validate_success(api.get_transcript(ctx["student"]["id"], REGISTRAR))
    assert transcript["official_credits_total"] == 0.0, "invariant restored to pre-post value"
    assert transcript["gpa_official"] is None, "empty POSTED set: no division by zero"
    assert transcript["transcript_sealed"] is False
