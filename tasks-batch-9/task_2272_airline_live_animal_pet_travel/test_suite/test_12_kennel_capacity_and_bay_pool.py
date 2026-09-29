"""Kennel provisioning: peak-occupancy projection, sanitation buffer, bay pool.

Capacity is a projection over overlapping windows widened by a forty-five minute
sanitation buffer, while the station's pool counter is a plain sum over the open
allocations, so the two numbers answer different questions.
"""

from test_helpers import (
    ApiErrorId,
    assert_station_bays,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_kennel_bays_aggregate_across_sanitation_buffer_window_rejected(
    api, workbench, staged_kennel_allocations, acceptance_agent_headers
):
    """Two holds whose windows only meet inside the sanitation buffer both count
    towards the projected peak, so a third one bay request no longer fits.

    PRD §3.7: "The projected peak is the candidate's `bay_count` plus the sum of
    `bay_count` over all overlapping allocations, and the create is accepted only when
    that projected peak is at most the station's `kennel_bay_count`; exact equality is
    accepted, and anything greater is refused with `ERR_KENNEL_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/kennel_bays_aggregate_across_sanitation_buffer_window_rejected
    """
    state = staged_kennel_allocations()
    hkg_id = state["catalog"]["hkg_id"]
    assert_station_bays(workbench.read_station(hkg_id), 4)

    refused = api.create_kennel_allocation(
        {
            "station_id": hkg_id,
            "animal_record_id": state["animal_id"],
            "bay_count": 1,
            "occupancy_start_utc": "2026-08-05T09:40:00Z",
            "occupancy_end_utc": "2026-08-05T10:00:00Z",
            "feeding_interval_minutes": 240,
            "expected_station_version": workbench.station_version(hkg_id),
        },
        acceptance_agent_headers,
    )
    validate_error(refused, ApiErrorId.KENNEL_CAPACITY_EXCEEDED, 409)

    assert_station_bays(workbench.read_station(hkg_id), 4)
    rows, meta = validate_paginated(
        api.list_kennel_allocations(acceptance_agent_headers, {"station_id": hkg_id})
    )
    assert meta["total_count"] == 2
    assert sorted(ids_of(rows)) == sorted(
        [state["allocation_one_id"], state["allocation_two_id"]]
    )


def test_kennel_allocation_starting_exactly_at_the_effective_end_does_not_overlap(
    api, workbench, screened_booking, acceptance_agent_headers
):
    """One minute inside the sanitation buffer the two holds aggregate and the request
    is refused; starting exactly at the effective end they do not overlap at all.

    PRD §3.7: "Because both interval comparisons are strict, an allocation starting
    exactly at another allocation's effective end does not overlap it."

    Design: Difficulty/resource_temporal_overlap/kennel_bays_aggregate_across_sanitation_buffer_window_rejected
    """
    state = screened_booking()
    hkg_id = state["catalog"]["hkg_id"]
    workbench.create_kennel_allocation(
        hkg_id,
        state["animal_id"],
        bay_count=2,
        occupancy_start_utc="2026-08-05T06:00:00Z",
        occupancy_end_utc="2026-08-05T09:00:00Z",
    )
    assert_station_bays(workbench.read_station(hkg_id), 2)

    inside_buffer = api.create_kennel_allocation(
        {
            "station_id": hkg_id,
            "animal_record_id": state["animal_id"],
            "bay_count": 4,
            "occupancy_start_utc": "2026-08-05T09:44:00Z",
            "occupancy_end_utc": "2026-08-05T12:00:00Z",
            "feeding_interval_minutes": 240,
            "expected_station_version": workbench.station_version(hkg_id),
        },
        acceptance_agent_headers,
    )
    validate_error(inside_buffer, ApiErrorId.KENNEL_CAPACITY_EXCEEDED, 409)
    assert_station_bays(workbench.read_station(hkg_id), 2)

    at_effective_end = validate_success(
        api.create_kennel_allocation(
            {
                "station_id": hkg_id,
                "animal_record_id": state["animal_id"],
                "bay_count": 4,
                "occupancy_start_utc": "2026-08-05T09:45:00Z",
                "occupancy_end_utc": "2026-08-05T12:00:00Z",
                "feeding_interval_minutes": 240,
                "expected_station_version": workbench.station_version(hkg_id),
            },
            acceptance_agent_headers,
        ),
        201,
    )
    assert at_effective_end["status"] == "RESERVED"
    assert at_effective_end["bay_count"] == 4
    assert_station_bays(workbench.read_station(hkg_id), 6)


def test_station_bay_pool_returns_to_zero_after_staged_releases(
    api, workbench, screened_booking
):
    """Two holds raise the pool by their own bay counts and two releases take it back
    down to the baseline it started from.

    PRD §3.7: "the allocation moves to `RELEASED`, the station's `reserved_bay_count`
    is decremented by the allocation's `bay_count`, and the station's `version`
    increments by one."

    Design: Difficulty/compensating_invariant/station_bay_pool_returns_to_zero_after_staged_releases
    """
    state = screened_booking()
    hkg_id = state["catalog"]["hkg_id"]
    assert_station_bays(workbench.read_station(hkg_id), 0)

    first = workbench.create_kennel_allocation(
        hkg_id,
        state["animal_id"],
        bay_count=2,
        occupancy_start_utc="2026-08-05T06:00:00Z",
        occupancy_end_utc="2026-08-05T09:00:00Z",
    )
    assert_station_bays(workbench.read_station(hkg_id), 2)

    second = workbench.create_kennel_allocation(
        hkg_id,
        state["animal_id"],
        bay_count=1,
        occupancy_start_utc="2026-08-05T14:00:00Z",
        occupancy_end_utc="2026-08-05T16:00:00Z",
    )
    assert_station_bays(workbench.read_station(hkg_id), 3)

    released_first = workbench.release_kennel_allocation(first["id"])
    assert released_first["status"] == "RELEASED"
    assert_station_bays(workbench.read_station(hkg_id), 1)

    released_second = workbench.release_kennel_allocation(second["id"])
    assert released_second["status"] == "RELEASED"
    assert_station_bays(workbench.read_station(hkg_id), 0)


def test_released_allocation_frees_its_bays_without_a_sanitation_window(
    api, workbench, screened_booking, acceptance_agent_headers
):
    """A released hold leaves the projection entirely, so the window it occupied —
    buffer included — becomes immediately reusable, and the pool still ends at zero.

    PRD §3.7: "Allocations whose `status` is `RELEASED` are excluded from the
    projection entirely and free their bays immediately, without a sanitation window."

    Design: Difficulty/compensating_invariant/station_bay_pool_returns_to_zero_after_staged_releases
    """
    state = screened_booking()
    hkg_id = state["catalog"]["hkg_id"]
    first = workbench.create_kennel_allocation(
        hkg_id,
        state["animal_id"],
        bay_count=2,
        occupancy_start_utc="2026-08-05T06:00:00Z",
        occupancy_end_utc="2026-08-05T09:00:00Z",
    )
    second = workbench.create_kennel_allocation(
        hkg_id,
        state["animal_id"],
        bay_count=1,
        occupancy_start_utc="2026-08-05T14:00:00Z",
        occupancy_end_utc="2026-08-05T16:00:00Z",
    )
    assert_station_bays(workbench.read_station(hkg_id), 3)

    workbench.release_kennel_allocation(first["id"])
    assert_station_bays(workbench.read_station(hkg_id), 1)

    reused = validate_success(
        api.create_kennel_allocation(
            {
                "station_id": hkg_id,
                "animal_record_id": state["animal_id"],
                "bay_count": 4,
                "occupancy_start_utc": "2026-08-05T06:00:00Z",
                "occupancy_end_utc": "2026-08-05T09:30:00Z",
                "feeding_interval_minutes": 240,
                "expected_station_version": workbench.station_version(hkg_id),
            },
            acceptance_agent_headers,
        ),
        201,
    )
    assert reused["status"] == "RESERVED"
    assert_station_bays(workbench.read_station(hkg_id), 5)

    workbench.release_kennel_allocation(reused["id"])
    workbench.release_kennel_allocation(second["id"])
    assert_station_bays(workbench.read_station(hkg_id), 0)


def test_kennel_allocation_with_stale_station_version_rejected(
    api, workbench, screened_booking, acceptance_agent_headers
):
    """The first hold advances the station's version, so the second request carrying the
    version the client first observed is refused on concurrency, not on capacity.

    PRD §2.9: "If `expected_station_version` does not equal the station's current
    `version`, the create is refused with `ERR_STALE_STATION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/kennel_allocation_with_stale_station_version_rejected
    """
    state = screened_booking()
    hkg_id = state["catalog"]["hkg_id"]
    observed_version = workbench.station_version(hkg_id)

    first = workbench.create_kennel_allocation(
        hkg_id,
        state["animal_id"],
        bay_count=2,
        occupancy_start_utc="2026-08-05T06:00:00Z",
        occupancy_end_utc="2026-08-05T09:00:00Z",
        expected_station_version=observed_version,
    )
    assert_station_bays(workbench.read_station(hkg_id), 2)
    assert workbench.station_version(hkg_id) == observed_version + 1

    stale = api.create_kennel_allocation(
        {
            "station_id": hkg_id,
            "animal_record_id": state["animal_id"],
            "bay_count": 1,
            "occupancy_start_utc": "2026-08-05T08:00:00Z",
            "occupancy_end_utc": "2026-08-05T10:00:00Z",
            "feeding_interval_minutes": 240,
            "expected_station_version": observed_version,
        },
        acceptance_agent_headers,
    )
    validate_error(stale, ApiErrorId.STALE_STATION_VERSION, 412)

    assert_station_bays(workbench.read_station(hkg_id), 2)
    rows, meta = validate_paginated(
        api.list_kennel_allocations(acceptance_agent_headers, {"station_id": hkg_id})
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [first["id"]]

    accepted = validate_success(
        api.create_kennel_allocation(
            {
                "station_id": hkg_id,
                "animal_record_id": state["animal_id"],
                "bay_count": 1,
                "occupancy_start_utc": "2026-08-05T08:00:00Z",
                "occupancy_end_utc": "2026-08-05T10:00:00Z",
                "feeding_interval_minutes": 240,
                "expected_station_version": workbench.station_version(hkg_id),
            },
            acceptance_agent_headers,
        ),
        201,
    )
    assert accepted["status"] == "RESERVED"
    assert_station_bays(workbench.read_station(hkg_id), 3)


def test_station_reserved_bay_count_reconciles_with_open_allocations(
    api, workbench, travel_ready_booking
):
    """The pool counter is the sum over the open holds: occupying one moves no bays,
    releasing it gives back exactly its own bay count.

    PRD §2.10: "`reserved_bay_count` is the sum of `bay_count` over the station's kennel
    allocations whose `status` is `RESERVED` or `OCCUPIED`."

    Design: Corner/cross_cutting_complexity_layers/station_reserved_bay_count_reconciles_with_open_allocations
    """
    state = travel_ready_booking()
    hkg_id = state["catalog"]["hkg_id"]
    observed_version = workbench.station_version(hkg_id)

    first = workbench.create_kennel_allocation(
        hkg_id,
        state["animal_id"],
        bay_count=2,
        occupancy_start_utc="2026-08-05T06:00:00Z",
        occupancy_end_utc="2026-08-05T09:00:00Z",
        expected_station_version=observed_version,
    )
    second = workbench.create_kennel_allocation(
        hkg_id,
        state["animal_id"],
        bay_count=1,
        occupancy_start_utc="2026-08-05T12:00:00Z",
        occupancy_end_utc="2026-08-05T14:00:00Z",
        expected_station_version=observed_version + 1,
    )
    assert_station_bays(workbench.read_station(hkg_id), 3)

    workbench.set_clock("2026-08-05T06:00:00Z")
    occupied = workbench.occupy_kennel_allocation(first["id"])
    assert occupied["status"] == "OCCUPIED"
    assert_station_bays(workbench.read_station(hkg_id), 3)
    assert workbench.read_allocation(second["id"])["status"] == "RESERVED"

    workbench.release_kennel_allocation(first["id"])
    assert_station_bays(workbench.read_station(hkg_id), 1)
    assert workbench.read_allocation(second["id"])["status"] == "RESERVED"
