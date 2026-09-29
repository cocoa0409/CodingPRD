"""
Which complaint the district hears when a request breaks two rules at once.

A single request frequently violates more than one rule, and the service answers
with exactly one error identifier — the one belonging to the first rule the fixed
global ladder reaches. Two pairings are exercised here. Provisioning a seat
against a suspended licence in a building that is already full is a state failure
and a fiscal failure at the same time, and the caller must be told the licence is
suspended rather than that the building is out of seats. Adding a student to a
class that is both full and timetabled against a class the student already takes
is a capacity failure and a timetable failure at the same time, and the caller
must be told about the timetable clash. In each case the losing rule is a real
violation of the same request, which is what makes the reported identifier
informative rather than accidental.
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
from test_helpers.assertions import assert_allocation, assert_seat_counters
from test_helpers.types import (
    AllocationPolicy,
    GradeBand,
    MeetingDay,
    OveragePolicy,
    RosterStatus,
    SeatModel,
    Subject,
    VendorAppStatus,
)

# One ELEMENTARY building holding two fourth-graders.
BUILDING_NAME = "Northside Elementary"
SIS_SCHOOL_ID = "SCH-NE"
BUILDING_CODE = "NE"

STUDENT_ONE = {
    "sis_student_id": "STU-2001",
    "first_name": "Alex",
    "last_name": "Nakamura",
    "date_of_birth": "2016-05-04",
}
STUDENT_TWO = {
    "sis_student_id": "STU-2002",
    "first_name": "Priya",
    "last_name": "Raman",
    "date_of_birth": "2016-07-11",
}
STUDENT_GRADE_LEVEL = 4

SIS_STAFF_ID = "STF-1001"
TEACHER_NAME = "Dana Reed"
TEACHER_EMAIL = "dana.reed@district.k12"

VENDOR_NAME = "MathBlast"
VENDOR_CODE = "MBX"

# The shared bell-schedule period and the two class lists that collide on it.
PERIOD_INDEX = 3
MATH_SIS_SECTION_ID = "SEC-3001"
MATH_COURSE_CODE = "MATH4"
MATH_MAX_SEATS = 5
READING_SIS_SECTION_ID = "SEC-3002"
READING_COURSE_CODE = "READ4"
READING_MAX_SEATS = 1

FIRST_ADD_DATE = "2026-08-15"
SECOND_ADD_DATE = "2026-08-16"


def _suspended_licence_and_full_building(api):
    """
    Build a one-seat elementary licence whose only building has already spent
    that seat on the first student, then suspend the licence, and finally attempt
    to seat the second student against the same allocation.

    The attempt carries the licence version read after the suspension, so the
    optimistic-concurrency rung is deliberately satisfied and cannot stand in for
    the state rung. Returns the refusal response alongside the world's ids.
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT, headers=users.IDENTITY_ADMIN)
    school = fx.create_school(
        api,
        grade_band=GradeBand.ELEMENTARY,
        name=BUILDING_NAME,
        sis_school_id=SIS_SCHOOL_ID,
        building_code=BUILDING_CODE,
    )
    term = fx.create_active_term(api)
    first_student = fx.create_student(
        api, school["id"], grade_level=STUDENT_GRADE_LEVEL, **STUDENT_ONE
    )
    second_student = fx.create_student(
        api, school["id"], grade_level=STUDENT_GRADE_LEVEL, **STUDENT_TWO
    )
    vendor_app = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=1,
        price_per_seat_cents=c.STANDARD_PRICE_PER_SEAT_CENTS,
        grade_band_scope=[GradeBand.ELEMENTARY],
        name=VENDOR_NAME,
        vendor_code=VENDOR_CODE,
        seat_model=SeatModel.PER_STUDENT,
        allocation_policy=AllocationPolicy.PROPORTIONAL_HEADCOUNT,
        overage_policy=OveragePolicy.BLOCK,
    )
    fx.activate_license(api, vendor_app["id"])
    allocation = fx.allocation_for_school(api, vendor_app["id"], school["id"])
    assert allocation["allocated_seats"] == 1

    seated_account = fx.provision_account(
        api,
        allocation["id"],
        vendor_app_id=vendor_app["id"],
        student_id=first_student["id"],
    )
    assert fx.read_allocation(api, allocation["id"])["consumed_seats"] == 1

    suspended = validate_success(
        api.update_vendor_app(
            vendor_app["id"],
            f.vendor_app_patch(status=VendorAppStatus.SUSPENDED),
            users.VENDOR_INTEGRATION_MANAGER,
        )
    )
    assert suspended["status"] == VendorAppStatus.SUSPENDED

    current_version = fx.vendor_app_version(api, vendor_app["id"])
    response = api.create_app_account(
        f.app_account_payload(
            allocation["id"], current_version, student_id=second_student["id"]
        ),
        users.IDENTITY_ADMIN,
    )
    return {
        "response": response,
        "school_id": school["id"],
        "vendor_app_id": vendor_app["id"],
        "allocation_id": allocation["id"],
        "seated_account_id": seated_account["id"],
        "second_student_id": second_student["id"],
    }


def test_a_suspended_licence_is_reported_ahead_of_a_building_out_of_seats(api):
    """The identity administrator learns the vendor licence is suspended, not that the school has run out of seats.

    "The first violated rule decides the response; no later rule is evaluated."
    Rung 14 requires the licence `status` to be `ACTIVE` "when an app account is
    provisioned against one of its allocations, else
    `ERR_VENDOR_APP_NOT_ACTIVE`", while the fiscal seat admission of rung 44 —
    "the target building admits the seat, else
    `ERR_BUILDING_ALLOCATION_EXHAUSTED`" — is "always last". The same request
    breaks both, because the building's single seat is already consumed and the
    hard cap forbids reaching into the district pool, so the state rung answers
    and the response carries exactly one error identifier.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_app_account_create
    """
    world = _suspended_licence_and_full_building(api)

    error = validate_error(
        world["response"], errors.ERR_VENDOR_APP_NOT_ACTIVE, expected_status=409
    )
    assert error["error_id"] != errors.ERR_BUILDING_ALLOCATION_EXHAUSTED
    assert error["error_id"] != errors.ERR_STALE_VENDOR_APP_VERSION


def test_the_refused_provisioning_leaves_the_seat_pool_and_the_committed_money_alone(api):
    """A refused provisioning request must not take a seat, mint an account or move the district's committed spend.

    Because the ladder refuses the request before any effect is applied, the
    building's grant still reads one seat allocated and one consumed, and the
    licence's `consumed_seats` and its `committed_charge_cents` — "the sum, over
    every app account of that licence regardless of `seat_status`, of that
    account's `seat_charge_cents` minus its `refunded_charge_cents`" — still
    describe only the student who was seated before the suspension.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_app_account_create
    """
    world = _suspended_licence_and_full_building(api)
    validate_error(world["response"], errors.ERR_VENDOR_APP_NOT_ACTIVE)

    assert_allocation(
        fx.read_allocation(api, world["allocation_id"]),
        allocated_seats=1,
        consumed_seats=1,
    )
    assert_seat_counters(
        fx.read_vendor_app(api, world["vendor_app_id"]),
        consumed_seats=1,
        committed_charge_cents=c.STANDARD_PRICE_PER_SEAT_CENTS,
    )

    refused_rows, refused_meta = validate_paginated(
        api.list_app_accounts(
            users.IDENTITY_ADMIN, student_id=world["second_student_id"]
        )
    )
    assert refused_rows == []
    assert refused_meta["total_count"] == 0

    seated_rows, _meta = validate_paginated(
        api.list_app_accounts(
            users.IDENTITY_ADMIN, building_allocation_id=world["allocation_id"]
        )
    )
    assert [row["id"] for row in seated_rows] == [world["seated_account_id"]]


def _double_booked_and_full_reading_section(api):
    """
    Time-table two period-3 classes that share Monday and Wednesday: a five-seat
    maths class the first student already takes, and a one-seat reading class the
    second student has already filled. Then try to add the first student to the
    reading class as well.

    The clock is moved to 20 August before either add is written, so both land
    ACTIVE in the same request and the maths row is genuinely live when the
    clashing add arrives. Returns the refusal response alongside the world's ids.
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
    first_student = fx.create_student(
        api, school["id"], grade_level=STUDENT_GRADE_LEVEL, **STUDENT_ONE
    )
    second_student = fx.create_student(
        api, school["id"], grade_level=STUDENT_GRADE_LEVEL, **STUDENT_TWO
    )
    math_section = fx.create_section(
        api,
        school["id"],
        term["id"],
        primary_teacher_id=teacher["id"],
        period_index=PERIOD_INDEX,
        meeting_days=list(MeetingDay.MWF),
        max_seats=MATH_MAX_SEATS,
        sis_section_id=MATH_SIS_SECTION_ID,
        course_code=MATH_COURSE_CODE,
        subject=Subject.MATH,
    )
    reading_section = fx.create_section(
        api,
        school["id"],
        term["id"],
        primary_teacher_id=None,
        period_index=PERIOD_INDEX,
        meeting_days=[MeetingDay.MON, MeetingDay.WED],
        max_seats=READING_MAX_SEATS,
        sis_section_id=READING_SIS_SECTION_ID,
        course_code=READING_COURSE_CODE,
        subject=Subject.ELA,
    )

    fx.set_clock(api, c.CLOCK_IN_WINDOW)
    math_enrollment = fx.create_enrollment(
        api, math_section["id"], first_student["id"], FIRST_ADD_DATE
    )
    reading_enrollment = fx.create_enrollment(
        api, reading_section["id"], second_student["id"], FIRST_ADD_DATE
    )
    assert math_enrollment["roster_status"] == RosterStatus.ACTIVE
    assert reading_enrollment["roster_status"] == RosterStatus.ACTIVE
    assert (
        validate_success(
            api.get_section(reading_section["id"], users.ROSTER_OPERATOR)
        )["active_enrollment_count"]
        == READING_MAX_SEATS
    )

    response = api.create_enrollment(
        f.enrollment_payload(
            reading_section["id"], first_student["id"], SECOND_ADD_DATE
        ),
        users.ROSTER_OPERATOR,
    )
    return {
        "response": response,
        "math_section_id": math_section["id"],
        "reading_section_id": reading_section["id"],
        "first_student_id": first_student["id"],
        "math_enrollment_id": math_enrollment["id"],
        "reading_enrollment_id": reading_enrollment["id"],
    }


def test_a_timetable_clash_is_reported_ahead_of_a_class_that_is_already_full(api):
    """The data steward learns the student is already booked in that period, not that the reading class is full.

    Rung 31, "no student double-booking, else
    `ERR_STUDENT_SCHEDULE_CONFLICT`", sits above rung 39, "the section has a free
    physical seat, else `ERR_SECTION_AT_CAPACITY`", and "the first violated rule
    decides the response; no later rule is evaluated." Both rules are genuinely
    broken: the reading class shares `period_index` 3 and the Monday and
    Wednesday meeting days with the maths class the student already holds an
    undropped enrollment in, over overlapping date intervals, and its
    `active_enrollment_count` already equals its `max_seats` of one. The
    temporal rung therefore answers, and the response carries exactly one error
    identifier.

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_enrollment_create
    """
    world = _double_booked_and_full_reading_section(api)

    error = validate_error(
        world["response"], errors.ERR_STUDENT_SCHEDULE_CONFLICT, expected_status=409
    )
    assert error["error_id"] != errors.ERR_SECTION_AT_CAPACITY


def test_the_refused_add_over_fills_nothing_and_leaves_both_class_lists_intact(api):
    """A rejected add must leave both class lists, the student's schedule and the surviving enrollment exactly as they were.

    `Section.active_enrollment_count` is "the number of enrollments of that
    section whose `roster_status` is `PENDING_ADD` or `ACTIVE`" and
    `Student.active_enrollment_count` counts that student's `PENDING_ADD`,
    `ACTIVE` and `PENDING_DROP` rows; because the ladder refused the request
    before any effect, the reading class still holds its single seat-taker, the
    maths class still holds its one, the student is still scheduled into exactly
    one class, and the maths row keeps the `effective_date` stamped from the date
    the source system asked for.

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_enrollment_create
    """
    world = _double_booked_and_full_reading_section(api)
    validate_error(world["response"], errors.ERR_STUDENT_SCHEDULE_CONFLICT)

    reading_section = validate_success(
        api.get_section(world["reading_section_id"], users.ROSTER_OPERATOR)
    )
    assert reading_section["active_enrollment_count"] == 1
    assert reading_section["max_seats"] == 1

    math_section = validate_success(
        api.get_section(world["math_section_id"], users.ROSTER_OPERATOR)
    )
    assert math_section["active_enrollment_count"] == 1

    student = validate_success(
        api.get_student(world["first_student_id"], users.ROSTER_OPERATOR)
    )
    assert student["active_enrollment_count"] == 1

    rows, _meta = validate_paginated(
        api.list_enrollments(
            users.ROSTER_OPERATOR, section_id=world["reading_section_id"]
        )
    )
    assert [row["id"] for row in rows] == [world["reading_enrollment_id"]]

    math_enrollment = validate_success(
        api.get_enrollment(world["math_enrollment_id"], users.ROSTER_OPERATOR)
    )
    assert math_enrollment["roster_status"] == RosterStatus.ACTIVE
    assert math_enrollment["effective_date"] == FIRST_ADD_DATE
