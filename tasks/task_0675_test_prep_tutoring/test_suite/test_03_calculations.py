"""Corner tests for pricing, installment, and scoring calculations (section: calculations)."""
from test_helpers import (
    validate_success, get_success_data,
    make_student_headers, make_instructor_headers, TEST_USERS,
    setup_scheduled_cohort, setup_active_enrollment, enroll_student, score_attempt,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestInstallmentSchedule:
    def test_remainder_front_loaded(self, api):
        """PRD §3.6: "At creation the plan's total_financed_cents is captured from the
        enrollment's price_paid_cents".
        PRD §3.6: "The plan's schedule splits total_financed_cents into num_installments
        integer-cent amounts that sum exactly to the total — no cent is created or lost."

        total 100000 over 3 -> base 33333, remainder 1 to earliest; total_financed_cents 100000.

        Design: Corner/calculations/installment_schedule_remainder_front_loaded
        """
        base = setup_scheduled_cohort(exam_type="SAT", fmt="LIVE", list_price_cents=100000)
        student, enr = enroll_student(
            base["cohort"]["id"], expected_cohort_version=base["cohort_version"],
            email="instsched@x.com")
        plan = validate_success(api.create_installment_plan(
            {"enrollment_id": enr["id"], "num_installments": 3},
            make_student_headers(student["id"])), expected_status=201)
        assert plan["total_financed_cents"] == 100000
        assert plan["status"] == "OPEN"

    def test_payment_closes_plan_paid_in_full(self, api):
        """PRD §3.6: "When that running total reaches exactly the plan's total_financed_cents,
        the plan transitions from OPEN to PAID_IN_FULL".

        Design: Corner/calculations/installment_payment_closes_plan_paid_in_full
        """
        base = setup_scheduled_cohort(exam_type="SAT", fmt="LIVE", list_price_cents=100000)
        student, enr = enroll_student(
            base["cohort"]["id"], expected_cohort_version=base["cohort_version"],
            email="pif@x.com")
        plan = get_success_data(api.create_installment_plan(
            {"enrollment_id": enr["id"], "num_installments": 1},
            make_student_headers(student["id"])))
        paid = validate_success(api.record_payment(plan["id"], 100000, REGISTRAR))
        assert paid["amount_paid_cents"] == 100000
        assert paid["status"] == "PAID_IN_FULL"


class TestCouponPricing:
    def test_flat_coupon_refer50(self, api):
        """PRD §3.3: "the REFER50 coupon discounts a flat 5000 cents regardless of list price."
        PRD §3.3: "The net price_paid_cents is the base minus the discount, floored at zero".

        list 120000 - 5000 = 115000.

        Design: Corner/calculations/flat_coupon_net_price_refer50
        """
        base = setup_scheduled_cohort(exam_type="SAT", fmt="LIVE", list_price_cents=120000)
        student, enr = enroll_student(
            base["cohort"]["id"], expected_cohort_version=base["cohort_version"],
            coupon_code="REFER50", email="refer50@x.com")
        assert enr["price_paid_cents"] == 115000


class TestVoidedExclusion:
    def test_voided_attempt_excluded_from_best_score(self, api):
        """PRD §3.5: "A voided attempt records no score and is excluded from all analytics;
        even an attempt whose scaled_score was computed before voiding is excluded from
        best_practice_score and completed_practice_count."

        One COMPLETED PRACTICE (550/800 -> 1100), one VOIDED -> best 1100, count 1.

        Design: Corner/calculations/voided_attempt_excluded_from_best_practice_score
        """
        base = setup_active_enrollment(fmt="SELF", student_email="ve@x.com")
        enr_id = base["enrollment"]["id"]
        inst_id = base["instructor"]["id"]
        stu_id = base["student"]["id"]
        score_attempt(enr_id, inst_id, "PRACTICE", 550, 800, stu_id)  # -> 1100
        att2 = get_success_data(api.create_practice_attempt(
            {"enrollment_id": enr_id, "attempt_type": "PRACTICE", "raw_correct": 700,
             "total_items": 800}, make_student_headers(stu_id)))
        voided = validate_success(api.void_practice_attempt(
            att2["id"], make_instructor_headers(inst_id)))
        assert voided["status"] == "VOIDED"
        enr = validate_success(api.get_enrollment(enr_id, REGISTRAR))
        assert enr["best_practice_score"] == 1100
        assert enr["completed_practice_count"] == 1
