"""Three state machines that are not simple chains: the application's two orthogonal
dimensions, the crew window's bounded defer/reschedule loop, and the play event's
re-enterable readiness failure."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ERR_DEFERRAL_LIMIT_REACHED
from test_helpers.assertions import (
    assert_2dp,
    assert_application,
    assert_instant,
    assert_maintenance_window,
    assert_play_event,
    assert_turf_area,
)
from test_helpers.factories import MOWING, reschedule_window_payload
from test_helpers.fixtures import (
    certify_conditions,
    create_applicator,
    create_course,
    create_green,
    create_maintenance_window,
    create_play_event,
    create_playability_reading,
    create_product,
    declare_weather_event,
    get_application,
    get_course,
    get_maintenance_window,
    get_play_event,
    get_turf_area,
    list_course_weather_events,
    record_application,
    release_posting,
    reschedule_maintenance_window,
    set_clock,
    verify_application,
)
from test_helpers.test_users import AGRO_HEADERS
from test_helpers.types import (
    PlayEventStatus,
    PlayEventType,
    PlayPosture,
    PostingStatus,
    ReadinessStatus,
    RecordStatus,
    WeatherEventType,
    WindowStatus,
)
from test_helpers.api_client import api_client

SPRAYED_AT = "2026-08-10T06:00:00Z"
REI_EXPIRY = "2026-08-11T06:00:00Z"


def _posted_application_by_dana():
    """A posting-required fungicide sprayed by Dana, leaving the record `RECORDED` and
    the posting `POSTED` until its 24 hour interval elapses."""
    set_clock(SPRAYED_AT)
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    dana = create_applicator()
    miguel = create_applicator(
        full_name="Miguel Ortiz",
        license_number="OR-CAT37-22002",
        license_category="CAT_3_AND_7",
        license_expires_on="2028-03-31",
    )
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
        green7["id"],
        fungicide["id"],
        dana["id"],
        SPRAYED_AT,
        rate_lb_per_acre=200,
        wind_speed_mph=5,
        distance_to_water_ft=40,
    )
    return green7, dana, miguel, record


def _mowing_window_and_a_course_that_keeps_raining():
    """One MOWING window with a crew of 4 on a course whose heavy rain keeps arriving."""
    course = create_course()
    green7 = create_green(course["id"])
    window = create_maintenance_window(
        course["id"],
        green7["id"],
        MOWING,
        "2026-08-01T05:00:00Z",
        "2026-08-01T06:00:00Z",
        crew_size=4,
    )
    return course, window


def _tournament_with_one_poor_green():
    """Three measured greens whose per-green indices are 75.00, 100.00 and 45.00."""
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
    create_playability_reading(
        green7["id"], "2026-08-05T06:00:00Z",
        green_speed_ft=11.5, firmness_gravities=1.4, moisture_pct=19.0,
    )
    create_playability_reading(
        green12["id"], "2026-08-05T06:00:00Z",
        green_speed_ft=11.0, firmness_gravities=1.35, moisture_pct=18.0,
    )
    poor = create_playability_reading(
        green3["id"], "2026-08-05T06:00:00Z",
        green_speed_ft=10.4, firmness_gravities=1.2, moisture_pct=24.0,
    )
    return event, green3, poor


# --------------------------------------------------------------------------
# The application's two dimensions
# --------------------------------------------------------------------------
def test_releasing_a_posting_leaves_the_record_dimension_at_recorded():
    """The posting moves `POSTED → RELEASED` at the expiry instant while the record
    dimension stays `RECORDED`, and the green's re-entry gate clears.

    "A record in `RECORDED` may have its posting released, and a record in `VERIFIED`
    may still be `POSTED` — the dimensions are orthogonal."

    Design: Difficulty/non_linear_state_machine/application_record_and_posting_dimensions_advance_independently
    """
    green7, dana, _miguel, record = _posted_application_by_dana()

    assert_application(
        record,
        expected_version=1,
        record_status=RecordStatus.RECORDED.value,
        posting_status=PostingStatus.POSTED.value,
        total_lb=25.25,
        nitrogen_lb=0.00,
        rei_expires_at=REI_EXPIRY,
    )
    assert_turf_area(get_turf_area(green7["id"]), rei_expires_at=REI_EXPIRY)

    set_clock(REI_EXPIRY)
    released = release_posting(record["id"], dana["id"])

    assert_application(
        released,
        expected_version=2,
        posting_status=PostingStatus.RELEASED.value,
        record_status=RecordStatus.RECORDED.value,
        verified_by_applicator_id=None,
    )
    assert_turf_area(get_turf_area(green7["id"]), rei_expires_at=None)


def test_verification_after_release_leaves_the_posting_released():
    """A second applicator's sign-off advances only the record dimension, taking the pair
    to (`VERIFIED`, `RELEASED`) at version 3.

    "On success the record's `verified_by_applicator_id` is set to the verifying caller's
    `X-User-ID` and the record's `version` is incremented by 1."

    Design: Difficulty/non_linear_state_machine/application_record_and_posting_dimensions_advance_independently
    """
    _green7, dana, miguel, record = _posted_application_by_dana()

    set_clock(REI_EXPIRY)
    release_posting(record["id"], dana["id"])
    verified = verify_application(record["id"], miguel["id"])

    assert_application(
        verified,
        expected_version=3,
        record_status=RecordStatus.VERIFIED.value,
        verified_by_applicator_id=miguel["id"],
        posting_status=PostingStatus.RELEASED.value,
    )
    assert_application(
        get_application(record["id"]),
        expected_version=3,
        posting_status=PostingStatus.RELEASED.value,
    )


# --------------------------------------------------------------------------
# The crew window's bounded loop
# --------------------------------------------------------------------------
def test_window_returns_to_scheduled_after_each_deferral_without_losing_the_count():
    """Rain defers the window to `DEFERRED` with a count of 1, a reschedule returns it to
    `SCHEDULED`, and the count is not given back.

    "A successful deferral sets the status to `DEFERRED`, increments `deferral_count` by
    1, and increments the window's `version` by 1; when the window was carrying a plan
    task, that task reverts `SCHEDULED → PLANNED`, which recomputes the plan's
    `committed_nitrogen_lb` and the turf area's `nitrogen_projected_lb_per_1000`; and
    when the trigger was a weather declaration, that event's `deferred_window_count` is
    incremented by 1."

    Design: Difficulty/non_linear_state_machine/maintenance_window_defer_reschedule_cycle_caps_at_two
    """
    course, window = _mowing_window_and_a_course_that_keeps_raining()

    assert_maintenance_window(
        window,
        expected_version=1,
        status=WindowStatus.SCHEDULED.value,
        deferral_count=0,
        crew_hours=4.00,
    )

    rain1 = declare_weather_event(
        course["id"], WeatherEventType.HEAVY_RAIN.value, "2026-08-01T06:00:00Z"
    )
    assert rain1["deferred_window_count"] == 1

    deferred = get_maintenance_window(window["id"])
    assert_maintenance_window(
        deferred,
        expected_version=2,
        status=WindowStatus.DEFERRED.value,
        deferral_count=1,
    )
    reread_course = get_course(course["id"])
    assert reread_course["play_posture"] == PlayPosture.CART_PATH_ONLY.value
    assert reread_course["frost_delay_minutes"] == 0

    rescheduled = reschedule_maintenance_window(
        window["id"], "2026-08-02T05:00:00Z", "2026-08-02T06:00:00Z"
    )
    assert_maintenance_window(
        rescheduled,
        expected_version=3,
        status=WindowStatus.SCHEDULED.value,
        deferral_count=1,
        crew_hours=4.00,
        window_start="2026-08-02T05:00:00Z",
    )


def test_the_third_pass_through_the_deferral_edge_is_refused():
    """A second rain takes the count to 2, and the next reschedule is refused with
    `ERR_DEFERRAL_LIMIT_REACHED` leaving the window exactly where it stood.

    "For a reschedule out of `DEFERRED`, `deferral_count` must be strictly less than 2,
    and a window that has already exhausted its two deferrals is refused with
    `ERR_DEFERRAL_LIMIT_REACHED` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/maintenance_window_defer_reschedule_cycle_caps_at_two
    """
    course, window = _mowing_window_and_a_course_that_keeps_raining()

    declare_weather_event(
        course["id"], WeatherEventType.HEAVY_RAIN.value, "2026-08-01T06:00:00Z"
    )
    reschedule_maintenance_window(
        window["id"], "2026-08-02T05:00:00Z", "2026-08-02T06:00:00Z"
    )
    rain2 = declare_weather_event(
        course["id"], WeatherEventType.HEAVY_RAIN.value, "2026-08-02T06:00:00Z"
    )
    assert rain2["deferred_window_count"] == 1

    twice_deferred = get_maintenance_window(window["id"])
    assert_maintenance_window(
        twice_deferred,
        expected_version=4,
        status=WindowStatus.DEFERRED.value,
        deferral_count=2,
    )

    refused = api_client.reschedule_maintenance_window(
        window["id"],
        reschedule_window_payload("2026-08-03T05:00:00Z", "2026-08-03T06:00:00Z"),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_DEFERRAL_LIMIT_REACHED, 409)

    assert_maintenance_window(
        get_maintenance_window(window["id"]),
        expected_version=4,
        status=WindowStatus.DEFERRED.value,
        deferral_count=2,
    )
    events, _meta = list_course_weather_events(course["id"])
    assert len(events) == 2, "both declarations must remain on the course's weather log"


# --------------------------------------------------------------------------
# The play event's readiness dimension
# --------------------------------------------------------------------------
def test_readiness_fails_at_seventy_three_thirty_three_on_the_first_attempt():
    """75.00, 100.00 and 45.00 average to 73.33, which is below the threshold, so the
    readiness dimension reads `FAILED` while the schedule dimension does not move.

    "**The per-green rounding happens first**; the event's `readiness_index` is then the
    sum of the already-rounded per-green indices divided by the number of participating
    greens, rounded half up to two decimal places."

    Design: Difficulty/non_linear_state_machine/play_event_readiness_dimension_recovers_from_failed
    """
    event, green3, poor_reading = _tournament_with_one_poor_green()

    certified = certify_conditions(event["id"])

    assert_play_event(
        certified,
        readiness_index=73.33,
        readiness_status=ReadinessStatus.FAILED.value,
        status=PlayEventStatus.SCHEDULED.value,
        delayed_minutes=0,
    )
    assert poor_reading["within_tournament_spec"] is True, (
        "moisture does not participate in the within-spec flag"
    )
    assert_turf_area(get_turf_area(green3["id"]), current_moisture_pct=24.0)


def test_a_fresh_reading_recovers_the_failed_readiness_to_certified():
    """A better 07:00Z reading on hole 3 lifts the index to 91.67 and moves the readiness
    dimension `FAILED → CERTIFIED` while the schedule dimension stays `SCHEDULED`.

    "Certification is available while `readiness_status` is `PENDING` or `FAILED`, which
    makes the readiness dimension cyclic: after a failure, crews re-prepare the greens,
    fresh readings are recorded, and certification is re-attempted, moving
    `FAILED → CERTIFIED` if the recomputed index now reaches 82.00 and moving
    `FAILED → FAILED` — replacing the stored `readiness_index` with the new value and
    still incrementing `version` by 1 — if it does not."

    Design: Difficulty/non_linear_state_machine/play_event_readiness_dimension_recovers_from_failed
    """
    event, green3, _poor_reading = _tournament_with_one_poor_green()

    failed = certify_conditions(event["id"])
    assert failed["readiness_status"] == ReadinessStatus.FAILED.value

    create_playability_reading(
        green3["id"], "2026-08-05T07:00:00Z",
        green_speed_ft=11.0, firmness_gravities=1.35, moisture_pct=18.0,
    )
    assert_turf_area(get_turf_area(green3["id"]), current_moisture_pct=18.0)

    recovered = certify_conditions(event["id"])
    assert_2dp(recovered["readiness_index"], 91.67)
    assert recovered["readiness_status"] == ReadinessStatus.CERTIFIED.value

    reread = get_play_event(event["id"])
    assert reread["status"] == PlayEventStatus.SCHEDULED.value
    assert reread["delayed_minutes"] == 0
    assert_instant(reread["effective_start_at"], "2026-08-05T14:00:00Z")
