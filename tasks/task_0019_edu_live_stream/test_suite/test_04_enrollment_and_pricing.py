"""Enrollment creation and the paid_amount_cents calculation (PRD §3.2, §3.6)."""

import math

import pytest

from test_helpers import (
    api_client,
    assert_enrollment,
    create_class_group,
    create_draft_course,
    create_enrollment_payload,
    create_instructor,
    create_published_course,
    create_student,
    delist_course,
    enroll_student,
    expected_paid_amount_cents,
    make_instructor_headers,
    make_student_headers,
    NON_EXISTENT_UUID,
    TEST_USERS,
    validate_error,
    validate_success,
    assign_enrollment_to_group,
    assign_enrollment_payload,
)


class TestEnrollmentCreation:
    """PRD §3.2: 'A Student may enrol in a PUBLISHED course; the request body
    carries the student_id of the enrolling student.'"""

    def test_enroll_in_published_course_succeeds(self, api):
        """PRD §3.2: 'A Student may enrol in a PUBLISHED course.'

        Initial state: payment_status=PAID, learning_status=ACTIVE
        (PRD §3.2: 'initialises both axes of the enrollment status —
        payment_status to PAID and learning_status to ACTIVE').
        """
        course, _, _ = create_published_course()
        student = create_student()
        res = api.create_enrollment(
            course["id"],
            create_enrollment_payload(student["id"]),
            make_student_headers(student["id"]),
        )
        enrollment = validate_success(res, expected_status=201)
        assert_enrollment(enrollment)
        assert enrollment["payment_status"] == "PAID"
        assert enrollment["learning_status"] == "ACTIVE"
        assert enrollment["course_id"] == course["id"]
        assert enrollment["student_id"] == student["id"]

    def test_enroll_in_draft_course_rejected(self, api):
        """PRD §3.2: 'If the parent course is not in PUBLISHED, the request
        fails with ERR_COURSE_NOT_PUBLISHED.'"""
        course, instructor = create_draft_course()
        student = create_student()
        res = api.create_enrollment(
            course["id"],
            create_enrollment_payload(student["id"]),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_COURSE_NOT_PUBLISHED")

    def test_enroll_in_frozen_course_rejected(self, api):
        """PRD §3.2: 'if the parent course is FROZEN, it fails with
        ERR_COURSE_FROZEN.'"""
        course, _, _ = create_published_course()
        delist_course(course)  # PUBLISHED → DELISTED, posture → FROZEN
        student = create_student()
        res = api.create_enrollment(
            course["id"],
            create_enrollment_payload(student["id"]),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_COURSE_FROZEN")

    def test_enroll_unknown_course_returns_404(self, api):
        """PRD §2.6: 'returns the not-found error of the first identifier that
        fails to resolve' — ERR_COURSE_NOT_FOUND."""
        student = create_student()
        res = api.create_enrollment(
            NON_EXISTENT_UUID,
            create_enrollment_payload(student["id"]),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_COURSE_NOT_FOUND")


class TestEnrollmentSideEffects:
    """PRD §3.2 side effects on POST /courses/{id}/enrollments."""

    def test_enrollment_records_enrolled_at(self, api):
        """PRD §3.2: 'records the moment of successful enrollment in
        enrolled_at as an ISO 8601 UTC timestamp.'"""
        course, _, _ = create_published_course()
        enrollment, _ = enroll_student(course)
        assert "enrolled_at" in enrollment and enrollment["enrolled_at"], \
            "enrolled_at must be present and non-empty"

    def test_enrollment_class_group_id_null_until_grouping(self, api):
        """PRD §3.2: 'leaves class_group_id null until grouping.'"""
        course, _, _ = create_published_course()
        enrollment, _ = enroll_student(course)
        assert enrollment.get("class_group_id") in (None, ""), \
            f"class_group_id must be null until grouping, got {enrollment.get('class_group_id')}"

    def test_enrollment_appends_audit_log(self, api):
        """PRD §3.2: 'appends an AuditLogEntry whose action is ENROLLMENT_CREATED.'"""
        course, _, _ = create_published_course()
        enrollment, _ = enroll_student(course)
        res = api.list_audit_logs(
            TEST_USERS["admin_headers"],
            params={"subject_type": "ENROLLMENT", "subject_id": enrollment["id"]},
        )
        from test_helpers import validate_paginated
        rows, _ = validate_paginated(res)
        actions = {r["action"] for r in rows}
        assert "ENROLLMENT_CREATED" in actions, \
            f"Expected ENROLLMENT_CREATED in audit log, got {actions}"


class TestPaidAmountCalculation:
    """PRD §3.6: 'paid_amount_cents = list_price_cents * (100 - effective_pct)
    / 100' with discount clamped to [0,80] and round-half-up to integer cents."""

    @pytest.mark.parametrize(
        "list_price_cents,discount_percent,expected_paid",
        [
            (10000, 0, 10000),     # no discount
            (10000, 15, 8500),     # plain percentage
            (10000, 80, 2000),     # exact 80% boundary
            (100000, 0, 100000),   # bigger price
            (100000, 50, 50000),   # half off
        ],
    )
    def test_paid_amount_within_valid_discount_range(
        self, api, list_price_cents, discount_percent, expected_paid
    ):
        """PRD §3.6: 'The raw cent amount is list_price_cents multiplied by
        (one hundred minus the effective percentage), divided by one hundred.
        The result is rounded half-up to the nearest integer cent and stored
        as the enrolment's paid_amount_cents.'"""
        course, _, _ = create_published_course(
            list_price_cents=list_price_cents,
            discount_percent=discount_percent,
        )
        enrollment, _ = enroll_student(course)
        assert enrollment["paid_amount_cents"] == expected_paid, (
            f"Expected paid={expected_paid} for list={list_price_cents}, "
            f"discount={discount_percent}, got {enrollment['paid_amount_cents']}"
        )

    def test_round_half_up_at_half_cent(self, api):
        """PRD §3.6 + §2.9: 'rounded half-up to the nearest integer cent.'

        With list_price_cents=11 and discount_percent=50: raw = 11*50/100 = 5.5
        which must round-half-up to 6.
        """
        course, _, _ = create_published_course(
            list_price_cents=11,
            discount_percent=50,
        )
        enrollment, _ = enroll_student(course)
        assert enrollment["paid_amount_cents"] == 6, (
            f"raw=5.5 must round-half-up to 6, got {enrollment['paid_amount_cents']}"
        )


class TestClassGroupCapacity:
    """PRD §3.2: 'An attempt to assign an enrollment into a class group whose
    enrolled_count already equals its capacity fails with
    ERR_CLASS_GROUP_FULL.'"""

    def test_assign_enrollment_to_full_group_rejected(self, api):
        """PRD §3.2: 'An attempt to assign an enrollment into a class group
        whose enrolled_count already equals its capacity fails with
        ERR_CLASS_GROUP_FULL.'"""
        course, instructor, _ = create_published_course()
        group = create_class_group(course, instructor, capacity=1)
        enrollment_a, _ = enroll_student(course)
        enrollment_b, _ = enroll_student(course)
        # Fill the group
        assign_enrollment_to_group(group, enrollment_a, instructor)
        # Second enrollment must be rejected
        res = api.assign_enrollment_to_group(
            group["id"],
            assign_enrollment_payload(enrollment_b["id"]),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_CLASS_GROUP_FULL")

    def test_assign_to_group_appends_audit_log(self, api):
        """PRD §3.2: 'appends an AuditLogEntry whose action is
        ENROLLMENT_GROUPED.'"""
        course, instructor, _ = create_published_course()
        group = create_class_group(course, instructor, capacity=10)
        enrollment, _ = enroll_student(course)
        assign_enrollment_to_group(group, enrollment, instructor)
        res = api.list_audit_logs(
            TEST_USERS["admin_headers"],
            params={"subject_type": "ENROLLMENT", "subject_id": enrollment["id"]},
        )
        from test_helpers import validate_paginated
        rows, _ = validate_paginated(res)
        actions = {r["action"] for r in rows}
        assert "ENROLLMENT_GROUPED" in actions, \
            f"Expected ENROLLMENT_GROUPED in audit log, got {actions}"
