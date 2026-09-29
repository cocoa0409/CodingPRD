"""Two bookings competing for the same crew, and three competing for the same beds.

The deployment window is closed with a mandatory rest day either side of it; the
lodging night interval is half-open and pools demand across every group at the site.
The two conventions disagree about adjacency, which is what these scenarios pin down.
"""

from typing import Any, Dict

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_bed_night_identity,
    assert_housing_assignment,
    assert_lodging_site,
    assert_volunteer_deployment,
    create_deployment,
    create_housing_assignment,
    setup_lodging_site_with_groups,
    setup_permitted_project_with_group,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["volunteer_coordinator_headers"]


def _setup_group_already_booked_for_one_week() -> Dict[str, Any]:
    """A permitted phase with one requested booking running 2026-09-07 to 2026-09-11."""
    scenario = setup_permitted_project_with_group(
        project_overrides={
            "required_trade_hours": {"FRAMING": 300, "ROOFING": 150, "GENERAL_LABOR": 300},
            "estimated_material_cents": 900_000,
            "critical_trades": ["FRAMING"],
        },
        group_overrides={
            "group_name": "Pine Bluff Work Team",
            "home_organization": "Pine Bluff Fellowship",
            "member_count": 12,
            "skill_profile": {"FRAMING": 5, "ROOFING": 2, "GENERAL_LABOR": 12},
            "requires_housing": False,
        },
        permit_number="PB-3320",
    )
    scenario["first"] = create_deployment(
        scenario["group"]["id"], scenario["project"]["id"], "2026-09-07", "2026-09-11"
    )
    return scenario


def test_a_back_to_back_window_collides_through_the_one_day_turnaround(api):
    """PRD §3.8: "Concretely, the request is refused with
    `ERR_DEPLOYMENT_WINDOW_CONFLICT` when the group already has a deployment whose
    status is `REQUESTED`, `CONFIRMED` or `COMPLETED` such that the new `arrival_date`
    falls on or before that existing deployment's `departure_date` advanced by one day,
    **and** the new `departure_date` advanced by one day falls on or after that existing
    deployment's `arrival_date`."

    Design: Difficulty/resource_temporal_overlap/deployment_closed_interval_plus_one_day_turnaround_on_the_same_group
    """
    scenario = _setup_group_already_booked_for_one_week()
    assert scenario["first"]["status"] == "REQUESTED"

    response = api.create_volunteer_deployment(
        {
            "group_id": scenario["group"]["id"],
            "project_id": scenario["project"]["id"],
            "arrival_date": "2026-09-12",
            "departure_date": "2026-09-16",
        },
        COORDINATOR,
    )

    # The windows do not overlap, but there is no rest day between them.
    validate_error(response, ApiErrorId.ERR_DEPLOYMENT_WINDOW_CONFLICT.value, 409)
    bookings, meta = validate_paginated(
        api.list_volunteer_deployments(
            COORDINATOR, params={"group_id": scenario["group"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert bookings[0]["id"] == scenario["first"]["id"]


def test_one_rest_day_clears_the_turnaround_and_both_bookings_stand(api):
    """PRD §3.8: "Back-to-back windows with no rest day between them therefore collide,
    and the buffer applies on both sides."

    Design: Difficulty/resource_temporal_overlap/deployment_closed_interval_plus_one_day_turnaround_on_the_same_group
    """
    scenario = _setup_group_already_booked_for_one_week()
    validate_error(
        api.create_volunteer_deployment(
            {
                "group_id": scenario["group"]["id"],
                "project_id": scenario["project"]["id"],
                "arrival_date": "2026-09-12",
                "departure_date": "2026-09-16",
            },
            COORDINATOR,
        ),
        ApiErrorId.ERR_DEPLOYMENT_WINDOW_CONFLICT.value,
        409,
    )

    second = validate_success(
        api.create_volunteer_deployment(
            {
                "group_id": scenario["group"]["id"],
                "project_id": scenario["project"]["id"],
                "arrival_date": "2026-09-13",
                "departure_date": "2026-09-17",
            },
            COORDINATOR,
        ),
        201,
    )

    assert_volunteer_deployment(second)
    assert second["status"] == "REQUESTED"
    assert second["skill_fit_score_bps"] == 6000
    bookings, meta = validate_paginated(
        api.list_volunteer_deployments(
            COORDINATOR, params={"group_id": scenario["group"]["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert sorted(booking["arrival_date"] for booking in bookings) == [
        "2026-09-07",
        "2026-09-13",
    ]


def test_the_work_window_is_inclusive_at_both_ends(api):
    """PRD §3.8: "Both ends of the deployment window are **inclusive**: the crew works on
    the arrival date and on the departure date. The server computes `day_count` as the
    number of days from arrival to departure plus one, and `crew_hours_committed` as the
    group's `member_count` multiplied by six volunteer hours per day multiplied by
    `day_count`."

    Design: Difficulty/resource_temporal_overlap/deployment_closed_interval_plus_one_day_turnaround_on_the_same_group
    """
    scenario = _setup_group_already_booked_for_one_week()

    second = validate_success(
        api.create_volunteer_deployment(
            {
                "group_id": scenario["group"]["id"],
                "project_id": scenario["project"]["id"],
                "arrival_date": "2026-09-13",
                "departure_date": "2026-09-17",
            },
            COORDINATOR,
        ),
        201,
    )

    # 13th through 17th inclusive is five working days, not four.
    assert second["day_count"] == 5
    assert second["crew_hours_committed"] == 360
    assert scenario["first"]["day_count"] == 5
    assert scenario["first"]["crew_hours_committed"] == 360


def _setup_site_filled_by_two_groups() -> Dict[str, Any]:
    """A twenty-bed site whose 9th, 10th and 11th nights are pooled to capacity.

    A twelve-bed group stays 09-07 to 09-12 and an eight-bed group stays 09-09 to
    09-14; the three nights they share carry exactly twenty beds. A third group of one
    stands by.
    """
    scenario = setup_lodging_site_with_groups(
        bed_capacity=20,
        group_specs=[
            {
                "group_name": "Alder Street Crew",
                "home_organization": "Alder Street Church",
                "member_count": 12,
                "skill_profile": {"FRAMING": 5, "GENERAL_LABOR": 12},
            },
            {
                "group_name": "Birchwood Crew",
                "home_organization": "Birchwood Chapel",
                "member_count": 8,
                "skill_profile": {"ROOFING": 3, "GENERAL_LABOR": 8},
            },
            {
                "group_name": "Cottonwood Solo Volunteer",
                "home_organization": "Cottonwood Rotary",
                "member_count": 1,
                "skill_profile": {"GENERAL_LABOR": 1},
            },
        ],
    )
    scenario["first"] = create_housing_assignment(
        scenario["groups"][0]["id"], scenario["site"]["id"], "2026-09-07", "2026-09-12"
    )
    scenario["second"] = create_housing_assignment(
        scenario["groups"][1]["id"], scenario["site"]["id"], "2026-09-09", "2026-09-14"
    )
    return scenario


def test_bed_demand_pools_across_groups_on_the_nights_they_share(api):
    """PRD §2.9: "For a lodging site, `peak_committed_beds` is the largest value, taken
    over every night covered by any of that site's housing assignments whose status is
    `ACTIVE`, of the summed `beds_requested` of the assignments covering that night."

    Design: Difficulty/resource_temporal_overlap/lodging_beds_are_half_open_per_night_and_aggregate_across_groups
    """
    scenario = _setup_site_filled_by_two_groups()

    site = validate_success(api.get_lodging_site(scenario["site"]["id"], COORDINATOR))

    assert_lodging_site(site)
    assert site["bed_capacity"] == 20
    # 12 beds and 8 beds coincide on the nights of the 9th, 10th and 11th.
    assert site["peak_committed_beds"] == 20
    assert site["available_beds"] == 0
    assert site["status"] == "FULL"
    assert_bed_night_identity(site)
    assert scenario["first"]["beds_requested"] == 12
    assert scenario["first"]["night_count"] == 5
    assert scenario["second"]["beds_requested"] == 8


def test_one_extra_bed_on_a_pooled_full_night_is_refused(api):
    """PRD §3.8: "And the site must have room on every night of the interval: for each
    night from the check-in date up to but not including the check-out date, the sum of
    `beds_requested` over that site's `ACTIVE` housing assignments covering that night,
    plus this group's `member_count`, may not exceed the site's `bed_capacity`; a
    violation on any single night is refused with `ERR_LODGING_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/lodging_beds_are_half_open_per_night_and_aggregate_across_groups
    """
    scenario = _setup_site_filled_by_two_groups()

    response = api.create_housing_assignment(
        {
            "group_id": scenario["groups"][2]["id"],
            "lodging_site_id": scenario["site"]["id"],
            "check_in_date": "2026-09-10",
            "check_out_date": "2026-09-11",
        },
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_LODGING_CAPACITY_EXCEEDED.value, 409)
    site = validate_success(api.get_lodging_site(scenario["site"]["id"], COORDINATOR))
    assert site["peak_committed_beds"] == 20
    assert site["status"] == "FULL"


def test_the_night_of_a_check_out_date_is_free_for_someone_else(api):
    """PRD §3.8: "A housing assignment hosts one group at one site over a **half-open**
    night interval given by `check_in_date` and `check_out_date`: the night of the
    check-out date is *not* occupied."

    Design: Difficulty/resource_temporal_overlap/lodging_beds_are_half_open_per_night_and_aggregate_across_groups
    """
    scenario = _setup_site_filled_by_two_groups()
    validate_error(
        api.create_housing_assignment(
            {
                "group_id": scenario["groups"][2]["id"],
                "lodging_site_id": scenario["site"]["id"],
                "check_in_date": "2026-09-10",
                "check_out_date": "2026-09-11",
            },
            COORDINATOR,
        ),
        ApiErrorId.ERR_LODGING_CAPACITY_EXCEEDED.value,
        409,
    )

    # The twelve-bed group checks out on the 12th, so it does not hold that night.
    accepted = validate_success(
        api.create_housing_assignment(
            {
                "group_id": scenario["groups"][2]["id"],
                "lodging_site_id": scenario["site"]["id"],
                "check_in_date": "2026-09-12",
                "check_out_date": "2026-09-13",
            },
            COORDINATOR,
        ),
        201,
    )

    assert_housing_assignment(accepted)
    assert accepted["status"] == "ACTIVE"
    assert accepted["night_count"] == 1
    assert accepted["beds_requested"] == 1
    assignments, meta = validate_paginated(
        api.list_housing_assignments(
            COORDINATOR, params={"lodging_site_id": scenario["site"]["id"]}
        )
    )
    assert meta["total_count"] == 3
    assert all(assignment["status"] == "ACTIVE" for assignment in assignments)
