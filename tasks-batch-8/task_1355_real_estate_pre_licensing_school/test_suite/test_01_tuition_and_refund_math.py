"""Tuition charge computation and refund adjudication math (PRD §3.5, §3.9).

Covers the pinned evaluation order of the enrollment charge, the dual refund
philosophies (published tier schedule vs statutory pro-rata), their pinned
rounding steps, tier boundaries, and the money-conservation invariant.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_enrollment,
    assert_money_conservation,
    assert_refund_request,
    create_course_payload,
    create_credit_report_payload,
    create_enrollment_payload,
    create_offering_payload,
    create_school_payload,
    enroll,
    enroll_and_pay,
    enrollment_completed,
    get_enrollment,
    get_refund_for_enrollment,
    get_success_data,
    record_attendance,
    setup_publishable_school,
    validate_error,
    validate_success,
    withdraw_and_get_refund,
    withdraw_payload,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    DIRECTOR,
    REGISTRAR,
    create_active_course,
    create_licensed_school,
    create_published_offering,
)
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/order_total_evaluation_order
# ---------------------------------------------------------------------------

class TestOrderTotalEvaluationOrder:
    def test_scholarship_cap_and_low_fee_tier(self, api):
        """PRD §3.5: "For example, a 50000-cent tuition with a 30000-cent
        scholarship applies a 25000-cent scholarship cap, yields 25000
        discounted, attracts the 1500-cent fee, and totals 26500 cents".

        Design: Difficulty/combinatorial_formula/order_total_evaluation_order
        """
        env = setup_publishable_school()
        # Enroll a student carrying a 30000 scholarship to exercise the cap.
        student2 = get_success_data(api.create_student(
            {"school_id": env["school"]["id"], "full_name": "Scholar",
             "email": "scholar@example.com", "license_goal_state": "TX"},
            REGISTRAR))
        enr = get_success_data(api.create_enrollment(
            {"offering_id": env["offering"]["id"], "student_id": student2["id"],
             "scholarship_cents": 30000}, REGISTRAR))
        assert_enrollment(enr)
        assert enr["charge_total_cents"] == 26500, (
            f"50000 tuition with 30000 scholarship: cap floor(50000/2)=25000 applies, "
            f"discounted 25000 < 100000 so fee 1500; expected 26500, got "
            f"{enr['charge_total_cents']}")

    def test_high_tier_fee_keys_on_discounted_tuition_not_total(self, api):
        """PRD §3.5: "the registration fee is 2500 cents when the discounted
        tuition is at least 100000 cents, and 1500 cents otherwise — note the fee
        tier keys on the discounted tuition, not on the final total" and "a
        150000-cent tuition with no scholarship totals 152500 cents".

        Design: Difficulty/combinatorial_formula/order_total_evaluation_order
        """
        school = create_licensed_school()
        course = create_active_course(school["id"], tuition_cents=150000)
        from test_helpers.fixtures import create_credentialed_instructor
        ins = create_credentialed_instructor(school["id"])
        offering = create_published_offering(course["id"], ins["id"],
                                             start_date="2026-10-01",
                                             end_date="2026-10-05",
                                             capacity=2, delivery_mode="DISTANCE")
        student = get_success_data(api.create_student(
            {"school_id": school["id"], "full_name": "NoAid",
             "email": "noaid@example.com", "license_goal_state": "TX"}, REGISTRAR))
        enr = get_success_data(api.create_enrollment(
            {"offering_id": offering["id"], "student_id": student["id"]}, REGISTRAR))
        assert enr["charge_total_cents"] == 152500, (
            f"150000 tuition, no scholarship: discounted 150000 >= 100000 -> fee 2500, "
            f"expected 152500, got {enr['charge_total_cents']}")


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/refund_scheduled_vs_statutory_greater_of_two
# ---------------------------------------------------------------------------

class TestRefundScheduledVsStatutory:
    def _paid_with_300_minutes(self, api):
        env = setup_publishable_school()
        student, enr = enroll_and_pay(env["offering"]["id"], env["school"]["id"],
                                      amount_cents=51500)
        record_attendance(enr["id"], env["instructor"]["id"],
                          session_date="2026-09-03", minutes=300)
        return env, student, enr

    def test_granted_is_max_of_scheduled_and_statutory(self, api):
        """PRD §3.9: "The granted amount, `granted_refund_cents`, is the larger of
        the scheduled and statutory refunds; to see the philosophies diverge, a
        50000-cent payment withdrawn voluntarily at a 1000-basis-point fraction
        schedules 40000 cents but statutes 29000 — the student receives 40000."

        Design: Difficulty/dual_variant_calc/refund_scheduled_vs_statutory_greater_of_two
        """
        _env, _student, enr = self._paid_with_300_minutes(api)
        withdrawn, rr = withdraw_and_get_refund(enr["id"], reason="VOLUNTARY",
                                                effective_date="2026-09-04")
        assert_refund_request(rr)
        assert rr["completion_fraction_bps_at_withdrawal"] == 1000
        # scheduled = round_half_up(51500 * 0.90) - 5000 = 46350 - 5000
        assert rr["scheduled_refund_cents"] == 41350
        # statutory = 51500 - round_half_up(51500/10) * 4 - 1000 = 51500 - 20600 - 1000
        assert rr["statutory_refund_cents"] == 29900
        assert rr["granted_refund_cents"] == max(rr["scheduled_refund_cents"],
                                                 rr["statutory_refund_cents"])
        assert withdrawn["academic_status"] == "WITHDRAWN"

    def test_scheduled_branch_dominates_at_low_completion(self, api):
        """PRD §3.9: "For `VOLUNTARY` withdrawals a 5000-cent administrative fee
        is subtracted from the tiered amount, floored at zero" and "a fraction of
        at most 1000 basis points — ten percent of the seat requirement completed
        — refunds 90 percent of the amount paid".

        Design: Difficulty/dual_variant_calc/refund_scheduled_vs_statutory_greater_of_two
        """
        _env, _student, enr = self._paid_with_300_minutes(api)
        _w, rr = withdraw_and_get_refund(enr["id"], reason="VOLUNTARY",
                                         effective_date="2026-09-04")
        # Scheduled (41350) exceeds statutory (29900): granted follows scheduled.
        assert rr["granted_refund_cents"] == 41350
        assert rr["granted_refund_cents"] > rr["statutory_refund_cents"]


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/refund_scheduled_tier_reason_branching
# ---------------------------------------------------------------------------

class TestRefundScheduledTierReasonBranching:
    def _three_paid_enrollments(self, api):
        env = setup_publishable_school(capacity=3)
        paid = []
        for _ in range(3):
            _s, e = enroll_and_pay(env["offering"]["id"], env["school"]["id"],
                                   amount_cents=51500)
            record_attendance(e["id"], env["instructor"]["id"],
                              session_date="2026-09-03", minutes=300)
            paid.append(e)
        return env, paid

    def test_voluntary_vs_administrative_fee_branch(self, api):
        """PRD §3.9: "For `ADMINISTRATIVE` withdrawals that tiered amount is the
        refund, the administrative fee waived. For `VOLUNTARY` withdrawals a
        5000-cent administrative fee is subtracted from the tiered amount,
        floored at zero."

        Design: Difficulty/combinatorial_formula/refund_scheduled_tier_reason_branching
        """
        _env, (ea, eb, _ec) = self._three_paid_enrollments(api)
        _wa, rra = withdraw_and_get_refund(ea["id"], reason="VOLUNTARY",
                                           effective_date="2026-09-04")
        _wb, rrb = withdraw_and_get_refund(eb["id"], reason="ADMINISTRATIVE",
                                           effective_date="2026-09-04")
        assert rra["scheduled_refund_cents"] == 41350  # 90% tier minus 5000 fee
        assert rrb["scheduled_refund_cents"] == 46350  # 90% tier, fee waived

    def test_school_cancelled_short_circuits_to_full_refund(self, api):
        """PRD §3.9: "A `SCHOOL_CANCELLED` withdrawal refunds the full
        `paid_cents` — one hundred percent, no administrative fee." and §3.4:
        "for each such enrollment whose `payment_status` is `PAID`, a refund
        request is auto-created in `PENDING` with `reason` `SCHOOL_CANCELLED`".

        Design: Difficulty/combinatorial_formula/refund_scheduled_tier_reason_branching
        """
        env, (ea, eb, ec) = self._three_paid_enrollments(api)
        # Withdraw two manually first so the cascade reaches only the third.
        withdraw_and_get_refund(ea["id"], reason="VOLUNTARY", effective_date="2026-09-04")
        withdraw_and_get_refund(eb["id"], reason="ADMINISTRATIVE", effective_date="2026-09-04")
        get_success_data(api.cancel_offering(env["offering"]["id"], DIRECTOR))
        rrc = get_refund_for_enrollment(ec["id"])
        assert rrc is not None, "cancel cascade must auto-create a refund for the PAID enrollment"
        assert rrc["reason"] == "SCHOOL_CANCELLED"
        assert rrc["scheduled_refund_cents"] == 51500
        assert rrc["granted_refund_cents"] == 51500
        assert get_enrollment(ec["id"])["academic_status"] == "WITHDRAWN"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/refund_statutory_nested_rounding_order
# ---------------------------------------------------------------------------

class TestRefundStatutoryNestedRounding:
    def _setup_rounding_case(self, api):
        school = create_licensed_school()
        course = create_active_course(school["id"], tuition_cents=49999)
        from test_helpers.fixtures import create_credentialed_instructor
        ins = create_credentialed_instructor(school["id"])
        offering = create_published_offering(course["id"], ins["id"],
                                             start_date="2026-09-01",
                                             end_date="2026-09-03",
                                             capacity=1, delivery_mode="DISTANCE")
        student, enr = enroll(offering["id"], school["id"])
        return enr

    def test_daily_rate_rounded_before_multiplication(self, api):
        """PRD §3.9: "The daily rate is `paid_cents` divided by the total days,
        rounded half-up to integer cents first — this rounding happens before the
        multiplication, and rounding only at the end is non-conformant."

        Design: Difficulty/combinatorial_formula/refund_statutory_nested_rounding_order
        """
        enr = self._setup_rounding_case(api)
        assert enr["charge_total_cents"] == 51499  # 49999 + 1500 low-tier fee
        get_success_data(api.pay_enrollment(enr["id"], {"amount_cents": 51499}, REGISTRAR))
        _w, rr = withdraw_and_get_refund(enr["id"], reason="VOLUNTARY",
                                         effective_date="2026-09-02")
        # daily = round_half_up(51499/3) = 17166 -> earned 34332 -> statutory 16167.
        # PRD pins the order: round the daily rate first, then multiply.
        daily = 17166  # round_half_up(51499 / 3)
        earned = daily * 2
        expected_statutory = 51499 - earned - 1000
        assert expected_statutory == 16167
        assert rr["statutory_refund_cents"] == expected_statutory, (
            f"expected statutory {expected_statutory} (daily {daily} rounded before "
            f"multiplication), got {rr['statutory_refund_cents']}")
        # Zero completion fraction -> 90% tier: round_half_up(51499*0.9) - 5000.
        assert rr["scheduled_refund_cents"] == 41349
        assert rr["granted_refund_cents"] == 41349  # scheduled wins at f == 0

    def test_rounding_order_isolates_one_cent_divergence(self, api):
        """PRD §3.9: "The ordering matters in practice: 50000 cents paid over a
        3-day offering with 2 days elapsed yields a daily rate of 16667 cents,
        earned 33334, and a statutory refund of 15666 — rounding only at the end
        would produce 15667."

        Design: Difficulty/combinatorial_formula/refund_statutory_nested_rounding_order
        """
        school = create_licensed_school()
        course = create_active_course(school["id"], tuition_cents=48500)  # charge 50000
        from test_helpers.fixtures import create_credentialed_instructor
        ins = create_credentialed_instructor(school["id"])
        offering = create_published_offering(course["id"], ins["id"],
                                             start_date="2026-09-01",
                                             end_date="2026-09-03",
                                             capacity=1, delivery_mode="DISTANCE")
        student, enr = enroll(offering["id"], school["id"])
        assert enr["charge_total_cents"] == 50000
        get_success_data(api.pay_enrollment(enr["id"], {"amount_cents": 50000}, REGISTRAR))
        _w, rr = withdraw_and_get_refund(enr["id"], reason="VOLUNTARY",
                                         effective_date="2026-09-02")
        # PRD's pinned worked example: 50000 over 3 days, 2 elapsed -> 15666.
        assert rr["statutory_refund_cents"] == 15666, (
            f"PRD worked example: daily 16667 -> earned 33334 -> statutory 15666; "
            f"got {rr['statutory_refund_cents']}")


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/refund_tier_boundary_1000bps
# ---------------------------------------------------------------------------

class TestRefundTierBoundary1000bps:
    def test_fraction_at_1000_bps_gets_90_pct_tier(self, api):
        """PRD §3.9: "a tier percentage is chosen by the frozen completion
        fraction, with boundaries inclusive on the lower refund tier: a fraction
        of at most 1000 basis points — ten percent of the seat requirement
        completed — refunds 90 percent of the amount paid".

        Design: Difficulty/boundary_precision_check/refund_tier_boundary_1000bps
        """
        env = setup_publishable_school()
        _s, enr = enroll_and_pay(env["offering"]["id"], env["school"]["id"],
                                 amount_cents=51500)
        record_attendance(enr["id"], env["instructor"]["id"],
                          session_date="2026-09-03", minutes=300)
        _w, rr = withdraw_and_get_refund(enr["id"], reason="VOLUNTARY",
                                         effective_date="2026-09-04")
        assert rr["completion_fraction_bps_at_withdrawal"] == 1000
        assert rr["granted_refund_cents"] == 41350  # 90% tier, inclusive boundary

    def test_fraction_just_over_1000_bps_drops_to_75_pct_tier(self, api):
        """PRD §3.9: "at most 2500 basis points refunds 75 percent" and the
        boundary is "inclusive on the lower refund tier", so a fraction of 1003
        basis points falls out of the 90% tier into the 75% tier.

        Design: Difficulty/boundary_precision_check/refund_tier_boundary_1000bps
        """
        env = setup_publishable_school()
        _s, enr = enroll_and_pay(env["offering"]["id"], env["school"]["id"],
                                 amount_cents=51500)
        record_attendance(enr["id"], env["instructor"]["id"],
                          session_date="2026-09-03", minutes=301)
        _w, rr = withdraw_and_get_refund(enr["id"], reason="VOLUNTARY",
                                         effective_date="2026-09-04")
        assert rr["completion_fraction_bps_at_withdrawal"] == 1003
        # scheduled = round_half_up(51500 * 0.75) - 5000 = 38625 - 5000
        assert rr["scheduled_refund_cents"] == 33625
        assert rr["granted_refund_cents"] == 33625


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/tuition_money_conservation
# ---------------------------------------------------------------------------

class TestTuitionMoneyConservation:
    def test_paid_equals_retained_plus_granted_partial_refund(self, api):
        """PRD §3.9: "`retained_cents` becomes `paid_cents` minus
        `granted_refund_cents`, preserving the invariant that the paid amount
        always equals retained plus granted, and `payment_status` moves to
        `REFUNDED` when the granted amount equals the full `paid_cents`,
        otherwise to `PARTIALLY_REFUNDED`."

        Design: Difficulty/compensating_invariant/tuition_money_conservation
        """
        env = setup_publishable_school()
        _s, enr = enroll_and_pay(env["offering"]["id"], env["school"]["id"],
                                 amount_cents=51500)
        record_attendance(enr["id"], env["instructor"]["id"],
                          session_date="2026-09-03", minutes=300)
        _w, rr = withdraw_and_get_refund(enr["id"], reason="VOLUNTARY",
                                         effective_date="2026-09-04")
        get_success_data(api.approve_refund_request(rr["id"], DIRECTOR))
        paid_rr = get_success_data(api.pay_refund_request(rr["id"], REGISTRAR))
        assert paid_rr["status"] == "PAID"
        assert paid_rr["granted_refund_cents"] == 41350
        final = get_enrollment(enr["id"])
        assert final["paid_cents"] == 51500
        assert final["retained_cents"] == 10150
        assert_money_conservation(final, paid_rr["granted_refund_cents"])
        assert final["payment_status"] == "PARTIALLY_REFUNDED"

    def test_full_refund_flips_payment_status_to_refunded(self, api):
        """PRD §3.9: "`payment_status` moves to `REFUNDED` when the granted
        amount equals the full `paid_cents`, otherwise to
        `PARTIALLY_REFUNDED`." and §3.4: a SCHOOL_CANCELLED cascade refund has
        "the scheduled, statutory, and granted amounts all equal to the
        enrollment's `paid_cents`".

        Design: Difficulty/compensating_invariant/tuition_money_conservation
        """
        env = setup_publishable_school()
        _s, enr = enroll_and_pay(env["offering"]["id"], env["school"]["id"],
                                 amount_cents=51500)
        get_success_data(api.cancel_offering(env["offering"]["id"], DIRECTOR))
        rr = get_refund_for_enrollment(enr["id"])
        assert rr["granted_refund_cents"] == 51500
        get_success_data(api.approve_refund_request(rr["id"], DIRECTOR))
        get_success_data(api.pay_refund_request(rr["id"], REGISTRAR))
        final = get_enrollment(enr["id"])
        assert final["payment_status"] == "REFUNDED"
        assert final["retained_cents"] == 0
        assert_money_conservation(final, 51500)
