"""Half-open amenity windows, and the settling day either side of noisy work."""

from test_helpers import (
    LANDLORD_HEADERS,
    ApiErrorId,
    assert_allocation,
    book_and_confirm_allocation,
    create_amenity,
    get_allocation,
    get_phase,
    ids,
    schedule_phase,
    same_instant,
    setup_permitted_project,
    setup_project_with_phases,
    utc,
    validate_error,
    validate_paginated,
    validate_success,
)

NAMEPLATE = {
    "name": "Kendall Labs 400",
    "published_floor_to_floor_ft": 14.0,
    "published_live_load_psf": 95,
    "published_vibration_class": "VC_C",
    "exhaust_riser_capacity_cfm": 60000,
    "emergency_power_capacity_kw": 800,
    "chilled_water_capacity_tons": 1200,
}
PLATE = {
    "floor_to_floor_ft": 14.0,
    "live_load_psf": 95,
    "vibration_class": "VC_C",
    "sprinklered": True,
}
DEMAND = {
    "required_vibration_class": "VC_C",
    "required_exhaust_cfm": 50000,
    "required_power_kw": 700,
    "measured_live_load_psf": 88,
}
LEASE = {"base_rent_psf": 105.00, "delivery_deadline": "2026-12-31T00:00:00Z"}

# Two confirmed bookings that overlap each other on a suite for two.
EARLY_WINDOW = (utc(2026, 9, 10, 10), utc(2026, 9, 10, 12))
LATE_WINDOW = (utc(2026, 9, 10, 11), utc(2026, 9, 10, 13))
STRADDLING_WINDOW = (utc(2026, 9, 10, 11, 30), utc(2026, 9, 10, 12, 30))
ABUTTING_WINDOW = (utc(2026, 9, 10, 12), utc(2026, 9, 10, 13))
FOLLOWING_WINDOW = (utc(2026, 9, 10, 13), utc(2026, 9, 10, 14))

# The generating package's window, and the two candidates either side of the
# instant its settling day expires.
GENERATING_WINDOW = (utc(2026, 8, 10), utc(2026, 8, 12))
AT_THE_BUFFER = ("2026-08-13T00:00:00Z", utc(2026, 8, 14))
ONE_SECOND_CLEAR = ("2026-08-13T00:00:01Z", utc(2026, 8, 14))


def _conference_suite_for_two(api):
    """A permitted project plus a two-place conference suite on the same plate."""
    bundle = setup_permitted_project(
        api,
        allowance_psf=80.00,
        research_type="BSL2_BIOLOGY",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=4000,
        lease_overrides=dict(LEASE),
        building_overrides=NAMEPLATE,
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        project_overrides={
            "design_exhaust_cfm": 15000,
            "design_power_kw": 220,
            "scope_summary": "BSL2 biology fit-out, floor 2",
        },
    )
    bundle["amenity"] = create_amenity(
        api,
        bundle["building"]["id"],
        2,
        name="Level 2 Conference Suite",
        amenity_type="CONFERENCE",
        concurrent_capacity=2,
        vibration_sensitive=False,
        utility_draw_kw=5.00,
    )
    bundle["early"] = book_and_confirm_allocation(
        api, bundle["amenity"]["id"], bundle["project"]["id"], *EARLY_WINDOW, headcount=8
    )
    bundle["late"] = book_and_confirm_allocation(
        api, bundle["amenity"]["id"], bundle["project"]["id"], *LATE_WINDOW, headcount=6
    )
    return bundle


def _book(api, bundle, window, headcount):
    """Attempt one booking on the suite and return the raw response."""
    return api.create_allocation(
        {
            "amenity_id": bundle["amenity"]["id"],
            "project_id": bundle["project"]["id"],
            "window_start": window[0],
            "window_end": window[1],
            "headcount": headcount,
        },
        LANDLORD_HEADERS,
    )


def _noisy_work_and_a_quiet_package(api):
    """A scheduled vibration-generating package and a quiet package in draft."""
    bundle = setup_project_with_phases(
        api,
        [
            {
                "premium_class": "LAB_MEP",
                "work_class": "VIBRATION_GENERATING",
                "hard_cost_usd": 50000.00,
                "restoration_cost_usd": 30000.00,
            },
            {
                "premium_class": "CLEANROOM",
                "work_class": "QUIET",
                "hard_cost_usd": 30000.00,
                "restoration_cost_usd": 15000.00,
            },
        ],
        allowance_psf=80.00,
        research_type="BSL2_BIOLOGY",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=4000,
        lease_overrides=dict(LEASE),
        building_overrides=NAMEPLATE,
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        project_overrides={
            "design_exhaust_cfm": 15000,
            "design_power_kw": 220,
            "scope_summary": "BSL2 biology fit-out, floor 2",
        },
    )
    schedule_phase(api, bundle["phases"][0]["id"], *GENERATING_WINDOW)
    bundle["phases"] = [get_phase(api, p["id"]) for p in bundle["phases"]]
    return bundle


def test_a_booking_starting_inside_both_live_windows_is_refused(api):
    """The ceiling is an aggregate count taken at the peak instant.

    Two confirmed bookings already overlap on a suite that admits two at a time,
    and a third whose start instant falls inside both of them would make three,
    so it is refused even though it starts after one of them has nearly finished.

    Design: Difficulty/resource_temporal_overlap/amenity_capacity_counts_half_open_windows_end_instant_excluded
    """
    bundle = _conference_suite_for_two(api)
    assert bundle["amenity"]["concurrent_capacity"] == 2
    assert bundle["early"]["status"] == "CONFIRMED"
    assert bundle["late"]["status"] == "CONFIRMED"

    response = _book(api, bundle, STRADDLING_WINDOW, 4)
    validate_error(response, ApiErrorId.ERR_AMENITY_CAPACITY_EXCEEDED.value, 409)

    rows, meta = validate_paginated(
        api.list_allocations(LANDLORD_HEADERS, {"amenity_id": bundle["amenity"]["id"]})
    )
    assert meta["total_count"] == 2
    assert sorted(ids(rows)) == sorted([bundle["early"]["id"], bundle["late"]["id"]])


def test_a_booking_starting_as_another_ends_does_not_count_that_one(api):
    """A window runs from its start inclusive to its end exclusive.

    A booking starting at the instant the earlier one ends meets only the one
    booking that is genuinely still running, which brings the count to exactly
    the ceiling and is admitted; a booking starting as the later one ends meets
    nobody at all.

    Design: Difficulty/resource_temporal_overlap/amenity_capacity_counts_half_open_windows_end_instant_excluded
    """
    bundle = _conference_suite_for_two(api)

    abutting = validate_success(_book(api, bundle, ABUTTING_WINDOW, 4), 201)
    following = validate_success(_book(api, bundle, FOLLOWING_WINDOW, 4), 201)

    assert_allocation(abutting)
    assert abutting["status"] == "REQUESTED"
    assert same_instant(abutting["window_start"], ABUTTING_WINDOW[0])
    assert following["status"] == "REQUESTED"
    assert same_instant(following["window_start"], FOLLOWING_WINDOW[0])

    rows, meta = validate_paginated(
        api.list_allocations(LANDLORD_HEADERS, {"amenity_id": bundle["amenity"]["id"]})
    )
    assert meta["total_count"] == 4
    assert len(rows) == 4
    assert get_allocation(api, bundle["early"]["id"])["status"] == "CONFIRMED"
    assert get_allocation(api, bundle["late"]["id"])["status"] == "CONFIRMED"


def test_a_window_opening_exactly_one_day_after_the_noise_stops_still_conflicts(api):
    """The buffer comparison is inclusive at both ends.

    A quiet package asking for the instant exactly twenty-four hours after the
    generating package finishes lands on the far edge of the settling day, and
    because the comparison admits the touching instant the request is refused.

    Design: Difficulty/resource_temporal_overlap/phase_vibration_buffer_conflicts_at_exactly_24h_gap
    """
    bundle = _noisy_work_and_a_quiet_package(api)
    generating, quiet = bundle["phases"]
    assert generating["status"] == "SCHEDULED"
    assert generating["work_class"] == "VIBRATION_GENERATING"
    assert quiet["work_class"] == "QUIET"

    response = api.schedule_phase(
        quiet["id"],
        {"window_start": AT_THE_BUFFER[0], "window_end": AT_THE_BUFFER[1]},
        LANDLORD_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_VIBRATION_WINDOW_CONFLICT.value, 409)

    unchanged = get_phase(api, quiet["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["window_start"] is None


def test_one_second_past_the_settling_day_is_admitted(api):
    """A single second past the buffer edge clears the conflict.

    The same request moved one second later no longer touches the extended
    window and is scheduled, so the buffer is measured to the instant rather
    than to the day.

    Design: Difficulty/resource_temporal_overlap/phase_vibration_buffer_conflicts_at_exactly_24h_gap
    """
    bundle = _noisy_work_and_a_quiet_package(api)
    quiet = bundle["phases"][1]

    scheduled = schedule_phase(api, quiet["id"], *ONE_SECOND_CLEAR)

    assert scheduled["status"] == "SCHEDULED"
    assert same_instant(scheduled["window_start"], ONE_SECOND_CLEAR[0])
    assert same_instant(scheduled["window_end"], ONE_SECOND_CLEAR[1])
    assert get_phase(api, bundle["phases"][0]["id"])["status"] == "SCHEDULED"
