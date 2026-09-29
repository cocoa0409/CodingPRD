"""Three endpoint families exercised end to end: the computed water assessment that returns
no entity, the retirement that links a successor without disturbing the schedule, and the
pump station's create-read-list-patch round trip."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_REPLACEMENT_UNIT_TYPE_MISMATCH
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_course,
    assert_equipment_unit,
    assert_maintenance_window,
    assert_pump_station,
    assert_total_count,
    assert_water_assessment,
)
from test_helpers.factories import PEST_CONTROL, retire_payload
from test_helpers.fixtures import (
    create_course,
    create_equipment_unit,
    create_green,
    create_maintenance_window,
    create_pump_station,
    get_course,
    get_equipment_unit,
    get_maintenance_window,
    get_pump_station,
    get_water_assessment,
    list_pump_stations,
    retire_equipment_unit,
    set_pump_station_status,
)
from test_helpers.test_users import AGRO_HEADERS, SUPER_HEADERS, TECH_HEADERS
from test_helpers.types import (
    AssessmentTier,
    EquipmentStatus,
    PumpStationStatus,
    SourceType,
    UnitType,
    WindowStatus,
)


def _two_sprayers_a_mower_and_the_window_that_needs_a_sprayer():
    """Three identically specified machines of two classes, and one pest-control window that
    names `SPRAYER` as the class it cannot run without."""
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    spray_old = create_equipment_unit(
        course["id"], unit_type=UnitType.SPRAYER.value, model_year=2018,
        purchase_cost=38000, expected_life_hours=6000,
        service_interval_hours=250, avg_daily_hours=3.5,
    )
    spray_new = create_equipment_unit(
        course["id"], unit_type=UnitType.SPRAYER.value, model_year=2018,
        purchase_cost=38000, expected_life_hours=6000,
        service_interval_hours=250, avg_daily_hours=3.5,
    )
    mower = create_equipment_unit(
        course["id"], unit_type=UnitType.FAIRWAY_MOWER.value, model_year=2018,
        purchase_cost=38000, expected_life_hours=6000,
        service_interval_hours=250, avg_daily_hours=3.5,
    )
    w_pest = create_maintenance_window(
        course["id"], green7["id"], PEST_CONTROL,
        "2026-08-15T06:00:00Z", "2026-08-15T10:00:00Z", crew_size=1,
        required_unit_type=UnitType.SPRAYER.value,
    )
    return spray_old, spray_new, mower, w_pest


# --------------------------------------------------------------------------
# The computed read that returns a breakdown instead of a row
# --------------------------------------------------------------------------
def test_a_course_inside_its_allocation_is_billed_nothing_at_all():
    """With no station and no run the assessment reads zero on every money field, lands in
    `T1` at the 0.90 rate, and leaves the course exactly as registration left it.

    "A computed read on the course returns a tiered overage assessment, and it returns no
    entity — the response body is the breakdown itself, comprising `billable_gal`,
    `base_charge`, `tier`, `surcharge_rate`, `surcharge`, and `total_charge`."

    "First, `billable_gal` is the amount by which the course's gallons used this year exceeds
    its annual allocation, or zero if it has not exceeded it — that is, the larger of zero and
    the difference."

    Design: Corner/endpoints/water_assessment_computed_read_returns_a_zero_bill_in_tier_one
    """
    course = create_course(annual_water_allocation_gal=100000)

    assessment = get_water_assessment(course["id"])

    assert_water_assessment(
        assessment,
        billable_gal=0.0,
        base_charge=0.00,
        tier=AssessmentTier.T1.value,
        surcharge_rate=0.90,
        surcharge=0.00,
        total_charge=0.00,
    )
    reread = get_course(course["id"])
    assert_course(reread, expected_version=1)
    assert_1dp(reread["water_used_gal"], 0.0)


# --------------------------------------------------------------------------
# Retirement and its successor link
# --------------------------------------------------------------------------
def test_only_a_same_class_successor_may_be_named_on_a_retirement():
    """Naming the fairway mower is refused with 422
    `ERR_REPLACEMENT_UNIT_TYPE_MISMATCH` and writes nothing; naming the second sprayer
    retires the machine and stores the link, while the pest-control window survives because a
    sprayer remains in service.

    "An optional `replacement_unit_id` may name the successor machine, and when it is supplied
    that unit must exist (else `ERR_EQUIPMENT_NOT_FOUND`), must be `IN_SERVICE` (else
    `ERR_EQUIPMENT_STATE_INVALID`), and must belong to the same course and be of the same
    `unit_type` as the retiring machine (else `ERR_REPLACEMENT_UNIT_TYPE_MISMATCH`, HTTP 422)."

    "Retirement moves the unit `IN_SERVICE → RETIRED` or `DOWN_FOR_SERVICE → RETIRED`, sets
    its self-referential `replaced_by_unit_id` to the named replacement or to null when none
    was named, and increments its `version` by 1."

    "Every maintenance window on that course in status `SCHEDULED` whose `required_unit_type`
    equals the retired unit's `unit_type`, and for which no other unit of that type on that
    course remains `IN_SERVICE`, moves `SCHEDULED → DEFERRED` under the rules of §3.6 — which
    itself reverts any plan task the window was carrying `SCHEDULED → PLANNED`, which itself
    recomputes that plan's `committed_nitrogen_lb` and the turf area's
    `nitrogen_projected_lb_per_1000`."

    Design: Corner/endpoints/equipment_retire_with_a_correct_type_replacement_links_the_successor
    """
    spray_old, spray_new, mower, w_pest = (
        _two_sprayers_a_mower_and_the_window_that_needs_a_sprayer()
    )

    refused = api_client.retire_equipment_unit(
        spray_old["id"], SUPER_HEADERS, retire_payload(mower["id"])
    )
    validate_error(refused, ERR_REPLACEMENT_UNIT_TYPE_MISMATCH, 422)

    assert_equipment_unit(
        get_equipment_unit(spray_old["id"]),
        expected_version=1,
        status=EquipmentStatus.IN_SERVICE.value,
        replaced_by_unit_id=None,
    )

    retired = retire_equipment_unit(spray_old["id"], spray_new["id"])

    assert_equipment_unit(
        retired,
        expected_version=2,
        status=EquipmentStatus.RETIRED.value,
        replaced_by_unit_id=spray_new["id"],
    )
    assert_equipment_unit(
        get_equipment_unit(spray_new["id"]),
        expected_version=1,
        status=EquipmentStatus.IN_SERVICE.value,
        replaced_by_unit_id=None,
    )
    assert_equipment_unit(
        get_equipment_unit(mower["id"]),
        expected_version=1,
        status=EquipmentStatus.IN_SERVICE.value,
    )

    surviving = get_maintenance_window(w_pest["id"])
    assert_maintenance_window(
        surviving, status=WindowStatus.SCHEDULED.value, deferral_count=0
    )
    assert_2dp(surviving["crew_hours"], 4.00)


# --------------------------------------------------------------------------
# The pump station round trip
# --------------------------------------------------------------------------
def test_a_station_is_created_online_read_back_listed_and_then_taken_offline():
    """Both stations open at version 1 on an `OPEN` course, the well reads back with its full
    cap and nothing drawn, and taking it offline moves only that station, which the status and
    source-type filters then separate.

    "A new station has `withdrawn_today_gal` at 0 and `version` 1, and is created `ONLINE` —
    except that a station registered on a course whose water posture is already `RESTRICTED`
    or `SUSPENDED` is created `RESTRICTED` instead."

    "`OFFLINE` is only ever set explicitly, by a `Superintendent` or an
    `EquipmentTechnician` supplying a `status` on the station-status operation, and it
    survives posture changes: a station taken offline for repair stays offline through any
    number of posture movements until somebody sets it back."

    "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta`
    object of the envelope, where `total_count` is the number of rows matching the filter
    before pagination is applied and `has_more` states whether any matching row remains
    beyond the returned page."

    "List pump stations, filterable by `course_id`, `source_type`, and `status`."

    Design: Corner/endpoints/pump_station_create_read_list_and_status_update_round_trip
    """
    course = create_course(annual_water_allocation_gal=500000)

    pump_a = create_pump_station(
        course["id"], source_type=SourceType.WELL.value, max_flow_gpm=300,
        max_concurrent_zones=2, daily_withdrawal_cap_gal=10000,
    )
    pump_b = create_pump_station(
        course["id"], source_type=SourceType.POND.value, max_flow_gpm=450,
        max_concurrent_zones=4, daily_withdrawal_cap_gal=25000,
    )

    assert_pump_station(
        pump_a, expected_version=1, status=PumpStationStatus.ONLINE.value
    )
    assert_pump_station(
        pump_b, expected_version=1, status=PumpStationStatus.ONLINE.value
    )

    read_back = get_pump_station(pump_a["id"], headers=AGRO_HEADERS)
    assert read_back["daily_withdrawal_cap_gal"] == 10000
    assert_1dp(read_back["withdrawn_today_gal"], 0.0)

    online_rows, online_meta = list_pump_stations(
        course_id=course["id"], status=PumpStationStatus.ONLINE.value
    )
    assert_total_count(online_meta, 2)
    assert online_meta["has_more"] is False
    assert {row["id"] for row in online_rows} == {pump_a["id"], pump_b["id"]}

    patched = set_pump_station_status(
        pump_a["id"], PumpStationStatus.OFFLINE.value, headers=TECH_HEADERS
    )
    assert_pump_station(
        patched, expected_version=2, status=PumpStationStatus.OFFLINE.value
    )

    offline_rows, offline_meta = list_pump_stations(
        course_id=course["id"], status=PumpStationStatus.OFFLINE.value
    )
    assert_total_count(offline_meta, 1)
    assert [row["id"] for row in offline_rows] == [pump_a["id"]]

    pond_rows, pond_meta = list_pump_stations(
        course_id=course["id"], source_type=SourceType.POND.value
    )
    assert_total_count(pond_meta, 1)
    assert [row["id"] for row in pond_rows] == [pump_b["id"]]
    assert_pump_station(
        pond_rows[0], expected_version=1, status=PumpStationStatus.ONLINE.value
    )
