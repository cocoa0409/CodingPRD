"""Four boundaries pinned at their exact endpoints: a nitrogen budget met to the nickel,
a re-entry instant met to the minute, a water posture met to the tenth of a percent, and a
certification quorum met by counting greens."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_INSUFFICIENT_READINGS,
    ERR_NITROGEN_BUDGET_EXCEEDED,
    ERR_REI_ACTIVE,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_instant,
    assert_maintenance_window,
    assert_plan,
    assert_play_event,
    assert_total_count,
)
from test_helpers.factories import (
    FERTILITY,
    MOWING,
    maintenance_window_payload,
    schedule_task_payload,
)
from test_helpers.fixtures import (
    approve_plan,
    certify_conditions,
    complete_irrigation_run,
    create_applicator,
    create_course,
    create_green,
    create_irrigation_run,
    create_maintenance_window,
    create_play_event,
    create_playability_reading,
    create_plan,
    create_plan_task,
    create_product,
    create_pump_station,
    get_course,
    get_maintenance_window,
    get_plan,
    get_plan_task,
    get_play_event,
    get_pump_station,
    get_turf_area,
    list_maintenance_windows,
    record_application,
    revise_water_allocation,
    schedule_plan_task,
    set_clock,
    submit_plan,
)
from test_helpers.test_users import AGRO_HEADERS, TOURN_HEADERS
from test_helpers.types import (
    PlanTaskStatus,
    PlayEventStatus,
    PlayEventType,
    PumpStationStatus,
    ReadinessStatus,
    SourceType,
    WaterPosture,
    WindowStatus,
)

PERFECT_READING = {"green_speed_ft": 11.0, "firmness_gravities": 1.35,
                   "moisture_pct": 18.0}


def _plan_budgeted_to_the_exact_penny():
    """A 7.91 lb budget, three fertility tasks committing 4.68, 3.23 and 0.05, three
    windows, and the first task already bound."""
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    green12 = create_green(course["id"], hole_number=12, area_sq_ft=4300,
                           distance_to_water_ft=200)
    green3 = create_green(course["id"], hole_number=3, area_sq_ft=5000,
                          distance_to_water_ft=150)
    plan = create_plan(course["id"], plan_year=2026, nitrogen_budget_lb=7.91)
    task1 = create_plan_task(plan["id"], green7["id"], nitrogen_lb_per_1000=0.85)
    task2 = create_plan_task(plan["id"], green12["id"], nitrogen_lb_per_1000=0.75)
    task3 = create_plan_task(plan["id"], green3["id"], nitrogen_lb_per_1000=0.01)
    win1 = create_maintenance_window(
        course["id"], green7["id"], FERTILITY,
        "2026-08-12T05:00:00Z", "2026-08-12T07:00:00Z",
    )
    win2 = create_maintenance_window(
        course["id"], green12["id"], FERTILITY,
        "2026-08-13T05:00:00Z", "2026-08-13T07:00:00Z",
    )
    win3 = create_maintenance_window(
        course["id"], green3["id"], FERTILITY,
        "2026-08-14T05:00:00Z", "2026-08-14T07:00:00Z",
    )
    submitted = submit_plan(plan["id"])
    active = approve_plan(plan["id"], submitted["version"])
    schedule_plan_task(task1["id"], win1["id"], active["version"])
    return plan, (task1, task2, task3), (win1, win2, win3)


def _green_under_a_twenty_four_hour_reentry_interval():
    """One posted 24 hour product on hole 7 at 2026-08-10T06:00:00Z, so the area's gate
    stands at exactly 2026-08-11T06:00:00Z."""
    set_clock("2026-08-10T06:00:00Z")
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    dana = create_applicator()
    fungicide = create_product(
        trade_name="Fairway Guard SC",
        epa_reg_no="1234-56",
        rei_hours=24,
        min_buffer_ft=25,
        max_wind_speed_mph=12,
        posting_required=True,
        nitrogen_pct=0,
    )
    record = record_application(
        green7["id"], fungicide["id"], dana["id"], "2026-08-10T06:00:00Z",
        rate_lb_per_acre=200, wind_speed_mph=5, distance_to_water_ft=40,
    )
    return course, green7, record


def _course_holding_exactly_six_hundred_eighty_two_gallons():
    """An 853.0 gal allocation with 682.0 gal withdrawn, which is 79.953 percent."""
    course = create_course(
        annual_water_allocation_gal=853.0,
        water_restricted_threshold_pct=80,
        water_suspended_threshold_pct=100,
    )
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    station = create_pump_station(
        course["id"],
        source_type=SourceType.WELL.value,
        max_flow_gpm=300,
        max_concurrent_zones=2,
        daily_withdrawal_cap_gal=10000,
    )
    run = create_irrigation_run(
        station["id"], green7["id"],
        "2026-08-05T04:00:00Z", "2026-08-05T05:00:00Z", 20,
        expected_pump_station_version=station["version"],
    )
    completed = complete_irrigation_run(run["id"])
    return course, station, run, completed


def _tournament_with_only_two_measured_greens():
    """Three ACTIVE greens on the course but perfect readings on only two of them."""
    set_clock("2026-08-05T08:00:00Z")
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    green12 = create_green(course["id"], hole_number=12, area_sq_ft=4300,
                           distance_to_water_ft=200)
    green3 = create_green(course["id"], hole_number=3, area_sq_ft=5000,
                          distance_to_water_ft=150)
    event = create_play_event(
        course["id"],
        event_type=PlayEventType.TOURNAMENT_ROUND.value,
        start_at="2026-08-05T14:00:00Z",
        end_at="2026-08-05T19:00:00Z",
        holes_in_play=18,
        field_size=120,
    )
    create_playability_reading(green7["id"], "2026-08-05T06:00:00Z", **PERFECT_READING)
    create_playability_reading(green12["id"], "2026-08-05T06:00:00Z", **PERFECT_READING)
    return event, green3


# --------------------------------------------------------------------------
# The nitrogen budget's inclusive upper endpoint
# --------------------------------------------------------------------------
def test_a_commitment_landing_exactly_on_the_budget_is_accepted():
    """4.68 plus 3.23 is 7.91, precisely the budget, so the second binding succeeds and
    the ledger sits flush against its ceiling.

    "The budget comparison is inclusive, so a committed total exactly equal to the budget
    is allowed."

    Design: Difficulty/boundary_precision_check/plan_ledger_exactly_at_budget_then_one_nickel_over
    """
    plan, tasks, windows = _plan_budgeted_to_the_exact_penny()
    _task1, task2, _task3 = tasks

    after_first = get_plan(plan["id"])
    assert_2dp(after_first["committed_nitrogen_lb"], 4.68)

    schedule_plan_task(task2["id"], windows[1]["id"], after_first["version"])

    at_budget = get_plan(plan["id"])
    assert_2dp(at_budget["committed_nitrogen_lb"], 7.91)
    assert_2dp(at_budget["nitrogen_budget_lb"], 7.91)
    assert get_plan_task(task2["id"])["status"] == PlanTaskStatus.SCHEDULED.value


def test_one_further_nickel_of_nitrogen_is_refused():
    """With the ledger flush at 7.91 a 0.05 lb task would make 7.96, so the third binding
    answers 422 `ERR_NITROGEN_BUDGET_EXCEEDED` and changes nothing.

    "and the resulting committed total must not exceed the plan's `nitrogen_budget_lb`,
    else `ERR_NITROGEN_BUDGET_EXCEEDED`"

    Design: Difficulty/boundary_precision_check/plan_ledger_exactly_at_budget_then_one_nickel_over
    """
    plan, tasks, windows = _plan_budgeted_to_the_exact_penny()
    _task1, task2, task3 = tasks

    schedule_plan_task(task2["id"], windows[1]["id"], get_plan(plan["id"])["version"])
    at_budget = get_plan(plan["id"])

    refused = api_client.schedule_plan_task(
        task3["id"],
        schedule_task_payload(windows[2]["id"], at_budget["version"]),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_NITROGEN_BUDGET_EXCEEDED, 422)

    reread_task3 = get_plan_task(task3["id"])
    assert reread_task3["status"] == PlanTaskStatus.PLANNED.value
    assert_2dp(reread_task3["commitment_lb"], 0.05)
    assert_plan(
        get_plan(plan["id"]),
        expected_version=at_budget["version"],
        committed_nitrogen_lb=7.91,
    )
    assert_maintenance_window(
        get_maintenance_window(windows[2]["id"]), plan_task_id=None
    )


# --------------------------------------------------------------------------
# The re-entry instant's inclusive lower endpoint
# --------------------------------------------------------------------------
def test_a_window_starting_one_minute_before_reentry_expiry_is_refused():
    """The record's gate lands on 2026-08-11T06:00:00Z, and a crew booked to start at
    05:59Z is turned away with 409 `ERR_REI_ACTIVE`.

    "Fourth, the record's own `rei_expires_at` is `applied_at` advanced by the product's
    `rei_hours` hours."

    Design: Difficulty/boundary_precision_check/window_start_exactly_at_rei_expiry_is_admitted
    """
    course, green7, record = _green_under_a_twenty_four_hour_reentry_interval()

    assert_instant(record["rei_expires_at"], "2026-08-11T06:00:00Z")
    assert_instant(
        get_turf_area(green7["id"])["rei_expires_at"], "2026-08-11T06:00:00Z"
    )

    refused = api_client.create_maintenance_window(
        maintenance_window_payload(
            course["id"], green7["id"], MOWING,
            "2026-08-11T05:59:00Z", "2026-08-11T07:00:00Z", crew_size=3,
        ),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_REI_ACTIVE, 409)

    _rows, meta = list_maintenance_windows(turf_area_id=green7["id"])
    assert_total_count(meta, 0)


def test_a_window_starting_exactly_at_reentry_expiry_is_admitted():
    """Booking the same crew one minute later, at the expiry instant itself, succeeds and
    a two hour window with a crew of 3 carries 6.00 crew hours.

    "The comparison is inclusive, and the whole rule is vacuous when the area's
    `rei_expires_at` is null."

    Design: Difficulty/boundary_precision_check/window_start_exactly_at_rei_expiry_is_admitted
    """
    course, green7, _record = _green_under_a_twenty_four_hour_reentry_interval()

    admitted = create_maintenance_window(
        course["id"], green7["id"], MOWING,
        "2026-08-11T06:00:00Z", "2026-08-11T08:00:00Z", crew_size=3,
    )
    assert_maintenance_window(
        admitted,
        expected_version=1,
        status=WindowStatus.SCHEDULED.value,
        crew_hours=6.00,
        deferral_count=0,
    )

    _rows, meta = list_maintenance_windows(turf_area_id=green7["id"])
    assert_total_count(meta, 1)


# --------------------------------------------------------------------------
# The water posture's two inclusive thresholds
# --------------------------------------------------------------------------
def test_seventy_nine_point_nine_five_three_percent_of_the_allocation_is_still_open():
    """682.0 gallons against 853.0 is 79.953 percent, below the restricted threshold, so
    the posture holds at `OPEN` and the station stays `ONLINE`.

    "Otherwise, if it is greater than or equal to `water_restricted_threshold_pct` the
    posture is `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/water_posture_flips_at_exactly_eighty_percent_of_allocation
    """
    course, station, _run, completed = (
        _course_holding_exactly_six_hundred_eighty_two_gallons()
    )

    assert_1dp(completed["allotted_gal"], 682.0)
    assert_2dp(completed["flow_gpm"], 11.37)
    assert_1dp(completed["volume_gal"], 682.0)

    before = get_course(course["id"])
    assert_1dp(before["water_used_gal"], 682.0)
    assert before["water_posture"] == WaterPosture.OPEN.value
    assert get_pump_station(station["id"])["status"] == PumpStationStatus.ONLINE.value

    revise_water_allocation(course["id"], annual_water_allocation_gal=852.5)

    restricted = get_course(course["id"])
    assert restricted["water_posture"] == WaterPosture.RESTRICTED.value
    assert (
        get_pump_station(station["id"])["status"] == PumpStationStatus.RESTRICTED.value
    )


def test_exactly_one_hundred_percent_of_the_allocation_suspends_the_course():
    """Cutting the allocation to the 682.0 gallons already used puts the ratio at exactly
    100.0 percent, which suspends the course while the numerator never moves.

    "If it is greater than or equal to `water_suspended_threshold_pct` the posture is
    `SUSPENDED`."

    Design: Difficulty/boundary_precision_check/water_posture_flips_at_exactly_eighty_percent_of_allocation
    """
    course, _station, _run, _completed = (
        _course_holding_exactly_six_hundred_eighty_two_gallons()
    )

    revise_water_allocation(course["id"], annual_water_allocation_gal=852.5)
    assert get_course(course["id"])["water_posture"] == WaterPosture.RESTRICTED.value

    revise_water_allocation(course["id"], annual_water_allocation_gal=682.0)

    suspended = get_course(course["id"])
    assert suspended["water_posture"] == WaterPosture.SUSPENDED.value
    assert_1dp(suspended["water_used_gal"], 682.0)
    assert_1dp(suspended["annual_water_allocation_gal"], 682.0)


# --------------------------------------------------------------------------
# The certification quorum's integer boundary
# --------------------------------------------------------------------------
def test_two_perfectly_measured_greens_are_one_short_of_a_quorum():
    """Both measured greens read a flawless 100.00, and certification is still refused
    with 422 `ERR_INSUFFICIENT_READINGS` because the gate counts greens, not points.

    "At least 3 such greens must qualify, else the attempt is refused with
    `ERR_INSUFFICIENT_READINGS` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/certification_requires_the_third_measured_green_exactly
    """
    event, _green3 = _tournament_with_only_two_measured_greens()

    refused = api_client.certify_conditions(event["id"], TOURN_HEADERS)
    validate_error(refused, ERR_INSUFFICIENT_READINGS, 422)

    unchanged = get_play_event(event["id"])
    assert_play_event(
        unchanged,
        expected_version=1,
        readiness_status=ReadinessStatus.PENDING.value,
        readiness_index=None,
        status=PlayEventStatus.SCHEDULED.value,
    )


def test_measuring_the_third_green_certifies_the_round_at_one_hundred():
    """One more perfect reading brings the count to 3, and the round certifies at 100.00
    on the event's second version — the refused attempt bumped nothing.

    "A `readiness_index` of at least 82.00 sets `readiness_status` to `CERTIFIED`; anything
    below it sets `readiness_status` to `FAILED`."

    Design: Difficulty/boundary_precision_check/certification_requires_the_third_measured_green_exactly
    """
    event, green3 = _tournament_with_only_two_measured_greens()

    refused = api_client.certify_conditions(event["id"], TOURN_HEADERS)
    validate_error(refused, ERR_INSUFFICIENT_READINGS, 422)

    create_playability_reading(green3["id"], "2026-08-05T06:30:00Z", **PERFECT_READING)

    certified = certify_conditions(event["id"])
    assert_2dp(certified["readiness_index"], 100.00)
    assert_play_event(
        certified,
        expected_version=2,
        readiness_status=ReadinessStatus.CERTIFIED.value,
        status=PlayEventStatus.SCHEDULED.value,
    )
