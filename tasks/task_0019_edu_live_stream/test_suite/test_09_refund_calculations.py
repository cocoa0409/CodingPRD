"""Refund flow: provisional calculation at request, final calculation at approval (PRD §3.7)."""

import pytest

from test_helpers import (
    advance_clock,
    advance_clock_days,
    api_client,
    approve_refund_request,
    assert_refund_request,
    create_published_course,
    create_refund_request_payload,
    enroll_student,
    file_refund_request,
    log_watch_session,
    make_student_headers,
    NON_EXISTENT_UUID,
    reject_refund_request_payload,
    setup_enrollment_for_refund,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRefundIdempotency:
    """PRD §3.7: 'The system serialises concurrent refund requests on the
    same enrolment so that at most one non-terminal RefundRequest exists at a
    time; the second-arriving request sees ERR_REFUND_ALREADY_REQUESTED.'"""

    def test_second_pending_request_rejected(self, api):
        """PRD §3.7: 'at most one non-terminal RefundRequest exists at a time;
        the second-arriving request sees ERR_REFUND_ALREADY_REQUESTED.'"""
        course, _, _ = create_published_course()
        enrollment, student = enroll_student(course)
        file_refund_request(enrollment, student)
        res = api.create_refund_request(
            enrollment["id"],
            create_refund_request_payload(),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_REFUND_ALREADY_REQUESTED")


class TestRefundCreationSideEffects:
    """PRD §3.7: 'flips the enrolment's payment_status from PAID to
    REFUND_PENDING, and appends an AuditLogEntry whose action is
    REFUND_REQUESTED.'"""

    def test_refund_creation_flips_payment_status(self, api):
        """PRD §3.7: 'flips the enrolment's payment_status from PAID to
        REFUND_PENDING.'"""
        course, _, _ = create_published_course()
        enrollment, student = enroll_student(course)
        file_refund_request(enrollment, student)
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["payment_status"] == "REFUND_PENDING"

    def test_refund_creation_appends_audit_log(self, api):
        """PRD §3.7: 'appends an AuditLogEntry whose action is
        REFUND_REQUESTED.'"""
        course, _, _ = create_published_course()
        enrollment, student = enroll_student(course)
        refund = file_refund_request(enrollment, student)
        rows, _ = validate_paginated(api.list_audit_logs(
            TEST_USERS["admin_headers"],
            params={"subject_type": "REFUND_REQUEST", "subject_id": refund["id"]},
        ))
        assert any(r["action"] == "REFUND_REQUESTED" for r in rows), (
            f"Expected REFUND_REQUESTED audit row, got actions={[r['action'] for r in rows]}"
        )


class TestProvisionalRefundTiers:
    """PRD §3.7: 'If days_elapsed is at most seven and progress is at most five
    percent, the ratio is one (full refund). Otherwise, if days_elapsed is at
    most thirty and progress is at most thirty percent, the ratio is zero point
    seven. Otherwise, if progress is at most sixty percent, the ratio is zero
    point three. Otherwise, the ratio is zero.'"""

    def test_full_refund_at_day_7_progress_5(self, api):
        """PRD §3.7: 'days_elapsed is at most seven and progress is at most
        five percent, the ratio is one (full refund).'

        Tier-1 boundary: days==7 (inclusive), progress==5.0 (inclusive).
        With paid=100000, kits=0, attended=0 → provisional_amount_cents=100000.
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_for_refund(
            list_price_cents=100000,
            days_after_enroll=7,
            target_progress_percent=5.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        refund = file_refund_request(enrollment, student, materials_kit_count=0)
        assert_refund_request(refund)
        assert refund["provisional_amount_cents"] == 100000, (
            f"Tier-1 full refund should be 100000; got {refund['provisional_amount_cents']}"
        )

    def test_mid_refund_at_progress_5_point_1(self, api):
        """PRD §3.7: 'if days_elapsed is at most thirty and progress is at most
        thirty percent, the ratio is zero point seven.'

        progress=5.1 fails tier-1's progress<=5.0 but passes tier-2's
        progress<=30.0; with days=7, paid=100000, expected provisional =
        round_half_up(100000 * 0.7) = 70000.
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_for_refund(
            list_price_cents=100000,
            days_after_enroll=7,
            target_progress_percent=5.1,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        refund = file_refund_request(enrollment, student, materials_kit_count=0)
        assert refund["provisional_amount_cents"] == 70000, (
            f"Tier-2 ratio 0.7 of 100000 should be 70000; got {refund['provisional_amount_cents']}"
        )

    def test_mid_refund_at_day_8_progress_5(self, api):
        """PRD §3.7: tier-2 boundary on the days axis. days=8 fails tier-1's
        days<=7 but passes tier-2's days<=30 with progress=5.0<=30.0.

        Expected provisional = 70000.
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_for_refund(
            list_price_cents=100000,
            days_after_enroll=8,
            target_progress_percent=5.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        refund = file_refund_request(enrollment, student, materials_kit_count=0)
        assert refund["provisional_amount_cents"] == 70000, (
            f"Tier-2 at day=8 should be 70000; got {refund['provisional_amount_cents']}"
        )

    def test_late_refund_at_progress_60(self, api):
        """PRD §3.7: 'if progress is at most sixty percent, the ratio is zero
        point three.' progress=60.0 inclusive."""
        course, instructor, student, enrollment, chapters = setup_enrollment_for_refund(
            list_price_cents=100000,
            days_after_enroll=31,
            target_progress_percent=60.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        refund = file_refund_request(enrollment, student, materials_kit_count=0)
        assert refund["provisional_amount_cents"] == 30000, (
            f"Tier-3 ratio 0.3 of 100000 should be 30000; got {refund['provisional_amount_cents']}"
        )

    def test_no_refund_above_progress_60(self, api):
        """PRD §3.7: 'Otherwise, the ratio is zero.' progress=60.1 fails all
        tiers."""
        course, instructor, student, enrollment, chapters = setup_enrollment_for_refund(
            list_price_cents=100000,
            days_after_enroll=31,
            target_progress_percent=60.1,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        refund = file_refund_request(enrollment, student, materials_kit_count=0)
        assert refund["provisional_amount_cents"] == 0, (
            f"Above-tier-3 progress should yield 0; got {refund['provisional_amount_cents']}"
        )


class TestRefundDeductions:
    """PRD §3.7: 'The materials deduction is kits multiplied by five thousand
    cents — that is, fifty dollars per kit. The services deduction is
    attended_count multiplied by one thousand five hundred cents — that is,
    fifteen dollars per attended live class. The provisional amount is the
    gross minus both deductions, with a floor of zero.'"""

    def test_kit_deduction_applies(self, api):
        """PRD §3.7: 'The materials deduction is kits multiplied by five
        thousand cents.'

        Tier-1 full refund of 100000 minus one $50 kit = 95000.
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_for_refund(
            list_price_cents=100000,
            days_after_enroll=0,
            target_progress_percent=0.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        refund = file_refund_request(enrollment, student, materials_kit_count=1)
        assert refund["provisional_amount_cents"] == 95000, (
            f"Tier-1 full refund - 1 kit = 95000; got {refund['provisional_amount_cents']}"
        )

    def test_floor_at_zero(self, api):
        """PRD §3.7: 'with a floor of zero (the system never produces a
        negative refund).'

        Above-tier-3 (ratio 0) gross is 0; any deduction must NOT make
        provisional negative.
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_for_refund(
            list_price_cents=100000,
            days_after_enroll=31,
            target_progress_percent=70.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        refund = file_refund_request(enrollment, student, materials_kit_count=5)
        assert refund["provisional_amount_cents"] == 0, (
            f"Provisional must floor at 0; got {refund['provisional_amount_cents']}"
        )


class TestRefundApprovalAndCascade:
    """PRD §3.7: 'On approval, the system runs the final refund calculation ...
    The result is written to final_amount_cents, and the enrolment's
    refund_amount_cents is set to that same value. The enrolment's
    payment_status flips from REFUND_PENDING to REFUNDED, the enrolment's
    learning_status flips to WITHDRAWN ... an AuditLogEntry whose action is
    REFUND_APPROVED is appended.'"""

    def test_approve_writes_final_amount_and_cascades(self, api):
        """PRD §3.7: 'The result is written to final_amount_cents, and the
        enrolment's refund_amount_cents is set to that same value. The
        enrolment's payment_status flips from REFUND_PENDING to REFUNDED, the
        enrolment's learning_status flips to WITHDRAWN.'"""
        course, instructor, student, enrollment, _ = setup_enrollment_for_refund(
            list_price_cents=100000,
            days_after_enroll=0,
            target_progress_percent=0.0,
        )
        refund = file_refund_request(enrollment, student, materials_kit_count=0)
        approved = approve_refund_request(refund)
        assert approved["status"] == "APPROVED"
        assert isinstance(approved.get("final_amount_cents"), int)
        # Enrollment cascade
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["payment_status"] == "REFUNDED"
        assert e["learning_status"] == "WITHDRAWN"
        assert e["refund_amount_cents"] == approved["final_amount_cents"]

    def test_approve_appends_refund_approved_audit(self, api):
        """PRD §3.7: 'an AuditLogEntry whose action is REFUND_APPROVED is
        appended.'"""
        course, instructor, student, enrollment, _ = setup_enrollment_for_refund()
        refund = file_refund_request(enrollment, student)
        approve_refund_request(refund)
        rows, _ = validate_paginated(api.list_audit_logs(
            TEST_USERS["admin_headers"],
            params={"subject_type": "REFUND_REQUEST", "subject_id": refund["id"]},
        ))
        assert any(r["action"] == "REFUND_APPROVED" for r in rows)

    def test_approve_not_pending_rejected(self, api):
        """PRD §3.7: 'Approval requires the request to still be PENDING
        (ERR_REFUND_NOT_PENDING).'"""
        course, instructor, student, enrollment, _ = setup_enrollment_for_refund()
        refund = file_refund_request(enrollment, student)
        approve_refund_request(refund)  # Now APPROVED
        res = api.approve_refund_request(refund["id"], TEST_USERS["admin_headers"])
        validate_error(res, "ERR_REFUND_NOT_PENDING")


class TestRefundReject:
    """PRD §3.7: 'Rejection by an AcademicAdmin instead transitions the request
    to REJECTED. Rejection requires the request to still be PENDING
    (ERR_REFUND_NOT_PENDING) and the body to carry a non-empty
    rejection_reason (ERR_REFUND_REJECTION_REASON_REQUIRED). The enrolment's
    payment_status reverts from REFUND_PENDING back to PAID.'"""

    def test_reject_requires_reason(self, api):
        """PRD §3.7: 'the body to carry a non-empty rejection_reason
        (ERR_REFUND_REJECTION_REASON_REQUIRED).'"""
        course, instructor, student, enrollment, _ = setup_enrollment_for_refund()
        refund = file_refund_request(enrollment, student)
        res = api.reject_refund_request(
            refund["id"],
            {"rejection_reason": ""},
            TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_REFUND_REJECTION_REASON_REQUIRED")

    def test_reject_reverts_payment_status_to_paid(self, api):
        """PRD §3.7: 'The enrolment's payment_status reverts from
        REFUND_PENDING back to PAID.'"""
        course, instructor, student, enrollment, _ = setup_enrollment_for_refund()
        refund = file_refund_request(enrollment, student)
        validate_success(api.reject_refund_request(
            refund["id"],
            reject_refund_request_payload("ineligible"),
            TEST_USERS["admin_headers"],
        ), expected_status=200)
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["payment_status"] == "PAID"
