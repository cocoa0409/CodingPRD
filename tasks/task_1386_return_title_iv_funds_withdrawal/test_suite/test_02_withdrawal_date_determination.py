"""Withdrawal date determination variants and the 60% earned-cap boundary."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_withdrawal_case,
    create_and_fund_award,
    create_enrollment,
    create_student,
    create_term,
    create_term_t1,
    get_enrollment,
    set_clock,
    setup_full_aid_case,
    setup_term_student_enrollment,
    validate_error,
    validate_success,
    withdraw_official,
    withdraw_unofficial,
)
from test_helpers.test_users import make_student_headers

REGISTRAR = TEST_USERS["registrar_clerk_headers"]
OFFICER = TEST_USERS["financial_aid_officer_headers"]


class TestOfficialVsUnofficialMidpointBasis:
    """Identical aid packages, two different withdrawal-date bases."""

    def _setup_pair(self):
        """T1 (105 days). E1 withdrawn OFFICIAL 2026-10-25 (day 63 ->
        0.600); E2 withdrawn UNOFFICIAL with the clock at 2026-12-01
        (midpoint day 53 = 2026-10-15 -> 0.505). Identical aid:
        PELL 200000 + SUBSIDIZED_LOAN 300000, all disbursed."""
        term = create_term_t1()
        cases = {}
        for key in ("e1", "e2"):
            student = create_student()
            enrollment = create_enrollment(student["id"], term["id"],
                                           institutional_charges_cents=600_000)
            create_and_fund_award(enrollment["id"], student["id"],
                                  "PELL_GRANT", 200_000, 200_000)
            create_and_fund_award(enrollment["id"], student["id"],
                                  "SUBSIDIZED_LOAN", 300_000, 300_000)
            cases[key] = (student, enrollment)
        set_clock("2026-12-01T00:00:00Z")
        c1 = withdraw_official(cases["e1"][1]["id"], "2026-10-25")
        c2 = withdraw_unofficial(cases["e2"][1]["id"])
        return term, cases, c1, c2

    def test_basis_drives_withdrawal_date_percentage_and_earned_aid(self):
        """PRD section 3.4: "For an official withdrawal, the
        `withdrawal_date` is the supplied `notification_date`, and the
        `determination_date` equals it."
        PRD section 3.4: "the midpoint day is computed by adding one to the
        term's `total_days`, halving the result, and rounding down to a whole
        number, and the `withdrawal_date` is the calendar date of that day of
        the period, counting the term's start date as day one — so a 105-day
        period yields day 53 and a 100-day period yields day 50"
        PRD section 3.5: "Each award's earned amount is then the award's
        disbursable amount multiplied by the case's `earned_pct`, rounded
        half-up to whole cents — and this rounding happens per award, before
        any summation."

        Design: Difficulty/dual_variant_calc/official_vs_unofficial_midpoint_withdrawal_basis
        """
        _, _, c1, c2 = self._setup_pair()
        calc1 = validate_success(api_client.calculate_case(
            c1["id"], TEST_USERS["financial_aid_officer_headers"]), 200)
        calc2 = validate_success(api_client.calculate_case(
            c2["id"], TEST_USERS["financial_aid_officer_headers"]), 200)
        assert_withdrawal_case(calc1)
        assert_withdrawal_case(calc2)

        # OFFICIAL: notification date 2026-10-25 is day 63 of 105 -> 0.600.
        assert calc1["withdrawal_date"] == "2026-10-25"
        assert calc1["percentage_completed"] == pytest_approx(0.600)
        assert calc1["earned_pct"] == pytest_approx(0.600)
        assert calc1["aid_earned_cents"] == 300_000

        # UNOFFICIAL (no attendance taking): midpoint day 53 = 2026-10-15.
        assert calc2["withdrawal_date"] == "2026-10-15"
        assert calc2["percentage_completed"] == pytest_approx(0.505)
        assert calc2["earned_pct"] == pytest_approx(0.505)
        assert calc2["aid_earned_cents"] == 252_500

        # The variant, not the money, drives the delta.
        assert calc1["aid_disbursable_cents"] == calc2["aid_disbursable_cents"]
        assert calc1["aid_earned_cents"] != calc2["aid_earned_cents"]

    def test_determination_date_differs_by_basis(self):
        """PRD section 3.4: "For an official withdrawal, the
        `withdrawal_date` is the supplied `notification_date`, and the
        `determination_date` equals it."
        PRD section 3.4: "For an unofficial withdrawal on a term that does
        not take attendance, the statute's midpoint rule applies: the
        midpoint day is computed by adding one to the term's `total_days`,
        halving the result, and rounding down to a whole number, and the
        `withdrawal_date` is the calendar date of that day of the period,
        counting the term's start date as day one — so a 105-day period
        yields day 53 and a 100-day period yields day 50; the
        `determination_date` is again the logical processing date."

        Design: Difficulty/dual_variant_calc/official_vs_unofficial_midpoint_withdrawal_basis
        """
        _, _, c1, c2 = self._setup_pair()
        # OFFICIAL: determination travels with the notification date.
        assert c1["determination_date"] == "2026-10-25"
        # UNOFFICIAL: determination is the logical clock date (2026-12-01).
        assert c2["determination_date"] == "2026-12-01"
        assert c1["withdrawal_date"] == "2026-10-25"
        assert c2["withdrawal_date"] == "2026-10-15"
        # Obligation deadlines hang off determination_date: official case due
        # 2026-10-25 + 45d = 2026-12-09; unofficial case due 2026-12-01 + 45d
        # = 2027-01-15. Verify via calculate + obligations.
        calc1 = validate_success(api_client.calculate_case(
            c1["id"], OFFICER), 200)
        calc2 = validate_success(api_client.calculate_case(
            c2["id"], OFFICER), 200)
        ob1 = validate_success(api_client.list_case_obligations(
            c1["id"], OFFICER), 200)
        ob2 = validate_success(api_client.list_case_obligations(
            c2["id"], OFFICER), 200)
        # 0.600 -> return path with school obligation due 2026-12-09.
        assert calc1["return_amount_cents"] == 200_000
        assert ob1[0]["due_date"] == "2026-12-09"
        # 0.505 -> earned 252500, return 247500, school share
        # min(600000*0.495=297000, 247500) = 247500; due 2027-01-15.
        assert calc2["return_amount_cents"] == 247_500
        assert ob2[0]["due_date"] == "2027-01-15"


def pytest_approx(value):
    return pytest.approx(value, abs=1e-9)


class TestWithdrawalSnapshotAtCreation:

    def test_withdraw_creates_open_case_with_snapshot(self):
        """PRD section 3.4: "Initiating the withdrawal creates the
        `WithdrawalCase` in `OPEN` status, stamped with the enrollment's
        `enrollment_id`, the determined dates, a `total_days` snapshot frozen
        from the term at withdrawal time, and the computed `completed_days`
        and `percentage_completed`."
        PRD section 3.4: "In the same action the enrollment moves from
        `ENROLLED` to `WITHDRAWN`, its `current_withdrawal_case_id` is set to
        the new case, and the enrollment's `version` increments."

        Design: Corner/state_machines/withdraw_creates_open_case_with_snapshot
        """
        term, student, enrollment = setup_term_student_enrollment(
            charges=600_000)
        set_clock("2026-12-01T00:00:00Z")
        case = withdraw_unofficial(enrollment["id"])
        assert_withdrawal_case(case)
        assert case["status"] == "OPEN"
        assert case["withdrawal_date"] == "2026-10-15"
        assert case["determination_date"] == "2026-12-01"
        assert case["completed_days"] == 53
        assert case["total_days"] == 105
        assert case["percentage_completed"] == pytest_approx(0.505)
        # Financial snapshots stay null until calculation (PRD 3.4).
        for field in ("aid_disbursable_cents", "aid_disbursed_cents",
                      "aid_earned_cents", "aid_unearned_cents"):
            assert case.get(field) is None, field

        enr = get_enrollment(enrollment["id"])
        assert enr["status"] == "WITHDRAWN"
        assert enr["current_withdrawal_case_id"] == case["id"]
        assert enr["version"] == enrollment["version"] + 1


class TestAttendanceBasis:

    def test_attendance_basis_unofficial_uses_last_attendance(self):
        """PRD section 3.4: "For an unofficial withdrawal on an
        attendance-taking term, the `withdrawal_date` is the supplied
        `last_attendance_date`, while the `determination_date` is the logical
        date on which the withdrawal request is processed."

        Design: Corner/calculations/attendance_basis_unofficial_uses_last_attendance
        """
        term, student, enrollment = setup_term_student_enrollment(
            charges=600_000,
            term_overrides={"name": "Fall Att",
                            "attendance_taking_required": True})
        set_clock("2026-12-01T00:00:00Z")
        case = withdraw_unofficial(enrollment["id"],
                                   last_attendance_date="2026-09-20")
        assert_withdrawal_case(case)
        # Attendance basis: NOT the midpoint (2026-10-15, day 53).
        assert case["withdrawal_date"] == "2026-09-20"
        assert case["determination_date"] == "2026-12-01"
        # Day 28 of 105 -> 28/105 = 0.2666... -> 0.267 round half-up.
        assert case["completed_days"] == 28
        assert case["percentage_completed"] == pytest_approx(0.267)


class TestSixtyPercentCapBoundary:
    """X-1 / X / X+1 around the strictly-greater-than-0.600 earned cap."""

    def _setup_case_at(self, notification_date):
        return setup_full_aid_case(charges=600_000, pell_amount=200_000,
                                   loan_amount=300_000,
                                   withdraw_date=notification_date,
                                   calculate=False)

    def test_exactly_0600_earns_sixty_percent_and_0610_earns_all(self):
        """PRD section 3.4: "when `percentage_completed` exceeds 0.600, the
        student is treated as having earned one hundred percent of their aid
        and `earned_pct` reads 1.000; otherwise `earned_pct` equals
        `percentage_completed`. The boundary is inclusive of the cap's
        threshold — a completion of exactly 0.600 earns exactly 60.0 percent,
        and the full-earning rule engages only at 0.601 and beyond."

        Design: Difficulty/boundary_precision_check/sixty_percent_cap_exact_boundary
        """
        # Both enrollments share ONE term (terms may not overlap), exactly as
        # the canonical calendar intends: same period, two withdrawal days.
        term = create_term_t1()
        cases = {}
        for key, notif in (("a", "2026-10-25"), ("b", "2026-10-26")):
            student = create_student()
            enrollment = create_enrollment(student["id"], term["id"],
                                           institutional_charges_cents=600_000)
            create_and_fund_award(enrollment["id"], student["id"],
                                  "PELL_GRANT", 200_000, 200_000)
            create_and_fund_award(enrollment["id"], student["id"],
                                  "SUBSIDIZED_LOAN", 300_000, 300_000)
            cases[key] = withdraw_official(enrollment["id"], notif)
        calc_a = validate_success(api_client.calculate_case(
            cases["a"]["id"], OFFICER), 200)
        calc_b = validate_success(api_client.calculate_case(
            cases["b"]["id"], OFFICER), 200)

        # Exactly 0.600: cap NOT applied (rule is strictly-greater).
        assert calc_a["percentage_completed"] == pytest_approx(0.600)
        assert calc_a["earned_pct"] == pytest_approx(0.600)
        assert calc_a["aid_earned_cents"] == 300_000

        # 0.610 > 0.600: full earning engaged.
        assert calc_b["percentage_completed"] == pytest_approx(0.610)
        assert calc_b["earned_pct"] == pytest_approx(1.000)
        assert calc_b["aid_earned_cents"] == 500_000

        # One day (63 -> 64 of 105) jumps earned aid by 200000 cents.
        assert calc_b["aid_earned_cents"] - calc_a["aid_earned_cents"] \
            == 200_000

    def test_below_the_boundary_earned_equals_percentage(self):
        """PRD section 3.4: "when `percentage_completed` exceeds 0.600, the
        student is treated as having earned one hundred percent of their aid
        and `earned_pct` reads 1.000; otherwise `earned_pct` equals
        `percentage_completed`."

        Design: Difficulty/boundary_precision_check/sixty_percent_cap_exact_boundary
        """
        scen = self._setup_case_at("2026-10-24")  # day 62 of 105
        calc = validate_success(api_client.calculate_case(
            scen["case"]["id"], OFFICER), 200)
        # 62/105 = 0.590476... -> 0.590; below the cap, earned == percentage.
        assert calc["percentage_completed"] == pytest_approx(0.590)
        assert calc["earned_pct"] == pytest_approx(0.590)
        # PELL 120000? No: 0.590 * 200000 = 118000; 0.590 * 300000 = 177000.
        assert calc["aid_earned_cents"] == 118_000 + 177_000
