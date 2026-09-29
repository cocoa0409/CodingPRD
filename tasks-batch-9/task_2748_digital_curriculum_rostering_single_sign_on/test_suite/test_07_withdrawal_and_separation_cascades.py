"""
The two deep wind-down chains of the district roster.

A student withdrawal is the deepest chain the service runs: the student leaves,
so the enrollment is wound down, so the licensed seat goes back and the single
sign-on identity is switched off, so the building's seat grant and the licence's
committed money and renewal position all re-settle. A staff separation is a
shallower but differently shaped chain: the teacher leaves, so the section it led
loses its match and the teacher's identity is switched off, so triage raises a
blocking defect and the roster run that had already projected its invoice is
pushed back for rework. The separation chain deliberately leaves the seat axis
alone, which is the whole point of keeping the seat pool and the identity
directory independent.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import constants as c
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_account_axes,
    assert_allocation,
    assert_app_account,
    assert_seat_counters,
)
from test_helpers.types import (
    AllocationPolicy,
    EmploymentStatus,
    EnrollmentSource,
    EnrollmentState,
    ErrorCategory,
    ErrorQueueItemStatus,
    ErrorSeverity,
    GradeBand,
    IdentityStatus,
    MeetingDay,
    OveragePolicy,
    PasswordState,
    RenewalRecommendation,
    RosterHealth,
    RosterStatus,
    RunType,
    SeatModel,
    SeatStatus,
    Subject,
    SyncHealth,
    SyncRunState,
    UnmatchedTeacherPolicy,
)

# The single ELEMENTARY building, its staff and its one fourth-grader.
BUILDING_NAME = "Northside Elementary"
SIS_SCHOOL_ID = "SCH-NE"
BUILDING_CODE = "NE"
SIS_STAFF_ID = "STF-1001"
TEACHER_NAME = "Dana Reed"
TEACHER_EMAIL = "dana.reed@district.k12"
SIS_STUDENT_ID = "STU-2001"
STUDENT_FIRST_NAME = "Alex"
STUDENT_LAST_NAME = "Nakamura"
STUDENT_DATE_OF_BIRTH = "2016-05-04"
STUDENT_GRADE_LEVEL = 4
SIS_SECTION_ID = "SEC-3001"
COURSE_CODE = "MATH4"
PERIOD_INDEX = 3
SECTION_MAX_SEATS = 5

VENDOR_NAME = "MathBlast"
VENDOR_CODE = "MBX"

# The add the source system asked for, and the date the district records for the
# student's exit and the teacher's exit alike.
REQUESTED_EFFECTIVE_DATE = "2026-08-15"
WITHDRAWAL_EFFECTIVE_DATE = "2026-08-20"
SEPARATION_EFFECTIVE_DATE = "2026-08-20"


def _read_student(api, student_id):
    """Read one student record."""
    return validate_success(api.get_student(student_id, users.ROSTER_OPERATOR))


def _read_section(api, section_id):
    """Read one section record."""
    return validate_success(api.get_section(section_id, users.ROSTER_OPERATOR))


def _read_enrollment(api, enrollment_id):
    """Read one enrollment record."""
    return validate_success(api.get_enrollment(enrollment_id, users.ROSTER_OPERATOR))


def _read_school(api, school_id):
    """Read one building record, including its live headcount."""
    return validate_success(api.get_school(school_id, users.ROSTER_OPERATOR))


def _read_teacher(api, teacher_id):
    """Read one teacher record."""
    return validate_success(api.get_teacher(teacher_id, users.ROSTER_OPERATOR))


def _withdrawn_student_world(api):
    """
    Seat one fourth-grader on a four-seat elementary licence, prove the world
    stands as intended, then have the governance officer withdraw the student on
    a date the logical clock has already reached.

    The clock is moved to 20 August before the add is written so that the add
    requested for 15 August lands ACTIVE in the same request, and 20 August is
    still inside the term's add/drop window, so the seat refund is the whole
    charge rather than nothing.
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT)
    school = fx.create_school(
        api,
        grade_band=GradeBand.ELEMENTARY,
        name=BUILDING_NAME,
        sis_school_id=SIS_SCHOOL_ID,
        building_code=BUILDING_CODE,
    )
    term = fx.create_active_term(api)
    teacher = fx.create_teacher(
        api,
        school["id"],
        sis_staff_id=SIS_STAFF_ID,
        full_name=TEACHER_NAME,
        email=TEACHER_EMAIL,
    )
    student = fx.create_student(
        api,
        school["id"],
        grade_level=STUDENT_GRADE_LEVEL,
        sis_student_id=SIS_STUDENT_ID,
        first_name=STUDENT_FIRST_NAME,
        last_name=STUDENT_LAST_NAME,
        date_of_birth=STUDENT_DATE_OF_BIRTH,
    )
    section = fx.create_section(
        api,
        school["id"],
        term["id"],
        primary_teacher_id=teacher["id"],
        period_index=PERIOD_INDEX,
        meeting_days=list(MeetingDay.MWF),
        max_seats=SECTION_MAX_SEATS,
        sis_section_id=SIS_SECTION_ID,
        course_code=COURSE_CODE,
        subject=Subject.MATH,
    )
    vendor_app = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=4,
        price_per_seat_cents=c.STANDARD_PRICE_PER_SEAT_CENTS,
        grade_band_scope=[GradeBand.ELEMENTARY],
        name=VENDOR_NAME,
        vendor_code=VENDOR_CODE,
        seat_model=SeatModel.PER_STUDENT,
        allocation_policy=AllocationPolicy.PROPORTIONAL_HEADCOUNT,
        overage_policy=OveragePolicy.BLOCK,
    )
    fx.activate_license(api, vendor_app["id"])

    fx.set_clock(api, c.CLOCK_IN_WINDOW)
    enrollment = fx.create_enrollment(
        api,
        section["id"],
        student["id"],
        REQUESTED_EFFECTIVE_DATE,
        source=EnrollmentSource.SIS_EXTRACT,
    )
    assert enrollment["roster_status"] == RosterStatus.ACTIVE

    allocation = fx.allocation_for_school(api, vendor_app["id"], school["id"])
    assert allocation["allocated_seats"] == 4
    account = fx.provision_account(
        api,
        allocation["id"],
        vendor_app_id=vendor_app["id"],
        student_id=student["id"],
    )
    assert account["seat_charge_cents"] == c.STANDARD_PRICE_PER_SEAT_CENTS
    fx.set_account_password(api, account["id"])

    assert fx.read_allocation(api, allocation["id"])["consumed_seats"] == 1
    assert_seat_counters(
        fx.read_vendor_app(api, vendor_app["id"]),
        consumed_seats=1,
        committed_charge_cents=c.STANDARD_PRICE_PER_SEAT_CENTS,
    )

    fx.withdraw_student(api, student["id"], WITHDRAWAL_EFFECTIVE_DATE)
    return {
        "school_id": school["id"],
        "term_id": term["id"],
        "student_id": student["id"],
        "section_id": section["id"],
        "enrollment_id": enrollment["id"],
        "vendor_app_id": vendor_app["id"],
        "allocation_id": allocation["id"],
        "account_id": account["id"],
    }


def test_withdrawing_the_student_drops_the_roster_row_and_the_building_headcount(api):
    """Withdrawing the district's only fourth-grader empties the class list and the building's headcount.

    On success "the student's `enrollment_state` becomes `WITHDRAWN`,
    `withdrawal_effective_date` is stored, the building's
    `enrolled_student_count` is recomputed", and on the second hop every
    enrollment that was `PENDING_ADD` or `ACTIVE` "becomes `DROPPED` when the
    withdrawal date is on or before the clock date" with `drop_effective_date`
    stamped from the withdrawal date, after which "the affected sections
    recompute `active_enrollment_count`". The withdrawal date of 20 August is the
    clock date itself, so the row reaches `DROPPED` and not `PENDING_DROP`, and
    because `Student.active_enrollment_count` counts only `PENDING_ADD`, `ACTIVE`
    and `PENDING_DROP` rows, the student is left scheduled into nothing.

    Design: Difficulty/transitive_cascade/student_withdraw_depth4_cascade
    """
    world = _withdrawn_student_world(api)

    student = _read_student(api, world["student_id"])
    assert student["enrollment_state"] == EnrollmentState.WITHDRAWN
    assert student["withdrawal_effective_date"] == WITHDRAWAL_EFFECTIVE_DATE
    assert student["active_enrollment_count"] == 0

    enrollment = _read_enrollment(api, world["enrollment_id"])
    assert enrollment["roster_status"] == RosterStatus.DROPPED
    assert enrollment["drop_effective_date"] == WITHDRAWAL_EFFECTIVE_DATE

    section = _read_section(api, world["section_id"])
    assert section["active_enrollment_count"] == 0

    school = _read_school(api, world["school_id"])
    assert school["enrolled_student_count"] == 0


def test_the_withdrawn_students_seat_goes_back_and_the_identity_is_switched_off(api):
    """The withdrawn student's vendor account gives its seat back, is deprovisioned and is refunded in full.

    On the third hop "every enrollment that actually reached `DROPPED` releases
    the student's seat-holding app accounts ... `seat_status` becomes `RELEASED`,
    `refunded_charge_cents` is set to the account's `seat_charge_cents` when the
    clock date is on or before the term's `add_drop_cutoff_date` and to zero
    otherwise, `identity_status` becomes `DEPROVISIONED`, and
    `deprovision_scheduled_date` is stamped with the withdrawal date." The clock
    reads 20 August against an add/drop cutoff of 15 September, so the whole
    1000-cent charge comes back, and a deprovisioned identity "sets
    `password_state` to `EXPIRED`". This is a state cascade and not a delete, so
    the released row is still listed against the student.

    Design: Difficulty/transitive_cascade/student_withdraw_depth4_cascade
    """
    world = _withdrawn_student_world(api)

    account = fx.read_account(api, world["account_id"])
    assert_app_account(account)
    assert_account_axes(
        account,
        seat_status=SeatStatus.RELEASED,
        identity_status=IdentityStatus.DEPROVISIONED,
        password_state=PasswordState.EXPIRED,
    )
    assert account["refunded_charge_cents"] == c.STANDARD_PRICE_PER_SEAT_CENTS
    assert account["deprovision_scheduled_date"] == WITHDRAWAL_EFFECTIVE_DATE

    rows, _meta = validate_paginated(
        api.list_app_accounts(users.IDENTITY_ADMIN, student_id=world["student_id"])
    )
    assert [row["id"] for row in rows] == [world["account_id"]]
    assert rows[0]["seat_status"] == SeatStatus.RELEASED


def test_the_released_seat_re_settles_the_building_grant_and_the_licence_economics(api):
    """Handing one seat back empties the building's consumption and zeroes the licence's committed money and renewal case.

    On the fourth hop "each release decrements the owning allocation's
    `consumed_seats` by one and then recomputes the licence's `consumed_seats`,
    `unallocated_seats`, `committed_charge_cents`, `renewal_score` and
    `renewal_recommendation`". The building's own grant of four seats is not
    re-cut by a release, so `allocated_seats` stays at 4 while `consumed_seats`
    and `borrowed_seats` fall to zero. `committed_charge_cents` is "the sum, over
    every app account of that licence regardless of `seat_status`, of that
    account's `seat_charge_cents` minus its `refunded_charge_cents`", which is
    1000 less 1000, or nothing. With no consumed seat, nothing provisioned and
    nothing engaged, every weighted term of the score is zero, and a score below
    40 recommends `DROP`.

    Design: Difficulty/transitive_cascade/student_withdraw_depth4_cascade
    """
    world = _withdrawn_student_world(api)

    allocation = fx.read_allocation(api, world["allocation_id"])
    assert_allocation(
        allocation,
        allocated_seats=4,
        consumed_seats=0,
        borrowed_seats=0,
    )

    vendor_app = fx.read_vendor_app(api, world["vendor_app_id"])
    assert_seat_counters(vendor_app, consumed_seats=0, committed_charge_cents=0)
    assert vendor_app["renewal_score"] == 0.0
    assert vendor_app["renewal_recommendation"] == RenewalRecommendation.DROP


def _separated_teacher_world(api):
    """
    Stand up a licence that seats teachers as well as students, provision the
    teacher of record, drive one roster run all the way to a projected invoice,
    prove that projection, then have the governance officer record the teacher's
    separation.

    The clock stays at 1 August throughout, so the add requested for 15 August
    remains `PENDING_ADD` and is still carried by the run's scope.
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT)
    school = fx.create_school(
        api,
        grade_band=GradeBand.ELEMENTARY,
        name=BUILDING_NAME,
        sis_school_id=SIS_SCHOOL_ID,
        building_code=BUILDING_CODE,
    )
    term = fx.create_active_term(api)
    teacher = fx.create_teacher(
        api,
        school["id"],
        sis_staff_id=SIS_STAFF_ID,
        full_name=TEACHER_NAME,
        email=TEACHER_EMAIL,
    )
    student = fx.create_student(
        api,
        school["id"],
        grade_level=STUDENT_GRADE_LEVEL,
        sis_student_id=SIS_STUDENT_ID,
        first_name=STUDENT_FIRST_NAME,
        last_name=STUDENT_LAST_NAME,
        date_of_birth=STUDENT_DATE_OF_BIRTH,
    )
    section = fx.create_section(
        api,
        school["id"],
        term["id"],
        primary_teacher_id=teacher["id"],
        period_index=PERIOD_INDEX,
        meeting_days=list(MeetingDay.MWF),
        max_seats=SECTION_MAX_SEATS,
        sis_section_id=SIS_SECTION_ID,
        course_code=COURSE_CODE,
        subject=Subject.MATH,
    )
    enrollment = fx.create_enrollment(
        api,
        section["id"],
        student["id"],
        REQUESTED_EFFECTIVE_DATE,
        source=EnrollmentSource.SIS_EXTRACT,
    )
    assert enrollment["roster_status"] == RosterStatus.PENDING_ADD

    vendor_app = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=6,
        price_per_seat_cents=c.STANDARD_PRICE_PER_SEAT_CENTS,
        grade_band_scope=[GradeBand.ELEMENTARY],
        name=VENDOR_NAME,
        vendor_code=VENDOR_CODE,
        seat_model=SeatModel.PER_STUDENT_AND_TEACHER,
        allocation_policy=AllocationPolicy.PROPORTIONAL_HEADCOUNT,
        overage_policy=OveragePolicy.BLOCK,
        unmatched_teacher_policy=UnmatchedTeacherPolicy.HOLD_RUN,
    )
    fx.activate_license(api, vendor_app["id"])
    allocation = fx.allocation_for_school(api, vendor_app["id"], school["id"])
    account = fx.provision_account(
        api,
        allocation["id"],
        vendor_app_id=vendor_app["id"],
        student_id=None,
        teacher_id=teacher["id"],
    )
    fx.set_account_password(api, account["id"])

    run = fx.open_sync_run(api, vendor_app["id"], run_type=RunType.FULL)
    run = fx.transform_run(api, run["id"])

    # The world the separation is about to disturb: a clean run carrying a
    # student seat and a teacher seat, and a licence in good sync health.
    assert run["state"] == SyncRunState.TRANSFORMED
    assert run["projected_charge_cents"] == 2 * c.STANDARD_PRICE_PER_SEAT_CENTS
    assert run["projected_seat_delta"] == 1
    assert run["blocking_error_count"] == 0
    assert _read_section(api, section["id"])["roster_health"] == RosterHealth.OK
    assert fx.read_vendor_app(api, vendor_app["id"])["sync_health"] == SyncHealth.OK
    assert_account_axes(
        fx.read_account(api, account["id"]),
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PROVISIONED,
    )
    assert fx.read_allocation(api, allocation["id"])["consumed_seats"] == 1

    fx.separate_teacher(api, teacher["id"], SEPARATION_EFFECTIVE_DATE)
    return {
        "school_id": school["id"],
        "term_id": term["id"],
        "teacher_id": teacher["id"],
        "student_id": student["id"],
        "section_id": section["id"],
        "vendor_app_id": vendor_app["id"],
        "allocation_id": allocation["id"],
        "account_id": account["id"],
        "run_id": run["id"],
    }


def test_separating_the_teacher_of_record_leaves_the_section_unmatched(api):
    """The class the resigning teacher led is immediately flagged as having nobody at the front of the room.

    A separation "takes the teacher from `ACTIVE` to `SEPARATED`, stores the
    supplied `separation_effective_date`", and from there "every section whose
    teacher of record was this teacher has its `roster_health` set to
    `UNMATCHED_TEACHER`" — which is exactly the defect the rostering pipeline is
    built to complain about, and it is reachable through the sections list's
    `roster_health` filter.

    Design: Difficulty/transitive_cascade/teacher_separation_depth3_cascade
    """
    world = _separated_teacher_world(api)

    teacher = _read_teacher(api, world["teacher_id"])
    assert teacher["employment_status"] == EmploymentStatus.SEPARATED
    assert teacher["separation_effective_date"] == SEPARATION_EFFECTIVE_DATE

    section = _read_section(api, world["section_id"])
    assert section["roster_health"] == RosterHealth.UNMATCHED_TEACHER

    rows, _meta = validate_paginated(
        api.list_sections(
            users.ROSTER_OPERATOR, roster_health=RosterHealth.UNMATCHED_TEACHER
        )
    )
    assert [row["id"] for row in rows] == [world["section_id"]]


def test_the_separated_teachers_identity_is_switched_off_while_the_seat_stays_taken(api):
    """A resigning teacher loses the ability to sign in but the district keeps paying for, and holding, the seat.

    A separation moves "the teacher's own app accounts ... `identity_status` to
    `DEPROVISIONED` — never to `SUSPENDED`", and deprovisioning an identity
    "sets `password_state` to `EXPIRED` — while leaving the seat axis untouched,
    so a deprovisioned identity may keep a `RESERVED` or `ACTIVE` seat until
    somebody releases it." The licence seat axis and the single sign-on identity
    axis are independent, so the building's `consumed_seats` is unmoved and the
    licence's committed money still carries the full teacher seat.

    Design: Difficulty/transitive_cascade/teacher_separation_depth3_cascade
    """
    world = _separated_teacher_world(api)

    account = fx.read_account(api, world["account_id"])
    assert_account_axes(
        account,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.DEPROVISIONED,
        password_state=PasswordState.EXPIRED,
    )
    assert account["refunded_charge_cents"] == 0

    assert_allocation(
        fx.read_allocation(api, world["allocation_id"]),
        allocated_seats=6,
        consumed_seats=1,
        borrowed_seats=0,
    )
    assert_seat_counters(
        fx.read_vendor_app(api, world["vendor_app_id"]),
        consumed_seats=1,
        committed_charge_cents=c.STANDARD_PRICE_PER_SEAT_CENTS,
    )


def test_the_unmatched_section_blocks_the_run_and_pushes_it_back_for_rework(api):
    """A resignation invalidates an invoice projection the operator has already been shown, so the run goes back to the queue.

    "For every such section that sits inside the scope of an in-flight sync run,
    a `BLOCKING` triage item of category `UNMATCHED_TEACHER` is raised against
    that run, and any such run that had already reached `TRANSFORMED` falls back
    to `HELD` with its `projected_seat_delta` and `projected_charge_cents` reset
    to null, because the projection it published to the operator is no longer
    trustworthy. Each affected run recomputes its `blocking_error_count`, and the
    governing licence's `sync_health` becomes `BLOCKED`." The item is born `OPEN`
    with `subject_section_id` pointing at the offending section.

    Design: Difficulty/transitive_cascade/teacher_separation_depth3_cascade
    """
    world = _separated_teacher_world(api)

    items = fx.queue_items(
        api,
        sync_run_id=world["run_id"],
        category=ErrorCategory.UNMATCHED_TEACHER,
        status=ErrorQueueItemStatus.OPEN,
    )
    assert len(items) == 1
    assert items[0]["severity"] == ErrorSeverity.BLOCKING
    assert items[0]["subject_section_id"] == world["section_id"]

    run = fx.read_run(api, world["run_id"])
    assert run["state"] == SyncRunState.HELD
    assert run["blocking_error_count"] == 1
    assert run["projected_charge_cents"] is None
    assert run["projected_seat_delta"] is None

    vendor_app = fx.read_vendor_app(api, world["vendor_app_id"])
    assert vendor_app["sync_health"] == SyncHealth.BLOCKED
