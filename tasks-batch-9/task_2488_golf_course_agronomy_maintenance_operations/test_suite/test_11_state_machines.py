"""Transitions taken and transitions refused: the plan's review cycle, the record
dimension's terminal state, the weather event's one-way clear, and the two cascades that
move a turf area's agronomic status without any client asking."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_APPLICATION_STATE_INVALID,
    ERR_PLAN_STATE_INVALID,
    ERR_REVISION_LIMIT_REACHED,
    ERR_WEATHER_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_2dp,
    assert_3dp,
    assert_application,
    assert_instant,
    assert_maintenance_window,
    assert_plan,
    assert_plan_task,
    assert_total_count,
    assert_turf_area,
    assert_weather_event,
)
from test_helpers.factories import (
    AERATION,
    MOWING,
    STORM_CLEANUP,
    TOPDRESSING,
    plan_task_payload,
    return_plan_payload,
    void_payload,
)
from test_helpers.fixtures import (
    approve_plan,
    clear_weather_event,
    complete_maintenance_window,
    create_applicator,
    create_course,
    create_green,
    create_maintenance_window,
    create_plan,
    create_plan_task,
    create_play_event,
    create_product,
    declare_weather_event,
    get_applicator,
    get_application,
    get_course,
    get_maintenance_window,
    get_plan,
    get_plan_task,
    get_play_event,
    get_turf_area,
    list_plan_tasks,
    record_application,
    return_plan,
    schedule_plan_task,
    set_clock,
    start_maintenance_window,
    submit_plan,
    void_application,
)
from test_helpers.test_users import (
    AGRO_2_HEADERS,
    AGRO_HEADERS,
    AGRONOMIST_PRIMARY,
    AGRONOMIST_SECONDARY,
    SUPER_HEADERS,
    make_applicator_headers,
)
from test_helpers.types import (
    AgronomicStatus,
    LicenseCategory,
    LicenseStatus,
    PlanStatus,
    PlanTaskStatus,
    PlayEventStatus,
    PlayEventType,
    PlayPosture,
    RecordStatus,
    VoidReason,
    WeatherEventStatus,
    WeatherEventType,
    WindowStatus,
)


def _draft_plan_with_one_aeration_task():
    """A DRAFT 2026 plan carrying a single PLANNED aeration task, which is what makes it
    submittable."""
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    plan = create_plan(course["id"], plan_year=2026, nitrogen_budget_lb=40.0)
    task = create_plan_task(plan["id"], green7["id"], task_type=AERATION)
    return course, green7, plan, task


def _voided_record_and_its_would_be_verifier():
    """Dana's spray, voided for a data-entry error, and Miguel who never got to sign it
    off."""
    set_clock("2026-08-01T06:00:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    dana = create_applicator()
    miguel = create_applicator(
        full_name="Miguel Santos",
        license_number="OR-CAT3-11002",
        license_category=LicenseCategory.CAT_3_TURF.value,
        license_expires_on="2028-01-31",
    )
    urea = create_product()
    record = record_application(
        green7["id"], urea["id"], dana["id"], "2026-08-01T06:00:00Z",
        rate_lb_per_acre=200, wind_speed_mph=5, distance_to_water_ft=40,
    )
    voided = void_application(record["id"], VoidReason.DATA_ENTRY_ERROR.value)
    return green7, dana, miguel, voided


def _two_greens_under_two_different_crews():
    """An aeration crew on the hole 7 green and a mowing crew on the hole 12 green, booked
    over the identical two hours."""
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    green12 = create_green(course["id"], hole_number=12, area_sq_ft=5000,
                           distance_to_water_ft=200)
    aeration = create_maintenance_window(
        course["id"], green7["id"], AERATION,
        "2026-08-05T06:00:00Z", "2026-08-05T08:00:00Z", crew_size=3,
    )
    mowing = create_maintenance_window(
        course["id"], green12["id"], MOWING,
        "2026-08-05T06:00:00Z", "2026-08-05T08:00:00Z", crew_size=2,
    )
    return green7, green12, aeration, mowing


def _storm_ready_course():
    """One green carrying a bound aeration task and a storm-cleanup crew, a second green
    carrying only a mowing crew, and a round posted for the afternoon."""
    set_clock("2026-08-01T06:00:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    green12 = create_green(course["id"], hole_number=12, area_sq_ft=5000,
                           distance_to_water_ft=200)
    plan = create_plan(course["id"], plan_year=2026, nitrogen_budget_lb=40.0)
    task = create_plan_task(
        plan["id"], green7["id"], task_type=AERATION,
        planned_window_start="2026-08-01T00:00:00Z",
        planned_window_end="2026-08-02T00:00:00Z",
    )
    aeration = create_maintenance_window(
        course["id"], green7["id"], AERATION,
        "2026-08-01T08:00:00Z", "2026-08-01T10:00:00Z", crew_size=3,
    )
    cleanup = create_maintenance_window(
        course["id"], green7["id"], STORM_CLEANUP,
        "2026-08-01T11:00:00Z", "2026-08-01T13:00:00Z", crew_size=5,
    )
    mowing = create_maintenance_window(
        course["id"], green12["id"], MOWING,
        "2026-08-01T08:00:00Z", "2026-08-01T10:00:00Z", crew_size=2,
    )
    round_posted = create_play_event(
        course["id"],
        event_type=PlayEventType.STANDARD_TEE_TIMES.value,
        start_at="2026-08-01T14:00:00Z",
        end_at="2026-08-01T18:00:00Z",
        holes_in_play=18,
        field_size=80,
    )
    submitted = submit_plan(plan["id"])
    active = approve_plan(plan["id"], submitted["version"])
    schedule_plan_task(task["id"], aeration["id"], active["version"])
    return course, green7, green12, plan, task, aeration, cleanup, mowing, round_posted


# --------------------------------------------------------------------------
# The plan's review cycle
# --------------------------------------------------------------------------
def test_submitting_a_draft_plan_stamps_the_submitter_and_leaves_the_task_alone():
    """The plan moves out of `DRAFT` on its second version carrying the submitting caller's
    identifier, while the task it was submitted for is untouched.

    "Submission moves the plan `DRAFT → SUBMITTED`. It is performed by an `Agronomist`,
    requires the plan to be in `DRAFT`, and requires at least one task on the plan to exist
    in status `PLANNED`. The caller's `X-User-ID` is captured into `submitted_by_user_id` and
    the plan's `version` is incremented by 1."

    Design: Corner/state_machines/plan_submit_advances_to_submitted_and_records_the_submitter
    """
    _course, _green7, plan, task = _draft_plan_with_one_aeration_task()
    assert_plan(plan, expected_version=1, status=PlanStatus.DRAFT.value)

    submitted = submit_plan(plan["id"])

    assert_plan(
        submitted,
        expected_version=2,
        status=PlanStatus.SUBMITTED.value,
        submitted_by_user_id=AGRONOMIST_PRIMARY,
        return_count=0,
        committed_nitrogen_lb=0.00,
    )
    assert_plan_task(
        get_plan_task(task["id"]),
        expected_version=1,
        status=PlanTaskStatus.PLANNED.value,
    )


def test_an_active_plan_can_neither_be_resubmitted_nor_take_a_new_task():
    """`ACTIVE` is not the state either write names, so both answer 409
    `ERR_PLAN_STATE_INVALID` and the plan stands at the version approval left it on.

    "Submit, return and approve each require the plan to be in the state their transition
    names — `DRAFT` for submit, `SUBMITTED` for return and for approve — and a plan in any
    other state yields `ERR_PLAN_STATE_INVALID`."

    Design: Corner/state_machines/submit_of_an_active_plan_is_rejected
    """
    _course, green7, plan, task = _draft_plan_with_one_aeration_task()
    submitted = submit_plan(plan["id"])
    assert submitted["version"] == 2
    active = approve_plan(plan["id"], submitted["version"])
    assert active["version"] == 3

    refused_submit = api_client.submit_plan(plan["id"], AGRO_HEADERS)
    validate_error(refused_submit, ERR_PLAN_STATE_INVALID, 409)

    refused_task = api_client.create_plan_task(
        plan_task_payload(plan["id"], green7["id"], task_type=TOPDRESSING),
        AGRO_HEADERS,
    )
    validate_error(refused_task, ERR_PLAN_STATE_INVALID, 409)

    assert_plan(
        get_plan(plan["id"]), expected_version=3, status=PlanStatus.ACTIVE.value
    )
    rows, meta = list_plan_tasks(plan_id=plan["id"])
    assert_total_count(meta, 1)
    assert [row["id"] for row in rows] == [task["id"]]


def test_the_third_return_is_refused_and_the_plan_stays_submitted():
    """Two returns are spent, each clearing the submitter that the next submit re-stamps, and
    the third attempt answers 409 `ERR_REVISION_LIMIT_REACHED`.

    "The revision cycle is capped: `return_count` must be strictly less than 2 for a return
    to be permitted, so the first and second returns succeed and leave the count at 1 and
    then 2, while a third return attempt is refused with `ERR_REVISION_LIMIT_REACHED`
    (HTTP 409) and leaves the plan in `SUBMITTED`."

    Design: Corner/state_machines/plan_return_cycle_stops_at_the_revision_limit
    """
    _course, _green7, plan, _task = _draft_plan_with_one_aeration_task()

    submit_plan(plan["id"])
    first_return = return_plan(plan["id"], return_note="Tighten the aeration timing.")
    assert_plan(
        first_return,
        status=PlanStatus.DRAFT.value,
        return_count=1,
        submitted_by_user_id=None,
    )

    second_submit = submit_plan(plan["id"], headers=AGRO_2_HEADERS)
    assert second_submit["submitted_by_user_id"] == AGRONOMIST_SECONDARY
    second_return = return_plan(plan["id"], return_note="Still not there.")
    assert second_return["return_count"] == 2

    third_submit = submit_plan(plan["id"])
    assert third_submit["version"] == 6

    refused = api_client.return_plan(
        plan["id"], return_plan_payload("One more pass."), SUPER_HEADERS
    )
    validate_error(refused, ERR_REVISION_LIMIT_REACHED, 409)

    assert_plan(
        get_plan(plan["id"]),
        expected_version=6,
        status=PlanStatus.SUBMITTED.value,
        return_count=2,
        submitted_by_user_id=AGRONOMIST_PRIMARY,
    )


# --------------------------------------------------------------------------
# Terminal states
# --------------------------------------------------------------------------
def test_a_voided_record_refuses_both_a_second_void_and_a_verification():
    """`VOIDED` is terminal on the record dimension, so both writes answer 409
    `ERR_APPLICATION_STATE_INVALID` and the rejected safety void suspends nobody.

    "**Voiding** is reserved to the `Superintendent` and moves the record dimension to
    `VOIDED` from either `RECORDED` or `VERIFIED` — `RECORDED → VOIDED` and
    `VERIFIED → VOIDED` are both permitted and behave identically; a record that is already
    `VOIDED` yields `ERR_APPLICATION_STATE_INVALID`."

    Design: Corner/state_machines/a_voided_application_cannot_be_voided_or_verified_again
    """
    green7, dana, miguel, voided = _voided_record_and_its_would_be_verifier()

    refused_void = api_client.void_application(
        voided["id"], void_payload(VoidReason.SAFETY_VIOLATION.value), SUPER_HEADERS
    )
    validate_error(refused_void, ERR_APPLICATION_STATE_INVALID, 409)

    refused_verify = api_client.verify_application(
        voided["id"], make_applicator_headers(miguel["id"])
    )
    validate_error(refused_verify, ERR_APPLICATION_STATE_INVALID, 409)

    assert_application(
        get_application(voided["id"]),
        expected_version=voided["version"],
        record_status=RecordStatus.VOIDED.value,
        void_reason=VoidReason.DATA_ENTRY_ERROR.value,
        verified_by_applicator_id=None,
    )
    assert get_applicator(dana["id"])["license_status"] == LicenseStatus.ACTIVE.value
    assert_3dp(
        get_turf_area(green7["id"])["nitrogen_applied_lb_per_1000_ytd"], 0.000
    )


def test_clearing_a_cleared_weather_event_is_refused_and_writes_nothing():
    """The clear is not idempotent: the second call answers 409 `ERR_WEATHER_STATE_INVALID`
    and leaves the first `cleared_at` and the once-relaxed course posture as they were.

    "The event must be `ACTIVE`, else `ERR_WEATHER_STATE_INVALID` (HTTP 409); an event that
    does not exist is `ERR_WEATHER_EVENT_NOT_FOUND`."

    Design: Corner/state_machines/clearing_an_already_cleared_weather_event_is_rejected
    """
    course = create_course(annual_water_allocation_gal=500000)
    rain = declare_weather_event(
        course["id"], WeatherEventType.HEAVY_RAIN.value, "2026-08-01T12:00:00Z",
        expected_course_version=course["version"],
    )
    cleared = clear_weather_event(rain["id"])
    assert_instant(cleared["cleared_at"], "2026-08-01T00:00:00Z")

    refused = api_client.clear_weather_event(rain["id"], SUPER_HEADERS)
    validate_error(refused, ERR_WEATHER_STATE_INVALID, 409)

    assert_weather_event(
        cleared,
        status=WeatherEventStatus.CLEARED.value,
        cleared_at="2026-08-01T00:00:00Z",
    )
    reread_course = get_course(course["id"])
    assert reread_course["play_posture"] == PlayPosture.OPEN.value
    assert reread_course["version"] == 3


# --------------------------------------------------------------------------
# Statuses moved by cascade rather than by request
# --------------------------------------------------------------------------
def test_only_the_aeration_crew_puts_its_green_under_renovation():
    """Starting the aeration window renovates its green and completing it hands the green
    back, while the mowing crew's green never leaves version 1.

    "On success the window's `version` is incremented by 1, and when the task class is
    `AERATION` the turf area's `agronomic_status` becomes `UNDER_RENOVATION` with that area's
    `version` incremented by 1."

    Design: Corner/state_machines/aeration_window_flips_the_turf_area_into_renovation_and_back
    """
    green7, green12, aeration, mowing = _two_greens_under_two_different_crews()
    assert_2dp(aeration["crew_hours"], 6.00)
    assert_2dp(mowing["crew_hours"], 4.00)

    start_maintenance_window(aeration["id"])
    assert_turf_area(
        get_turf_area(green7["id"]),
        expected_version=2,
        agronomic_status=AgronomicStatus.UNDER_RENOVATION.value,
    )

    start_maintenance_window(mowing["id"])
    assert_turf_area(
        get_turf_area(green12["id"]),
        expected_version=1,
        agronomic_status=AgronomicStatus.ACTIVE.value,
    )

    complete_maintenance_window(aeration["id"])
    assert_turf_area(
        get_turf_area(green7["id"]),
        expected_version=3,
        agronomic_status=AgronomicStatus.ACTIVE.value,
    )

    complete_maintenance_window(mowing["id"])
    assert get_maintenance_window(aeration["id"])["status"] == (
        WindowStatus.COMPLETED.value
    )
    assert get_maintenance_window(mowing["id"])["status"] == WindowStatus.COMPLETED.value
    assert get_turf_area(green12["id"])["version"] == 1


def test_storm_damage_cancels_the_named_greens_work_and_the_clear_only_restores_the_green():
    """The declaration flags the named green out of play, cancels its non-cleanup window and
    the task that window carried, and closes the plan; the clear restores the green and the
    posture but leaves every terminal row cancelled.

    "A `STORM_DAMAGE` declaration additionally sets every turf area named in
    `affected_turf_area_ids` to `agronomic_status` `OUT_OF_PLAY`, incrementing each of those
    areas' `version` by 1, and cancels every non-`STORM_CLEANUP` maintenance window on those
    areas that stands in `SCHEDULED` or `DEFERRED`, which in turn cancels the plan tasks those
    windows carried."

    Design: Corner/state_machines/storm_damage_cancels_windows_task_and_play_then_clear_restores_the_green
    """
    (course, green7, green12, plan, task, aeration, cleanup, mowing,
     round_posted) = _storm_ready_course()

    storm = declare_weather_event(
        course["id"], WeatherEventType.STORM_DAMAGE.value, "2026-08-01T18:00:00Z",
        affected_turf_area_ids=[green7["id"]],
    )

    assert_weather_event(
        storm,
        declared_at="2026-08-01T06:00:00Z",
        deferred_window_count=0,
    )
    assert get_course(course["id"])["play_posture"] == PlayPosture.CLOSED.value
    assert get_turf_area(green7["id"])["agronomic_status"] == (
        AgronomicStatus.OUT_OF_PLAY.value
    )
    assert get_turf_area(green12["id"])["agronomic_status"] == (
        AgronomicStatus.ACTIVE.value
    )
    assert_maintenance_window(
        get_maintenance_window(aeration["id"]),
        status=WindowStatus.CANCELLED.value,
        plan_task_id=None,
    )
    assert get_maintenance_window(cleanup["id"])["status"] == (
        WindowStatus.SCHEDULED.value
    )
    assert get_maintenance_window(mowing["id"])["status"] == WindowStatus.SCHEDULED.value
    assert get_plan_task(task["id"])["status"] == PlanTaskStatus.CANCELLED.value
    assert_plan(
        get_plan(plan["id"]),
        status=PlanStatus.CLOSED.value,
        committed_nitrogen_lb=0.00,
    )
    assert get_play_event(round_posted["id"])["status"] == (
        PlayEventStatus.CANCELLED.value
    )

    clear_weather_event(storm["id"])

    assert get_turf_area(green7["id"])["agronomic_status"] == (
        AgronomicStatus.ACTIVE.value
    )
    assert get_course(course["id"])["play_posture"] == PlayPosture.OPEN.value
    assert get_maintenance_window(aeration["id"])["status"] == (
        WindowStatus.CANCELLED.value
    )
    assert get_plan_task(task["id"])["status"] == PlanTaskStatus.CANCELLED.value
    assert get_play_event(round_posted["id"])["status"] == (
        PlayEventStatus.CANCELLED.value
    )
