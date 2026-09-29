"""Optimistic concurrency: a superseded version guard refuses an otherwise legal write."""

from test_helpers import (
    DIRECTOR_HEADERS,
    LAUNDRY_LEAD_HEADERS,
    OCCUPANCY_DUE_OUT,
    SERVICE_CHECKOUT,
    ApiErrorId,
    assert_credits,
    assert_linen_buckets,
    build_scenario,
    laundry_cycle_payload,
    read_linen_item,
    read_roster,
    soil_linen,
    validate_error,
    validate_paginated,
    validate_success,
)

TWO_DEPARTURE_DAY = {
    "forecast_occupied_rooms": 2,
    "forecast_arrivals": 0,
    "forecast_departures": 2,
    "planned_deep_clean_rooms": 0,
}


# --------------------------------------------------------------------------
# The roster version guard on assignment creation
# --------------------------------------------------------------------------


def test_replaying_the_version_seen_before_the_first_room_is_refused(api):
    """Adding a second room is legitimate work, so only the stale version can refuse it.

    PRD 2.7: "If `expected_roster_version` does not equal the roster's current
    `version`, the create is rejected with `ERR_STALE_ROSTER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_expected_roster_version_on_assignment_create_is_rejected
    """
    scenario = build_scenario(
        api,
        rooms=[
            {"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT},
            {"number": "102", "occupancy_state": OCCUPANCY_DUE_OUT},
        ],
        forecast=TWO_DEPARTURE_DAY,
        clocked_in=False,
    )
    stale_version = read_roster(api, scenario.roster_id)["version"]
    assert stale_version == 1
    first = scenario.assign(
        "101", SERVICE_CHECKOUT, headers=scenario.supervisor_headers()
    )
    assert first["roster_version_after"] == 2, (
        "the first create must report the roster version one greater than the created "
        f"version 1, got {first['roster_version_after']}"
    )

    response = scenario.assign_raw(
        "102",
        SERVICE_CHECKOUT,
        expected_roster_version=stale_version,
        headers=scenario.supervisor_headers(),
    )

    validate_error(response, ApiErrorId.STALE_ROSTER_VERSION, 412)
    roster = read_roster(api, scenario.roster_id)
    assert_credits(roster["assigned_credits"], 1.00, "assigned_credits")
    assert roster["version"] == 2, "the refused write must have changed nothing"
    rows, meta = validate_paginated(
        api.list_room_assignments({"roster_id": scenario.roster_id}, DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    accepted = validate_success(
        scenario.assign_raw(
            "102",
            SERVICE_CHECKOUT,
            expected_roster_version=2,
            headers=scenario.supervisor_headers(),
        ),
        201,
    )
    assert accepted["roster_version_after"] == 3, (
        "the identical body with the current version must be accepted and chain on"
    )


# --------------------------------------------------------------------------
# The linen version guard on laundry dispatch
# --------------------------------------------------------------------------


def test_a_fully_fundable_dispatch_on_a_superseded_linen_view_is_refused(api):
    """Six sets out of a queue of eight is affordable; the soil call moved the version.

    PRD 2.7: "If `expected_linen_item_version` does not equal the linen item's
    current `version`, the dispatch is rejected with `ERR_STALE_LINEN_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_expected_linen_item_version_on_dispatch_is_rejected
    """
    scenario = build_scenario(
        api,
        rooms=["101"],
        linen={"total_owned_sets": 20},
        with_worker=False,
        with_inspector=False,
        with_day=False,
        with_roster=False,
    )
    stale_version = read_linen_item(api, scenario.linen_id)["version"]
    assert stale_version == 1
    soiled = soil_linen(api, scenario.linen_id, 8)
    assert_linen_buckets(soiled, 12, 0, 8)
    assert soiled["version"] == 2, (
        f"the soil must advance the linen version by one, got {soiled['version']}"
    )
    payload = laundry_cycle_payload(
        scenario.linen_id,
        6,
        "2026-08-03T08:00:00.000Z",
        "2026-08-03T12:00:00.000Z",
        stale_version,
    )

    response = api.create_laundry_cycle(payload, LAUNDRY_LEAD_HEADERS)

    validate_error(response, ApiErrorId.STALE_LINEN_VERSION, 412)
    line = read_linen_item(api, scenario.linen_id)
    assert_linen_buckets(line, 12, 0, 8)
    assert line["version"] == 2, "the refused dispatch must not move the linen version"
    _, meta = validate_paginated(
        api.list_laundry_cycles({"linen_item_id": scenario.linen_id}, DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 0, "the refused dispatch must leave no cycle"
    payload["expected_linen_item_version"] = 2
    dispatched = validate_success(
        api.create_laundry_cycle(payload, LAUNDRY_LEAD_HEADERS), 201
    )
    assert dispatched["batch_sets"] == 6
    assert_linen_buckets(read_linen_item(api, scenario.linen_id), 12, 6, 2)
