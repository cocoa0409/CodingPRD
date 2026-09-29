"""
The rostering pipeline's deliberate loop: EXTRACTED -> HELD -> TRANSFORMED -> HELD.

One sync run makes two laps around the hold cycle. A section left without a
teacher of record holds the first transform; a second transform is refused while
that triage item is still open; attaching a replacement teacher clears the hold
without transforming anything; the next transform finally projects the roster —
and a staff separation then drags that very same run backwards into the hold. The
run is never superseded and never duplicated: one row records the whole journey.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as errors
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.types import (
    EnrollmentSource,
    ErrorCategory,
    ErrorQueueItemStatus,
    ErrorSeverity,
    GradeBand,
    OveragePolicy,
    RosterHealth,
    RunType,
    SeatModel,
    Subject,
    SyncHealth,
    SyncRunState,
    UnmatchedTeacherPolicy,
)

STARTUP_CLOCK = "2026-08-01T00:00:00Z"
FUTURE_ADD_DATE = "2026-08-15"
SEPARATION_DATE = "2026-08-20"
FULL_PRICE_PER_SEAT = 1000
UNMATCHED_SIS_SECTION_ID = "SEC-3002"


def _pipeline_world(api):
    """
    One elementary building in an ACTIVE Fall 2026 term with two teachers, one
    teacher-matched section, one section deliberately left without a teacher of
    record, one future-dated add, and a HOLD_RUN per-student licence whose FULL
    sync run sits in EXTRACTED having never been transformed.
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
    teacher_a = fx.create_teacher(
        api,
        school["id"],
        sis_staff_id="STF-1001",
        full_name="Dana Reed",
        email="dana.reed@district.k12",
    )
    teacher_b = fx.create_teacher(
        api,
        school["id"],
        sis_staff_id="STF-1002",
        full_name="Owen Pike",
        email="owen.pike@district.k12",
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
    matched_section = fx.create_section(
        api,
        school["id"],
        term["id"],
        primary_teacher_id=teacher_a["id"],
        period_index=3,
        meeting_days=["MON", "WED", "FRI"],
        max_seats=5,
        sis_section_id="SEC-3001",
        course_code="MATH4",
        subject=Subject.MATH,
    )
    unmatched_section = fx.create_section(
        api,
        school["id"],
        term["id"],
        primary_teacher_id=None,
        period_index=5,
        meeting_days=["MON", "WED"],
        max_seats=5,
        sis_section_id=UNMATCHED_SIS_SECTION_ID,
        course_code="READ4",
        subject=Subject.ELA,
    )
    enrollment = fx.create_enrollment(
        api,
        matched_section["id"],
        student["id"],
        FUTURE_ADD_DATE,
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
    return {
        "school": school,
        "term": term,
        "teacher_a": teacher_a,
        "teacher_b": teacher_b,
        "student": student,
        "matched_section": matched_section,
        "unmatched_section": unmatched_section,
        "enrollment": enrollment,
        "vendor_app": vendor_app,
        "run": run,
    }


def _held_world(api):
    """The world after the first transform, which lands the run in HELD."""
    world = _pipeline_world(api)
    world["run"] = fx.transform_run(api, world["run"]["id"])
    return world


def _open_unmatched_item(api, run_id):
    """The single OPEN unmatched-teacher item raised against the run."""
    items = fx.queue_items(
        api,
        run_id,
        category=ErrorCategory.UNMATCHED_TEACHER,
        status=ErrorQueueItemStatus.OPEN,
    )
    assert len(items) == 1, f"expected exactly one open unmatched-teacher item, got {items}"
    return items[0]


def _cleared_world(api):
    """The world after triage attached Owen Pike to the unmatched section."""
    world = _held_world(api)
    raised = _open_unmatched_item(api, world["run"]["id"])
    world["item"] = fx.resolve_match(
        api,
        raised["id"],
        world["teacher_b"]["id"],
        resolution_note="reassigned to Owen Pike",
    )
    return world


def _second_lap_world(api):
    """The world after the cleared run made its second lap to TRANSFORMED."""
    world = _cleared_world(api)
    world["run"] = fx.transform_run(api, world["run"]["id"])
    return world


def test_first_transform_holds_the_run_and_raises_a_blocking_triage_item(api):
    """A section with no teacher of record holds the run on its very first pass.

    Triage raises an `UNMATCHED_TEACHER` item "for every in-scope section whose
    `primary_teacher_id` is null", and that item's severity is "`BLOCKING` when
    the license's `unmatched_teacher_policy` is `HOLD_RUN`". Because "triage did
    produce at least one `BLOCKING` `UNMATCHED_TEACHER` item, the run goes to
    `HELD` instead", where it "leaves both projected figures null" while
    "`transform_count` increases by one" and the counts are recomputed "as the
    numbers of its `OPEN` items of `BLOCKING` and `ADVISORY` severity".

    Design: Difficulty/non_linear_state_machine/sync_run_held_to_transformed_cycle
    """
    world = _held_world(api)
    run = world["run"]

    assert run["state"] == SyncRunState.HELD
    assert run["transform_count"] == 1
    assert run["blocking_error_count"] == 1
    assert run["advisory_error_count"] == 0
    assert run["projected_charge_cents"] is None
    assert run["projected_seat_delta"] is None

    raised = _open_unmatched_item(api, run["id"])
    assert raised["category"] == ErrorCategory.UNMATCHED_TEACHER
    assert raised["severity"] == ErrorSeverity.BLOCKING
    assert raised["status"] == ErrorQueueItemStatus.OPEN
    assert raised["subject_section_id"] == world["unmatched_section"]["id"]
    assert raised["source_ref"] == UNMATCHED_SIS_SECTION_ID


def test_the_held_run_marks_its_licence_as_blocked(api):
    """The licence advertises the hold to the district while the defect is open.

    On either transform outcome "the license's `sync_health` becomes `OK` when no
    `OPEN` `BLOCKING` item remains on the run and `BLOCKED` when one does" — and
    one does, so the vendor licence reports a blocked pipeline.

    Design: Difficulty/non_linear_state_machine/sync_run_held_to_transformed_cycle
    """
    world = _held_world(api)

    vendor_app = fx.read_vendor_app(api, world["vendor_app"]["id"])

    assert vendor_app["sync_health"] == SyncHealth.BLOCKED


def test_a_second_transform_is_refused_while_the_unmatched_teacher_stays_open(api):
    """The loop refuses to spin: a held run cannot be re-transformed uncleared.

    "A `HELD` run may be transformed again, but only once the triage that held it
    has been cleared: there must be zero items of this run with `category` of
    `UNMATCHED_TEACHER`, `severity` of `BLOCKING` and `status` of `OPEN`, else the
    re-transform is refused with `ERR_BLOCKING_ERRORS_UNRESOLVED`." The refusal
    leaves the run exactly where it was — no lap is recorded for a rejected call.

    Design: Difficulty/non_linear_state_machine/sync_run_held_to_transformed_cycle
    """
    world = _held_world(api)

    response = api.transform_sync_run(world["run"]["id"], users.ROSTER_OPERATOR)
    validate_error(response, errors.ERR_BLOCKING_ERRORS_UNRESOLVED, 409)

    run = fx.read_run(api, world["run"]["id"])
    assert run["transform_count"] == 1
    assert run["state"] == SyncRunState.HELD


def test_attaching_a_replacement_teacher_clears_the_hold_without_transforming(api):
    """Triage repairs the roster but never moves the run for the operator.

    On a successful match "the subject section's `primary_teacher_id` is set to
    the replacement and its `roster_health` returns to `OK`, and the item moves
    from `OPEN` to `RESOLVED_MATCHED`"; "the run's `blocking_error_count` is
    recomputed — but the run stays `HELD`: returning to `TRANSFORMED` is an
    explicit operator action, and triage never re-transforms on its own."

    Design: Difficulty/non_linear_state_machine/sync_run_held_to_transformed_cycle
    """
    world = _cleared_world(api)

    assert world["item"]["status"] == ErrorQueueItemStatus.RESOLVED_MATCHED

    section = validate_success(
        api.get_section(world["unmatched_section"]["id"], users.ROSTER_OPERATOR), 200
    )
    assert section["primary_teacher_id"] == world["teacher_b"]["id"]
    assert section["roster_health"] == RosterHealth.OK

    run = fx.read_run(api, world["run"]["id"])
    assert run["blocking_error_count"] == 0
    assert run["state"] == SyncRunState.HELD
    assert run["transform_count"] == 1


def test_the_cleared_run_completes_its_second_lap_to_transformed(api):
    """The repaired roster transforms on the operator's next explicit pass.

    "A permitted re-transform re-runs triage against current data" and "the run
    reaches `TRANSFORMED` whenever triage produced no `BLOCKING` item of category
    `UNMATCHED_TEACHER`". `transform_count` "records how many laps a run made
    around the `TRANSFORMED` -> `HELD` -> `TRANSFORMED` cycle", so it now reads 2.
    The transformed run counts two feed sections plus the one in-scope student and
    no teachers under a `PER_STUDENT` licence, and prices that one genuinely new
    seat at the full 1000-cent list price because its requested date of
    2026-08-15 is on or before the term's 2026-09-15 add/drop cutoff.

    Design: Difficulty/non_linear_state_machine/sync_run_held_to_transformed_cycle
    """
    world = _second_lap_world(api)
    run = world["run"]

    assert run["state"] == SyncRunState.TRANSFORMED
    assert run["transform_count"] == 2
    assert run["transformed_record_count"] == 3
    assert run["projected_seat_delta"] == 1
    assert run["projected_charge_cents"] == FULL_PRICE_PER_SEAT == 1000

    vendor_app = fx.read_vendor_app(api, world["vendor_app"]["id"])
    assert vendor_app["sync_health"] == SyncHealth.OK


def test_a_staff_separation_drags_the_transformed_run_back_into_the_hold(api):
    """The run falls backwards into the loop with no operator doing anything.

    A separation sets the affected section's `roster_health` to
    `UNMATCHED_TEACHER`, raises a `BLOCKING` item against the in-flight run, and
    "any such run that had already reached `TRANSFORMED` falls back to `HELD` with
    its `projected_seat_delta` and `projected_charge_cents` reset to null, because
    the projection it published to the operator is no longer trustworthy"; the
    licence's "`sync_health` becomes `BLOCKED`". The two completed laps stand:
    `transform_count` is a history, not a state.

    Design: Difficulty/non_linear_state_machine/sync_run_held_to_transformed_cycle
    """
    world = _second_lap_world(api)

    fx.separate_teacher(api, world["teacher_b"]["id"], SEPARATION_DATE)

    run = fx.read_run(api, world["run"]["id"])
    assert run["state"] == SyncRunState.HELD
    assert run["blocking_error_count"] == 1
    assert run["projected_charge_cents"] is None
    assert run["projected_seat_delta"] is None
    assert run["transform_count"] == 2

    vendor_app = fx.read_vendor_app(api, world["vendor_app"]["id"])
    assert vendor_app["sync_health"] == SyncHealth.BLOCKED


def test_the_whole_cycle_is_recorded_on_a_single_reused_sync_run(api):
    """Looping is not restarting: the licence still shows exactly one run.

    Only opening a new run pre-empts others — "every other run of the same license
    sitting in `EXTRACTED`, `TRANSFORMED` or `HELD` becomes `SUPERSEDED`" — and no
    transform, triage resolution or separation opens one. Two laps and a
    backwards fall therefore leave the licence with the one run it started with.

    Design: Difficulty/non_linear_state_machine/sync_run_held_to_transformed_cycle
    """
    world = _second_lap_world(api)
    fx.separate_teacher(api, world["teacher_b"]["id"], SEPARATION_DATE)

    rows, meta = validate_paginated(
        api.list_sync_runs(
            users.ROSTER_OPERATOR, vendor_app_id=world["vendor_app"]["id"]
        )
    )

    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == world["run"]["id"]
