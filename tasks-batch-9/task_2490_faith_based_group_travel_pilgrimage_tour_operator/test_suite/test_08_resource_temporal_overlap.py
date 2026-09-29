"""Shared resources contended over time: half-open buffered site intervals,
closed-inclusive land date ranges, and the per-day pax aggregate."""

from __future__ import annotations

from test_helpers import (
    assert_instant_equals,
    ApiErrorId,
    api_client,
    create_departure,
    create_land_assignment,
    create_land_resource,
    create_program,
    create_sacred_site,
    create_service_booking,
    read_land_assignment,
    read_service_booking,
    validate_error,
    validate_success,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]
LAND = TEST_USERS["land_contractor"]


# ---------------------------------------------------------------------------
# Half-open buffered intervals at a sacred site
# ---------------------------------------------------------------------------


def _site_with_a_morning_mass():
    """One 60-minute Mass at a site with a 30-minute turnaround buffer."""
    program = create_program()
    first = create_departure(program["id"], departure_date="2026-11-01")
    second = create_departure(
        program["id"], departure_date="2026-11-15", return_date="2026-11-25"
    )
    site = create_sacred_site(
        name="Basilica of the Holy Sepulchre",
        country="IL",
        access_regime="PERMIT_REQUIRED",
        daily_capacity_pax=200,
        turnaround_buffer_minutes=30,
        requires_local_clergy=True,
    )
    held = create_service_booking(
        first["id"],
        site["id"],
        service_type="MASS",
        scheduled_start_utc="2026-11-02T06:00:00Z",
        duration_minutes=60,
        pax_count=20,
        permit_reference="PRM-2026-501",
    )
    return site, second, held


def test_a_service_starting_inside_the_previous_buffer_conflicts(api):
    """PRD §3.2: "Concretely, the requested booking conflicts with an existing
    booking whose `status` is `SITE_HELD`, `CLERGY_CONFIRMED` or `CONFIRMED`
    when the requested start falls strictly before the existing booking's
    buffered end **and** the existing booking's start falls strictly before the
    requested booking's buffered end."

    Design: Difficulty/resource_temporal_overlap/sacred_site_half_open_buffered_minute_overlap
    """
    site, second, held = _site_with_a_morning_mass()

    response = api_client.create_service_booking(
        {
            "departure_id": second["id"],
            "sacred_site_id": site["id"],
            "service_type": "GUIDED_VISIT",
            "scheduled_start_utc": "2026-11-02T07:15:00Z",
            "duration_minutes": 30,
            "pax_count": 20,
            "permit_reference": "PRM-2026-502",
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.SITE_SLOT_CONFLICT.value)

    live = read_service_booking(held["id"])
    # 06:00 plus 60 minutes of service plus a 30-minute buffer.
    assert_instant_equals(live["buffered_end_utc"], "2026-11-02T07:30:00Z")
    assert live["status"] == "SITE_HELD"


def test_a_service_starting_exactly_at_the_buffered_end_is_accepted(api):
    """PRD §3.2: "Touching exactly at a buffered-end boundary is therefore
    **not** an overlap: a service that begins at the precise instant a previous
    group's buffer expires is accepted."

    Design: Difficulty/resource_temporal_overlap/sacred_site_half_open_buffered_minute_overlap
    """
    site, second, _held = _site_with_a_morning_mass()

    response = api_client.create_service_booking(
        {
            "departure_id": second["id"],
            "sacred_site_id": site["id"],
            "service_type": "GUIDED_VISIT",
            "scheduled_start_utc": "2026-11-02T07:30:00Z",
            "duration_minutes": 30,
            "pax_count": 20,
            "permit_reference": "PRM-2026-502",
        },
        PLANNER,
    )
    created = validate_success(response, 201)

    assert created["status"] == "SITE_HELD"
    assert_instant_equals(created["buffered_end_utc"], "2026-11-02T08:30:00Z")


# ---------------------------------------------------------------------------
# Closed-inclusive land ranges
# ---------------------------------------------------------------------------


def _coach_pool_with_one_line():
    """A three-coach pool with two coaches drawn from 2026-10-05 to 2026-10-09."""
    program = create_program()
    first = create_departure(
        program["id"], departure_date="2026-10-05", return_date="2026-10-15"
    )
    second = create_departure(
        program["id"], departure_date="2026-10-09", return_date="2026-10-19"
    )
    resource = create_land_resource(
        operator_name="Jerusalem Ground Services",
        country="IL",
        resource_type="MOTORCOACH",
        units_total=3,
        unit_rate_local_cents=127_500,
        fx_rate_bp=10_833,
        force_majeure_notice_days=30,
    )
    line = create_land_assignment(
        resource["id"],
        first["id"],
        date_from="2026-10-05",
        date_to="2026-10-09",
        units_requested=2,
    )
    return resource, second, line


def test_land_lines_sharing_one_endpoint_date_add_up_and_oversubscribe(api):
    """PRD §3.3: "Note that unlike sacred-site intervals, which are half-open,
    land ranges are closed: two lines that share only a single endpoint date
    **do** overlap on that date and their draws **do** add up."

    Design: Difficulty/resource_temporal_overlap/land_resource_closed_inclusive_date_unit_capacity
    """
    resource, second, line = _coach_pool_with_one_line()

    response = api_client.create_land_assignment(
        {
            "land_resource_id": resource["id"],
            "departure_id": second["id"],
            "date_from": "2026-10-09",
            "date_to": "2026-10-12",
            "units_requested": 2,
        },
        LAND,
    )
    validate_error(response, ApiErrorId.LAND_RESOURCE_OVERSUBSCRIBED.value)

    live = read_land_assignment(line["id"])
    assert live["days_inclusive"] == 5
    assert live["line_local_cents"] == 1_275_000
    # 1275000 * 10833 / 10000 = 1381207.5 -> 1381208.
    assert live["line_usd_cents"] == 1_381_208


def test_the_same_range_for_one_unit_fits_the_pool_exactly(api):
    """PRD §3.3: "the server computes `days_inclusive` as the whole-day
    difference between `date_to` and `date_from` plus one, so a line whose
    `date_from` equals its `date_to` bills one day, not zero."

    Design: Difficulty/resource_temporal_overlap/land_resource_closed_inclusive_date_unit_capacity
    """
    resource, second, _line = _coach_pool_with_one_line()

    response = api_client.create_land_assignment(
        {
            "land_resource_id": resource["id"],
            "departure_id": second["id"],
            "date_from": "2026-10-09",
            "date_to": "2026-10-12",
            "units_requested": 1,
        },
        LAND,
    )
    created = validate_success(response, 201)

    assert created["status"] == "DRAFT"
    assert created["days_inclusive"] == 4
    assert created["line_local_cents"] == 510_000
    # 510000 * 10833 / 10000 = 552483 exactly.
    assert created["line_usd_cents"] == 552_483


# ---------------------------------------------------------------------------
# The per-day pax aggregate
# ---------------------------------------------------------------------------


def _grotto_with_a_morning_liturgy():
    """A 40-pax-per-day site already carrying a 25-pax liturgy."""
    program = create_program()
    departure = create_departure(program["id"], departure_date="2026-11-01")
    site = create_sacred_site(
        name="Grotto of the Annunciation",
        country="IL",
        access_regime="TICKETED_SLOT",
        daily_capacity_pax=40,
        turnaround_buffer_minutes=15,
        requires_local_clergy=False,
    )
    held = create_service_booking(
        departure["id"],
        site["id"],
        service_type="LITURGY",
        scheduled_start_utc="2026-11-03T09:00:00Z",
        duration_minutes=60,
        pax_count=25,
        permit_reference="SLOT-9911",
    )
    return site, departure, held


def test_a_non_overlapping_booking_can_still_breach_the_daily_pax_capacity(api):
    """PRD §3.2: "The sum of `pax_count` over the site's bookings whose `status`
    is not `CANCELLED` and whose `scheduled_start_utc` falls on the same UTC
    calendar date, taken together with the requested `pax_count`, must not
    exceed the site's `daily_capacity_pax`; exceeding it is
    `ERR_SITE_DAILY_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/sacred_site_daily_pax_aggregate_capacity
    """
    site, departure, held = _grotto_with_a_morning_liturgy()

    response = api_client.create_service_booking(
        {
            "departure_id": departure["id"],
            "sacred_site_id": site["id"],
            "service_type": "GUIDED_VISIT",
            "scheduled_start_utc": "2026-11-03T11:00:00Z",
            "duration_minutes": 45,
            "pax_count": 20,
            "permit_reference": "SLOT-9912",
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.SITE_DAILY_CAPACITY_EXCEEDED.value)

    live = read_service_booking(held["id"])
    assert live["status"] == "SITE_HELD"
    assert_instant_equals(live["buffered_end_utc"], "2026-11-03T10:15:00Z")


def test_a_booking_that_fills_the_daily_capacity_exactly_is_accepted(api):
    """PRD §3.2: "The sum of `pax_count` over the site's bookings whose `status`
    is not `CANCELLED` and whose `scheduled_start_utc` falls on the same UTC
    calendar date, taken together with the requested `pax_count`, must not
    exceed the site's `daily_capacity_pax`; exceeding it is
    `ERR_SITE_DAILY_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/sacred_site_daily_pax_aggregate_capacity
    """
    site, departure, _held = _grotto_with_a_morning_liturgy()

    response = api_client.create_service_booking(
        {
            "departure_id": departure["id"],
            "sacred_site_id": site["id"],
            "service_type": "GUIDED_VISIT",
            "scheduled_start_utc": "2026-11-03T11:00:00Z",
            "duration_minutes": 45,
            "pax_count": 15,
            "permit_reference": "SLOT-9912",
        },
        PLANNER,
    )
    created = validate_success(response, 201)

    assert created["status"] == "SITE_HELD"
    assert created["pax_count"] == 15
