"""At-risk score combination, the no-show sweep's risk cascade, and the two
retention report variants with their boundary behaviors."""
import pytest

from test_helpers import (
    assert_student_risk_invariants,
    book_appointment,
    create_advisor,
    create_student,
    get_student,
    mark_no_show_via_sweep,
    set_logical_clock,
    setup_retention_cohort_2025,
    setup_student_at_score_98,
    validate_success,
)


# ─── Difficulty: combinatorial_formula / at_risk_score_conditional_bands ──────

def test_at_risk_score_combines_all_five_components(api, director_headers):
    """PRD §3.2: "The base comes from the student's GPA band: 40 points when `gpa` is below 2.0, 25 points when it is at least 2.0 but below 2.5, and 10 points when it is 2.5 or higher. The referral boost is the single largest severity boost among the student's referrals in `OPEN`, `OUTREACH_IN_PROGRESS`, `NO_RESPONSE`, or `ESCALATED` status — 20 for `HIGH`, 12 for `MEDIUM`, 6 for `LOW` — or zero when no such referral exists; `RESPONDED` and `CLOSED` referrals contribute nothing. No-show points add 10 per recorded no-show, counting no more than three no-shows. Intervention points add 10 per `OPEN` intervention. Hold points add 8 per `ACTIVE` registration hold. The score is the sum of these five components, capped at 100."

    Design: Difficulty/combinatorial_formula/at_risk_score_conditional_bands
    """
    ctx = setup_student_at_score_98()
    student = get_student(ctx["student"]["id"])
    assert student["at_risk_score"] == 98, (
        "40 base (gpa 1.9) + 20 HIGH referral + 20 two no-shows + 10 one OPEN "
        "intervention + 8 one ACTIVE hold = 98"
    )
    assert_student_risk_invariants(student)


def test_at_risk_tier_high_at_seventy_and_above(api, director_headers):
    """PRD §3.2: "From the score, the `risk_tier` is `HIGH` when the score is 70 or higher, `MEDIUM` when it is at least 40 but below 70, and `LOW` below 40."

    Design: Difficulty/combinatorial_formula/at_risk_score_conditional_bands
    """
    ctx = setup_student_at_score_98()
    student = get_student(ctx["student"]["id"])
    assert student["at_risk_score"] == 98
    assert student["risk_tier"] == "HIGH", "98 >= 70 -> HIGH"


# ─── Difficulty: dual_variant_calc / retention_cohort_vs_term_variant ─────────

def test_retention_cohort_persisted_snapshot(api, director_headers):
    """PRD §3.9: "The `COHORT_PERSISTED` variant requires `cohort_year`: the denominator counts every student of that entry cohort, and the numerator counts those among them currently `ENROLLED`."
    PRD §3.9: "the rate is the numerator divided by the denominator, rendered to four decimal places with round-half-up; when the denominator is 0, the rate and numerator are both reported as 0."

    Design: Difficulty/dual_variant_calc/retention_cohort_vs_term_variant
    """
    setup_retention_cohort_2025()
    res = api.get_retention_report(
        director_headers, params={"variant": "COHORT_PERSISTED", "cohort_year": 2025}
    )
    report = validate_success(res, 200)
    assert report["numerator"] == 2, "r1 and r4 are ENROLLED; r2 ON_LEAVE, r3 INACTIVE"
    assert report["denominator"] == 4
    assert float(report["rate"]) == pytest.approx(0.5, abs=1e-9), (
        "2/4 rendered to four decimal places"
    )


def test_retention_term_over_term_sequential(api, director_headers):
    """PRD §3.9: "The `TERM_OVER_TERM` variant requires `from_term_code` and `to_term_code`, with `cohort_year` as an optional further filter: the pool is all students of any `care_status` whose `enrolled_term_codes` history contains the from-term — restricted to the cohort when `cohort_year` is supplied — the denominator is the pool's size, and the numerator counts pool members whose history also contains the to-term."
    PRD §3.9: "the rate is the numerator divided by the denominator, rendered to four decimal places with round-half-up; when the denominator is 0, the rate and numerator are both reported as 0."

    Design: Difficulty/dual_variant_calc/retention_cohort_vs_term_variant
    """
    setup_retention_cohort_2025()
    res = api.get_retention_report(
        director_headers,
        params={
            "variant": "TERM_OVER_TERM",
            "from_term_code": "FA25",
            "to_term_code": "SP26",
            "cohort_year": 2025,
        },
    )
    report = validate_success(res, 200)
    assert report["denominator"] == 3, "r1, r2, r3 hold FA25; r4 entered in SP26"
    assert report["numerator"] == 1, "only r1 also holds SP26"
    assert float(report["rate"]) == pytest.approx(0.3333, abs=1e-9), (
        "1/3 round-half-up to four decimal places"
    )


# ─── Corner: calculations / retention_rate_zero_denominator ───────────────────

def test_retention_rate_zero_denominator(api, director_headers):
    """PRD §3.9: "the rate is the numerator divided by the denominator, rendered to four decimal places with round-half-up; when the denominator is 0, the rate and numerator are both reported as 0."

    Design: Corner/calculations/retention_rate_zero_denominator
    """
    create_student(full_name="QC6", email="qc6@x.edu", current_term_code="FA26")
    res = api.get_retention_report(
        director_headers,
        params={
            "variant": "TERM_OVER_TERM",
            "from_term_code": "ZZ99",
            "to_term_code": "ZZ98",
        },
    )
    report = validate_success(res, 200)
    assert report["denominator"] == 0, "no student holds the from-term ZZ99"
    assert report["numerator"] == 0
    assert float(report["rate"]) == pytest.approx(0.0, abs=1e-9)


# ─── Corner: state_machines / daily_close_marks_no_show_and_cascades_risk ─────

def test_daily_close_marks_no_show_and_cascades_risk(api, director_headers):
    """PRD §3.9: "Every appointment still `SCHEDULED` whose start lies more than ten minutes in the past is marked `NO_SHOW`, firing the full no-show cascade of §3.4 — the incremented `no_show_count`, the risk recomputation, the possible `HIGH`-tier flag and clearance changes, and the advisor load refreshes."
    PRD §3.2: "No-show points add 10 per recorded no-show, counting no more than three no-shows."

    Design: Corner/state_machines/daily_close_marks_no_show_and_cascades_risk
    """
    student = create_student(full_name="S4", email="s4c@x.edu", gpa=1.9)
    advisor = create_advisor(full_name="Advisor SM4", email="sm4@x.edu")
    appt = book_appointment(
        student["id"], advisor["id"],
        "2026-08-01T10:00:00Z", "2026-08-01T10:30:00Z",
    )
    set_logical_clock("2026-08-01T10:11:00Z")  # 11 minutes past the 10:00 start
    report = mark_no_show_via_sweep()
    assert report["no_show_marked"] == 1

    appt_after = validate_success(api.get_appointment(appt["id"], director_headers), 200)
    assert appt_after["status"] == "NO_SHOW"
    student_after = get_student(student["id"])
    assert student_after["no_show_count"] == 1
    assert student_after["at_risk_score"] == 50, "40 base (gpa 1.9) + 10 no-show"
    assert student_after["risk_tier"] == "MEDIUM"
