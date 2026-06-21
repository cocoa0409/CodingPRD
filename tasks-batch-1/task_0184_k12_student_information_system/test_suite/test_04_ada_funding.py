"""ADA funding reports: the two funding flavors, round-then-sum precision,
recompute, certification guards, and terminal-state lockdown.

Covers difficulty instances under dual_variant_calc, combinatorial_formula
(ADA rounding), cross_entity_state_dependency (certify guard), plus corner
instances under state_machines/endpoints.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_registrar_headers, make_state_reporting_officer_headers,
    fixtures as fx,
)

REG = TEST_USERS["registrar_headers"]
OFFICER = TEST_USERS["state_reporting_officer_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / ada_aggregate_membership_vs_days_present_diverge
# ---------------------------------------------------------------------------
def _present_two_absent_one(ada_method):
    """School (ada_method) clock day 3, one fte=1.0 enrollment in a 240-min section,
    PRESENT days 1-2, ABSENT day 3. Returns the school id."""
    ctx = fx.setup_school_single_present_enrollment(
        ada_method=ada_method, clock_days=3, present_days=[1, 2], absent_days=[3],
        meeting_minutes=240, session_total_days=180, minimum_daily_minutes=240,
        entry_day_index=1, fte=1.0)
    return ctx["school"]["id"]


def test_ada_aggregate_membership_counts_full_span(api):
    """PRD §3.11: "Under AGGREGATE_MEMBERSHIP, an enrollment's ADA is its membership
    span divided by session_total_days, multiplied by its fte, rounded half-up to
    four decimals — the numerator is enrolled days regardless of attendance, so a
    fully absent but enrolled student still earns ADA."

    Design: Difficulty/dual_variant_calc/ada_aggregate_membership_vs_days_present_diverge
    """
    school_id = _present_two_absent_one("AGGREGATE_MEMBERSHIP")
    rep = validate_success(
        api.create_ada_report({"school_id": school_id, "as_of_day_index": 3},
                              make_state_reporting_officer_headers("officer-1")),
        expected_status=201)
    assert rep["method_used"] == "AGGREGATE_MEMBERSHIP"
    # span 3 / 180 = 0.016666... -> 0.0167
    assert rep["total_ada"] == pytest.approx(0.0167, abs=1e-9), \
        f"AGG total_ada expected 0.0167, got {rep['total_ada']}"


def test_ada_days_present_counts_only_present_days(api):
    """PRD §3.11: "Under DAYS_PRESENT, an enrollment's ADA is its eligible present
    count divided by session_total_days, multiplied by its fte, rounded half-up to
    four decimals — the numerator is ADA-eligible present days, so for an identical
    roster and identical span the total is strictly lower whenever any eligible day
    is missed."

    Design: Difficulty/dual_variant_calc/ada_aggregate_membership_vs_days_present_diverge
    """
    school_id = _present_two_absent_one("DAYS_PRESENT")
    rep = validate_success(
        api.create_ada_report({"school_id": school_id, "as_of_day_index": 3},
                              make_state_reporting_officer_headers("officer-1")),
        expected_status=201)
    assert rep["method_used"] == "DAYS_PRESENT"
    # present 2 / 180 = 0.011111... -> 0.0111, strictly lower than the AGG 0.0167
    assert rep["total_ada"] == pytest.approx(0.0111, abs=1e-9), \
        f"DAYS_PRESENT total_ada expected 0.0111, got {rep['total_ada']}"


# ---------------------------------------------------------------------------
# combinatorial_formula / ada_round_then_sum_order_pinned
# ---------------------------------------------------------------------------
def test_ada_round_then_sum_two_half_fte_enrollments(api):
    """PRD §2.8: "Each per-enrollment ADA contribution is rounded half-up to four
    decimal places, and the report's total_ada is the sum of those already-rounded
    per-enrollment values, itself rounded half-up to four decimal places — the
    round-then-sum order is fixed and must not be reordered into a sum-then-round."

    Design: Difficulty/combinatorial_formula/ada_round_then_sum_order_pinned
    """
    school = fx.create_school(ada_method="AGGREGATE_MEMBERSHIP", session_total_days=180)
    fx.advance_clock(school["id"], 3)
    course = fx.create_course(school["id"])
    section = fx.create_section(course["id"], period=1, meeting_minutes=240)
    for grade in ("K", "K"):
        student = fx.create_student(school["id"], grade_level=grade)
        enr = fx.create_enrollment(student["id"], entry_day_index=1, fte=0.5)
        sa = fx.seat(enr["id"], section["id"])
        for d in (1, 2, 3):
            fx.post_attendance(sa["id"], d, "PRESENT")
    rep = validate_success(
        api.create_ada_report({"school_id": school["id"], "as_of_day_index": 3}, REG),
        expected_status=201)
    # per-enrollment 3/180*0.5 = 0.008333 -> 0.0083; sum 0.0166 (NOT 0.0167)
    assert rep["total_ada"] == pytest.approx(0.0166, abs=1e-9), \
        f"round-then-sum total_ada expected 0.0166, got {rep['total_ada']}"
    assert rep["funded_enrollment_count"] == 2, \
        f"funded_enrollment_count expected 2, got {rep['funded_enrollment_count']}"


def test_ada_funded_enrollment_count_excludes_zero_ada(api):
    """PRD §3.11: "funded_enrollment_count is the number of in-scope enrollments
    whose ADA contribution is greater than 0."

    Design: Difficulty/combinatorial_formula/ada_round_then_sum_order_pinned
    """
    school = fx.create_school(ada_method="AGGREGATE_MEMBERSHIP", session_total_days=180)
    fx.advance_clock(school["id"], 3)
    course = fx.create_course(school["id"])
    section = fx.create_section(course["id"], period=1, meeting_minutes=240)
    student = fx.create_student(school["id"], grade_level="K")
    enr = fx.create_enrollment(student["id"], entry_day_index=1, fte=0.5)
    sa = fx.seat(enr["id"], section["id"])
    for d in (1, 2, 3):
        fx.post_attendance(sa["id"], d, "PRESENT")
    rep = validate_success(
        api.create_ada_report({"school_id": school["id"], "as_of_day_index": 3}, REG),
        expected_status=201)
    assert rep["funded_enrollment_count"] == 1, \
        f"single positive-ADA enrollment funded, got {rep['funded_enrollment_count']}"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / ada_certify_requires_no_active_enrollment_missing_attendance
# ---------------------------------------------------------------------------
def test_certify_rejected_when_active_enrollment_has_no_attendance(api):
    """PRD §3.11: "no in-scope enrollment is still ACTIVE with an entry_day_index at
    or before the as_of_day_index yet has zero DailyAttendance rows through the
    as_of_day_index (otherwise ERR_ATTENDANCE_NOT_POSTED, which guards against
    certifying before attendance has been entered)."

    Design: Difficulty/cross_entity_state_dependency/ada_certify_requires_no_active_enrollment_missing_attendance
    """
    school = fx.create_school(ada_method="DAYS_PRESENT", minimum_daily_minutes=240)
    fx.advance_clock(school["id"], 2)
    student = fx.create_student(school["id"])
    fx.create_enrollment(student["id"], entry_day_index=1)  # ACTIVE, no attendance
    rep = fx.draft_ada_report(school["id"], as_of_day_index=2, drafter_user_id="registrar-drafter")
    resp = api.certify_ada_report(
        rep["id"], {"expected_report_version": rep["version"]},
        make_state_reporting_officer_headers("officer-1"))
    validate_error(resp, ApiErrorId.ERR_ATTENDANCE_NOT_POSTED.value, expected_status=409)
    refreshed = validate_success(api.get_ada_report(rep["id"], REG))
    assert refreshed["status"] == "DRAFT", "report stays DRAFT after rejected certify"


def test_certify_passes_segregation_but_blocks_on_missing_attendance(api):
    """PRD §3.11: "no in-scope enrollment is still ACTIVE with an entry_day_index at
    or before the as_of_day_index yet has zero DailyAttendance rows through the
    as_of_day_index (otherwise ERR_ATTENDANCE_NOT_POSTED, which guards against
    certifying before attendance has been entered)."

    Design: Difficulty/cross_entity_state_dependency/ada_certify_requires_no_active_enrollment_missing_attendance
    """
    school = fx.create_school(ada_method="DAYS_PRESENT", minimum_daily_minutes=240)
    fx.advance_clock(school["id"], 2)
    student = fx.create_student(school["id"])
    fx.create_enrollment(student["id"], entry_day_index=1)
    rep = fx.draft_ada_report(school["id"], as_of_day_index=2, drafter_user_id="registrar-drafter")
    # certifier (officer-1) differs from drafter (registrar-drafter): SoD passes,
    # but ATTENDANCE_NOT_POSTED still fires.
    resp = api.certify_ada_report(
        rep["id"], {"expected_report_version": rep["version"]},
        make_state_reporting_officer_headers("officer-1"))
    validate_error(resp, ApiErrorId.ERR_ATTENDANCE_NOT_POSTED.value, expected_status=409)


# ---------------------------------------------------------------------------
# corner: ada_report_recompute_after_attendance_change
# ---------------------------------------------------------------------------
def test_recompute_raises_total_ada_after_attendance_posted(api):
    """PRD §3.11: "While the report is still DRAFT, a registrar or officer may
    recompute it against current data — rejected with ERR_REPORT_NOT_DRAFT if it is
    no longer DRAFT — which refreshes total_ada and funded_enrollment_count and
    increments the report's version, the bump the certify OCC check in §2.9 relies
    upon."

    Design: Corner/endpoints/ada_report_recompute_after_attendance_change
    """
    school = fx.create_school(ada_method="DAYS_PRESENT", minimum_daily_minutes=240,
                              session_total_days=180)
    fx.advance_clock(school["id"], 1)
    student = fx.create_student(school["id"])
    enr = fx.create_enrollment(student["id"], entry_day_index=1)
    course = fx.create_course(school["id"])
    section = fx.create_section(course["id"], period=1, meeting_minutes=240)
    sa = fx.seat(enr["id"], section["id"])
    rep = fx.draft_ada_report(school["id"], as_of_day_index=1, drafter_user_id="registrar-d")
    fx.post_attendance(sa["id"], 1, "PRESENT")
    recomputed = validate_success(api.recompute_ada_report(rep["id"], REG))
    # 1 present / 180 = 0.005555... -> 0.0056
    assert recomputed["total_ada"] == pytest.approx(0.0056, abs=1e-9), \
        f"recomputed total_ada expected 0.0056, got {recomputed['total_ada']}"
    assert recomputed["funded_enrollment_count"] == 1


# ---------------------------------------------------------------------------
# corner: certify_terminal_rejected_report_locked
# ---------------------------------------------------------------------------
def test_certify_rejected_terminal_report_locked(api):
    """PRD §3.11: "A state reporting officer certifies a draft, which requires (after
    the OCC version match) that the report be DRAFT (otherwise ERR_REPORT_NOT_DRAFT)".

    Design: Corner/state_machines/certify_terminal_rejected_report_locked
    """
    school = fx.create_school(ada_method="AGGREGATE_MEMBERSHIP")
    rep = fx.draft_ada_report(school["id"], as_of_day_index=0, drafter_user_id="registrar-d")
    # Rejecting is a mutation (§2.6) that bumps the report's version. Carry the
    # report's *current* version into certify so the OCC match (§2.9, which runs
    # before the state precondition) passes and the terminal-state lock
    # (ERR_REPORT_NOT_DRAFT, §3.11) is the check that genuinely trips.
    rejected = validate_success(
        api.reject_ada_report(rep["id"], make_state_reporting_officer_headers("officer-1")))
    resp = api.certify_ada_report(
        rep["id"], {"expected_report_version": rejected["version"]},
        make_state_reporting_officer_headers("officer-2"))
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_DRAFT.value, expected_status=409)
    refreshed = validate_success(api.get_ada_report(rep["id"], REG))
    assert refreshed["status"] == "REJECTED", "terminal report stays REJECTED"
