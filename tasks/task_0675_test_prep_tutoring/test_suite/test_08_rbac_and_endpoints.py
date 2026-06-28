"""Corner tests for RBAC, listing endpoints, computed reads, and OCC concurrency
(sections: rbac, endpoints, cross_cutting_complexity_layers)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, make_student_headers, TEST_USERS,
    create_course, register_student, setup_scheduled_cohort,
    setup_active_enrollment, enroll_student, score_attempt,
)

REGISTRAR = TEST_USERS["registrar_headers"]
ANON = TEST_USERS["anonymous_headers"]


class TestRbacExclusiveOps:
    def test_student_cannot_score_practice_attempt(self, api):
        """PRD §2.1: "If the headers are well-formed but the named role is not permitted to
        perform the requested operation, the request is rejected with ERR_UNAUTHORIZED."
        PRD §3.5: "Scoring an attempt is an instructor-only action that advances STARTED to
        COMPLETED."

        Design: Corner/rbac/student_cannot_score_practice_attempt
        """
        base = setup_active_enrollment(fmt="SELF", student_email="rbacscore@x.com")
        stu_id = base["student"]["id"]
        att = get_success_data(api.create_practice_attempt(
            {"enrollment_id": base["enrollment"]["id"], "attempt_type": "PRACTICE",
             "raw_correct": 400, "total_items": 800}, make_student_headers(stu_id)))
        resp = api.score_practice_attempt(att["id"], make_student_headers(stu_id))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_student_cannot_publish_course(self, api):
        """PRD §2.1: "the request is rejected with ERR_UNAUTHORIZED."
        PRD §3.1: "Publishing it advances DRAFT to PUBLISHED, which is the precondition for
        scheduling any cohort beneath it."
        (Publishing is a Registrar-only operation per §4.)

        Design: Corner/rbac/student_cannot_publish_course
        """
        course = create_course(exam_type="SAT", format="LIVE")
        student = register_student(email="rbacpub@x.com", full_name="RB")
        resp = api.publish_course(course["id"], make_student_headers(student["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        c = validate_success(api.get_course(course["id"], REGISTRAR))
        assert c["status"] == "DRAFT"

    def test_student_cannot_cancel_other_students_enrollment(self, api):
        """PRD §2.1: "A `Student` may act only on enrollments it owns, on the practice
        attempts, installment plans, and guarantee claims that belong to those enrollments,
        and on its own student record; an attempt to act on another student's resource is
        rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/student_cannot_cancel_other_students_enrollment
        """
        base = setup_scheduled_cohort(exam_type="SAT", fmt="LIVE")
        student_a, enr_a = enroll_student(
            base["cohort"]["id"], expected_cohort_version=base["cohort_version"],
            email="owna@x.com")
        student_b = register_student(email="ownb@x.com", full_name="OwnB")
        cohort = validate_success(api.get_cohort(base["cohort"]["id"], REGISTRAR))
        resp = api.cancel_enrollment(
            enr_a["id"], cohort["version"], make_student_headers(student_b["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        e = validate_success(api.get_enrollment(enr_a["id"], REGISTRAR))
        assert e["status"] == "PENDING_PAYMENT"

    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "If a protected endpoint receives a request with a missing header, or an
        X-User-Role value that is not one of these four role names, the request is rejected
        with ERR_UNAUTHENTICATED."

        Design: Corner/rbac/missing_auth_headers_on_protected_endpoint
        """
        resp = api._request(
            "POST", "/instructors",
            {"full_name": "NoAuth", "certified_exam_types": ["SAT"], "max_concurrent_cohorts": 2},
            headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestListingEndpoints:
    def test_list_courses_pagination_envelope(self, api):
        """PRD §2.3: "Every list response includes limit, offset, total_count, and has_more in
        the envelope's meta object, where total_count is the number of resources matching the
        query before pagination and has_more indicates whether more pages remain beyond the
        current one."

        Design: Corner/endpoints/list_courses_pagination_envelope
        """
        create_course(exam_type="SAT", format="LIVE", title="C1", list_price_cents=100000)
        create_course(exam_type="ACT", format="ONLINE", title="C2", list_price_cents=80000,
                      baseline_scale_max=36, guarantee_min_delta=3, required_practice_tests=2,
                      required_attendance_pct=0.6, materials_access_days=60)
        data, meta = validate_paginated(api.list_courses(ANON))
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

class TestComputedReads:
    def test_analytics_best_practice_score(self, api):
        """PRD §3.5: "its best_practice_score is recomputed as the maximum scaled_score over
        those completed practice attempts (null if there are none)."

        One scored PRACTICE 575/800 -> 1150; analytics reflects best 1150, count 1.

        Design: Corner/endpoints/enrollment_analytics_computed_read
        """
        base = setup_active_enrollment(fmt="SELF", student_email="an@x.com")
        enr_id = base["enrollment"]["id"]
        stu_id = base["student"]["id"]
        score_attempt(enr_id, base["instructor"]["id"], "PRACTICE", 575, 800, stu_id)
        data = validate_success(
            api.get_enrollment_analytics(enr_id, make_student_headers(stu_id)))
        assert data["best_practice_score"] == 1150
        assert data["completed_practice_count"] == 1


class TestOptimisticConcurrency:
    def test_stale_cohort_version_rejected(self, api):
        """PRD §2.6: "if the supplied value does not equal the target cohort's current
        version, the request is rejected with ERR_STALE_VERSION at HTTP status 412, and no
        seat is claimed or released."
        PRD §2.6: "a successful enrollment creation or cancellation advances the cohort's
        version by one".

        A enrolls (version advances); B enrolls carrying the pre-advance version -> rejected.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_cohort_version_rejected
        """
        base = setup_scheduled_cohort(exam_type="SAT", fmt="LIVE")
        student_a, enr_a = enroll_student(
            base["cohort"]["id"], expected_cohort_version=base["cohort_version"],
            email="occa@x.com")
        # After A's enroll the cohort version advanced; carry the stale pre-advance value.
        student_b = register_student(email="occb@x.com", full_name="OccB")
        resp = api.create_enrollment(
            {"student_id": student_b["id"], "cohort_id": base["cohort"]["id"],
             "expected_cohort_version": base["cohort_version"]},
            make_student_headers(student_b["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_correct_cohort_version_succeeds_and_advances(self, api):
        """PRD §2.6: "a successful enrollment creation or cancellation advances the cohort's
        version by one".
        PRD §3.3: "The enrollment's own status begins at PENDING_PAYMENT".

        Design: Corner/cross_cutting_complexity_layers/occ_correct_cohort_version_succeeds
        """
        base = setup_scheduled_cohort(exam_type="SAT", fmt="LIVE")
        student = register_student(email="occok@x.com", full_name="OccOk")
        data = validate_success(api.create_enrollment(
            {"student_id": student["id"], "cohort_id": base["cohort"]["id"],
             "expected_cohort_version": base["cohort_version"]},
            make_student_headers(student["id"])), expected_status=201)
        assert data["status"] == "PENDING_PAYMENT"
        cohort = validate_success(api.get_cohort(base["cohort"]["id"], REGISTRAR))
        assert cohort["version"] == base["cohort_version"] + 1
