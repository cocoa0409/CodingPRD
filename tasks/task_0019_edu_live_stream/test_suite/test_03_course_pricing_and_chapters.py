"""Course pricing validation and chapter aggregates (PRD §3.1)."""

import pytest

from test_helpers import (
    add_chapter,
    api_client,
    create_chapter_payload,
    create_course_payload,
    create_draft_course,
    create_instructor,
    make_instructor_headers,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPricingValidation:
    """PRD §3.1: 'The price must be at least zero and the discount, if supplied,
    must lie between zero and eighty inclusive; values outside that range cause
    ERR_INVALID_PRICING.'"""

    def test_negative_list_price_rejected(self, api):
        """PRD §3.1: 'The price must be at least zero ... values outside that
        range cause ERR_INVALID_PRICING.'"""
        instructor = create_instructor()
        payload = create_course_payload(instructor["id"], list_price_cents=-1)
        res = api.create_course(payload, make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_INVALID_PRICING")

    def test_discount_above_80_rejected(self, api):
        """PRD §3.1: 'the discount, if supplied, must lie between zero and
        eighty inclusive; values outside that range cause ERR_INVALID_PRICING.'"""
        instructor = create_instructor()
        payload = create_course_payload(instructor["id"], discount_percent=81)
        res = api.create_course(payload, make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_INVALID_PRICING")

    def test_discount_below_zero_rejected(self, api):
        """PRD §3.1: 'the discount, if supplied, must lie between zero and
        eighty inclusive; values outside that range cause ERR_INVALID_PRICING.'"""
        instructor = create_instructor()
        payload = create_course_payload(instructor["id"], discount_percent=-1)
        res = api.create_course(payload, make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_INVALID_PRICING")

    def test_discount_exactly_80_accepted(self, api):
        """PRD §3.1: 'the discount, if supplied, must lie between zero and
        eighty inclusive.' Exact-boundary 80 is inside the inclusive range."""
        instructor = create_instructor()
        payload = create_course_payload(instructor["id"], discount_percent=80)
        res = api.create_course(payload, make_instructor_headers(instructor["id"]))
        validate_success(res, expected_status=201)

    def test_zero_list_price_accepted(self, api):
        """PRD §3.1: 'The price must be at least zero.' Zero is inclusive."""
        instructor = create_instructor()
        payload = create_course_payload(instructor["id"], list_price_cents=0)
        res = api.create_course(payload, make_instructor_headers(instructor["id"]))
        validate_success(res, expected_status=201)


class TestChapterCreation:
    """PRD §3.1: 'Each chapter is created with a title, a one-based ordinal
    whose value must be unique within its parent course (recorded internally as
    course_id), an authoritative video_duration_seconds length that must be
    strictly greater than zero, and an optional required_for_completion flag
    that defaults to true.'"""

    def test_chapter_default_required_for_completion_is_true(self, api):
        """PRD §3.1: 'an optional required_for_completion flag that defaults to
        true.' Omitting the field must produce true."""
        course, instructor = create_draft_course()
        payload = create_chapter_payload(ordinal=1, video_duration_seconds=1000)
        del payload["required_for_completion"]
        res = api.create_chapter(course["id"], payload, make_instructor_headers(instructor["id"]))
        ch = validate_success(res, expected_status=201)
        assert ch["required_for_completion"] is True

    def test_chapter_aggregates_total_video_seconds(self, api):
        """PRD §3.1: 'The total_chapters and total_video_seconds aggregates on
        the parent course are computed automatically from the chapter set.'"""
        course, instructor = create_draft_course()
        add_chapter(course, instructor, ordinal=1, video_duration_seconds=400)
        add_chapter(course, instructor, ordinal=2, video_duration_seconds=600)
        get_res = api.get_course(course["id"], make_instructor_headers(instructor["id"]))
        c = validate_success(get_res, expected_status=200)
        assert c["total_chapters"] == 2
        assert c["total_video_seconds"] == 1000


class TestPatchCourse:
    """PRD §3.1: 'While a course is in DRAFT (or, after a rejection, back in
    DRAFT) the owning instructor may freely modify the title, list_price_cents,
    and discount_percent.'"""

    def test_patch_pricing_in_draft_succeeds(self, api):
        """PRD §3.1: 'the owning instructor may freely modify the title,
        list_price_cents, and discount_percent' while DRAFT."""
        course, instructor = create_draft_course(list_price_cents=10000)
        res = api.patch_course(
            course["id"],
            {"list_price_cents": 20000},
            make_instructor_headers(instructor["id"]),
        )
        updated = validate_success(res, expected_status=200)
        assert updated["list_price_cents"] == 20000

    def test_patch_invalid_pricing_rejected(self, api):
        """PRD §2.8 priority 16: 'refund pricing inputs ... ERR_INVALID_PRICING.'
        The same pricing constraint named in PRD §3.1 (discount in [0,80])
        applies on PATCH /courses/{id}."""
        course, instructor = create_draft_course()
        res = api.patch_course(
            course["id"],
            {"discount_percent": 95},
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_INVALID_PRICING")
