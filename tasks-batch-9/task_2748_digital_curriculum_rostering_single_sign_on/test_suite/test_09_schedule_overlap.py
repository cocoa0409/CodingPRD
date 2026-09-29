"""
Double-booking on the master schedule: the student's period slot and the
teacher's travel buffer.

Two different contended resources with two deliberately different interval
conventions. A student clash is decided over the half-open date interval of the
two enrollments combined with exact equality of `period_index` and at least one
shared meeting day, so an add that starts on the very day a pending drop takes
effect is legal. A teacher clash is decided over the one-period travel buffer on
the period axis with no date dimension at all, so the period next door already
collides. Both directions of each boundary are probed here: the probe that must
be served proves the rule is not over-enforced, and the probe that must be
refused proves it is enforced at all.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as errors
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import assert_ids_equal
from test_helpers.types import GradeBand, MeetingDay, RosterStatus, Subject

# The district's Fall 2026 calendar, as the shared world below builds it.
ENROLLED_ON = "2026-08-15"
DROP_TAKES_EFFECT_ON = "2026-09-01"
ONE_DAY_BEFORE_THE_DROP = "2026-08-31"


def _student_with_a_pending_drop_at_third_period(api):
    """
    One elementary building running four third-period classes, and one fourth
    grader who has already asked to leave the first of them on 1 September.

    All four classes meet at `period_index` 3 with `max_seats` of 5, so a
    physical chair is never the reason a later add is refused, and only the
    first class has a teacher of record so the teacher travel buffer stays out
    of the way. The student's live class is the Monday/Wednesday/Friday maths
    section; the drop is post-dated against a clock standing on 20 August, so
    the row is `PENDING_DROP` and its occupied date interval is the half-open
    15 August through 1 September.
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
    student = fx.create_student(
        api,
        school["id"],
        grade_level=4,
        sis_student_id="STU-2001",
        first_name="Alex",
        last_name="Nakamura",
        date_of_birth="2016-05-04",
    )
    maths_mwf = fx.create_section(
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
    reading_mw = fx.create_section(
        api,
        school["id"],
        term["id"],
        period_index=3,
        meeting_days=[MeetingDay.MON, MeetingDay.WED],
        max_seats=5,
        sis_section_id="SEC-3002",
        course_code="READ4",
        subject=Subject.ELA,
    )
    science_tr = fx.create_section(
        api,
        school["id"],
        term["id"],
        period_index=3,
        meeting_days=MeetingDay.TR,
        max_seats=5,
        sis_section_id="SEC-3003",
        course_code="SCI4",
        subject=Subject.SCIENCE,
    )
    art_mon = fx.create_section(
        api,
        school["id"],
        term["id"],
        period_index=3,
        meeting_days=[MeetingDay.MON],
        max_seats=5,
        sis_section_id="SEC-3004",
        course_code="ART4",
        subject=Subject.ELECTIVE,
    )
    fx.set_clock(api, c.CLOCK_IN_WINDOW)
    maths_enrollment = fx.create_enrollment(
        api, maths_mwf["id"], student["id"], ENROLLED_ON
    )
    pending_drop = fx.drop_enrollment(
        api, maths_enrollment["id"], DROP_TAKES_EFFECT_ON
    )
    return {
        "school_id": school["id"],
        "term_id": term["id"],
        "student_id": student["id"],
        "maths_mwf_id": maths_mwf["id"],
        "reading_mw_id": reading_mw["id"],
        "science_tr_id": science_tr["id"],
        "art_mon_id": art_mon["id"],
        "maths_enrollment_id": maths_enrollment["id"],
        "pending_drop": pending_drop,
    }


def _add_the_touching_reading_class(api, world):
    """Add the reading class starting on the day the maths drop takes effect."""
    return api.create_enrollment(
        f.enrollment_payload(
            world["reading_mw_id"], world["student_id"], DROP_TAKES_EFFECT_ON
        ),
        users.ROSTER_OPERATOR,
    )


def _add_the_overlapping_art_class(api, world):
    """Add the Monday art class one day before the maths drop takes effect."""
    return api.create_enrollment(
        f.enrollment_payload(
            world["art_mon_id"], world["student_id"], ONE_DAY_BEFORE_THE_DROP
        ),
        users.ROSTER_OPERATOR,
    )


def _add_the_tuesday_thursday_science_class(api, world):
    """Add the Tuesday/Thursday science class over the same overlapping dates."""
    return api.create_enrollment(
        f.enrollment_payload(
            world["science_tr_id"], world["student_id"], ONE_DAY_BEFORE_THE_DROP
        ),
        users.ROSTER_OPERATOR,
    )


def test_a_class_may_start_on_the_very_day_the_previous_one_ends(api):
    """A fourth grader may join the reading class on the day his maths drop takes effect.

    A post-dated drop on an ACTIVE row "records `drop_effective_date` and moves
    `roster_status` to `PENDING_DROP`", so the maths row occupies the half-open
    interval from 15 August "up to but not including its drop date". The reading
    add is dated 1 September, and "two intervals that merely touch, where one
    ends on the day the next begins, do not overlap" — so the shared Monday and
    Wednesday at the identical `period_index` cannot make this a clash. The date
    is still ahead of the 20 August clock, so the new row "stays `PENDING_ADD`".

    Design: Difficulty/resource_temporal_overlap/student_period_overlap_half_open_dates
    """
    world = _student_with_a_pending_drop_at_third_period(api)

    assert world["pending_drop"]["roster_status"] == RosterStatus.PENDING_DROP
    assert world["pending_drop"]["drop_effective_date"] == DROP_TAKES_EFFECT_ON

    reading = validate_success(_add_the_touching_reading_class(api, world), 201)
    assert reading["roster_status"] == RosterStatus.PENDING_ADD
    assert reading["section_id"] == world["reading_mw_id"]
    assert reading["requested_effective_date"] == DROP_TAKES_EFFECT_ON


def test_a_class_starting_one_day_before_the_drop_lands_double_books_the_student(api):
    """The same fourth grader may not sit in art on a Monday he is still enrolled in maths.

    The art add is dated 31 August, so its interval "from the new row's
    `requested_effective_date` up to but not including ... the term's `end_date`"
    genuinely overlaps the maths row's interval, which runs up to 1 September.
    Both classes sit at the same `period_index` and both meet on Monday, and the
    student rule "must not overlap the corresponding interval of any other
    enrollment of the same student that is not `DROPPED` and whose section has
    the same `period_index` and at least one shared entry of `meeting_days`" —
    "a violation is `ERR_STUDENT_SCHEDULE_CONFLICT`".

    Design: Difficulty/resource_temporal_overlap/student_period_overlap_half_open_dates
    """
    world = _student_with_a_pending_drop_at_third_period(api)
    validate_success(_add_the_touching_reading_class(api, world), 201)

    validate_error(
        _add_the_overlapping_art_class(api, world),
        errors.ERR_STUDENT_SCHEDULE_CONFLICT,
        409,
    )


def test_a_third_period_class_on_untaken_days_is_not_a_double_booking(api):
    """Science on Tuesday and Thursday is free to overlap the maths dates it never meets.

    The science class shares the identical `period_index` and its date interval
    from 31 August genuinely overlaps the maths row, yet the clash needs "at
    least one shared entry of `meeting_days`" and Tuesday/Thursday shares none
    with Monday/Wednesday/Friday or with Monday/Wednesday. The counters then
    read as §2.9 defines them: a section's `active_enrollment_count` counts only
    `PENDING_ADD` and `ACTIVE` rows, so the maths class shows zero while the
    student's own count "is the number of enrollments of that student whose
    `roster_status` is `PENDING_ADD`, `ACTIVE` or `PENDING_DROP`" — three.

    Design: Difficulty/resource_temporal_overlap/student_period_overlap_half_open_dates
    """
    world = _student_with_a_pending_drop_at_third_period(api)
    reading = validate_success(_add_the_touching_reading_class(api, world), 201)
    validate_error(
        _add_the_overlapping_art_class(api, world),
        errors.ERR_STUDENT_SCHEDULE_CONFLICT,
        409,
    )

    science = validate_success(_add_the_tuesday_thursday_science_class(api, world), 201)
    assert science["roster_status"] == RosterStatus.PENDING_ADD

    maths_class = validate_success(
        api.get_section(world["maths_mwf_id"], users.ROSTER_OPERATOR)
    )
    reading_class = validate_success(
        api.get_section(world["reading_mw_id"], users.ROSTER_OPERATOR)
    )
    science_class = validate_success(
        api.get_section(world["science_tr_id"], users.ROSTER_OPERATOR)
    )
    art_class = validate_success(
        api.get_section(world["art_mon_id"], users.ROSTER_OPERATOR)
    )
    assert maths_class["active_enrollment_count"] == 0
    assert reading_class["active_enrollment_count"] == 1
    assert science_class["active_enrollment_count"] == 1
    assert art_class["active_enrollment_count"] == 0

    student = validate_success(
        api.get_student(world["student_id"], users.ROSTER_OPERATOR)
    )
    assert student["active_enrollment_count"] == 3

    rows, meta = validate_paginated(
        api.list_enrollments(
            users.ROSTER_OPERATOR, student_id=world["student_id"], limit=100
        )
    )
    assert meta["total_count"] == 3
    assert_ids_equal(
        rows,
        [world["maths_enrollment_id"], reading["id"], science["id"]],
        "the student's roster",
    )


def _teacher_of_record_at_third_period(api):
    """
    One elementary building in an ACTIVE Fall 2026 term where a single teacher
    is the teacher of record of exactly one third-period class meeting Monday,
    Wednesday and Friday.

    Nothing else exists: no students, no enrollments and no licence, because the
    travel buffer is a purely structural rule with no date dimension and no seat
    dimension, so nothing else can explain an outcome here.
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
    third_period = fx.create_section(
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
    return {
        "school_id": school["id"],
        "term_id": term["id"],
        "teacher_id": teacher["id"],
        "third_period_id": third_period["id"],
    }


def _assign_class(api, world, sis_section_id, course_code, period_index, meeting_days):
    """Ask for one more class for the same teacher of record in the same term."""
    return api.create_section(
        f.section_payload(
            world["school_id"],
            world["term_id"],
            primary_teacher_id=world["teacher_id"],
            period_index=period_index,
            meeting_days=meeting_days,
            max_seats=5,
            sis_section_id=sis_section_id,
            course_code=course_code,
            subject=Subject.MATH,
        ),
        users.ROSTER_OPERATOR,
    )


def test_a_teacher_may_not_take_the_period_next_door_on_a_shared_day(api):
    """Dana Reed cannot walk from third-period maths to a fourth-period Monday class.

    "The section being created occupies the closed period interval running from
    its `period_index` minus one to its `period_index` plus one — the travel
    buffer is one period — and if any existing `ACTIVE` section taught by the
    same teacher in the same term has a `period_index` inside that interval and
    shares at least one entry of `meeting_days`, the request is refused with
    `ERR_TEACHER_PERIOD_CONFLICT`." Period 4 and period 3 are merely adjacent,
    and the contract is explicit that "adjacent periods therefore do conflict
    for teachers". The identical period on a shared Wednesday is refused by the
    same rule.

    Design: Difficulty/resource_temporal_overlap/teacher_buffered_period_overlap_closed_interval
    """
    world = _teacher_of_record_at_third_period(api)

    validate_error(
        _assign_class(api, world, "SEC-4001", "MATH4B", 4, [MeetingDay.MON]),
        errors.ERR_TEACHER_PERIOD_CONFLICT,
        409,
    )
    validate_error(
        _assign_class(api, world, "SEC-4004", "MATH4E", 3, [MeetingDay.WED]),
        errors.ERR_TEACHER_PERIOD_CONFLICT,
        409,
    )


def test_a_teacher_may_take_a_period_two_slots_away_on_the_same_day(api):
    """Dana Reed keeps her Monday fifth period, which the travel buffer never reaches.

    The buffer is exactly one period wide, so a fifth-period class occupies the
    closed interval from period 4 to period 6 and the existing third-period
    class sits outside it. No existing section taught by this teacher has "a
    `period_index` inside that interval", so nothing refuses the assignment and
    the section is created.

    Design: Difficulty/resource_temporal_overlap/teacher_buffered_period_overlap_closed_interval
    """
    world = _teacher_of_record_at_third_period(api)

    fifth_period = validate_success(
        _assign_class(api, world, "SEC-4002", "MATH4C", 5, [MeetingDay.MON]), 201
    )
    assert fifth_period["period_index"] == 5
    assert fifth_period["meeting_days"] == [MeetingDay.MON]
    assert fifth_period["primary_teacher_id"] == world["teacher_id"]


def test_the_travel_buffer_only_bites_on_a_day_the_teacher_already_teaches(api):
    """A Tuesday fourth period is free even though two of Dana Reed's classes bracket it.

    The buffered interval of the fourth-period request covers periods 3 through
    5 and therefore covers both classes she already holds, but the rule fires
    only when the new section also "shares at least one entry of `meeting_days`"
    — and Tuesday appears in neither Monday/Wednesday/Friday nor Monday. The
    master schedule that survives therefore holds exactly the three legal
    classes: the refused requests created nothing, and sections are listed
    "ordered by `created_at` ascending".

    Design: Difficulty/resource_temporal_overlap/teacher_buffered_period_overlap_closed_interval
    """
    world = _teacher_of_record_at_third_period(api)
    validate_error(
        _assign_class(api, world, "SEC-4001", "MATH4B", 4, [MeetingDay.MON]),
        errors.ERR_TEACHER_PERIOD_CONFLICT,
        409,
    )
    fifth_period = validate_success(
        _assign_class(api, world, "SEC-4002", "MATH4C", 5, [MeetingDay.MON]), 201
    )

    tuesday_fourth = validate_success(
        _assign_class(api, world, "SEC-4003", "MATH4D", 4, [MeetingDay.TUE]), 201
    )
    assert tuesday_fourth["period_index"] == 4
    assert tuesday_fourth["meeting_days"] == [MeetingDay.TUE]

    validate_error(
        _assign_class(api, world, "SEC-4004", "MATH4E", 3, [MeetingDay.WED]),
        errors.ERR_TEACHER_PERIOD_CONFLICT,
        409,
    )

    rows, meta = validate_paginated(
        api.list_sections(
            users.ROSTER_OPERATOR, primary_teacher_id=world["teacher_id"], limit=100
        )
    )
    assert meta["total_count"] == 3
    assert_ids_equal(
        rows,
        [world["third_period_id"], fifth_period["id"], tuesday_fourth["id"]],
        "the teacher's schedule",
    )
