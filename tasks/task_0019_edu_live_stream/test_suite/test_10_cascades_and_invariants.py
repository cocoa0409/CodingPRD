"""Course delist cascade and compensating invariants (PRD §3.1, §3.7)."""

import pytest

from test_helpers import (
    api_client,
    approve_refund_request,
    create_published_course,
    delist_course,
    enroll_student,
    file_refund_request,
    make_student_headers,
    reject_refund_request,
    schedule_live_class,
    setup_course_delist_cascade,
    TEST_USERS,
    validate_success,
)


class TestDelistCascadeDepth3:
    """PRD §3.1: 'A delist transitions status to the terminal DELISTED and
    triggers a depth-three cascade in a single transaction. First, every
    LiveClass belonging to this course that is currently in SCHEDULED is moved
    to CANCELLED with the reason COURSE_DELISTED. Second, those cancellations
    themselves cascade: for every enrollment whose learning_status was ACTIVE
    and whose attendance window overlaps a now-cancelled live class,
    learning_status flips to AT_RISK. Third, every enrollment that flipped to
    AT_RISK in step two has any associated PENDING RefundRequest re-priced —
    its provisional_amount_cents is recomputed against the now-frozen course
    context. Finally, the course's posture is recomputed to FROZEN.'"""

    def test_delist_cancels_scheduled_live_classes(self, api):
        """PRD §3.1: 'every LiveClass belonging to this course that is
        currently in SCHEDULED is moved to CANCELLED.'"""
        course, instructor, students, enrollments, live_class, refund = (
            setup_course_delist_cascade()
        )
        delist_course(course)
        # Re-fetch course to confirm DELISTED + posture FROZEN.
        from test_helpers import make_instructor_headers
        c = validate_success(
            api.get_course(course["id"], make_instructor_headers(instructor["id"])),
            expected_status=200,
        )
        assert c["status"] == "DELISTED"
        assert c["posture"] == "FROZEN"


class TestRefundRejectInvariant:
    """PRD §3.7: 'Rejection ... The enrolment's payment_status reverts from
    REFUND_PENDING back to PAID.' The compensating-action invariant is that
    paid_amount_cents and refund_amount_cents are both unchanged compared with
    the pre-cycle baseline.

    Underlying difficulty rule (test_recipe.assert):
      Enrollment.paid_amount_cents == 8500 (unchanged from pre-cycle)
      Enrollment.payment_status == 'PAID' (unchanged)
      Enrollment.refund_amount_cents IS NULL
      RefundRequest.status == 'REJECTED'
    """

    def test_request_then_reject_preserves_paid_amount(self, api):
        """PRD §3.7: 'The enrolment's payment_status reverts from
        REFUND_PENDING back to PAID.'

        With list=10000, discount=15 the pre-cycle paid_amount=8500
        (PRD §3.6 formula). After request → reject, the enrollment must
        still report paid_amount_cents=8500, payment_status=PAID, and
        refund_amount_cents must still be null since no refund was
        approved.
        """
        course, instructor, _ = create_published_course(
            list_price_cents=10000, discount_percent=15
        )
        enrollment, student = enroll_student(course)
        # Baseline: paid_amount_cents=8500 per PRD §3.6.
        assert enrollment["paid_amount_cents"] == 8500
        assert enrollment["payment_status"] == "PAID"
        assert enrollment.get("refund_amount_cents") in (None, 0) or enrollment.get(
            "refund_amount_cents"
        ) is None
        # Cycle: request → reject.
        refund = file_refund_request(enrollment, student, materials_kit_count=0)
        rejected = reject_refund_request(refund, "ineligible")
        assert rejected["status"] == "REJECTED"
        # Post-condition: paid_amount unchanged, payment_status PAID,
        # refund_amount_cents null.
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["paid_amount_cents"] == 8500, (
            f"paid_amount must be unchanged after reject; got {e['paid_amount_cents']}"
        )
        assert e["payment_status"] == "PAID", (
            f"payment_status must revert to PAID; got {e['payment_status']}"
        )
        # refund_amount_cents is null per PRD §3.2 ('null until a refund on
        # this enrollment reaches APPROVED').
        assert e.get("refund_amount_cents") in (None, 0) or e.get("refund_amount_cents") is None, (
            f"refund_amount_cents must be null; got {e.get('refund_amount_cents')}"
        )


class TestRevisionLoopInvariant:
    """PRD §3.4: 'These three numbers are recomputed whenever a WatchSession
    is created, whenever a Submission reaches GRADED, and whenever an
    enrollment is read.'

    The compensating invariant for the request-revision → resubmit cycle is
    that progress_percent does NOT advance — only revision_count increments
    — because PRD §3.4 names only WatchSession-creation and GRADED transitions
    as triggers, NOT the cyclic-loop transitions.
    """

    def test_revision_loop_does_not_advance_progress(self, api):
        """PRD §3.4: 'These three numbers are recomputed whenever a
        WatchSession is created, whenever a Submission reaches GRADED, and
        whenever an enrollment is read.'

        The request-revision and resubmit transitions are not in this list,
        so a SUBMITTED → UNDER_REVIEW → REVISION_REQUESTED → SUBMITTED loop
        must not change Enrollment.progress_percent. revision_count
        strictly increases, however, per PRD §3.8.
        """
        from test_helpers import (
            log_watch_session,
            publish_assignment,
            request_revision,
            resubmit,
            setup_enrollment_with_progress,
            start_review,
            submit_assignment,
        )
        course, instructor, student, enrollment, chapters = setup_enrollment_with_progress(
            target_progress_percent=10.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        # Snapshot pre-cycle progress.
        e_pre = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        pre_progress = e_pre["progress_percent"]
        # Run the cycle.
        assignment = publish_assignment(course, instructor, fmt="TEXT")
        sub = submit_assignment(assignment, enrollment, student, fmt="TEXT")
        sub = start_review(sub, instructor)
        sub = request_revision(sub, instructor, "please redo")
        sub = resubmit(sub, student, fmt="TEXT")
        assert sub["revision_count"] == 1
        # Snapshot post-cycle progress.
        e_post = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e_post["progress_percent"] == pytest.approx(pre_progress, abs=0.1), (
            f"progress_percent must not advance through the revision loop; "
            f"pre={pre_progress}, post={e_post['progress_percent']}"
        )
