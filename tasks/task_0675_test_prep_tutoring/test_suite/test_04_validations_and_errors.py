"""Corner tests for validation rules and error conditions (sections: validations, errors)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, make_student_headers, make_instructor_headers, TEST_USERS,
    create_published_course, create_instructor, create_cohort,
    setup_scheduled_cohort, setup_active_enrollment, enroll_student,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestEnrollmentValidations:
    def test_invalid_coupon_rejected(self, api):
        """PRD §3.3: "If a coupon_code is supplied, it must be either EARLYBIRD or REFER50;
        any other value is rejected with ERR_INVALID_COUPON."

        Design: Corner/validations/enroll_invalid_coupon_returns_invalid_coupon
        """
        base = setup_scheduled_cohort(exam_type="SAT", fmt="LIVE")
        student = get_success_data(api.register_student(
            {"email": "ic@x.com", "full_name": "IC"}, TEST_USERS["anonymous_headers"]))
        resp = api.create_enrollment(
            {"student_id": student["id"], "cohort_id": base["cohort"]["id"],
             "expected_cohort_version": base["cohort_version"], "coupon_code": "BOGUS"},
            make_student_headers(student["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_COUPON)

    def test_duplicate_enrollment_rejected(self, api):
        """PRD §3.3: "The student must not already hold a non-terminal enrollment — one in
        PENDING_PAYMENT, WAITLISTED, ACTIVE, or COMPLETED — in this same cohort, or the
        request fails with ERR_DUPLICATE_ENROLLMENT."

        Design: Corner/validations/duplicate_enrollment_same_cohort_rejected
        """
        base = setup_scheduled_cohort(exam_type="SAT", fmt="LIVE")
        student, enr1 = enroll_student(
            base["cohort"]["id"], expected_cohort_version=base["cohort_version"],
            email="dup@x.com")
        cohort = validate_success(api.get_cohort(base["cohort"]["id"], REGISTRAR))
        resp = api.create_enrollment(
            {"student_id": student["id"], "cohort_id": base["cohort"]["id"],
             "expected_cohort_version": cohort["version"]},
            make_student_headers(student["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)


class TestScoreRange:
    def test_raw_correct_exceeds_total_rejected(self, api):
        """PRD §3.5: "the raw_correct count of correct items (zero or greater, and no more
        than total_items)".
        PRD §3.5: "it requires that raw_correct not exceed total_items and that the resulting
        scaled_score not exceed the course's baseline_scale_max, failing with
        ERR_SCORE_OUT_OF_RANGE otherwise".

        Design: Corner/validations/score_out_of_range_raw_exceeds_total
        """
        base = setup_active_enrollment(fmt="SELF", student_email="sr@x.com")
        resp = api.create_practice_attempt(
            {"enrollment_id": base["enrollment"]["id"], "attempt_type": "PRACTICE",
             "raw_correct": 90, "total_items": 80},
            make_student_headers(base["student"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SCORE_OUT_OF_RANGE)


class TestInstructorLoad:
    def test_instructor_overloaded_at_max(self, api):
        """PRD §3.2: "The instructor must not already be at capacity — that is, the
        instructor's active_cohort_count must be strictly less than max_concurrent_cohorts,
        or the request fails with ERR_INSTRUCTOR_OVERLOADED."

        max_concurrent_cohorts 1, already SCHEDULED on a non-overlapping cohort -> second
        non-overlapping schedule rejected.

        Design: Corner/validations/instructor_overloaded_at_max_concurrent
        """
        get_success_data(api.set_clock("2026-05-01T00:00:00Z", REGISTRAR))
        course = create_published_course(exam_type="SAT", format="LIVE")
        inst = create_instructor(certified_exam_types=["SAT"], max_concurrent_cohorts=1)
        cA = create_cohort(course["id"], seat_capacity=5,
                          starts_at="2026-06-01T00:00:00Z", ends_at="2026-06-30T00:00:00Z")
        validate_success(api.schedule_cohort(cA["id"], inst["id"], REGISTRAR))
        cB = create_cohort(course["id"], seat_capacity=5,
                          starts_at="2026-08-01T00:00:00Z", ends_at="2026-08-30T00:00:00Z")
        resp = api.schedule_cohort(cB["id"], inst["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_OVERLOADED)
        c = validate_success(api.get_cohort(cB["id"], REGISTRAR))
        assert c["status"] == "DRAFT"


class TestActivationFiscal:
    def test_activate_before_payment_settled(self, api):
        """PRD §3.4: "it requires that an installment plan exists for the enrollment whose
        amount_paid_cents is at least the first installment's amount, or the request fails
        with ERR_PAYMENT_NOT_SETTLED".

        Plan exists but amount_paid_cents 0 -> ERR_PAYMENT_NOT_SETTLED.

        Design: Corner/validations/activate_before_payment_settled_returns_payment_not_settled
        """
        base = setup_scheduled_cohort(exam_type="SAT", fmt="LIVE")
        student, enr = enroll_student(
            base["cohort"]["id"], expected_cohort_version=base["cohort_version"],
            email="ps@x.com")
        get_success_data(api.create_installment_plan(
            {"enrollment_id": enr["id"], "num_installments": 2},
            make_student_headers(student["id"])))
        resp = api.activate_enrollment(enr["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_SETTLED)
        e = validate_success(api.get_enrollment(enr["id"], REGISTRAR))
        assert e["status"] == "PENDING_PAYMENT"


class TestMaterialsExpiry:
    def test_materials_access_after_expiry_denied(self, api):
        """PRD §3.8: "A materials read is denied — rejected with ERR_MATERIALS_EXPIRED — when
        the logical clock is at or after materials_expire_at."

        Activated 2026-05-01 + 30 days = expire 2026-05-31; clock advanced to 2026-06-15.

        Design: Corner/validations/materials_access_after_expiry_returns_materials_expired
        """
        base = setup_active_enrollment(
            fmt="SELF", materials_access_days=30, student_email="me@x.com")
        get_success_data(api.set_clock("2026-06-15T00:00:00Z", REGISTRAR))
        resp = api.get_enrollment_materials(
            base["enrollment"]["id"], make_student_headers(base["student"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MATERIALS_EXPIRED)


class TestEnrollmentNotScorable:
    def test_score_attempt_on_pending_enrollment_rejected(self, api):
        """PRD §3.5: "it requires the parent enrollment to be in ACTIVE or COMPLETED, or it
        fails with ERR_ENROLLMENT_NOT_SCORABLE."

        Enrollment still PENDING_PAYMENT (never activated); scoring a STARTED attempt rejected.

        Design: Corner/errors/score_attempt_on_pending_enrollment_not_scorable
        """
        base = setup_scheduled_cohort(exam_type="SAT", fmt="SELF")
        student, enr = enroll_student(
            base["cohort"]["id"], expected_cohort_version=base["cohort_version"],
            email="ns@x.com")
        att = get_success_data(api.create_practice_attempt(
            {"enrollment_id": enr["id"], "attempt_type": "PRACTICE", "raw_correct": 400,
             "total_items": 800}, make_student_headers(student["id"])))
        resp = api.score_practice_attempt(
            att["id"], make_instructor_headers(base["instructor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_SCORABLE)
        data = validate_success(api.get_practice_attempt(
            att["id"], make_instructor_headers(base["instructor"]["id"])))
        assert data["status"] == "STARTED"
