"""Three resources with three different interval geometries: crew occupancy of a turf area
on closed intervals, pump zones on half-open intervals, and a play event's derived per-hole
occupancy against a crew window extended by its clearance buffer."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_PUMP_ZONE_CAPACITY,
    ERR_WINDOW_CONFLICTS_PLAY,
    ERR_WINDOW_OVERLAP,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_instant,
    assert_irrigation_run,
    assert_maintenance_window,
    assert_total_count,
)
from test_helpers.factories import (
    MOWING,
    TOPDRESSING,
    irrigation_run_payload,
    maintenance_window_payload,
)
from test_helpers.fixtures import (
    create_course,
    create_green,
    create_irrigation_run,
    create_maintenance_window,
    create_play_event,
    create_pump_station,
    create_turf_area,
    get_pump_station,
    list_irrigation_runs,
    list_maintenance_windows,
)
from test_helpers.test_users import AGRO_HEADERS
from test_helpers.types import (
    AreaType,
    IrrigationRunStatus,
    PlayEventType,
    SoilType,
    SourceType,
    WindowStatus,
)


def _one_mowing_window_from_five_to_seven():
    """A two hour mowing window on the hole 7 green, with an unoccupied hole 12 green
    available as a control."""
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    green12 = create_green(course["id"], hole_number=12, area_sq_ft=4300,
                           distance_to_water_ft=200)
    window = create_maintenance_window(
        course["id"], green7["id"], MOWING,
        "2026-08-05T05:00:00Z", "2026-08-05T07:00:00Z", crew_size=3,
    )
    return course, green7, green12, window


def _two_touching_runs_on_a_two_zone_station():
    """Back-to-back runs from 04:00Z to 05:00Z and 05:00Z to 06:00Z on a station that
    allows two simultaneous zones."""
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    station = create_pump_station(
        course["id"],
        source_type=SourceType.WELL.value,
        max_flow_gpm=300,
        max_concurrent_zones=2,
        daily_withdrawal_cap_gal=10000,
    )
    run1 = create_irrigation_run(
        station["id"], green7["id"],
        "2026-08-05T04:00:00Z", "2026-08-05T05:00:00Z", 5,
        expected_pump_station_version=station["version"],
    )
    run2 = create_irrigation_run(
        station["id"], green7["id"],
        "2026-08-05T05:00:00Z", "2026-08-05T06:00:00Z", 5,
        expected_pump_station_version=station["version"],
    )
    return green7, station, run1, run2


def _sequential_round_starting_at_thirteen_hundred():
    """Standard tee times from 13:00Z at a 12 minute pace, so hole 7 is occupied from
    14:12Z to 14:24Z and hole 12 from 15:12Z to 15:24Z."""
    course = create_course()
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    fairway7 = create_turf_area(
        course["id"],
        area_type=AreaType.FAIRWAY.value,
        hole_number=7,
        area_sq_ft=130000,
        mowing_height_mm=12.7,
        distance_to_water_ft=15,
        soil_type=SoilType.NATIVE_LOAM.value,
    )
    green12 = create_green(course["id"], hole_number=12, area_sq_ft=4300,
                           distance_to_water_ft=200)
    event = create_play_event(
        course["id"],
        event_type=PlayEventType.STANDARD_TEE_TIMES.value,
        start_at="2026-08-06T13:00:00Z",
        end_at="2026-08-06T18:00:00Z",
        holes_in_play=18,
        field_size=80,
    )
    return course, green7, fairway7, green12, event


# --------------------------------------------------------------------------
# Crew against crew: closed intervals on one turf area
# --------------------------------------------------------------------------
def test_a_second_crew_touching_the_first_windows_end_is_refused():
    """A topdressing crew starting at 07:00Z, exactly when the mower finishes, collides on
    closed-interval geometry and is refused with `ERR_WINDOW_OVERLAP`.

    "Two maintenance windows on the same turf area conflict when the new window's start is
    at or before the other window's end **and** the other window's start is at or before
    the new window's end."

    Design: Difficulty/resource_temporal_overlap/crew_windows_on_one_turf_area_conflict_on_closed_intervals
    """
    course, green7, _green12, _window = _one_mowing_window_from_five_to_seven()

    refused = api_client.create_maintenance_window(
        maintenance_window_payload(
            course["id"], green7["id"], TOPDRESSING,
            "2026-08-05T07:00:00Z", "2026-08-05T09:00:00Z", crew_size=2,
        ),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_WINDOW_OVERLAP, 409)

    _rows, meta = list_maintenance_windows(turf_area_id=green7["id"])
    assert_total_count(meta, 1)


def test_the_conflicting_resource_is_the_area_and_one_minute_of_daylight_is_enough():
    """The identical 07:00Z interval is admitted on the hole 12 green, and a 07:01Z start
    is admitted on the hole 7 green, so the resource is the area and the collision needs a
    shared instant.

    "Because both comparisons are inclusive, windows that merely touch at an endpoint do
    conflict."

    Design: Difficulty/resource_temporal_overlap/crew_windows_on_one_turf_area_conflict_on_closed_intervals
    """
    course, green7, green12, _window = _one_mowing_window_from_five_to_seven()

    other_area = create_maintenance_window(
        course["id"], green12["id"], TOPDRESSING,
        "2026-08-05T07:00:00Z", "2026-08-05T09:00:00Z", crew_size=2,
    )
    assert_maintenance_window(
        other_area, expected_version=1, status=WindowStatus.SCHEDULED.value,
        crew_hours=4.00,
    )

    one_minute_later = create_maintenance_window(
        course["id"], green7["id"], TOPDRESSING,
        "2026-08-05T07:01:00Z", "2026-08-05T09:00:00Z", crew_size=2,
    )
    assert one_minute_later["status"] == WindowStatus.SCHEDULED.value

    _rows, meta = list_maintenance_windows(turf_area_id=green7["id"])
    assert_total_count(meta, 2)


# --------------------------------------------------------------------------
# Run against run: half-open intervals against a capacity above one
# --------------------------------------------------------------------------
def test_two_runs_touching_at_five_oclock_both_book_on_a_two_zone_station():
    """Back-to-back runs share no instant under half-open geometry, so both are admitted
    at 170.5 gallons and 2.84 gpm.

    "Adjacent runs that merely touch at an endpoint therefore do **not** intersect."

    Design: Difficulty/resource_temporal_overlap/pump_station_zone_capacity_counts_half_open_intersections
    """
    _green7, station, run1, run2 = _two_touching_runs_on_a_two_zone_station()

    for run in (run1, run2):
        assert_irrigation_run(
            run,
            status=IrrigationRunStatus.SCHEDULED.value,
            allotted_gal=170.5,
            flow_gpm=2.84,
        )

    _rows, meta = list_irrigation_runs(pump_station_id=station["id"])
    assert_total_count(meta, 2)


def test_a_third_run_straddling_both_of_them_breaks_the_zone_limit():
    """A 04:30Z to 05:30Z run intersects both booked runs, so 2 plus 1 exceeds the two
    zones and the booking is refused with `ERR_PUMP_ZONE_CAPACITY`.

    "Zone capacity is next: count the station's runs in status `SCHEDULED` whose half-open
    intervals intersect the new run's half-open interval per §2.11, add one for the new
    run, and require the result not to exceed `max_concurrent_zones`, else
    `ERR_PUMP_ZONE_CAPACITY` (HTTP 409); adjacent runs that merely touch endpoints are not
    counted."

    Design: Difficulty/resource_temporal_overlap/pump_station_zone_capacity_counts_half_open_intersections
    """
    green7, station, _run1, _run2 = _two_touching_runs_on_a_two_zone_station()

    refused = api_client.create_irrigation_run(
        irrigation_run_payload(
            station["id"], green7["id"],
            "2026-08-05T04:30:00Z", "2026-08-05T05:30:00Z", 5,
            station["version"],
        ),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_PUMP_ZONE_CAPACITY, 409)

    _rows, meta = list_irrigation_runs(pump_station_id=station["id"])
    assert_total_count(meta, 2)
    reread = get_pump_station(station["id"])
    assert_1dp(reread["withdrawn_today_gal"], 0)
    assert reread["version"] == station["version"]


# --------------------------------------------------------------------------
# Crew against play: derived hole occupancy plus a 30 minute clearance
# --------------------------------------------------------------------------
def test_a_window_whose_clearance_only_touches_the_hole_occupancy_is_admitted():
    """Extended by its 30 minute buffer the 13:30Z window ends exactly at 14:12Z, when
    hole 7's occupancy begins, and half-open intervals that touch do not intersect.

    "The crew window is first extended at its tail by a clearance buffer of 30 minutes,
    giving the interval that begins at the window's start, inclusive, and ends 30 minutes
    after the window's end, exclusive."

    Design: Difficulty/resource_temporal_overlap/hole_occupancy_conflict_uses_paced_half_open_windows_plus_clearance
    """
    course, green7, _fairway7, _green12, event = (
        _sequential_round_starting_at_thirteen_hundred()
    )

    assert_instant(event["effective_start_at"], "2026-08-06T13:00:00Z")
    assert event["delayed_minutes"] == 0

    admitted = create_maintenance_window(
        course["id"], green7["id"], MOWING,
        "2026-08-06T13:30:00Z", "2026-08-06T13:42:00Z", crew_size=3,
    )
    assert_maintenance_window(
        admitted, expected_version=1, status=WindowStatus.SCHEDULED.value,
        crew_hours=0.60,
    )


def test_one_minute_later_on_the_same_hole_overlaps_the_paced_occupancy():
    """Shifted by a minute the extended interval runs to 14:13Z and overlaps hole 7's
    [14:12Z, 14:24Z) occupancy, which is `ERR_WINDOW_CONFLICTS_PLAY` even though the crew
    is on a different turf area of that hole.

    "A sequential event — standard tee times or a tournament round — occupies hole *h* only
    during the interval that begins at its effective start plus (*h* minus 1) times the
    hole pace of 12 minutes, inclusive, and ends at its effective start plus *h* times 12
    minutes, exclusive."

    Design: Difficulty/resource_temporal_overlap/hole_occupancy_conflict_uses_paced_half_open_windows_plus_clearance
    """
    course, _green7, fairway7, _green12, _event = (
        _sequential_round_starting_at_thirteen_hundred()
    )

    refused = api_client.create_maintenance_window(
        maintenance_window_payload(
            course["id"], fairway7["id"], MOWING,
            "2026-08-06T13:31:00Z", "2026-08-06T13:43:00Z", crew_size=3,
        ),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_WINDOW_CONFLICTS_PLAY, 409)

    _rows, meta = list_maintenance_windows(turf_area_id=fairway7["id"])
    assert_total_count(meta, 0)


def test_the_same_clock_time_is_free_on_a_hole_the_field_has_not_reached():
    """Hole 12 is not occupied until 15:12Z, so the very interval that was refused on hole
    7 is admitted on the hole 12 green.

    "That extended interval is tested against a play event's occupancy of the specific hole
    the window's turf area serves."

    Design: Difficulty/resource_temporal_overlap/hole_occupancy_conflict_uses_paced_half_open_windows_plus_clearance
    """
    course, _green7, _fairway7, green12, _event = (
        _sequential_round_starting_at_thirteen_hundred()
    )

    admitted = create_maintenance_window(
        course["id"], green12["id"], MOWING,
        "2026-08-06T13:31:00Z", "2026-08-06T13:43:00Z", crew_size=3,
    )
    assert admitted["status"] == WindowStatus.SCHEDULED.value
    assert_2dp(admitted["crew_hours"], 0.60)

    _rows, meta = list_maintenance_windows(turf_area_id=green12["id"])
    assert_total_count(meta, 1)
