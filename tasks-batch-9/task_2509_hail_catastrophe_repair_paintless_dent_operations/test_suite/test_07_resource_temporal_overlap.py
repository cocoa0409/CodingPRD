"""Interval arithmetic on two resources that disagree about their endpoints."""

from test_helpers import (
    CREW_COORDINATOR,
    assert_housing_occupancy,
    create_deployment,
    create_technician,
    crew_deployment_payload,
    read_deployment,
    read_housing_units,
    setup_housed_crew,
    setup_operational_facility,
    tech_id,
    validate_error,
    validate_paginated,
    validate_success,
)

TA_END = "2026-08-20"


def _site_with_a_stint_ending_on_the_twentieth(api):
    scenario = setup_operational_facility(api, technicians=("TA",), deployment_end=TA_END)
    return scenario


def _request_deployment(api, scenario, technician_id, start_date, end_date):
    return api.create_crew_deployment(
        crew_deployment_payload(
            technician_id, scenario["facility_id"], start_date, end_date
        ),
        CREW_COORDINATOR,
    )


def test_back_to_back_deployments_of_one_technician_collide(api):
    """PRD §3.3: "The practical consequence is that at least one clear calendar
    day must separate two deployments of the same technician; back-to-back
    intervals collide."

    PRD §3.3: "The new deployment starts `CONFIRMED`, with a null
    `actual_end_date`; its `effective_end_date` is the planned `end_date` until
    the deployment ends, after which it is the `actual_end_date`."

    Design: Difficulty/resource_temporal_overlap/rest_buffer_day_rejects_adjacent_deployment_intervals_per_technician
    """
    scenario = _site_with_a_stint_ending_on_the_twentieth(api)
    traveller_id = tech_id(scenario, "TA")

    standing = read_deployment(api, scenario["deployments"]["TA"]["id"])
    assert standing["effective_end_date"] == TA_END
    assert standing["actual_end_date"] is None

    # Starting on the last day of the standing stint overlaps outright.
    same_day = _request_deployment(api, scenario, traveller_id, "2026-08-20", "2026-09-05")
    validate_error(same_day, "ERR_TECHNICIAN_DEPLOYMENT_OVERLAP", 409)

    # Starting the very next day is exactly what the rest buffer forbids.
    adjacent = _request_deployment(api, scenario, traveller_id, "2026-08-21", "2026-09-05")
    validate_error(adjacent, "ERR_TECHNICIAN_DEPLOYMENT_OVERLAP", 409)


def test_one_clear_day_is_enough_and_the_rule_is_per_technician(api):
    """PRD §3.3: "Second, **deployment exclusivity** protects the traveling crew
    from being double-booked and from being driven straight from one storm to the
    next."

    PRD §3.3: "A rest buffer of one calendar day is added to both ends of every
    interval before the comparison, so the requested deployment collides with an
    existing `CONFIRMED` or `ON_SITE` deployment of the same technician whenever
    the requested `start_date` is no later than one day after that existing
    deployment's effective end, **and** one day after the requested `end_date` is
    no earlier than that existing deployment's `start_date`."

    Design: Difficulty/resource_temporal_overlap/rest_buffer_day_rejects_adjacent_deployment_intervals_per_technician
    """
    scenario = _site_with_a_stint_ending_on_the_twentieth(api)
    traveller_id = tech_id(scenario, "TA")

    rested = _request_deployment(api, scenario, traveller_id, "2026-08-22", "2026-09-05")
    created = validate_success(rested, 201)
    assert created["status"] == "CONFIRMED"

    # A different technician is not bound by the first one's rest day.
    colleague = create_technician(api, "TB")
    peer = _request_deployment(api, scenario, colleague["id"], "2026-08-21", "2026-09-05")
    validate_success(peer, 201)

    _, traveller_meta = validate_paginated(
        api.list_crew_deployments(CREW_COORDINATOR, {"technician_id": traveller_id})
    )
    assert traveller_meta["total_count"] == 2
    _, peer_meta = validate_paginated(
        api.list_crew_deployments(CREW_COORDINATOR, {"technician_id": colleague["id"]})
    )
    assert peer_meta["total_count"] == 1


def _single_bed_with_a_same_day_handover(api):
    """One bed, one stay ending on the 20th and one starting on the 20th."""
    scenario = setup_housed_crew(api, bed_count=1)
    unit_id = scenario["housing_unit_id"]

    leaving = create_technician(api, "TB")
    leaving_deployment = create_deployment(
        api, leaving["id"], scenario["facility_id"], "2026-08-05", "2026-08-20", unit_id
    )
    return scenario, unit_id, leaving_deployment


def test_the_new_arrival_takes_the_bed_on_the_day_the_last_one_leaves(api):
    """PRD §3.3: "For every calendar date in the half-open span running from the
    requested `start_date` inclusive up to the requested `end_date` exclusive, the
    server counts the deployments already on that housing unit that are
    `CONFIRMED` or `ON_SITE` and whose own half-open span — from their
    `start_date` inclusive up to their effective end exclusive — contains that
    date."

    PRD §3.3: "Adding one bed for the requested deployment, the total on every one
    of those dates must not exceed the unit's `bed_count`."

    Design: Difficulty/resource_temporal_overlap/housing_half_open_interval_allows_same_day_bed_handover
    """
    scenario, unit_id, _ = _single_bed_with_a_same_day_handover(api)

    arriving = create_technician(api, "TA")
    response = api.create_crew_deployment(
        crew_deployment_payload(
            arriving["id"], scenario["facility_id"], "2026-08-20", "2026-09-05", unit_id
        ),
        CREW_COORDINATOR,
    )
    handover = validate_success(response, 201)
    assert handover["housing_unit_id"] == unit_id
    assert handover["status"] == "CONFIRMED"


def test_a_straddling_stay_overflows_the_bed_unless_it_self_houses(api):
    """PRD §3.3: "If any single date would overflow, the whole request is rejected
    with `ERR_HOUSING_CAPACITY_EXCEEDED`."

    PRD §3.3: "A deployment is created by naming the `technician_id`, the
    `facility_id`, an inclusive `start_date` and an inclusive `end_date` no
    earlier than the start, and optionally a `housing_unit_id`; when the housing
    identifier is omitted the technician self-houses and the field stays null."

    PRD §3.3: "`bed_nights_committed` sums, over the unit's deployments that are
    `CONFIRMED`, `ON_SITE` or `ENDED`, the whole number of days from `start_date`
    to the deployment's effective end date — so a cancelled booking contributes
    nothing while an ended one contributes its shortened stay."

    Design: Difficulty/resource_temporal_overlap/housing_half_open_interval_allows_same_day_bed_handover
    """
    scenario, unit_id, _ = _single_bed_with_a_same_day_handover(api)
    arriving = create_technician(api, "TA")
    create_deployment(
        api, arriving["id"], scenario["facility_id"], "2026-08-20", "2026-09-05", unit_id
    )

    straddler = create_technician(api, "TD")
    blocked = api.create_crew_deployment(
        crew_deployment_payload(
            straddler["id"], scenario["facility_id"], "2026-08-10", "2026-08-25", unit_id
        ),
        CREW_COORDINATOR,
    )
    validate_error(blocked, "ERR_HOUSING_CAPACITY_EXCEEDED", 409)

    # The same interval is fine once the technician stops asking for a bed.
    self_housed = api.create_crew_deployment(
        crew_deployment_payload(
            straddler["id"], scenario["facility_id"], "2026-08-10", "2026-08-25"
        ),
        CREW_COORDINATOR,
    )
    created = validate_success(self_housed, 201)
    assert created["housing_unit_id"] is None

    units = read_housing_units(api, scenario["facility_id"])
    # Fifteen nights for the first stay plus sixteen for the second; the shared
    # handover date is counted once, not twice.
    assert_housing_occupancy(units[0], occupied_beds=1, bed_nights_committed=31)
