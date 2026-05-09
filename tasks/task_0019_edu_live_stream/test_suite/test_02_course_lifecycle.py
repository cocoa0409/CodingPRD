"""Course publishing lifecycle: DRAFT → UNDER_REVIEW → {PUBLISHED | REJECTED} → DRAFT.

Covers the branching state machine and the revert leg (PRD §3.1).
"""

import pytest

from test_helpers import (
    add_chapter,
    api_client,
    approve_course,
    assert_course,
    create_draft_course,
    create_instructor,
    create_published_course,
    delist_course,
    make_admin_headers,
    make_instructor_headers,
    NON_EXISTENT_UUID,
    reject_course,
    return_course_to_draft,
    submit_course_for_review,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestCourseInitialState:
    """PRD §3.1: 'The newly created course lands in status = DRAFT with
    posture = RESTRICTED.'"""

    def test_create_course_starts_in_draft_restricted(self, api):
        """PRD §3.1: 'The newly created course lands in status = DRAFT with
        posture = RESTRICTED.'"""
        course, instructor = create_draft_course()
        assert_course(course)
        assert course["status"] == "DRAFT"
        assert course["posture"] == "RESTRICTED"
        assert course["instructor_id"] == instructor["id"]


class TestSubmitForReview:
    """PRD §3.1: 'Submitting requires that the caller is the course owner
    (ERR_FORBIDDEN_NOT_OWNER), that at least one chapter exists with
    required_for_completion set to true (ERR_COURSE_NO_CHAPTERS), and that the
    pricing fields are within their valid ranges (ERR_INVALID_PRICING).'"""

    def test_submit_no_chapters_rejected(self, api):
        """PRD §3.1: 'Submitting requires ... that at least one chapter exists
        with required_for_completion set to true (ERR_COURSE_NO_CHAPTERS).'"""
        course, instructor = create_draft_course()
        res = api.submit_course_for_review(
            course["id"], make_instructor_headers(instructor["id"])
        )
        validate_error(res, "ERR_COURSE_NO_CHAPTERS")

    def test_submit_only_optional_chapters_rejected(self, api):
        """PRD §3.1: 'Submitting requires ... that at least one chapter exists
        with required_for_completion set to true (ERR_COURSE_NO_CHAPTERS).'

        A chapter with required_for_completion=false does not count toward the
        minimum-one-required check.
        """
        course, instructor = create_draft_course()
        add_chapter(course, instructor, ordinal=1, required_for_completion=False)
        res = api.submit_course_for_review(
            course["id"], make_instructor_headers(instructor["id"])
        )
        validate_error(res, "ERR_COURSE_NO_CHAPTERS")

    def test_submit_advances_to_under_review(self, api):
        """PRD §3.1: 'Once the syllabus is satisfactory, the instructor submits
        the course for academic review, transitioning status from DRAFT to
        UNDER_REVIEW.'"""
        course, instructor = create_draft_course()
        add_chapter(course, instructor, ordinal=1, required_for_completion=True)
        res = api.submit_course_for_review(
            course["id"], make_instructor_headers(instructor["id"])
        )
        updated = validate_success(res, expected_status=200)
        assert updated["status"] == "UNDER_REVIEW"

    def test_submit_writes_syllabus_revision_one(self, api):
        """PRD §3.1: 'The submission also writes a fresh SyllabusRevision row
        whose revision_number is the current maximum for this course plus one
        — the very first revision is therefore numbered one — and whose outline
        array, pricing_snapshot_cents, and discount_snapshot_percent are
        captured at the moment of submission.'"""
        course, instructor = create_draft_course(list_price_cents=50000, discount_percent=10)
        add_chapter(course, instructor, ordinal=1, required_for_completion=True)
        submit_course_for_review(course, instructor)
        list_res = api.list_syllabus_revisions(
            course["id"], make_instructor_headers(instructor["id"])
        )
        from test_helpers import validate_paginated
        revs, _ = validate_paginated(list_res)
        assert len(revs) == 1, f"Expected exactly 1 revision after first submit, got {len(revs)}"
        rev = revs[0]
        assert rev["revision_number"] == 1
        assert rev["pricing_snapshot_cents"] == 50000
        assert rev["discount_snapshot_percent"] == 10


class TestApproveAndPublishedSyllabusPin:
    """PRD §3.1: 'Approval transitions the course from UNDER_REVIEW to
    PUBLISHED ... On approval, the system pins the latest SyllabusRevision's id
    onto the course's published_syllabus_revision_id field.'"""

    def test_approve_advances_to_published(self, api):
        """PRD §3.1: 'Approval transitions the course from UNDER_REVIEW to
        PUBLISHED.'"""
        course, instructor = create_draft_course()
        add_chapter(course, instructor)
        submit_course_for_review(course, instructor)
        res = api.approve_course(course["id"], TEST_USERS["admin_headers"])
        approved = validate_success(res, expected_status=200)
        assert approved["status"] == "PUBLISHED"

    def test_approve_pins_latest_syllabus_revision(self, api):
        """PRD §3.1: 'On approval, the system pins the latest SyllabusRevision's
        id onto the course's published_syllabus_revision_id field — this is the
        version-pinning step.'"""
        course, instructor = create_draft_course()
        add_chapter(course, instructor)
        submit_course_for_review(course, instructor)
        approved = approve_course(course)
        list_res = api.list_syllabus_revisions(
            course["id"], make_instructor_headers(instructor["id"])
        )
        from test_helpers import validate_paginated
        revs, _ = validate_paginated(list_res)
        latest = max(revs, key=lambda r: r["revision_number"])
        assert approved["published_syllabus_revision_id"] == latest["id"]

    def test_approve_recomputes_posture_to_open(self, api):
        """PRD §3.1: 'Approval moves posture to OPEN.'"""
        course, instructor = create_draft_course()
        add_chapter(course, instructor)
        submit_course_for_review(course, instructor)
        approved = approve_course(course)
        assert approved["posture"] == "OPEN"

    def test_approve_on_draft_rejected(self, api):
        """PRD §3.1: 'Approval ... is rejected with ERR_COURSE_NOT_UNDER_REVIEW
        if the course is in any other status.'"""
        course, instructor = create_draft_course()
        res = api.approve_course(course["id"], TEST_USERS["admin_headers"])
        validate_error(res, "ERR_COURSE_NOT_UNDER_REVIEW")

    def test_approve_already_published_rejected(self, api):
        """PRD §3.1: 'Approval ... is rejected with ERR_COURSE_NOT_UNDER_REVIEW
        if the course is in any other status.'"""
        course, instructor, _ = create_published_course()
        res = api.approve_course(course["id"], TEST_USERS["admin_headers"])
        validate_error(res, "ERR_COURSE_NOT_UNDER_REVIEW")


class TestRejectAndReturnToDraft:
    """PRD §3.1: 'Rejection by an AcademicAdmin instead transitions
    UNDER_REVIEW to REJECTED ... From REJECTED, the owning instructor can
    return the course to DRAFT.'"""

    def test_reject_advances_to_rejected(self, api):
        """PRD §3.1: 'Rejection by an AcademicAdmin instead transitions
        UNDER_REVIEW to REJECTED.'"""
        course, instructor = create_draft_course()
        add_chapter(course, instructor)
        submit_course_for_review(course, instructor)
        rejected = validate_success(
            api.reject_course(course["id"], TEST_USERS["admin_headers"]),
            expected_status=200,
        )
        assert rejected["status"] == "REJECTED"

    def test_reject_on_draft_rejected(self, api):
        """PRD §3.1: 'the same ERR_COURSE_NOT_UNDER_REVIEW guards the source
        state' for reject."""
        course, instructor = create_draft_course()
        res = api.reject_course(course["id"], TEST_USERS["admin_headers"])
        validate_error(res, "ERR_COURSE_NOT_UNDER_REVIEW")

    def test_return_to_draft_from_rejected(self, api):
        """PRD §3.1: 'From REJECTED, the owning instructor can return the
        course to DRAFT.'"""
        course, instructor = create_draft_course()
        add_chapter(course, instructor)
        submit_course_for_review(course, instructor)
        reject_course(course)
        res = api.return_course_to_draft(
            course["id"], make_instructor_headers(instructor["id"])
        )
        returned = validate_success(res, expected_status=200)
        assert returned["status"] == "DRAFT"

    def test_return_to_draft_from_draft_rejected(self, api):
        """PRD §3.1: '... rejected with ERR_COURSE_NOT_REJECTED if the course
        is not in REJECTED.'"""
        course, instructor = create_draft_course()
        res = api.return_course_to_draft(
            course["id"], make_instructor_headers(instructor["id"])
        )
        validate_error(res, "ERR_COURSE_NOT_REJECTED")

    def test_return_to_draft_non_owner_rejected(self, api):
        """PRD §3.1: 'rejected with ERR_FORBIDDEN_NOT_OWNER if the caller is
        not the owner' for return-to-draft.

        PRD §2.8 priority order: ownership (4) is checked before state (5),
        so ownership error fires regardless of state.
        """
        course, instructor = create_draft_course()
        add_chapter(course, instructor)
        submit_course_for_review(course, instructor)
        reject_course(course)
        other = create_instructor()
        res = api.return_course_to_draft(
            course["id"], make_instructor_headers(other["id"])
        )
        validate_error(res, "ERR_FORBIDDEN_NOT_OWNER")


class TestDelistAndPosture:
    """PRD §3.1 delist tests focused on the source-state guard. Cascade
    semantics live in test_10_cascades_and_invariants.py."""

    def test_delist_published_advances_to_delisted(self, api):
        """PRD §3.1: 'A delist transitions status to the terminal DELISTED.'"""
        course, instructor, _ = create_published_course()
        res = api.delist_course(course["id"], TEST_USERS["admin_headers"])
        delisted = validate_success(res, expected_status=200)
        assert delisted["status"] == "DELISTED"

    def test_delist_recomputes_posture_to_frozen(self, api):
        """PRD §3.1: 'the course's posture is recomputed to FROZEN.'"""
        course, instructor, _ = create_published_course()
        res = api.delist_course(course["id"], TEST_USERS["admin_headers"])
        delisted = validate_success(res, expected_status=200)
        assert delisted["posture"] == "FROZEN"

    def test_delist_on_draft_rejected(self, api):
        """PRD §3.1: 'An AcademicAdmin may delist only a course whose status is
        PUBLISHED; otherwise the request fails with ERR_COURSE_NOT_PUBLISHED.'"""
        course, instructor = create_draft_course()
        res = api.delist_course(course["id"], TEST_USERS["admin_headers"])
        validate_error(res, "ERR_COURSE_NOT_PUBLISHED")


class TestPathResolution404s:
    """PRD §2.6: 'When a request targets a nested resource, the server validates
    each identifier in left-to-right order and returns the not-found error of
    the first identifier that fails to resolve.'"""

    def test_get_unknown_course_returns_404(self, api):
        """PRD §2.6 names ERR_COURSE_NOT_FOUND in the 404 list."""
        res = api.get_course(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
        validate_error(res, "ERR_COURSE_NOT_FOUND")

    def test_approve_unknown_course_returns_404(self, api):
        """PRD §2.6: 'returns the not-found error of the first identifier that
        fails to resolve.'"""
        res = api.approve_course(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
        validate_error(res, "ERR_COURSE_NOT_FOUND")
