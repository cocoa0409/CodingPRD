"""Watch sessions, dual progress variants, and the at-risk evaluation (PRD §3.4, §3.5)."""

import pytest

from test_helpers import (
    advance_clock,
    advance_clock_days,
    api_client,
    create_published_course,
    enroll_student,
    log_watch_session,
    make_student_headers,
    setup_enrollment_with_progress,
    sweep_at_risk,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestDualProgressVariantsAgreeAtBoundaries:
    """PRD §3.4 progress numbers are recomputed on every watch session and read."""

    def test_no_watch_session_yields_zero_progress(self, api):
        """PRD §3.4: 'If the required-chapter set is empty,
        chapter_completion_percent is zero. Otherwise it is one hundred
        multiplied by the number of completed required chapters, divided by
        the total number of required chapters.'

        With chapters but no watch sessions, both numerators are zero so both
        variants are 0.0.
        """
        course, instructor, student, enrollment, _ = setup_enrollment_with_progress(
            target_progress_percent=0.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["chapter_completion_percent"] == pytest.approx(0.0, abs=0.01)
        assert e["watch_duration_percent"] == pytest.approx(0.0, abs=0.01)
        assert e["progress_percent"] == pytest.approx(0.0, abs=0.01)

    def test_full_completion_yields_100(self, api):
        """PRD §3.4: completing both required chapters gives chapter and
        watch percentages both equal to 100.0."""
        course, instructor, student, enrollment, chapters = setup_enrollment_with_progress(
            target_progress_percent=0.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        # Watch each chapter to its full duration.
        log_watch_session(enrollment, student, chapters[0]["id"], 1000)
        log_watch_session(enrollment, student, chapters[1]["id"], 1000)
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["chapter_completion_percent"] == pytest.approx(100.0, abs=0.05)
        assert e["watch_duration_percent"] == pytest.approx(100.0, abs=0.05)
        assert e["progress_percent"] == pytest.approx(100.0, abs=0.05)


class TestProgressTieBreak:
    """PRD §3.4: 'The single combined progress_percent exposed on the
    enrollment is the larger of the two; ties resolve to
    chapter_completion_percent.'"""

    def test_max_picks_watch_when_higher(self, api):
        """PRD §3.4: 'progress_percent ... is the larger of the two.'

        Watching half of one of two required chapters: chapter_completion=0
        (neither chapter complete), watch_duration=25.0 — progress should
        equal watch_duration_percent (25.0) per the max rule.
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_with_progress(
            target_progress_percent=0.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        # Watch 500 of 1000 on chapter 1; nothing on chapter 2.
        log_watch_session(enrollment, student, chapters[0]["id"], 500)
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["chapter_completion_percent"] == pytest.approx(0.0, abs=0.05)
        assert e["watch_duration_percent"] == pytest.approx(25.0, abs=0.05)
        assert e["progress_percent"] == pytest.approx(25.0, abs=0.05)


class TestPerChapterCap:
    """PRD §3.4: 'For each such chapter it computes the smaller of the chapter's
    total watched seconds and that chapter's video_duration_seconds — the cap
    prevents a learner from inflating their number by re-watching one chapter
    many times.'"""

    def test_watching_more_than_duration_caps(self, api):
        """PRD §3.4: 'the smaller of the chapter's total watched seconds and
        that chapter's video_duration_seconds.'

        With 1000s chapters and 5000s of watch on one chapter, the chapter
        contributes only 1000s to the numerator, so two 1000s chapters total
        of 2000s with 1000s capped contribution gives 50.0% watch_duration.
        """
        course, instructor, student, enrollment, chapters = setup_enrollment_with_progress(
            target_progress_percent=0.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        # Watch 5000 on chapter 1; only 1000 should count.
        log_watch_session(enrollment, student, chapters[0]["id"], 5000)
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        # chapter_completion=50 (chapter 1 watched fully meets binary threshold);
        # watch_duration=50 (1000 capped / 2000 total).
        assert e["chapter_completion_percent"] == pytest.approx(50.0, abs=0.05)
        assert e["watch_duration_percent"] == pytest.approx(50.0, abs=0.05)


class TestAtRiskFlip:
    """PRD §3.5: 'learning_status flips from ACTIVE to AT_RISK if and only if
    the days-since-enrolment is at least fourteen and either the current
    progress_percent is strictly less than thirty percent or the risk score
    is strictly greater than zero.'"""

    def test_flip_to_at_risk_after_14_days_with_low_progress(self, api):
        """PRD §3.5: 'days-since-enrolment is at least fourteen and ... the
        current progress_percent is strictly less than thirty percent.'"""
        course, instructor, student, enrollment, chapters = setup_enrollment_with_progress(
            target_progress_percent=10.0,  # 200 sec on chapter 1 of (1000+1000)
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        # Advance 14 days (PRD §3.5 boundary is "at least fourteen").
        advance_clock_days(14)
        sweep_at_risk()
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["learning_status"] == "AT_RISK"

    def test_no_flip_under_14_days_even_with_low_progress(self, api):
        """PRD §3.5: '... the days-since-enrolment is at least fourteen.'
        Below 14 days, no flip even with progress=0%."""
        course, instructor, student, enrollment, _ = setup_enrollment_with_progress(
            target_progress_percent=0.0,
            num_required_chapters=2,
            chapter_video_seconds=1000,
        )
        advance_clock_days(7)  # < 14 days
        sweep_at_risk()
        e = validate_success(
            api.get_enrollment(enrollment["id"], make_student_headers(student["id"])),
            expected_status=200,
        )
        assert e["learning_status"] == "ACTIVE"


class TestWatchSessionPositiveSeconds:
    """PRD §3.4: 'submitting the chapter_id watched and the seconds_watched for
    that session (which must be strictly greater than zero).'"""

    def test_zero_seconds_rejected(self, api):
        """PRD §3.4: 'seconds_watched ... must be strictly greater than zero.'"""
        course, instructor, _ = create_published_course(
            num_required_chapters=1, chapter_video_seconds=1000
        )
        enrollment, student = enroll_student(course)
        # Need a chapter id.
        from test_helpers import validate_paginated
        ch_res = api.list_chapters(course["id"], make_student_headers(student["id"]))
        chapters, _ = validate_paginated(ch_res)
        chapter_id = chapters[0]["id"]
        res = api.create_watch_session(
            enrollment["id"],
            {"chapter_id": chapter_id, "seconds_watched": 0},
            make_student_headers(student["id"]),
        )
        # PRD does not pin a specific error_id here; only assert non-2xx 4xx.
        assert 400 <= res.status_code < 500, (
            f"seconds_watched=0 must be rejected with 4xx; got {res.status_code}"
        )
