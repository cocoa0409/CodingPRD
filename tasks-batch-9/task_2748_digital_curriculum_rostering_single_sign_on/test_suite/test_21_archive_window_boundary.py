"""
The archived-class retention deadline, probed one millisecond either side.

When the instructional year is rolled over, the term's classes are archived and
the district gets a fixed retention window in which they may still be read. That
window closes on a strict comparison: the archived class is served while the
clock instant is strictly earlier than the deadline, so the last millisecond of
the window still answers and the deadline instant itself already refuses. Both
sides of that one-millisecond step are asserted here against requests that
differ in nothing but the logical clock.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as errors
from test_helpers import constants as c
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.types import GradeBand, MeetingDay, SectionStatus, Subject, TermState

# 18 December 2026 plus 90 retention days, anchored at midnight.
CLOCK_ON_TERM_END = "2026-12-18T00:00:00Z"
LAST_MILLISECOND_OF_THE_WINDOW = "2027-03-17T23:59:59.999Z"
RETENTION_DEADLINE = c.TERM_ARCHIVED_ACCESS_EXPIRES_AT


def _rolled_over_term_with_one_archived_class(api):
    """
    One elementary building whose single third-period class has been archived by
    summer rollover, leaving a 90-day window in which it can still be read.

    The term runs to 18 December 2026 and carries the default 90 retention days,
    so the officer rolls it over on the clock date that equals its `end_date` and
    the deadline lands on 18 March 2027 at midnight.
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT)
    school = fx.create_school(
        api,
        grade_band=GradeBand.ELEMENTARY,
        name="Northside Elementary",
        sis_school_id="SCH-NE",
        building_code="NE",
    )
    term = fx.create_active_term(api)
    teacher = fx.create_teacher(
        api,
        school["id"],
        sis_staff_id="STF-1001",
        full_name="Dana Reed",
        email="dana.reed@district.k12",
    )
    section = fx.create_section(
        api,
        school["id"],
        term["id"],
        primary_teacher_id=teacher["id"],
        period_index=3,
        meeting_days=MeetingDay.MWF,
        max_seats=5,
        sis_section_id="SEC-3001",
        course_code="MATH4",
        subject=Subject.MATH,
    )
    fx.set_clock(api, CLOCK_ON_TERM_END, headers=users.DATA_GOVERNANCE_OFFICER)
    rolled_over = fx.rollover_term(api, term["id"])
    return {
        "term_id": term["id"],
        "term": rolled_over,
        "section_id": section["id"],
    }


def test_rollover_dates_the_retention_deadline_and_archives_the_class(api):
    """Rolling the year over parks the December class and starts a 90-day retention clock.

    "`archived_access_expires_at` is set to the term's `end_date` plus its
    `archive_retention_days`, anchored at `00:00:00.000Z` on that date — calendar
    day addition on a date, not an arithmetic of hours", and 90 days after
    18 December 2026 is 18 March 2027. On the hop outward "every section of this
    term whose `status` is `ACTIVE` becomes `ARCHIVED`", and the term itself ends
    in `ROLLED_OVER`.

    Design: Difficulty/boundary_precision_check/archived_access_expiry_instant_is_closed
    """
    world = _rolled_over_term_with_one_archived_class(api)

    assert world["term"]["state"] == TermState.ROLLED_OVER
    assert world["term"]["archived_access_expires_at"] == RETENTION_DEADLINE

    fx.set_clock(api, LAST_MILLISECOND_OF_THE_WINDOW)
    section = validate_success(
        api.get_section(world["section_id"], users.ROSTER_OPERATOR)
    )
    assert section["status"] == SectionStatus.ARCHIVED


def test_the_archived_class_is_still_served_one_millisecond_before_the_deadline(api):
    """A registrar asking for last term's maths class at 23:59:59.999 still gets it.

    "Archived-class access is then permitted while the clock instant is strictly
    earlier than `archived_access_expires_at`", and the contract works this very
    boundary through: "with an `end_date` of 18 December 2026 and 90 retention
    days, the deadline is `2027-03-18T00:00:00.000Z`, so at
    `2027-03-17T23:59:59.999Z` the archived roster is served". One millisecond of
    window is still one millisecond of window, so the read answers 200 with the
    archived class in the body.

    Design: Difficulty/boundary_precision_check/archived_access_expiry_instant_is_closed
    """
    world = _rolled_over_term_with_one_archived_class(api)

    fx.set_clock(api, LAST_MILLISECOND_OF_THE_WINDOW)
    served = validate_success(
        api.get_section(world["section_id"], users.ROSTER_OPERATOR), 200
    )
    assert served["id"] == world["section_id"]
    assert served["status"] == SectionStatus.ARCHIVED
    assert served["period_index"] == 3


def test_the_identical_read_is_refused_at_the_retention_deadline_instant(api):
    """One millisecond later the same request for the same class is shut out.

    The window guard is strict, so "at that instant the window is already shut"
    and "at `2027-03-18T00:00:00.000Z` the identical request is refused" with
    `ERR_ARCHIVE_WINDOW_CLOSED`. The two requests differ in nothing but the
    logical clock, so only the boundary comparison can explain the difference.
    A closed window blocks the read and nothing more: the class is still
    `ARCHIVED`, and its `version` has not moved, because only a mutation moves
    `updated_at` and `version`.

    Design: Difficulty/boundary_precision_check/archived_access_expiry_instant_is_closed
    """
    world = _rolled_over_term_with_one_archived_class(api)

    fx.set_clock(api, LAST_MILLISECOND_OF_THE_WINDOW)
    served = validate_success(
        api.get_section(world["section_id"], users.ROSTER_OPERATOR), 200
    )

    fx.set_clock(api, RETENTION_DEADLINE)
    validate_error(
        api.get_section(world["section_id"], users.ROSTER_OPERATOR),
        errors.ERR_ARCHIVE_WINDOW_CLOSED,
        409,
    )

    fx.set_clock(api, LAST_MILLISECOND_OF_THE_WINDOW)
    unchanged = validate_success(
        api.get_section(world["section_id"], users.ROSTER_OPERATOR), 200
    )
    assert unchanged["status"] == SectionStatus.ARCHIVED
    assert unchanged["version"] == served["version"]
