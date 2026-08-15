"""The R2T4 calculation: earned/unearned snapshots, the return split
waterfall, pinned rounding order, and institutional refund variants."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_return_obligation,
    assert_withdrawal_case,
    create_and_fund_award,
    create_award,
    create_enrollment,
    create_student,
    create_term,
    create_term_t1,
    list_account_entries,
    list_obligations,
    schedule_disbursement,
    set_clock,
    setup_t2_split_case,
    validate_success,
    withdraw_official,
    withdraw_unofficial,
)

OFFICER = TEST_USERS["financial_aid_officer_headers"]


def approx3(value):
    return pytest.approx(value, abs=1e-9)


class TestReturnSplitNestedMinWithGrantProtection:

    def test_split_fields_and_both_obligations(self):
        """PRD section 3.5: "The school's share, `school_return_cents`, is
        the smaller of two figures: the enrollment's gross
        `institutional_charges_cents` multiplied by the unearned percentage
        and rounded half-up to whole cents, or the full
        `return_amount_cents`."
        PRD section 3.5: "the student grant base is the smaller of the
        student share and that grant total. The student's actual grant
        obligation, `student_grant_return_cents`, is half of that base
        rounded half-up to whole cents, reflecting the fifty-percent grant
        protection allowance; the remainder of the student share becomes
        `student_loan_deferred_cents`, an informational figure routed to
        normal loan repayment for which no obligation is ever created."
        PRD section 3.5: "Each obligation records its `withdrawal_case_id`,
        its `party` (`SCHOOL` or `STUDENT`), its `amount_cents`, and a
        `due_date` exactly 45 calendar days after the case's
        `determination_date`, and both begin `PENDING`."

        Design: Difficulty/combinatorial_formula/return_split_nested_min_with_grant_protection
        """
        scen = setup_t2_split_case(charges=100_000,
                                   clock="2026-11-15T00:00:00Z")
        case = scen["case"]
        assert_withdrawal_case(case)
        # Midpoint of 100 days -> 0.500; earned 100000 + 150000 = 250000.
        assert case["percentage_completed"] == approx3(0.500)
        assert case["aid_earned_cents"] == 250_000
        assert case["aid_unearned_cents"] == 250_000
        assert case["return_amount_cents"] == 250_000
        # school = min(round(100000 * 0.500), 250000) = 50000.
        assert case["school_return_cents"] == 50_000
        # student share 200000; grant base min(200000, 100000) = 100000;
        # grant return = 100000 * 0.5 = 50000; loan deferred = 100000.
        assert case["student_grant_return_cents"] == 50_000
        assert case["student_loan_deferred_cents"] == 100_000

        obligations = scen["obligations"]
        assert len(obligations) == 2
        for ob in obligations:
            assert_return_obligation(ob)
            assert ob["due_date"] == "2026-12-30"  # 2026-11-15 + 45d
            assert ob["status"] == "PENDING"
        # School row created first (created_at ASC -> index 0).
        assert obligations[0]["party"] == "SCHOOL"
        assert obligations[0]["amount_cents"] == 50_000
        assert obligations[1]["party"] == "STUDENT"
        assert obligations[1]["amount_cents"] == 50_000

    def test_school_share_capped_by_return_amount_leaves_no_student_row(self):
        """PRD section 3.5: "Obligations materialize only where money is
        actually owed: a school-party obligation is created when
        `school_return_cents` is greater than zero, and a student-party
        obligation when `student_grant_return_cents` is greater than zero —
        obligations with an amount of zero are never created."
        PRD section 3.5: "The student share is what remains of
        `return_amount_cents` after the school's share."

        Design: Difficulty/combinatorial_formula/return_split_nested_min_with_grant_protection
        """
        # Charges 1000000 -> charges * 0.500 = 500000 > return 250000, so the
        # nested min binds at return_amount: school absorbs everything.
        scen = setup_t2_split_case(charges=1_000_000,
                                   clock="2026-11-15T00:00:00Z")
        case = scen["case"]
        assert case["return_amount_cents"] == 250_000
        assert case["school_return_cents"] == 250_000
        assert case["student_grant_return_cents"] == 0
        assert case["student_loan_deferred_cents"] == 0
        obligations = scen["obligations"]
        assert len(obligations) == 1
        assert obligations[0]["party"] == "SCHOOL"
        assert obligations[0]["amount_cents"] == 250_000
        assert obligations[0]["due_date"] == "2026-12-30"


class TestPerAwardRoundThenSum:

    def _setup_rounding_case(self, pell_amount=100_001, loan_amount=100_001):
        """T1 midpoint withdrawal (0.505) with two awards whose sizes make
        per-award rounding observable."""
        term = create_term_t1()
        student = create_student()
        enrollment = create_enrollment(student["id"], term["id"],
                                       institutional_charges_cents=500_000)
        create_and_fund_award(enrollment["id"], student["id"],
                              "PELL_GRANT", pell_amount, pell_amount)
        create_and_fund_award(enrollment["id"], student["id"],
                              "SUBSIDIZED_LOAN", loan_amount, loan_amount)
        set_clock("2026-12-01T00:00:00Z")
        case = withdraw_unofficial(enrollment["id"])
        return case

    def test_round_each_award_then_sum(self):
        """PRD section 3.5: "The round-then-sum order is pinned: two awards
        of 100001 cents each at an earned share of 0.505 yield 50501 plus
        50501, an `aid_earned_cents` of 101002 — summing first and rounding
        the aggregate, which would yield 101001, is the rejected
        alternative."

        Design: Difficulty/combinatorial_formula/per_award_round_then_sum_order
        """
        case = self._setup_rounding_case()
        calc = validate_success(api_client.calculate_case(case["id"], OFFICER),
                                200)
        assert calc["percentage_completed"] == approx3(0.505)
        assert calc["aid_disbursable_cents"] == 200_002
        assert calc["aid_disbursed_cents"] == 200_002
        # round_half_up(100001 * 0.505) = 50501 per award; 50501 + 50501.
        assert calc["aid_earned_cents"] == 101_002
        # aid_unearned = disbursable - earned = 200002 - 101002.
        assert calc["aid_unearned_cents"] == 99_000

    def test_rounding_discriminates_with_another_odd_pair(self):
        """PRD section 2.7: "Whenever a calculation produces a fractional
        cent, the result is rounded half-up to a whole cent at the step the
        specification designates; multi-award calculations round each award
        first and sum afterward (see §3.5)."
        PRD section 3.5: "Each award's earned amount is then the award's
        disbursable amount multiplied by the case's `earned_pct`, rounded
        half-up to whole cents — and this rounding happens per award, before
        any summation."

        Design: Difficulty/combinatorial_formula/per_award_round_then_sum_order
        """
        # 99999 * 0.505 = 50499.495 -> 50499 per award; round-then-sum gives
        # 100998 while sum-then-round would give round(199998*0.505)=100999.
        case = self._setup_rounding_case(pell_amount=99_999,
                                         loan_amount=99_999)
        calc = validate_success(api_client.calculate_case(case["id"], OFFICER),
                                200)
        assert calc["percentage_completed"] == approx3(0.505)
        assert calc["aid_disbursable_cents"] == 199_998
        assert calc["aid_earned_cents"] == 100_998


class TestTieredVsProRataRefund:

    def _setup_refund_case(self, term_overrides, notification_date,
                           charges=400_000):
        term = create_term(**term_overrides)
        student = create_student()
        enrollment = create_enrollment(student["id"], term["id"],
                                       institutional_charges_cents=charges)
        case = withdraw_official(enrollment["id"], notification_date)
        calc = validate_success(api_client.calculate_case(case["id"], OFFICER),
                                200)
        refunds = list_account_entries(enrollment_id=enrollment["id"],
                                       entry_type="REFUND_CREDIT")
        return term, enrollment, calc, refunds

    def test_same_day_11_yields_different_refund_by_variant(self):
        """PRD section 3.5: "Under `TIERED`, the server walks the term's
        `refund_schedule` and selects the first tier whose `through_day` is
        at least the case's `completed_days`; that tier's `refund_pct`
        applies, and when `completed_days` exceeds every tier's `through_day`
        the refund percentage is zero — the same withdrawal day therefore
        yields a step-function refund. Under `PRO_RATA`, the refund
        percentage is one minus the case's `percentage_completed` — the
        rounded three-decimal figure, not `earned_pct`, so the sixty-percent
        earned cap has no effect on refunds. For contrast, day 11 of a
        110-day term with 400000 cents of charges yields a refund of 300000
        cents under the default tiered schedule but 360000 cents pro rata."

        Design: Difficulty/dual_variant_calc/tiered_vs_pro_rata_institutional_refund
        """
        # Two non-overlapping 110-day terms; both withdraw on relative day 11.
        _, enr_a, calc_a, refunds_a = self._setup_refund_case(
            {"name": "Spring A", "start_date": "2027-01-11",
             "end_date": "2027-04-30", "refund_method": "TIERED"},
            "2027-01-21")
        _, enr_b, calc_b, refunds_b = self._setup_refund_case(
            {"name": "Summer B", "start_date": "2027-05-03",
             "end_date": "2027-08-20", "refund_method": "PRO_RATA"},
            "2027-05-13")

        assert calc_a["completed_days"] == 11
        assert calc_b["completed_days"] == 11
        assert calc_b["percentage_completed"] == approx3(0.100)

        # TIERED: day 11 <= through_day 14 -> 0.75 * 400000 = 300000.
        assert len(refunds_a) == 1
        assert refunds_a[0]["amount_cents"] == -300_000
        # PRO_RATA: (1 - 0.100) * 400000 = 360000.
        assert len(refunds_b) == 1
        assert refunds_b[0]["amount_cents"] == -360_000
        assert refunds_a[0]["amount_cents"] != refunds_b[0]["amount_cents"]

    def test_pro_rata_uses_percentage_not_capped_earned_pct(self):
        """PRD section 3.5: "Under `PRO_RATA`, the refund percentage is one
        minus the case's `percentage_completed` — the rounded three-decimal
        figure, not `earned_pct`, so the sixty-percent earned cap has no
        effect on refunds."
        PRD section 3.5: "The refund amount is the charges multiplied by the
        refund percentage, rounded half-up to whole cents, and when it is
        greater than zero the server posts a `REFUND_CREDIT` ledger entry for
        the negated amount."

        Design: Difficulty/dual_variant_calc/tiered_vs_pro_rata_institutional_refund
        """
        # Day 67 of 110 -> 67/110 = 0.60909... -> 0.609 > 0.600, so the earned
        # cap sets earned_pct to 1.000; the refund must still use 0.609.
        _, _, calc, refunds = self._setup_refund_case(
            {"name": "Summer B", "start_date": "2027-05-03",
             "end_date": "2027-08-20", "refund_method": "PRO_RATA"},
            "2027-07-08")
        assert calc["percentage_completed"] == approx3(0.609)
        assert calc["earned_pct"] == approx3(1.000)
        # (1 - 0.609) * 400000 = 156400. Had the cap applied to refunds the
        # refund would be zero.
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == -156_400


class TestCalculationInputSet:

    def test_unaccepted_loan_excluded_from_disbursable(self):
        """PRD section 3.5: "Calculation evaluates only the enrollment's
        eligible awards, meaning those in `ACCEPTED` status; awards still
        `OFFERED` or already `CANCELLED` are excluded from the disbursable
        base entirely."

        Design: Corner/calculations/unaccepted_loan_excluded_from_disbursable
        """
        term = create_term_t1()
        student = create_student()
        enrollment = create_enrollment(student["id"], term["id"],
                                       institutional_charges_cents=600_000)
        create_and_fund_award(enrollment["id"], student["id"],
                              "PELL_GRANT", 200_000, 200_000)
        # Loan stays OFFERED; its 300000 SCHEDULED row must not count.
        loan = create_award(enrollment["id"], "SUBSIDIZED_LOAN", 300_000)
        schedule_disbursement(loan["id"], 300_000)
        case = withdraw_official(enrollment["id"], "2026-09-02")
        calc = validate_success(api_client.calculate_case(case["id"], OFFICER),
                                200)
        assert calc["aid_disbursable_cents"] == 200_000
        # Day 10 of 105 -> 10/105 = 0.095238... -> 0.095;
        # round_half_up(200000 * 0.095) = 19000.
        assert calc["percentage_completed"] == approx3(0.095)
        assert calc["aid_earned_cents"] == 19_000

    def test_zero_aid_withdrawal_auto_closes_case(self):
        """PRD section 3.5: "Obligations materialize only where money is
        actually owed: a school-party obligation is created when
        `school_return_cents` is greater than zero, and a student-party
        obligation when `student_grant_return_cents` is greater than zero —
        obligations with an amount of zero are never created."
        PRD section 3.7: "When all three hold, the case transitions from
        `CALCULATED` to `CLOSED`, clearing the enrollment's
        `current_withdrawal_case_id` and incrementing the case's `version`."
        PRD section 2.6: "Whenever a recomputation happens while a linked
        withdrawal case is `CALCULATED` and the resulting balance is greater
        than zero, the enrollment's `balance_notification_sent` flag is set
        to true and `balance_notified_at` is stamped with the current logical
        time"

        Design: Corner/calculations/zero_aid_withdrawal_auto_closes_case
        """
        term = create_term_t1()
        student = create_student()
        enrollment = create_enrollment(student["id"], term["id"],
                                       institutional_charges_cents=600_000)
        case = withdraw_official(enrollment["id"], "2026-10-25")
        calc = validate_success(api_client.calculate_case(case["id"], OFFICER),
                                200)
        assert calc["aid_earned_cents"] == 0
        assert calc["aid_disbursed_cents"] == 0
        assert calc["aid_disbursable_cents"] == 0
        # No obligations, no offers; balance 600000 > 0 -> notification sent;
        # all closure conditions hold immediately.
        assert calc["status"] == "CLOSED"
        obligations = list_obligations(case["id"])
        assert obligations == []
        enr = validate_success(api_client.get_enrollment(enrollment["id"],
                                                         OFFICER), 200)
        assert enr["balance_notification_sent"] is True
