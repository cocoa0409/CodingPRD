"""Standards gradebook, section grades, GPA, and the report-card lifecycle.

Covers difficulty instances under dual_variant_calc (grade divergence),
non_linear_state_machine (report-card cycle), boundary_precision_check
(empty score set), plus corner instances under calculations/validations/state_machines.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    find_line_item,
    fixtures as fx,
)

REG = TEST_USERS["registrar_headers"]
TEACH = TEST_USERS["teacher_headers"]
ADMIN = TEST_USERS["administrator_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / report_card_standards_vs_traditional_letter_diverge
# ---------------------------------------------------------------------------
def _two_section_standards_traditional(api):
    """One enrolled student in a STANDARDS section (mastery 3) and a TRADITIONAL
    section (pct 88). Returns (report_card, sec_s_id, sec_t_id)."""
    school = fx.create_school()
    student = fx.create_student(school["id"], grade_level="9")
    enr = fx.create_enrollment(student["id"])
    crs_s = fx.create_course(school["id"], grading_mode="STANDARDS", credit_value=1.0)
    crs_t = fx.create_course(school["id"], grading_mode="TRADITIONAL", credit_value=1.0)
    sec_s = fx.create_section(crs_s["id"], period=1)
    sec_t = fx.create_section(crs_t["id"], period=2)
    sa_s = fx.seat(enr["id"], sec_s["id"])
    sa_t = fx.seat(enr["id"], sec_t["id"])
    fx.post_standard_score(sa_s["id"], "ENG.9.RL.1", mastery_level=3, weight=1.0)
    fx.post_standard_score(sa_t["id"], "HIS.9.1", mastery_level=3, weight=1.0, percentage_points=88)
    rc = fx.open_report_card(enr["id"])
    return rc, sec_s["id"], sec_t["id"]


def test_report_card_standards_and_traditional_line_items_diverge(api):
    """PRD §3.8: "The letter and 4.0-scale grade points follow from that weighted
    mastery: a weighted mastery of at least 3.5 is an A worth 4.0; at least 3.0 but
    below 3.5 is a B worth 3.0; at least 2.5 but below 3.0 is a C worth 2.0; at least
    2.0 but below 2.5 is a D worth 1.0; anything below 2.0 is an F worth 0.0."
    PRD §3.8: "For a TRADITIONAL section, the weighted percentage is the sum over the
    scores of weight times percentage_points, divided by the sum of the weights, and
    the bands are: at least 90 is an A (4.0), at least 80 a B (3.0), at least 70 a C
    (2.0), at least 60 a D (1.0), and below 60 an F (0.0), with the section passed
    when the weighted percentage is at least 60."
    PRD §3.8: "The mastery_or_percent recorded on the line item is the weighted
    mastery for a standards section or the weighted percentage for a traditional one,
    rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/report_card_standards_vs_traditional_letter_diverge
    """
    rc, sec_s, sec_t = _two_section_standards_traditional(api)
    final = validate_success(
        api.finalize_report_card(rc["id"], {"expected_report_card_version": rc["version"]}, TEACH))
    assert final["status"] == "FINALIZED"
    li_s = find_line_item(final, sec_s)
    li_t = find_line_item(final, sec_t)
    assert li_s["grade_points"] == 3.0 and li_s["mastery_or_percent"] == 3.0, \
        f"STANDARDS line item: {li_s}"
    assert li_t["grade_points"] == 3.0 and li_t["mastery_or_percent"] == 88.0, \
        f"TRADITIONAL line item: {li_t}"


def test_report_card_two_b_sections_yield_gpa_3(api):
    """PRD §3.8: "The report card's overall_gpa is a single credit-weighted figure
    across all graded sections: the sum, over every graded section, of the section's
    credit_value times its grade points, divided by the sum of those credit_value
    weights, with the divide performed exactly once at the end over the accumulated
    totals — never as an average of per-section GPAs — and the final quotient rounded
    half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/report_card_standards_vs_traditional_letter_diverge
    """
    rc, _sec_s, _sec_t = _two_section_standards_traditional(api)
    final = validate_success(
        api.finalize_report_card(rc["id"], {"expected_report_card_version": rc["version"]}, TEACH))
    # (3.0*1.0 + 3.0*1.0) / (1.0 + 1.0) = 3.0
    assert final["overall_gpa"] == pytest.approx(3.0, abs=1e-9), \
        f"overall_gpa expected 3.0, got {final['overall_gpa']}"


# ---------------------------------------------------------------------------
# non_linear_state_machine / report_card_cycle_draft_finalize_reopen_finalize
# ---------------------------------------------------------------------------
def _setup_cycle(api):
    """Enrolled student, one STANDARDS section graded mastery 4, report card finalized
    then reopened, grade lowered to mastery 2. Returns (report_card_id, section_id)."""
    school = fx.create_school()
    student = fx.create_student(school["id"], grade_level="10")
    enr = fx.create_enrollment(student["id"])
    course = fx.create_course(school["id"], grading_mode="STANDARDS", credit_value=1.0)
    section = fx.create_section(course["id"], period=1)
    sa = fx.seat(enr["id"], section["id"])
    fx.post_standard_score(sa["id"], "BIO.1", mastery_level=4, weight=1.0)
    rc = fx.open_report_card(enr["id"])
    validate_success(
        api.finalize_report_card(rc["id"], {"expected_report_card_version": rc["version"]}, TEACH))
    validate_success(api.reopen_report_card(rc["id"], ADMIN))
    fx.post_standard_score(sa["id"], "BIO.1", mastery_level=2, weight=1.0)
    refreshed = validate_success(api.get_report_card(rc["id"], TEACH))
    return rc["id"], section["id"], refreshed["version"]


def test_report_card_cycle_second_finalize_recomputes(api):
    """PRD §3.8: "An administrator may later reopen a finalized card — rejected with
    ERR_REPORT_CARD_NOT_FINALIZED if it is not currently FINALIZED — which moves it
    FINALIZED → REOPENED, clears line_items, and resets overall_gpa to null and
    credits_earned to 0, permitting a recompute on the next finalize."

    Design: Difficulty/non_linear_state_machine/report_card_cycle_draft_finalize_reopen_finalize
    """
    rc_id, _sec, v2 = _setup_cycle(api)
    final = validate_success(
        api.finalize_report_card(rc_id, {"expected_report_card_version": v2}, TEACH))
    assert final["status"] == "FINALIZED"
    # mastery 2 -> D (1.0)
    assert final["overall_gpa"] == pytest.approx(1.0, abs=1e-9), \
        f"second finalize gpa expected 1.0, got {final['overall_gpa']}"


def test_report_card_cycle_line_item_reflects_lowered_grade(api):
    """PRD §3.8: "anything below 2.0 is an F worth 0.0. The section is passed when
    the weighted mastery is at least 2.0."
    PRD §3.8: "The mastery_or_percent recorded on the line item is the weighted
    mastery for a standards section or the weighted percentage for a traditional one,
    rounded half-up to two decimal places."

    Design: Difficulty/non_linear_state_machine/report_card_cycle_draft_finalize_reopen_finalize
    """
    rc_id, sec, v2 = _setup_cycle(api)
    final = validate_success(
        api.finalize_report_card(rc_id, {"expected_report_card_version": v2}, TEACH))
    li = find_line_item(final, sec)
    assert li["mastery_or_percent"] == 2.0, f"line item mastery_or_percent expected 2.0, got {li}"


# ---------------------------------------------------------------------------
# boundary_precision_check / finalize_empty_standard_score_set_boundary
# ---------------------------------------------------------------------------
def test_finalize_with_ungraded_section_rejected(api):
    """PRD §3.8: "Every ENROLLED schedule assignment of the enrollment must have at
    least one StandardScore, or the finalize is rejected with ERR_INCOMPLETE_GRADES."

    Design: Difficulty/boundary_precision_check/finalize_empty_standard_score_set_boundary
    """
    school = fx.create_school()
    student = fx.create_student(school["id"], grade_level="9")
    enr = fx.create_enrollment(student["id"])
    course = fx.create_course(school["id"], grading_mode="STANDARDS")
    sec_graded = fx.create_section(course["id"], period=1)
    sec_ungraded = fx.create_section(course["id"], period=2)
    sa_g = fx.seat(enr["id"], sec_graded["id"])
    fx.seat(enr["id"], sec_ungraded["id"])
    fx.post_standard_score(sa_g["id"], "ALG.1", mastery_level=3, weight=1.0)
    rc = fx.open_report_card(enr["id"])
    resp = api.finalize_report_card(rc["id"], {"expected_report_card_version": rc["version"]}, TEACH)
    validate_error(resp, ApiErrorId.ERR_INCOMPLETE_GRADES.value, expected_status=409)
    refreshed = validate_success(api.get_report_card(rc["id"], TEACH))
    assert refreshed["status"] == "DRAFT", "report card stays DRAFT after rejected finalize"


def test_finalize_succeeds_when_all_sections_graded(api):
    """PRD §3.8: "When those hold, the card moves DRAFT → FINALIZED (or REOPENED →
    FINALIZED), and line_items, overall_gpa, and credits_earned are computed and
    frozen."

    Design: Difficulty/boundary_precision_check/finalize_empty_standard_score_set_boundary
    """
    ctx = fx.setup_report_card_ready_single_section(grading_mode="STANDARDS", mastery_level=3)
    rc = ctx["report_card"]
    final = validate_success(
        api.finalize_report_card(rc["id"], {"expected_report_card_version": rc["version"]}, TEACH))
    assert final["status"] == "FINALIZED"


# ---------------------------------------------------------------------------
# corner: standards_weighted_mastery_band_boundary
# ---------------------------------------------------------------------------
def test_standards_weighted_mastery_band_boundary(api):
    """PRD §3.8: "For a STANDARDS section, the weighted mastery is the sum over the
    section's scores of weight times mastery_level, divided by the sum of the weights.
    The letter and 4.0-scale grade points follow from that weighted mastery: a
    weighted mastery of at least 3.5 is an A worth 4.0".

    Design: Corner/calculations/standards_weighted_mastery_band_boundary
    """
    school = fx.create_school()
    student = fx.create_student(school["id"], grade_level="9")
    enr = fx.create_enrollment(student["id"])
    course = fx.create_course(school["id"], grading_mode="STANDARDS", credit_value=1.0)
    section = fx.create_section(course["id"], period=1)
    sa = fx.seat(enr["id"], section["id"])
    fx.post_standard_score(sa["id"], "S.A", mastery_level=4, weight=2.0)
    fx.post_standard_score(sa["id"], "S.B", mastery_level=3, weight=1.0)
    rc = fx.open_report_card(enr["id"])
    final = validate_success(
        api.finalize_report_card(rc["id"], {"expected_report_card_version": rc["version"]}, TEACH))
    li = find_line_item(final, section["id"])
    # (4*2 + 3*1)/3 = 3.6667 -> 3.67 -> A (>= 3.5)
    assert li["mastery_or_percent"] == 3.67, f"mastery_or_percent expected 3.67, got {li}"
    assert li["grade_points"] == 4.0, f"grade_points expected 4.0, got {li}"
    assert final["overall_gpa"] == pytest.approx(4.0, abs=1e-9)


# ---------------------------------------------------------------------------
# corner: gpa_credit_weighted_divide_last
# ---------------------------------------------------------------------------
def test_gpa_credit_weighted_divide_last(api):
    """PRD §3.8: "The report card's overall_gpa is a single credit-weighted figure
    across all graded sections: the sum, over every graded section, of the section's
    credit_value times its grade points, divided by the sum of those credit_value
    weights, with the divide performed exactly once at the end over the accumulated
    totals — never as an average of per-section GPAs — and the final quotient rounded
    half-up to two decimal places."
    PRD §3.8: "The credits_earned figure is the exact sum of credit_value over only
    the sections whose passed flag is true."

    Design: Corner/calculations/gpa_credit_weighted_divide_last
    """
    school = fx.create_school()
    student = fx.create_student(school["id"], grade_level="9")
    enr = fx.create_enrollment(student["id"])
    crsA = fx.create_course(school["id"], grading_mode="STANDARDS", credit_value=1.0)
    crsB = fx.create_course(school["id"], grading_mode="STANDARDS", credit_value=0.5)
    secA = fx.create_section(crsA["id"], period=1)
    secB = fx.create_section(crsB["id"], period=2)
    saA = fx.seat(enr["id"], secA["id"])
    saB = fx.seat(enr["id"], secB["id"])
    fx.post_standard_score(saA["id"], "A.1", mastery_level=4, weight=1.0)   # A=4.0
    fx.post_standard_score(saB["id"], "B.1", mastery_level=3, weight=1.0)
    fx.post_standard_score(saB["id"], "B.2", mastery_level=2, weight=1.0)   # wm 2.5 -> C=2.0
    rc = fx.open_report_card(enr["id"])
    final = validate_success(
        api.finalize_report_card(rc["id"], {"expected_report_card_version": rc["version"]}, TEACH))
    # (4.0*1.0 + 2.0*0.5) / (1.0 + 0.5) = 5.0/1.5 = 3.3333 -> 3.33
    assert final["overall_gpa"] == pytest.approx(3.33, abs=1e-9), \
        f"overall_gpa expected 3.33, got {final['overall_gpa']}"
    assert final["credits_earned"] == pytest.approx(1.5, abs=1e-9), \
        f"credits_earned expected 1.5, got {final['credits_earned']}"


# ---------------------------------------------------------------------------
# corner: invalid_mastery_level_out_of_range_rejected
# ---------------------------------------------------------------------------
def test_invalid_mastery_level_rejected(api):
    """PRD §3.7: "when the course grades on standards, a mastery_level integer in the
    range 1 through 4 is required (1 is Beginning, 2 Developing, 3 Proficient, 4
    Advanced); when the course grades traditionally, a percentage_points value in the
    range 0 through 100 is required instead."
    PRD §3.7: "A score whose required value is missing or out of range for the
    course's grading mode is rejected with ERR_INVALID_GRADE_INPUT."

    Design: Corner/validations/invalid_mastery_level_out_of_range_rejected
    """
    ctx = fx.setup_seated_student(grading_mode="STANDARDS")
    resp = api.create_standard_score(
        {"schedule_assignment_id": ctx["assignment"]["id"], "standard_code": "X.1",
         "mastery_level": 5, "weight": 1.0}, TEACH)
    validate_error(resp, ApiErrorId.ERR_INVALID_GRADE_INPUT.value, expected_status=422)


# ---------------------------------------------------------------------------
# corner: child_against_withdrawn_enrollment_rejected — SKIPPED (applies_to-scope).
# The corner instance asserts opening a report card against a WITHDRAWN enrollment
# returns ERR_PARENT_NOT_ACTIVE. PRD prose names that parent-active rule only for
# schedule-assignment seating (§3.4), attendance posting (§3.5), and standard scores
# (§3.7). The §3.7 report-card-opening paragraph and §2.12 do not state that opening
# a report card requires an ACTIVE enrollment, so a faithful PRD-only implementer
# could allow it. No verbatim PRD coverage for report cards -> instance skipped.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# corner: reopen_non_finalized_report_card_rejected
# ---------------------------------------------------------------------------
def test_reopen_draft_report_card_rejected(api):
    """PRD §3.8: "An administrator may later reopen a finalized card — rejected with
    ERR_REPORT_CARD_NOT_FINALIZED if it is not currently FINALIZED".

    Design: Corner/state_machines/reopen_non_finalized_report_card_rejected
    """
    school = fx.create_school()
    student = fx.create_student(school["id"], grade_level="9")
    enr = fx.create_enrollment(student["id"])
    rc = fx.open_report_card(enr["id"])
    resp = api.reopen_report_card(rc["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_REPORT_CARD_NOT_FINALIZED.value, expected_status=409)
