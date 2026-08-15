"""Withdrawal, proration variants, and the district funding claim."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_funding_totals_consistent,
    create_district,
    create_student,
    enroll_student,
    list_enrollment_terms,
    record_attendance,
    request_reenrollment,
    set_clock,
    validate_error,
    verify_student,
    withdraw_student,
)

ENROLLMENT = TEST_USERS["enrollment_officer_headers"]


def _enroll_at(district_id, name, clock="2026-08-03T08:00:00Z", **overrides):
    """Create + verify + enroll a student at the given clock position."""
    student = create_student(district_id, legal_name=name, **overrides)
    student = verify_student(student["id"])
    set_clock(clock)
    return enroll_student(student)


def _record_three_days_pap(student_id):
    """PRESENT, ABSENT_UNEXCUSED, PRESENT on 2026-08-03/04/05."""
    record_attendance(student_id, "2026-08-03T00:00:00Z", 300, 3)
    record_attendance(student_id, "2026-08-04T00:00:00Z", 0, 0)
    record_attendance(student_id, "2026-08-05T00:00:00Z", 300, 3)


class TestWithdrawalGates:
    def test_withdraw_from_applied_rejected_invalid_state(self, api):
        """PRD §3.3: "The student must be `ENROLLED` and their current term
        must be `ACTIVE`, or the request fails with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/withdraw_from_applied_rejected_invalid_state
        """
        district = create_district(district_code="D-111", state_code="TX",
                                   funding_rate_cents=400, enrollment_cap=50)
        student = create_student(district["id"], legal_name="Inval",
                                 date_of_birth="2011-04-04T00:00:00Z")
        assert student["enrollment_status"] == "APPLIED"
        resp = api.withdraw_student(student["id"], "DROPOUT", ENROLLMENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTermClosure:
    def test_withdraw_sets_term_end_date_to_day_before(self, api):
        """PRD §3.3: "The term's `term_status` becomes `WITHDRAWN`, and its
        `term_end_date` is set to the day before the withdrawal: the current
        logical-clock date minus one day."
        PRD §3.3: "Under `CALENDAR_ELAPSED`, the term's `claimable_days` is
        the count of calendar days from `term_start_date` through
        `term_end_date` inclusive — never less than zero — regardless of what
        the attendance record shows."

        Design: Corner/endpoints/withdraw_sets_term_end_date_to_day_before
        """
        district = create_district(district_code="D-141", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=50)
        student = _enroll_at(district["id"], "WE")
        set_clock("2026-08-10T08:00:00Z")
        student = withdraw_student(student["id"], "HOMESCHOOL")
        assert student["enrollment_status"] == "WITHDRAWN"

        terms, meta = list_enrollment_terms(student["id"])
        assert meta["total_count"] == 1
        term = terms[0]
        assert term["term_status"] == "WITHDRAWN"
        assert term["term_end_date"].startswith("2026-08-09"), (
            f"term_end_date must be the day before the withdrawal, got "
            f"{term['term_end_date']!r}")
        assert term["proration_mode"] == "CALENDAR_ELAPSED"
        # 2026-08-03 .. 2026-08-09 inclusive = 7 calendar days
        assert term["claimable_days"] == 7


class TestDailyAttendanceProration:
    def _setup_dropout_withdrawal(self):
        """Enrolled 2026-08-03; PRESENT 08-03, ABSENT_UNEXCUSED 08-04,
        PRESENT 08-05; withdrawn 2026-08-06 with DROPOUT (term_end 08-05)."""
        district = create_district(district_code="D-001", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=100)
        student = _enroll_at(district["id"], "Alice",
                             date_of_birth="2012-01-15T00:00:00Z", grade_level=7)
        _record_three_days_pap(student["id"])
        set_clock("2026-08-06T08:00:00Z")
        return withdraw_student(student["id"], "DROPOUT")

    def test_daily_attendance_proration_counts_only_present_days(self, api):
        """PRD §3.3: "Under `DAILY_ATTENDANCE`, `claimable_days` counts only
        those days within that same inclusive span on which the student has an
        attendance record marked `PRESENT` or `PARTIAL`; days marked
        `ABSENT_UNEXCUSED` or `ABSENT_EXCUSED`, and days with no record at
        all, are excluded."
        PRD §3.3: "`funding_days_claimed` becomes the sum of `claimable_days`
        across all of the student's terms, whatever their status.
        `funding_claim_cents` is computed per term first — each term's
        `claimable_days` multiplied by the district's `funding_rate_cents` as
        it stands at computation time — and the per-term amounts are then
        summed into the student's total."

        Design: Difficulty/dual_variant_calc/funding_proration_daily_attendance_vs_calendar_elapsed
        """
        student = self._setup_dropout_withdrawal()
        assert student["funding_days_claimed"] == 2, (
            "only the two PRESENT days count under DAILY_ATTENDANCE")
        assert student["funding_claim_cents"] == 1000, (
            "2 claimable days x 500 cents")

    def test_daily_attendance_proration_term_fields(self, api):
        """PRD §3.3: "The recorded reason then selects the proration variant
        deterministically: `DROPOUT` and `ADMINISTRATIVE` map to
        `DAILY_ATTENDANCE`, while `MOVED_DISTRICT`,
        `RETURN_TO_BRICK_AND_MORTAR`, and `HOMESCHOOL` map to
        `CALENDAR_ELAPSED`, and the chosen variant is stored on the term as
        `proration_mode`."

        Design: Difficulty/dual_variant_calc/funding_proration_daily_attendance_vs_calendar_elapsed
        """
        student = self._setup_dropout_withdrawal()
        terms, meta = list_enrollment_terms(student["id"])
        assert meta["total_count"] == 1
        term = terms[0]
        assert term["proration_mode"] == "DAILY_ATTENDANCE"
        assert term["claimable_days"] == 2


class TestProrationModeBranches:
    def _setup_two_students_identical_attendance(self):
        """S1 and S2 in one district, both enrolled 2026-08-03 with identical
        attendance (PRESENT, ABSENT_UNEXCUSED, PRESENT); clock at 2026-08-06."""
        district = create_district(district_code="D-010", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=100)
        s1 = _enroll_at(district["id"], "Carol",
                        date_of_birth="2012-03-01T00:00:00Z")
        _record_three_days_pap(s1["id"])
        s2 = _enroll_at(district["id"], "Dave",
                        date_of_birth="2012-04-01T00:00:00Z")
        _record_three_days_pap(s2["id"])
        set_clock("2026-08-06T08:00:00Z")
        return s1, s2

    def test_same_attendance_dropout_yields_daily_attendance_days(self, api):
        """PRD §3.3: "Under `DAILY_ATTENDANCE`, `claimable_days` counts only
        those days within that same inclusive span on which the student has an
        attendance record marked `PRESENT` or `PARTIAL`; days marked
        `ABSENT_UNEXCUSED` or `ABSENT_EXCUSED`, and days with no record at
        all, are excluded."
        PRD §3.3: "The recorded reason then selects the proration variant
        deterministically: `DROPOUT` and `ADMINISTRATIVE` map to
        `DAILY_ATTENDANCE`, while `MOVED_DISTRICT`,
        `RETURN_TO_BRICK_AND_MORTAR`, and `HOMESCHOOL` map to
        `CALENDAR_ELAPSED`, and the chosen variant is stored on the term as
        `proration_mode`."

        Design: Difficulty/combinatorial_formula/funding_proration_conditional_branch_on_attendance_and_mode
        """
        s1, s2 = self._setup_two_students_identical_attendance()
        s1 = withdraw_student(s1["id"], "DROPOUT")
        s2 = withdraw_student(s2["id"], "MOVED_DISTRICT")
        assert s1["funding_days_claimed"] == 2
        assert s1["funding_claim_cents"] == 1000

    def test_same_attendance_moved_district_yields_calendar_elapsed_days(self, api):
        """PRD §3.3: "Under `CALENDAR_ELAPSED`, the term's `claimable_days` is
        the count of calendar days from `term_start_date` through
        `term_end_date` inclusive — never less than zero — regardless of what
        the attendance record shows."
        PRD §3.3: "The recorded reason then selects the proration variant
        deterministically: `DROPOUT` and `ADMINISTRATIVE` map to
        `DAILY_ATTENDANCE`, while `MOVED_DISTRICT`,
        `RETURN_TO_BRICK_AND_MORTAR`, and `HOMESCHOOL` map to
        `CALENDAR_ELAPSED`, and the chosen variant is stored on the term as
        `proration_mode`."

        Design: Difficulty/combinatorial_formula/funding_proration_conditional_branch_on_attendance_and_mode
        """
        s1, s2 = self._setup_two_students_identical_attendance()
        s1 = withdraw_student(s1["id"], "DROPOUT")
        s2 = withdraw_student(s2["id"], "MOVED_DISTRICT")
        # Same attendance data, CALENDAR_ELAPSED branch: all 3 days count.
        assert s2["funding_days_claimed"] == 3
        assert s2["funding_claim_cents"] == 1500


class TestFundingClaimAggregation:
    def _setup_two_term_student(self, district_code, funding_rate_cents):
        """Term 1: 2026-08-03..2026-08-05 (3 calendar days, MOVED_DISTRICT);
        term 2: 2026-08-10..2026-08-11 (2 calendar days, HOMESCHOOL)."""
        district = create_district(district_code=district_code, state_code="WA",
                                   funding_rate_cents=funding_rate_cents,
                                   enrollment_cap=100)
        student = _enroll_at(district["id"], "Eve",
                             date_of_birth="2010-09-01T00:00:00Z", grade_level=9)
        set_clock("2026-08-06T08:00:00Z")
        student = withdraw_student(student["id"], "MOVED_DISTRICT")
        student = request_reenrollment(student["id"])
        set_clock("2026-08-10T08:00:00Z")
        student = enroll_student(student)
        set_clock("2026-08-12T08:00:00Z")
        return withdraw_student(student["id"], "HOMESCHOOL")

    def test_two_terms_funding_days_sum_across_terms(self, api):
        """PRD §3.3: "`funding_days_claimed` becomes the sum of
        `claimable_days` across all of the student's terms, whatever their
        status."

        Design: Difficulty/combinatorial_formula/funding_claim_amount_per_term_then_sum_order
        """
        student = self._setup_two_term_student("D-011", 333)
        assert student["funding_days_claimed"] == 5, (
            "3 days from term 1 plus 2 days from term 2")

    def test_two_terms_claim_computed_per_term_then_summed(self, api):
        """PRD §3.3: "`funding_claim_cents` is computed per term first — each
        term's `claimable_days` multiplied by the district's
        `funding_rate_cents` as it stands at computation time — and the
        per-term amounts are then summed into the student's total. The
        alternative order, summing days across terms and multiplying once, is
        expressly forbidden, and all arithmetic remains in integer cents."

        Design: Difficulty/combinatorial_formula/funding_claim_amount_per_term_then_sum_order
        """
        student = self._setup_two_term_student("D-011", 333)
        terms, _ = list_enrollment_terms(student["id"])
        assert [t["claimable_days"] for t in terms] == [3, 2]
        assert student["funding_claim_cents"] == 1665, (
            "3*333 + 2*333 = 999 + 666 = 1665")
        assert_funding_totals_consistent(student, terms, 333)

    def test_funding_totals_reconcile_after_second_term(self, api):
        """PRD §3.3: "`funding_days_claimed` becomes the sum of
        `claimable_days` across all of the student's terms, whatever their
        status. `funding_claim_cents` is computed per term first — each term's
        `claimable_days` multiplied by the district's `funding_rate_cents` as
        it stands at computation time — and the per-term amounts are then
        summed into the student's total."
        PRD §3.3: "The same recomputation runs whenever any term's
        `claimable_days` changes or a new term is created, and when a
        district's rate has changed the claim is re-derived on read at the
        current rate."

        Design: Corner/cross_cutting_layers/derived_field_student_funding_claim_reconciles_after_second_term
        """
        student = self._setup_two_term_student("D-170", 500)
        terms, meta = list_enrollment_terms(student["id"])
        assert meta["total_count"] == 2
        assert student["funding_days_claimed"] == 5
        assert student["funding_claim_cents"] == 2500, (
            "3*500 + 2*500 = 1500 + 1000 = 2500")
        assert_funding_totals_consistent(student, terms, 500)
