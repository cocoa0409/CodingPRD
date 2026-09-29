"""Five derived quantities computed the way the contract pins them: nested rounding on an
application record, the per-area-type nutrient ceiling, the water assessment's tier keyed on
the base charge, the calendar-year predicate under the applied ledger, and the two ordered
projections a weather declaration produces."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_NITROGEN_LOAD_LIMIT
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_3dp,
    assert_application,
    assert_course,
    assert_instant,
    assert_irrigation_run,
    assert_nitrogen_ledgers,
    assert_play_event,
    assert_total_count,
    assert_water_assessment,
    assert_weather_event,
)
from test_helpers.factories import application_payload
from test_helpers.fixtures import (
    clear_weather_event,
    complete_irrigation_run,
    create_applicator,
    create_course,
    create_irrigation_run,
    create_play_event,
    create_product,
    create_pump_station,
    create_turf_area,
    declare_weather_event,
    get_course,
    get_play_event,
    get_turf_area,
    get_water_assessment,
    list_applications,
    record_application,
    revise_water_allocation,
    set_clock,
)
from test_helpers.test_users import make_applicator_headers
from test_helpers.types import (
    AreaType,
    AssessmentTier,
    PlayEventStatus,
    PlayEventType,
    PlayPosture,
    PostingStatus,
    RecordStatus,
    SoilType,
    SourceType,
    WaterPosture,
    WeatherEventStatus,
    WeatherEventType,
)


def _four_thousand_foot_green_and_a_urea_bag():
    """A 4000 sq ft green, a CAT_3_TURF applicator, and a 46 percent urea with no re-entry
    interval, no buffer and no posting requirement."""
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_turf_area(
        course["id"],
        area_type=AreaType.GREEN.value,
        hole_number=7,
        area_sq_ft=4000,
        mowing_height_mm=3.2,
        distance_to_water_ft=40,
        soil_type=SoilType.SAND_USGA.value,
    )
    dana = create_applicator(license_number="OR-CAT3-12001")
    urea = create_product()
    return green7, dana, urea


def _five_thousand_foot_green_and_rough():
    """A 5000 sq ft green on hole 3 and a 5000 sq ft rough on hole 11, identical in size and
    distance to water so only the area type can separate them."""
    course = create_course(annual_water_allocation_gal=500000)
    green3 = create_turf_area(
        course["id"],
        area_type=AreaType.GREEN.value,
        hole_number=3,
        area_sq_ft=5000,
        mowing_height_mm=3.2,
        distance_to_water_ft=40,
        soil_type=SoilType.SAND_USGA.value,
    )
    rough11 = create_turf_area(
        course["id"],
        area_type=AreaType.ROUGH.value,
        hole_number=11,
        area_sq_ft=5000,
        mowing_height_mm=50,
        distance_to_water_ft=40,
        soil_type=SoilType.NATIVE_LOAM.value,
    )
    dana = create_applicator(license_number="OR-CAT3-12002")
    urea = create_product(epa_reg_no="NA-FERT-0002")
    return green3, rough11, dana, urea


def _course_that_has_drawn_thirty_thousand_seven_hundred_seventy_gallons():
    """Three capped runs against a 100000 gal allocation, each one clipped by its station's
    daily headroom, taking the course to 30770.0 gallons used."""
    course = create_course(annual_water_allocation_gal=100000)
    fairway7 = create_turf_area(
        course["id"],
        area_type=AreaType.FAIRWAY.value,
        hole_number=7,
        area_sq_ft=130000,
        mowing_height_mm=12.7,
        distance_to_water_ft=60,
        soil_type=SoilType.NATIVE_LOAM.value,
    )
    green3 = create_turf_area(
        course["id"],
        area_type=AreaType.GREEN.value,
        hole_number=3,
        area_sq_ft=5500,
        mowing_height_mm=3.2,
        distance_to_water_ft=40,
        soil_type=SoilType.SAND_USGA.value,
    )
    rough11 = create_turf_area(
        course["id"],
        area_type=AreaType.ROUGH.value,
        hole_number=11,
        area_sq_ft=500000,
        mowing_height_mm=50,
        distance_to_water_ft=90,
        soil_type=SoilType.NATIVE_LOAM.value,
    )
    pump_a = create_pump_station(
        course["id"], source_type=SourceType.WELL.value, max_flow_gpm=200,
        max_concurrent_zones=3, daily_withdrawal_cap_gal=7690,
    )
    pump_b = create_pump_station(
        course["id"], source_type=SourceType.WELL.value, max_flow_gpm=50,
        max_concurrent_zones=1, daily_withdrawal_cap_gal=3,
    )
    pump_c = create_pump_station(
        course["id"], source_type=SourceType.WELL.value, max_flow_gpm=500,
        max_concurrent_zones=3, daily_withdrawal_cap_gal=23077,
    )
    run_a = create_irrigation_run(
        pump_a["id"], fairway7["id"],
        "2026-08-05T04:00:00Z", "2026-08-05T05:00:00Z", 10,
        expected_pump_station_version=pump_a["version"],
    )
    run_b = create_irrigation_run(
        pump_b["id"], green3["id"],
        "2026-08-05T05:00:00Z", "2026-08-05T06:00:00Z", 10,
        expected_pump_station_version=pump_b["version"],
    )
    run_c = create_irrigation_run(
        pump_c["id"], rough11["id"],
        "2026-08-05T06:00:00Z", "2026-08-05T07:00:00Z", 10,
        expected_pump_station_version=pump_c["version"],
    )
    return course, run_a, run_b, run_c


def _five_rounds_posted_out_of_order():
    """Five rounds on 2026-08-05 registered in the order 07:22, 07:00, 08:00, the 07:20
    shotgun, and the 07:05 tournament round, so creation order cannot be release order."""
    set_clock("2026-08-05T06:30:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    late = create_play_event(
        course["id"], event_type=PlayEventType.STANDARD_TEE_TIMES.value,
        start_at="2026-08-05T07:22:00Z", end_at="2026-08-05T11:00:00Z",
        holes_in_play=18, field_size=40,
    )
    first = create_play_event(
        course["id"], event_type=PlayEventType.STANDARD_TEE_TIMES.value,
        start_at="2026-08-05T07:00:00Z", end_at="2026-08-05T11:00:00Z",
        holes_in_play=18, field_size=60,
    )
    at_the_clear = create_play_event(
        course["id"], event_type=PlayEventType.STANDARD_TEE_TIMES.value,
        start_at="2026-08-05T08:00:00Z", end_at="2026-08-05T12:00:00Z",
        holes_in_play=18, field_size=40,
    )
    shotgun = create_play_event(
        course["id"], event_type=PlayEventType.SHOTGUN_START.value,
        start_at="2026-08-05T07:20:00Z", end_at="2026-08-05T12:00:00Z",
        holes_in_play=18, field_size=144,
    )
    tournament = create_play_event(
        course["id"], event_type=PlayEventType.TOURNAMENT_ROUND.value,
        start_at="2026-08-05T07:05:00Z", end_at="2026-08-05T11:30:00Z",
        holes_in_play=18, field_size=78,
    )
    frost = declare_weather_event(
        course["id"], WeatherEventType.FROST.value, "2026-08-05T08:00:00Z",
        expected_course_version=course["version"], delay_minutes=45,
    )
    return course, late, first, at_the_clear, shotgun, tournament, frost


# --------------------------------------------------------------------------
# The application record's nested rounding
# --------------------------------------------------------------------------
def test_the_nitrogen_mass_is_taken_from_the_rounded_product_mass():
    """13.774104 lb is pinned to 13.77 before the 46 percent multiplication, giving 6.33
    rather than the 6.34 an unrounded route would produce, and the area's ledger reads 1.583.

    "Second, `total_lb` is the `rate_lb_per_acre` multiplied by that acreage, rounded half up
    to two decimal places. Third, `nitrogen_lb` is the **already-rounded** `total_lb`
    multiplied by the product's `nitrogen_pct` divided by 100, rounded half up to two decimal
    places; computing it from the exact unrounded product instead is non-conforming."

    "For each application record on the area whose record status is `RECORDED` or `VERIFIED`
    and whose `applied_at` falls in the logical clock's calendar year, take the application's
    applied nitrogen mass divided by the area's square footage divided by 1000, and round
    that per-application figure half up to three decimal places; then add the already-rounded
    per-application figures and round the sum half up to three decimal places again."

    Design: Corner/calculations/application_precision_uses_nested_rounding_and_half_up_at_the_third_decimal
    """
    set_clock("2026-08-01T06:00:00Z")
    green7, dana, urea = _four_thousand_foot_green_and_a_urea_bag()

    record = record_application(
        green7["id"], urea["id"], dana["id"], "2026-08-01T06:00:00Z",
        rate_lb_per_acre=150, wind_speed_mph=4, distance_to_water_ft=40,
    )

    assert_application(
        record,
        expected_version=1,
        posting_status=PostingStatus.NOT_REQUIRED.value,
    )
    assert_2dp(record["total_lb"], 13.77)
    assert_2dp(record["nitrogen_lb"], 6.33)
    assert_instant(record["rei_expires_at"], "2026-08-01T06:00:00Z")
    assert_nitrogen_ledgers(get_turf_area(green7["id"]), 1.583, 1.583)


# --------------------------------------------------------------------------
# The nutrient ceiling keyed to the area type
# --------------------------------------------------------------------------
def test_three_point_six_nine_six_pounds_clears_the_green_ceiling():
    """40.17 lb of product carrying 18.48 lb of nitrogen over 5000 sq ft is 3.696 lb per
    thousand, which a `GREEN` may hold because its ceiling is 4.00.

    "That planned-commitment figure is the left-hand side of the regulatory nutrient ceiling.
    After adding a new task's or a new application's nitrogen, the area's planned-commitment
    figure must not exceed the ceiling for its area type: 4.00 pounds per thousand square feet
    for a `GREEN` and for a `PRACTICE_GREEN`, 5.00 for a `TEE` and for an `APPROACH`, 6.00 for
    a `FAIRWAY`, and 3.00 for a `ROUGH`."

    Design: Corner/calculations/nitrogen_ceiling_is_keyed_to_the_area_type_constant
    """
    set_clock("2026-08-01T06:00:00Z")
    green3, _rough11, dana, urea = _five_thousand_foot_green_and_rough()

    record = record_application(
        green3["id"], urea["id"], dana["id"], "2026-08-01T06:00:00Z",
        rate_lb_per_acre=350, wind_speed_mph=4, distance_to_water_ft=40,
    )

    assert_2dp(record["total_lb"], 40.17)
    assert_2dp(record["nitrogen_lb"], 18.48)
    assert_nitrogen_ledgers(get_turf_area(green3["id"]), 3.696, 3.696)


def test_the_identical_load_breaks_the_rough_ceiling_and_records_nothing():
    """The same product, rate and square footage on a `ROUGH` puts 3.696 against a ceiling of
    3.00, so the spray is refused with 422 `ERR_NITROGEN_LOAD_LIMIT` and no row is written.

    "Exceeding it is `ERR_NITROGEN_LOAD_LIMIT` (HTTP 422), and the check guards both task
    creation and application recording."

    Design: Corner/calculations/nitrogen_ceiling_is_keyed_to_the_area_type_constant
    """
    set_clock("2026-08-01T06:00:00Z")
    _green3, rough11, dana, urea = _five_thousand_foot_green_and_rough()

    refused = api_client.create_application(
        application_payload(
            rough11["id"], urea["id"], dana["id"], "2026-08-01T06:00:00Z",
            rate_lb_per_acre=350, wind_speed_mph=4, distance_to_water_ft=40,
        ),
        make_applicator_headers(dana["id"]),
    )
    validate_error(refused, ERR_NITROGEN_LOAD_LIMIT, 422)

    _rows, meta = list_applications(turf_area_id=rough11["id"])
    assert_total_count(meta, 0)
    assert_nitrogen_ledgers(get_turf_area(rough11["id"]), 0.000, 0.000)


# --------------------------------------------------------------------------
# The water assessment's tier, keyed on the base charge
# --------------------------------------------------------------------------
def test_the_tier_steps_at_twenty_five_and_one_hundred_with_nothing_billable():
    """24.99, 25.00 and 100.00 of base charge select `T1`, `T2` and `T3` while billable
    gallons stay at zero, which is only reachable if the tier reads the base charge.

    "Third, the `tier` is selected **from `base_charge`, never from the final total**: a base
    charge below 25.00 is tier `T1`, a base charge below 100.00 but not below 25.00 is tier
    `T2`, and a base charge of 100.00 or more is tier `T3`."

    Design: Corner/calculations/water_assessment_tier_floors_are_hit_exactly_at_t2_and_t3
    """
    course, run_a, run_b, run_c = (
        _course_that_has_drawn_thirty_thousand_seven_hundred_seventy_gallons()
    )

    assert_irrigation_run(run_a, allotted_gal=7690.0, flow_gpm=128.17)
    complete_irrigation_run(run_a["id"])
    assert_water_assessment(
        get_water_assessment(course["id"]),
        billable_gal=0.0, base_charge=24.99, tier=AssessmentTier.T1.value,
        surcharge_rate=0.90, surcharge=0.00, total_charge=24.99,
    )

    assert_irrigation_run(run_b, allotted_gal=3.0, flow_gpm=0.05)
    complete_irrigation_run(run_b["id"])
    assert_water_assessment(
        get_water_assessment(course["id"]),
        billable_gal=0.0, base_charge=25.00, tier=AssessmentTier.T2.value,
        surcharge_rate=1.40, surcharge=0.00, total_charge=25.00,
    )

    assert_irrigation_run(run_c, allotted_gal=23077.0, flow_gpm=384.62)
    complete_irrigation_run(run_c["id"])
    assert_water_assessment(
        get_water_assessment(course["id"]),
        billable_gal=0.0, base_charge=100.00, tier=AssessmentTier.T3.value,
        surcharge_rate=2.10, surcharge=0.00, total_charge=100.00,
    )

    assert_course(
        get_course(course["id"]), water_posture=WaterPosture.OPEN.value
    )
    assert_1dp(get_course(course["id"])["water_used_gal"], 30770.0)


def test_cutting_the_allocation_makes_the_overage_billable_and_suspends_the_course():
    """Two allocation cuts leave 30770.0 gallons against 25000, so 5770.0 gallons become
    billable at the `T3` rate for a 12.12 surcharge and a 112.12 total, and the posture ends
    `SUSPENDED`.

    "Fifth, the `surcharge` is `billable_gal` divided by 1000, multiplied by the surcharge
    rate, rounded half up to two decimal places. Sixth, the `total_charge` is the base charge
    plus the surcharge, rounded half up to two decimal places."

    Design: Corner/calculations/water_assessment_tier_floors_are_hit_exactly_at_t2_and_t3
    """
    course, run_a, run_b, run_c = (
        _course_that_has_drawn_thirty_thousand_seven_hundred_seventy_gallons()
    )
    for run in (run_a, run_b, run_c):
        complete_irrigation_run(run["id"])

    restricted = revise_water_allocation(
        course["id"], annual_water_allocation_gal=35000
    )
    assert restricted["water_posture"] == WaterPosture.RESTRICTED.value

    suspended = revise_water_allocation(
        course["id"], annual_water_allocation_gal=25000
    )
    assert suspended["water_posture"] == WaterPosture.SUSPENDED.value

    assert_water_assessment(
        get_water_assessment(course["id"]),
        billable_gal=5770.0, base_charge=100.00, tier=AssessmentTier.T3.value,
        surcharge_rate=2.10, surcharge=12.12, total_charge=112.12,
    )


# --------------------------------------------------------------------------
# The calendar-year predicate under the applied ledger
# --------------------------------------------------------------------------
def test_the_applied_ledger_drops_last_years_spray_when_the_clock_rolls_over():
    """1.583 lb per thousand recorded on 31 December reads 0.000 on 5 January, and the new
    January spray leaves the ledger at 1.055 rather than at the sum of the two.

    "**The applied-actual figure**, persisted as `nitrogen_applied_lb_per_1000_ytd` and
    reported when the area is read, counts only nitrogen already applied."

    "For each application record on the area whose record status is `RECORDED` or `VERIFIED`
    and whose `applied_at` falls in the logical clock's calendar year, take the application's
    applied nitrogen mass divided by the area's square footage divided by 1000, and round
    that per-application figure half up to three decimal places; then add the already-rounded
    per-application figures and round the sum half up to three decimal places again."

    Design: Corner/calculations/applied_load_counts_only_the_clock_years_applications
    """
    set_clock("2025-12-31T06:00:00Z")
    green7, dana, urea = _four_thousand_foot_green_and_a_urea_bag()
    december = record_application(
        green7["id"], urea["id"], dana["id"], "2025-12-31T06:00:00Z",
        rate_lb_per_acre=150, wind_speed_mph=4, distance_to_water_ft=40,
    )
    assert_3dp(
        get_turf_area(green7["id"])["nitrogen_applied_lb_per_1000_ytd"], 1.583
    )

    set_clock("2026-01-05T06:00:00Z")
    assert_3dp(
        get_turf_area(green7["id"])["nitrogen_applied_lb_per_1000_ytd"], 0.000
    )

    january = record_application(
        green7["id"], urea["id"], dana["id"], "2026-01-05T06:00:00Z",
        rate_lb_per_acre=100, wind_speed_mph=4, distance_to_water_ft=40,
    )

    assert_2dp(january["total_lb"], 9.18)
    assert_2dp(january["nitrogen_lb"], 4.22)
    assert_3dp(
        get_turf_area(green7["id"])["nitrogen_applied_lb_per_1000_ytd"], 1.055
    )
    assert december["record_status"] == RecordStatus.RECORDED.value
    assert january["record_status"] == RecordStatus.RECORDED.value


# --------------------------------------------------------------------------
# Frost pushback: pacing, exemption, and the strict candidate predicate
# --------------------------------------------------------------------------
def test_the_ten_minute_separation_and_not_the_frost_sets_the_second_release():
    """The 07:00 round takes the naive 45 minute release, the 07:05 round is lifted past its
    naive 07:50 to the 07:55 separation floor for 50 minutes, and the round starting exactly
    at the expected clear is never a candidate.

    "Otherwise, its `effective_start_at` is the naive release when no sequential event has yet
    been released, and otherwise the later of the naive release and the previous sequential
    effective start advanced by a minimum separation of 10 minutes; the candidate then becomes
    the carried previous sequential effective start."

    Design: Corner/calculations/frost_pushback_paces_sequential_fields_and_exempts_the_shotgun
    """
    course, _late, first, at_the_clear, _shotgun, tournament, frost = (
        _five_rounds_posted_out_of_order()
    )

    assert_play_event(
        get_play_event(first["id"]),
        effective_start_at="2026-08-05T07:45:00Z",
        delayed_minutes=45,
        status=PlayEventStatus.DELAYED.value,
    )
    assert_play_event(
        get_play_event(tournament["id"]),
        effective_start_at="2026-08-05T07:55:00Z",
        delayed_minutes=50,
        status=PlayEventStatus.DELAYED.value,
    )
    assert_play_event(
        get_play_event(at_the_clear["id"]),
        expected_version=1,
        effective_start_at="2026-08-05T08:00:00Z",
        delayed_minutes=0,
        status=PlayEventStatus.SCHEDULED.value,
    )
    assert_weather_event(
        frost,
        status=WeatherEventStatus.ACTIVE.value,
        declared_at="2026-08-05T06:30:00Z",
    )
    assert_course(
        get_course(course["id"]),
        expected_version=2,
        play_posture=PlayPosture.FROST_DELAY.value,
        frost_delay_minutes=45,
    )


def test_the_shotgun_takes_the_naive_release_and_does_not_push_the_field_behind_it():
    """The shotgun releases at 08:05 on the bare 45 minute pushback, and because it leaves the
    carried state alone the 07:22 round releases at its own naive 08:07 rather than at 08:15.

    "If the candidate is a `SHOTGUN_START`, its `effective_start_at` is exactly that naive
    release: a simultaneous start puts every group on the course at one instant, so it needs no
    separation from the group ahead of it, **and it does not push the group behind it** — it
    leaves the carried effective-start state unchanged."

    Design: Corner/calculations/frost_pushback_paces_sequential_fields_and_exempts_the_shotgun
    """
    _course, late, _first, _at_the_clear, shotgun, _tournament, _frost = (
        _five_rounds_posted_out_of_order()
    )

    assert_play_event(
        get_play_event(shotgun["id"]),
        effective_start_at="2026-08-05T08:05:00Z",
        delayed_minutes=45,
        status=PlayEventStatus.DELAYED.value,
    )
    assert_play_event(
        get_play_event(late["id"]),
        effective_start_at="2026-08-05T08:07:00Z",
        delayed_minutes=45,
        status=PlayEventStatus.DELAYED.value,
    )


# --------------------------------------------------------------------------
# Play posture as a projection of the active event set
# --------------------------------------------------------------------------
def test_the_posture_masks_and_unmasks_the_events_it_outranks():
    """Rain, frost and lightning stack up and come back down in precedence order: the frost
    re-emerges when the lightning clears, the newer frost governs while both are active, and
    each posture movement costs the course exactly one version.

    "Precedence is pinned, most restrictive first. If any active event is a lightning event or
    a storm-damage event, the posture is `CLOSED` and the course's `frost_delay_minutes` is 0.
    Otherwise, if any active event is a frost event, the posture is `FROST_DELAY` and
    `frost_delay_minutes` takes the delay of the **governing** frost event, which is the active
    frost event with the greatest `declared_at`, breaking a tie by the greatest `created_at`.
    Otherwise, if any active event is a heavy-rain event, the posture is `CART_PATH_ONLY` and
    `frost_delay_minutes` is 0. Otherwise the posture is `OPEN` and `frost_delay_minutes`
    is 0."

    Design: Corner/calculations/play_posture_projects_the_active_event_set_by_precedence
    """
    course = create_course(annual_water_allocation_gal=500000)

    rain = declare_weather_event(
        course["id"], WeatherEventType.HEAVY_RAIN.value, "2026-08-01T18:00:00Z",
        expected_course_version=course["version"],
    )
    after_rain = get_course(course["id"])
    assert_course(
        after_rain, expected_version=2,
        play_posture=PlayPosture.CART_PATH_ONLY.value, frost_delay_minutes=0,
    )

    first_frost = declare_weather_event(
        course["id"], WeatherEventType.FROST.value, "2026-08-01T14:00:00Z",
        expected_course_version=after_rain["version"], delay_minutes=30,
    )
    after_frost = get_course(course["id"])
    assert_course(
        after_frost, expected_version=3,
        play_posture=PlayPosture.FROST_DELAY.value, frost_delay_minutes=30,
    )

    lightning = declare_weather_event(
        course["id"], WeatherEventType.LIGHTNING.value, "2026-08-01T10:00:00Z",
        expected_course_version=after_frost["version"],
    )
    assert_course(
        get_course(course["id"]), expected_version=4,
        play_posture=PlayPosture.CLOSED.value, frost_delay_minutes=0,
    )

    clear_weather_event(lightning["id"])
    unmasked = get_course(course["id"])
    assert_course(
        unmasked, expected_version=5,
        play_posture=PlayPosture.FROST_DELAY.value, frost_delay_minutes=30,
    )

    second_frost = declare_weather_event(
        course["id"], WeatherEventType.FROST.value, "2026-08-01T15:00:00Z",
        expected_course_version=unmasked["version"], delay_minutes=60,
    )
    assert_course(
        get_course(course["id"]), expected_version=6,
        play_posture=PlayPosture.FROST_DELAY.value, frost_delay_minutes=60,
    )

    clear_weather_event(second_frost["id"])
    assert_course(
        get_course(course["id"]), expected_version=7,
        play_posture=PlayPosture.FROST_DELAY.value, frost_delay_minutes=30,
    )

    clear_weather_event(first_frost["id"])
    assert_course(
        get_course(course["id"]), expected_version=8,
        play_posture=PlayPosture.CART_PATH_ONLY.value, frost_delay_minutes=0,
    )

    cleared_rain = clear_weather_event(rain["id"])
    assert_course(
        get_course(course["id"]), expected_version=9,
        play_posture=PlayPosture.OPEN.value, frost_delay_minutes=0,
    )
    assert cleared_rain["status"] == WeatherEventStatus.CLEARED.value
