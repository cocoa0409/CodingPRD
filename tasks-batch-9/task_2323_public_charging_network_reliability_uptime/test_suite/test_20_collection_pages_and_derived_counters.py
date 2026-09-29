"""Pagination metadata over a whole filtered set, and a counter that can fall."""
from test_helpers import (
    OPERATOR_HEADERS,
    api_client,
    create_station,
    move_station_status,
    read_host_site,
    read_station,
    register_host_site,
    setup_spare_part_with_stock,
    validate_paginated,
)


def _three_depot_parts():
    setup_spare_part_with_stock("SP-1", part_class="DISPENSER", lead_time_days=3, on_hand_qty=0)
    setup_spare_part_with_stock("SP-2", part_class="POWER_MODULE", lead_time_days=5, on_hand_qty=0)
    setup_spare_part_with_stock("SP-3", part_class="CABLE_ASSEMBLY", lead_time_days=1, on_hand_qty=0)


def test_spare_part_pages_report_the_size_of_the_whole_filtered_set():
    """`total_count` describes the set, `has_more` describes the page.

    PRD §2.3: "`limit` is the maximum number of items returned ... `offset` is the
    number of items skipped before the page begins", and "Every list response
    carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta`
    object of the envelope."  PRD §2.3 also declares that "The spare-part
    collection accepts `part_class`."

    Design: Corner/entities/list_spare_parts_paginates_with_total_count_and_has_more
    """
    _three_depot_parts()

    first_response = api_client.list_spare_parts(OPERATOR_HEADERS, params={"limit": 2, "offset": 0})
    first_rows, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_rows, second_meta = validate_paginated(
        api_client.list_spare_parts(OPERATOR_HEADERS, params={"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2

    filtered_rows, filtered_meta = validate_paginated(
        api_client.list_spare_parts(
            OPERATOR_HEADERS, params={"part_class": "DISPENSER", "limit": 10, "offset": 0}
        )
    )
    assert len(filtered_rows) == 1
    assert filtered_rows[0]["part_number"] == "SP-1"
    assert filtered_meta["total_count"] == 1
    assert filtered_meta["has_more"] is False


def test_the_host_site_station_counter_rises_on_creation_and_falls_on_decommission():
    """A counter that only ever increments fails the third observation.

    PRD §3.1: `station_count` is "the number of stations installed at that site
    whose lifecycle state is anything other than `DECOMMISSIONED`.  It starts at
    zero, rises by one each time a station is created there, and falls by one when
    a station is decommissioned."

    Design: Corner/entities/host_site_station_count_is_derived_from_live_stations
    """
    host_site = register_host_site(
        "HS-1",
        committed_service_capacity_kw=800.00,
        agreement_status="EXECUTED",
        power_upgrade_status="ENERGIZED",
        parking_enforcement_mode="TOWING_ENFORCED",
    )
    assert read_host_site(host_site["id"])["station_count"] == 0

    create_station(host_site["id"], "ST-1", power_class="DCFC_150", declared_port_count=1)
    assert read_host_site(host_site["id"])["station_count"] == 1

    second = create_station(host_site["id"], "ST-2", power_class="L2_19", declared_port_count=1)
    assert read_host_site(host_site["id"])["station_count"] == 2

    move_station_status(second["id"], "DECOMMISSIONED")
    assert read_host_site(host_site["id"])["station_count"] == 1
    assert read_station(second["id"])["status"] == "DECOMMISSIONED"

    rows, _meta = validate_paginated(
        api_client.list_host_site_stations(host_site["id"], OPERATOR_HEADERS)
    )
    assert len(rows) == 2, (
        "the decommissioned station is still a row of the site's listing; only the "
        f"counter moved, got {len(rows)}"
    )

    decommissioned, _meta = validate_paginated(
        api_client.list_host_site_stations(
            host_site["id"], OPERATOR_HEADERS, params={"status": "DECOMMISSIONED"}
        )
    )
    assert len(decommissioned) == 1
    assert decommissioned[0]["id"] == second["id"]
