"""Two overlap rules on one endpoint, with deliberately different conventions."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import PERMIT_HEADERS, PLANNER_HEADERS, SCHEDULER_HEADERS
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import schedule_payload
from test_helpers.fixtures import (
    approve_all_permits,
    assess_pad,
    build_campus,
    certify_study,
    create_crew,
    create_request,
    create_schedule,
    create_site,
    create_study,
    create_unit,
    submit_study,
)

FIRST_WINDOW = ("2027-06-15", "2027-06-25")


def _two_permitted_requests(api, *, school_name, crew_name, max_concurrent_jobs,
                            asset_prefix, second_window, share_pad,
                            first_window=FIRST_WINDOW):
    """Two permitted requests over one crew, on one shared pad or on two pads."""
    ctx = build_campus(
        api,
        school_overrides={"name": school_name, "site_acreage": 9.0},
        projections=((6, 24), (7, 24), (8, 24)),
    )
    ctx["crew_id"] = create_crew(api, name=crew_name,
                                max_concurrent_jobs=max_concurrent_jobs)["id"]

    site_one = create_site(api, ctx["school_id"], pad_code="PAD-ONE")
    assess_pad(api, site_one["id"])
    ctx["site_one_id"] = site_one["id"]
    if share_pad:
        ctx["site_two_id"] = site_one["id"]
    else:
        site_two = create_site(api, ctx["school_id"], pad_code="PAD-TWO",
                               distance_to_fire_lane_ft=45)
        assess_pad(api, site_two["id"])
        ctx["site_two_id"] = site_two["id"]

    unit_one = create_unit(api, asset_tag=f"{asset_prefix}101")
    unit_two = create_unit(api, asset_tag=f"{asset_prefix}102")

    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])
    certify_study(api, study["id"])
    ctx["study_id"] = study["id"]

    ctx["request_one_id"] = create_request(
        api, study["id"], ctx["site_one_id"], ctx["budget_id"], haul_miles=10,
        portable_unit_id=unit_one["id"],
        requested_window_start=first_window[0], requested_window_end=first_window[1],
    )["id"]
    ctx["request_two_id"] = create_request(
        api, study["id"], ctx["site_two_id"], ctx["budget_id"], haul_miles=10,
        portable_unit_id=unit_two["id"],
        requested_window_start=second_window[0], requested_window_end=second_window[1],
    )["id"]

    for request_id in (ctx["request_one_id"], ctx["request_two_id"]):
        validate_success(api.assess_site(request_id, {}, PLANNER_HEADERS))
        validate_success(api.submit_permits(request_id, {}, PERMIT_HEADERS))
        approve_all_permits(api, request_id)

    ctx["schedule_one_id"] = create_schedule(
        api, ctx["request_one_id"], ctx["crew_id"],
        window_start=first_window[0], window_end=first_window[1],
    )["id"]
    return ctx


def _shared_pad_context(api, second_window=("2027-07-02", "2027-07-12"),
                        first_window=FIRST_WINDOW):
    return _two_permitted_requests(
        api, school_name="Ironwood Middle", crew_name="Crew Alpha",
        max_concurrent_jobs=2, asset_prefix="PU-P", second_window=second_window,
        share_pad=True, first_window=first_window,
    )


def test_pad_reuse_exactly_seven_days_after_the_previous_window_conflicts(api):
    """PRD §3.8: "**Pad occupation** treats windows as closed intervals with a 7
    calendar day turnaround buffer on each side: the new window conflicts with any
    schedule belonging to a different request on the same pad whose status is `PLANNED`
    or `IN_PROGRESS` unless the new opening date falls more than 7 days after that
    schedule's closing date, or the new closing date falls more than 7 days before that
    schedule's opening date. A conflict is rejected with `ERR_PAD_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/pad_reuse_closed_interval_with_turnaround_buffer
    """
    ctx = _shared_pad_context(api)

    response = api.create_installation_schedule(
        schedule_payload(ctx["request_two_id"], ctx["crew_id"],
                         window_start="2027-07-02", window_end="2027-07-12"),
        SCHEDULER_HEADERS,
    )
    validate_error(response, ApiErrorId.PAD_WINDOW_CONFLICT, expected_status=409)

    rows, meta = validate_paginated(
        api.list_installation_schedules(
            SCHEDULER_HEADERS, {"placement_request_id": ctx["request_two_id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0

    assert validate_success(
        api.get_placement_request(ctx["request_two_id"], PLANNER_HEADERS)
    )["status"] == "PERMITTED"
    assert validate_success(
        api.get_installation_schedule(ctx["schedule_one_id"], SCHEDULER_HEADERS)
    )["status"] == "PLANNED"


def test_pad_buffer_is_symmetric_and_clears_one_day_past_the_seventh(api):
    """PRD §3.8: "unless the new opening date falls more than 7 days after that
    schedule's closing date, or the new closing date falls more than 7 days before that
    schedule's opening date." PRD §3.8 on the accepted booking: "Booking moves the
    request `PERMITTED → SCHEDULED`, increments the request's `version` by 1, and opens
    the schedule in `PLANNED` with a null `cancellation_reason`."

    Design: Difficulty/resource_temporal_overlap/pad_reuse_closed_interval_with_turnaround_buffer
    """
    # The occupying schedule sits late in the summer window so that both probes
    # below still lie "entirely inside June 15 through August 15": PRD §2.6
    # evaluates that rule (35) ahead of the pad turnaround buffer (rule 38).
    ctx = _shared_pad_context(
        api,
        first_window=("2027-08-01", "2027-08-10"),
        second_window=("2027-07-20", "2027-07-25"),
    )

    early = api.create_installation_schedule(
        schedule_payload(ctx["request_two_id"], ctx["crew_id"],
                         window_start="2027-07-20", window_end="2027-07-25"),
        SCHEDULER_HEADERS,
    )
    validate_error(early, ApiErrorId.PAD_WINDOW_CONFLICT, expected_status=409)

    accepted = validate_success(
        api.create_installation_schedule(
            schedule_payload(ctx["request_two_id"], ctx["crew_id"],
                             window_start="2027-07-20", window_end="2027-07-24"),
            SCHEDULER_HEADERS,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "PLANNED"
    assert validate_success(
        api.get_placement_request(ctx["request_two_id"], PLANNER_HEADERS)
    )["status"] == "SCHEDULED"


def _solo_crew_context(api, second_window=("2027-06-20", "2027-06-30")):
    return _two_permitted_requests(
        api, school_name="Junipero Middle", crew_name="Crew Solo",
        max_concurrent_jobs=1, asset_prefix="PU-Q", second_window=second_window,
        share_pad=False,
    )


def test_a_solo_crew_cannot_take_an_overlapping_second_window(api):
    """PRD §3.8: "**Crew capacity** treats windows as half-open intervals, so
    back-to-back bookings are permitted: count the crew's schedules whose status is
    `PLANNED` or `IN_PROGRESS` for which the new opening date falls strictly before the
    existing closing date and the existing opening date falls strictly before the new
    closing date; that count must be strictly less than the crew's
    `max_concurrent_jobs`, and reaching the ceiling is rejected with
    `ERR_CREW_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/crew_capacity_half_open_window_allows_adjacency
    """
    ctx = _solo_crew_context(api)

    response = api.create_installation_schedule(
        schedule_payload(ctx["request_two_id"], ctx["crew_id"],
                         window_start="2027-06-20", window_end="2027-06-30"),
        SCHEDULER_HEADERS,
    )
    validate_error(response, ApiErrorId.CREW_CAPACITY_EXCEEDED, expected_status=409)

    _, meta = validate_paginated(
        api.list_installation_schedules(
            SCHEDULER_HEADERS, {"installation_crew_id": ctx["crew_id"]})
    )
    assert meta["total_count"] == 1

    assert validate_success(
        api.get_placement_request(ctx["request_two_id"], PLANNER_HEADERS)
    )["status"] == "PERMITTED"
    assert validate_success(
        api.get_installation_schedule(ctx["schedule_one_id"], SCHEDULER_HEADERS)
    )["status"] == "PLANNED"


def test_a_crew_window_starting_on_the_previous_closing_day_is_allowed(api):
    """PRD §3.8: "**Crew capacity** treats windows as half-open intervals, so
    back-to-back bookings are permitted: count the crew's schedules ... for which the new
    opening date falls strictly before the existing closing date and the existing opening
    date falls strictly before the new closing date; that count must be strictly less
    than the crew's `max_concurrent_jobs`".

    Design: Difficulty/resource_temporal_overlap/crew_capacity_half_open_window_allows_adjacency
    """
    ctx = _solo_crew_context(api, second_window=("2027-06-25", "2027-07-05"))

    overlapping = api.create_installation_schedule(
        schedule_payload(ctx["request_two_id"], ctx["crew_id"],
                         window_start="2027-06-24", window_end="2027-07-04"),
        SCHEDULER_HEADERS,
    )
    validate_error(overlapping, ApiErrorId.CREW_CAPACITY_EXCEEDED, expected_status=409)

    adjacent = validate_success(
        api.create_installation_schedule(
            schedule_payload(ctx["request_two_id"], ctx["crew_id"],
                             window_start="2027-06-25", window_end="2027-07-05"),
            SCHEDULER_HEADERS,
        ),
        expected_status=201,
    )
    assert adjacent["status"] == "PLANNED"

    _, meta = validate_paginated(
        api.list_installation_schedules(
            SCHEDULER_HEADERS, {"installation_crew_id": ctx["crew_id"]})
    )
    assert meta["total_count"] == 2
