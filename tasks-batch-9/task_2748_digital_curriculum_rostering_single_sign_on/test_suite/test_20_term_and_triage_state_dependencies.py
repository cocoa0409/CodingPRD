"""
Writes that are gated entirely on some other record's state.

Two pairs of entities are exercised here. An add to a section is decided by the
term behind that section: the identical payload shape is honoured while the term is
ACTIVE and refused the moment summer rollover has closed the year, even though the
enrollment's own fields and the target section's identity never changed. A publish
is decided by the triage queue behind the run: the run sits in TRANSFORMED for both
attempts, and the only thing that changes between the refusal and the success is
whether a duplicate-student item is still open.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as errors
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.types import (
    EnrollmentSource,
    EnrollmentState,
    ErrorCategory,
    ErrorQueueItemStatus,
    ErrorSeverity,
    GradeBand,
    OveragePolicy,
    RosterStatus,
    RunType,
    SeatModel,
    SectionStatus,
    Subject,
    SyncRunState,
    TermState,
    UnmatchedTeacherPolicy,
)

STARTUP_CLOCK = "2026-08-01T00:00:00Z"
MID_TERM_CLOCK = "2026-08-20T00:00:00Z"
MID_TERM_DATE = "2026-08-20"
TERM_END_CLOCK = "2026-12-18T00:00:00Z"
TERM_END_DATE = "2026-12-18"
FIRST_ADD_DATE = "2026-08-15"
FULL_PRICE_PER_SEAT = 1000
DUPLICATE_KEY = "nakamura|2016-05-04"


# ─────────────────────────────────────────────────────────────────────────────
# Enrollment <- Term
# ─────────────────────────────────────────────────────────────────────────────

def _scheduled_term_world(api):
    """
    One elementary building with two enrolled students and one teacher-matched
    section of five physical seats in an ACTIVE Fall 2026 term, with the clock at
    2026-08-20 and the first student already added on 2026-08-15.
    """
    fx.set_clock(api, STARTUP_CLOCK)
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
    first_student = fx.create_student(
        api,
        school["id"],
        grade_level=4,
        sis_student_id="STU-2001",
        first_name="Alex",
        last_name="Nakamura",
        date_of_birth="2016-05-04",
    )
    second_student = fx.create_student(
        api,
        school["id"],
        grade_level=4,
        sis_student_id="STU-2002",
        first_name="Priya",
        last_name="Raman",
        date_of_birth="2016-07-11",
    )
    section = fx.create_section(
        api,
        school["id"],
        term["id"],
        primary_teacher_id=teacher["id"],
        period_index=3,
        meeting_days=["MON", "WED", "FRI"],
        max_seats=5,
        sis_section_id="SEC-3001",
        course_code="MATH4",
        subject=Subject.MATH,
    )
    fx.set_clock(api, MID_TERM_CLOCK)
    enrollment = fx.create_enrollment(
        api, section["id"], first_student["id"], FIRST_ADD_DATE
    )
    return {
        "school": school,
        "term": term,
        "teacher": teacher,
        "first_student": first_student,
        "second_student": second_student,
        "section": section,
        "enrollment": enrollment,
    }


def _rolled_over_world(api):
    """The same world after the year ended and the officer rolled the term over."""
    world = _scheduled_term_world(api)
    fx.set_clock(api, TERM_END_CLOCK, headers=users.DATA_GOVERNANCE_OFFICER)
    world["term"] = fx.rollover_term(api, world["term"]["id"])
    return world


def test_an_add_is_honoured_while_the_term_is_still_active(api):
    """The positive half of the dependency: an ACTIVE term admits the add.

    Creating an enrollment requires the governing term to be `ACTIVE`, and "when
    `requested_effective_date` is on or before the clock date, the row advances
    from `PENDING_ADD` to `ACTIVE` in the same request", with `effective_date`
    "stamped from `requested_effective_date`". The requested 2026-08-15 has
    already passed at the 2026-08-20 clock, so the row lands live and dated.

    Design: Difficulty/cross_entity_state_dependency/enrollment_create_requires_term_active
    """
    world = _scheduled_term_world(api)

    assert world["enrollment"]["roster_status"] == RosterStatus.ACTIVE
    assert world["enrollment"]["effective_date"] == FIRST_ADD_DATE == "2026-08-15"


def test_the_identical_add_is_refused_once_the_term_has_rolled_over(api):
    """The negative half: the same section refuses the second student after rollover.

    Rollover takes the term's "`state` ... `ROLLED_OVER`", and the state ladder
    then bites: "the governing term is in the state the operation requires, else
    `ERR_TERM_NOT_ACTIVE`: `ACTIVE` for creating a section, creating an
    enrollment, ...". The section still exists and its `active_enrollment_count`
    is far below its five physical seats, so no capacity, conflict or coherence
    rule can account for the refusal — only the other entity's state can.

    Design: Difficulty/cross_entity_state_dependency/enrollment_create_requires_term_active
    """
    world = _rolled_over_world(api)

    assert world["term"]["state"] == TermState.ROLLED_OVER

    response = api.create_enrollment(
        f.enrollment_payload(
            world["section"]["id"], world["second_student"]["id"], TERM_END_DATE
        ),
        users.ROSTER_OPERATOR,
    )
    validate_error(response, errors.ERR_TERM_NOT_ACTIVE, 409)

    section = validate_success(
        api.get_section(world["section"]["id"], users.ROSTER_OPERATOR), 200
    )
    assert section["max_seats"] == 5
    assert section["active_enrollment_count"] < section["max_seats"]


def test_the_refused_student_keeps_an_empty_schedule(api):
    """A refused add leaves no trace whatsoever on the student it named.

    The ladder decides a request before any effect is applied, so the rejected
    student holds none of the enrollments whose `roster_status` is `PENDING_ADD`,
    `ACTIVE` or `PENDING_DROP` that `Student.active_enrollment_count` counts, and
    the enrollment collection filtered on that student returns nothing at all.

    Design: Difficulty/cross_entity_state_dependency/enrollment_create_requires_term_active
    """
    world = _rolled_over_world(api)
    api.create_enrollment(
        f.enrollment_payload(
            world["section"]["id"], world["second_student"]["id"], TERM_END_DATE
        ),
        users.ROSTER_OPERATOR,
    )

    student = validate_success(
        api.get_student(world["second_student"]["id"], users.ROSTER_OPERATOR), 200
    )
    assert student["active_enrollment_count"] == 0

    rows, meta = validate_paginated(
        api.list_enrollments(
            users.ROSTER_OPERATOR, student_id=world["second_student"]["id"]
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_rollover_archives_the_section_and_closes_out_its_roster(api):
    """The same transition that shuts the door also empties the room.

    On rollover "every section of this term whose `status` is `ACTIVE` becomes
    `ARCHIVED`", and "every enrollment of those newly archived sections whose
    `roster_status` is `PENDING_ADD`, `ACTIVE` or `PENDING_DROP` becomes
    `DROPPED`". Since `Section.active_enrollment_count` counts only `PENDING_ADD`
    and `ACTIVE` rows, the surviving live add leaves the count at zero.

    Design: Difficulty/cross_entity_state_dependency/enrollment_create_requires_term_active
    """
    world = _rolled_over_world(api)

    section = validate_success(
        api.get_section(world["section"]["id"], users.ROSTER_OPERATOR), 200
    )
    assert section["status"] == SectionStatus.ARCHIVED
    assert section["active_enrollment_count"] == 0

    enrollment = validate_success(
        api.get_enrollment(world["enrollment"]["id"], users.ROSTER_OPERATOR), 200
    )
    assert enrollment["roster_status"] == RosterStatus.DROPPED


# ─────────────────────────────────────────────────────────────────────────────
# SyncRun <- ErrorQueueItem
# ─────────────────────────────────────────────────────────────────────────────

def _duplicate_triage_world(api):
    """
    Two students registered twice under two spellings of the same child, both added
    to one teacher-matched section for 2026-08-15 under a ten-seat per-student
    licence, with the run already transformed and the clock moved to 2026-08-20 so
    that both adds are due.
    """
    fx.set_clock(api, STARTUP_CLOCK)
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
    survivor = fx.create_student(
        api,
        school["id"],
        grade_level=4,
        sis_student_id="STU-2001",
        first_name="Alex",
        last_name="Nakamura",
        date_of_birth="2016-05-04",
    )
    loser = fx.create_student(
        api,
        school["id"],
        grade_level=4,
        sis_student_id="STU-2002",
        first_name="Alexander",
        last_name="Nakamura",
        date_of_birth="2016-05-04",
    )
    section = fx.create_section(
        api,
        school["id"],
        term["id"],
        primary_teacher_id=teacher["id"],
        period_index=3,
        meeting_days=["MON", "WED", "FRI"],
        max_seats=5,
        sis_section_id="SEC-3001",
        course_code="MATH4",
        subject=Subject.MATH,
    )
    survivor_enrollment = fx.create_enrollment(
        api, section["id"], survivor["id"], FIRST_ADD_DATE,
        source=EnrollmentSource.SIS_EXTRACT,
    )
    loser_enrollment = fx.create_enrollment(
        api, section["id"], loser["id"], FIRST_ADD_DATE,
        source=EnrollmentSource.SIS_EXTRACT,
    )
    vendor_app = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=10,
        price_per_seat_cents=FULL_PRICE_PER_SEAT,
        grade_band_scope=[GradeBand.ELEMENTARY],
        name="MathBlast",
        vendor_code="MBX",
        seat_model=SeatModel.PER_STUDENT,
        overage_policy=OveragePolicy.BLOCK,
        unmatched_teacher_policy=UnmatchedTeacherPolicy.HOLD_RUN,
    )
    vendor_app = fx.activate_license(api, vendor_app["id"])
    run = fx.open_sync_run(api, vendor_app["id"], run_type=RunType.FULL)
    run = fx.transform_run(api, run["id"])
    fx.set_clock(api, MID_TERM_CLOCK)
    return {
        "school": school,
        "term": term,
        "teacher": teacher,
        "survivor": survivor,
        "loser": loser,
        "section": section,
        "survivor_enrollment": survivor_enrollment,
        "loser_enrollment": loser_enrollment,
        "vendor_app": vendor_app,
        "run": run,
    }


def _open_duplicate_item(api, run_id):
    """The single OPEN duplicate-student item raised against the run."""
    items = fx.queue_items(
        api,
        run_id,
        category=ErrorCategory.DUPLICATE_STUDENT,
        status=ErrorQueueItemStatus.OPEN,
    )
    assert len(items) == 1, f"expected exactly one open duplicate item, got {items}"
    return items[0]


def _merged_world(api):
    """The world after the officer merged the later twin into the earlier one."""
    world = _duplicate_triage_world(api)
    raised = _open_duplicate_item(api, world["run"]["id"])
    world["item"] = fx.merge_duplicate(
        api,
        raised["id"],
        world["survivor"]["id"],
        resolution_note="STU-2002 is the same child as STU-2001",
    )
    return world


def test_a_blocking_duplicate_does_not_stop_the_run_transforming(api):
    """The run transforms with the duplicate still open, and prices both twins.

    "Where the run lands is decided by one category only. The run reaches
    `TRANSFORMED` whenever triage produced no `BLOCKING` item of category
    `UNMATCHED_TEACHER`; a `BLOCKING` `DUPLICATE_STUDENT` ... item does not hold the
    run, so the run transforms with those items still open and it is publish that
    refuses later." The provisional projection dates each student subject by the
    earliest `requested_effective_date` — 2026-08-15, on or before the term's
    2026-09-15 add/drop cutoff — so both seats are priced at the full list price.

    Design: Difficulty/cross_entity_state_dependency/sync_run_publish_blocked_by_error_queue_item_state
    """
    world = _duplicate_triage_world(api)
    run = world["run"]

    assert run["state"] == SyncRunState.TRANSFORMED
    assert run["blocking_error_count"] == 1
    assert run["projected_seat_delta"] == 2
    assert run["projected_charge_cents"] == 2 * FULL_PRICE_PER_SEAT == 2000


def test_the_duplicate_item_names_the_earlier_twin_as_its_subject(api):
    """The queued defect records the collision key and both colliding children.

    A `DUPLICATE_STUDENT` item "is always `BLOCKING` and is raised once per
    duplicate key, the key being the student's `last_name` lower-cased, a pipe, and
    the student's `date_of_birth`. Of the two colliding students ordered by
    `created_at` ascending, the earlier-created one is recorded in
    `subject_student_id` and the later-created one in
    `duplicate_candidate_student_id`; `source_ref` is that duplicate key".

    Design: Difficulty/cross_entity_state_dependency/sync_run_publish_blocked_by_error_queue_item_state
    """
    world = _duplicate_triage_world(api)

    raised = _open_duplicate_item(api, world["run"]["id"])

    assert raised["category"] == ErrorCategory.DUPLICATE_STUDENT
    assert raised["severity"] == ErrorSeverity.BLOCKING
    assert raised["status"] == ErrorQueueItemStatus.OPEN
    assert raised["subject_student_id"] == world["survivor"]["id"]
    assert raised["duplicate_candidate_student_id"] == world["loser"]["id"]
    assert raised["source_ref"] == DUPLICATE_KEY == "nakamura|2016-05-04"


def test_publish_is_refused_while_the_duplicate_item_stays_open(api):
    """The roster of record cannot be written while the queue still holds a blocker.

    Publishing requires "a run with zero `OPEN` items of `BLOCKING` severity in any
    category (`ERR_BLOCKING_ERRORS_UNRESOLVED`)". The refusal happens before any of
    the five publish effects, so the run keeps the state it already had and no
    final billing figure is written.

    Design: Difficulty/cross_entity_state_dependency/sync_run_publish_blocked_by_error_queue_item_state
    """
    world = _duplicate_triage_world(api)

    response = api.publish_sync_run(
        world["run"]["id"], users.DATA_GOVERNANCE_OFFICER
    )
    validate_error(response, errors.ERR_BLOCKING_ERRORS_UNRESOLVED, 409)

    run = fx.read_run(api, world["run"]["id"])
    assert run["state"] == SyncRunState.TRANSFORMED
    assert run["published_charge_cents"] is None


def test_merging_the_duplicate_folds_the_loser_into_the_survivor(api):
    """Triage resolves the collision by retiring the later registration.

    "On success the loser takes the student transition to `MERGED_DUPLICATE` with
    `duplicate_of_student_id` pointed at the survivor", and each of the loser's live
    enrollments "is re-pointed to the surviving student when the survivor holds no
    enrollment in that same section that is not `DROPPED`, and is otherwise moved to
    `DROPPED` with `drop_effective_date` stamped with the clock date". The survivor
    already holds this very section, so the loser's row is dropped on 2026-08-20,
    and "the item moves to `RESOLVED_MERGED`".

    Design: Difficulty/cross_entity_state_dependency/sync_run_publish_blocked_by_error_queue_item_state
    """
    world = _merged_world(api)

    assert world["item"]["status"] == ErrorQueueItemStatus.RESOLVED_MERGED

    loser = validate_success(
        api.get_student(world["loser"]["id"], users.ROSTER_OPERATOR), 200
    )
    assert loser["enrollment_state"] == EnrollmentState.MERGED_DUPLICATE
    assert loser["duplicate_of_student_id"] == world["survivor"]["id"]

    dropped = validate_success(
        api.get_enrollment(world["loser_enrollment"]["id"], users.ROSTER_OPERATOR), 200
    )
    assert dropped["roster_status"] == RosterStatus.DROPPED
    assert dropped["drop_effective_date"] == MID_TERM_DATE == "2026-08-20"


def test_clearing_the_queue_does_not_publish_the_run_by_itself(api):
    """The block lifts, but the run waits for the officer's own publish call.

    After a merge "the run's `blocking_error_count` is recomputed while the run
    again stays" where it was — "triage never re-transforms on its own", and
    publishing is a separate `DataGovernanceOfficer` action on the run. The only
    thing the merge changed about the publish decision is the other entity's
    status.

    Design: Difficulty/cross_entity_state_dependency/sync_run_publish_blocked_by_error_queue_item_state
    """
    world = _merged_world(api)

    run = fx.read_run(api, world["run"]["id"])

    assert run["blocking_error_count"] == 0
    assert run["state"] == SyncRunState.TRANSFORMED
    assert run["published_charge_cents"] is None


def test_the_identical_publish_succeeds_once_the_duplicate_is_merged(api):
    """The same call, on the same run, now bills exactly one surviving seat.

    Publish writes "`published_seat_delta` and `published_charge_cents` ... from the
    final charge variant, evaluated after those two enrollment cascades have been
    applied", and the final variant "dates a student subject by the earliest
    `effective_date`". The merged-away twin's enrollment is `DROPPED` and
    "`DROPPED` rows are excluded" from scope, so one subject remains, dated
    2026-08-20 — inside the add/drop window and therefore at the full list price.

    Design: Difficulty/cross_entity_state_dependency/sync_run_publish_blocked_by_error_queue_item_state
    """
    world = _merged_world(api)

    published = validate_success(
        api.publish_sync_run(world["run"]["id"], users.DATA_GOVERNANCE_OFFICER), 200
    )

    assert published["state"] == SyncRunState.PUBLISHED
    assert published["published_seat_delta"] == 1
    assert published["published_charge_cents"] == FULL_PRICE_PER_SEAT == 1000


def test_publishing_lands_the_surviving_add_on_the_publish_date(api):
    """The survivor's pending add becomes the roster of record as the run publishes.

    First of the five publish effects, "mid-year adds land: every in-scope
    enrollment whose `roster_status` is `PENDING_ADD` and whose
    `requested_effective_date` is on or before the clock date becomes `ACTIVE`,
    with `effective_date` stamped as the later of `requested_effective_date` and the
    clock date" — 2026-08-20. The section then counts that one live row, since
    `active_enrollment_count` excludes the merged-away `DROPPED` one.

    Design: Difficulty/cross_entity_state_dependency/sync_run_publish_blocked_by_error_queue_item_state
    """
    world = _merged_world(api)
    fx.publish_run(api, world["run"]["id"])

    enrollment = validate_success(
        api.get_enrollment(
            world["survivor_enrollment"]["id"], users.ROSTER_OPERATOR
        ),
        200,
    )
    assert enrollment["roster_status"] == RosterStatus.ACTIVE
    assert enrollment["effective_date"] == MID_TERM_DATE == "2026-08-20"

    section = validate_success(
        api.get_section(world["section"]["id"], users.ROSTER_OPERATOR), 200
    )
    assert section["active_enrollment_count"] == 1
