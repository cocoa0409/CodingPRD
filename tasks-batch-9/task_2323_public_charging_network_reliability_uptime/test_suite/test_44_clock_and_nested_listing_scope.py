"""The logical clock is the only time source, and parents scope their children."""
from test_helpers import (
    AUDITOR_HEADERS,
    OPERATOR_HEADERS,
    TECHNICIAN_HEADERS,
    api_client,
    assert_instant_equals,
    create_station,
    ingest_outage,
    install_charging_port,
    make_host_site_manager_headers,
    read_charging_port,
    read_host_site,
    register_commissionable_host_site,
    register_host_site,
    validate_paginated,
    validate_success,
)


def test_a_clock_jump_moves_later_writes_without_rewriting_earlier_rows():
    """A `created_at` taken from wall-clock time would drift away from the reading
    every deadline in this contract is pinned to.

    PRD §2.4: "Both timestamps and every `logical clock now` reference in this
    document read from a server-side **logical clock**, not from wall-clock time.
    The clock's startup value is exactly `2026-08-01T00:00:00Z`, and before the
    clock is ever set it reads that default rather than falling back to real time.
    Any of the six roles may drive the clock forward or backward through a
    test-driving capability that accepts a single `current_utc` instant and returns
    that instant as the clock's new reading; every subsequent logical-clock read
    returns it."  PRD §2.4 on the common fields: `created_at` records "when the
    resource was first created", `updated_at` is "refreshed on every mutation of
    the resource", and `version` is "a counter that increments by one on every
    mutation".

    Design: Corner/endpoints/clock_endpoint_stamps_subsequent_writes_and_leaves_earlier_rows_alone
    """
    early_site = register_commissionable_host_site("HS-1", committed_service_capacity_kw=400.00)

    assert_instant_equals(early_site["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert_instant_equals(early_site["updated_at"], "2026-08-01T00:00:00Z", "updated_at")
    assert early_site["version"] == 1

    validate_success(api_client.set_clock("2026-09-15T08:30:00Z", AUDITOR_HEADERS))

    assert_instant_equals(
        read_host_site(early_site["id"])["created_at"],
        "2026-08-01T00:00:00Z",
        "created_at after the jump",
    )

    later_site = register_host_site("HS-2", committed_service_capacity_kw=250.00)

    assert_instant_equals(later_site["created_at"], "2026-09-15T08:30:00Z", "created_at")
    assert_instant_equals(later_site["updated_at"], "2026-09-15T08:30:00Z", "updated_at")
    assert later_site["version"] == 1
    assert later_site["agreement_status"] == "DRAFT", "the declared registration defaults"
    assert later_site["power_upgrade_status"] == "REQUESTED"
    assert later_site["access_hours_mode"] == "TWENTY_FOUR_SEVEN"
    assert later_site["parking_enforcement_mode"] == "NONE"
    assert later_site["station_count"] == 0

    amended = validate_success(
        api_client.update_host_site(
            early_site["id"], {"committed_service_capacity_kw": 500.00}, OPERATOR_HEADERS
        )
    )

    assert_instant_equals(amended["updated_at"], "2026-09-15T08:30:00Z", "updated_at")
    assert_instant_equals(amended["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert amended["version"] == 2
    assert float(amended["committed_service_capacity_kw"]) == 500.00


def test_nested_listings_partition_by_the_parent_and_still_honour_their_filters():
    """Returning the whole child table would pass a single-parent fixture.

    PRD §2.3: "Reverse-reachability collections that hang off a parent resource
    take that parent's `id` as their path segment."  PRD §2.3 on the filters that
    compose with that scoping: "Stations under a host site are filtered by
    `status`" and "Charging ports under a station are filtered by `service_state`
    and `maintenance_state`".  PRD §3.4 on why one dispenser drops out of the filtered
    page: "When the ingested `fault_class` is `CRITICAL` or `MAJOR` and the
    dispenser is currently `IN_SERVICE`, the dispenser is driven `IN_SERVICE →
    OUT_OF_SERVICE`".  PRD §3.1 on the parent's own roll-up: `station_count` is
    "the number of stations installed at that site whose lifecycle state is
    anything other than `DECOMMISSIONED`".

    Design: Corner/endpoints/sub_resource_listings_are_scoped_to_the_parent_in_the_path
    """
    first_site = register_commissionable_host_site("HS-1", committed_service_capacity_kw=800.00)
    second_site = register_commissionable_host_site(
        "HS-2", committed_service_capacity_kw=250.00, parking_enforcement_mode="SIGNAGE_ONLY"
    )

    first_station = create_station(first_site["id"], "ST-1", declared_port_count=1)
    second_station = create_station(first_site["id"], "ST-2", declared_port_count=1)
    create_station(second_site["id"], "ST-3", power_class="L2_19", declared_port_count=1)

    first_port = install_charging_port(first_station["id"], "DS-1", terminal_model="PT-4")
    second_port = install_charging_port(
        second_station["id"], "DS-2", connector_type="NACS", terminal_model="PT-4"
    )

    ingest_outage(
        first_port["id"], "2026-08-01T00:00:00Z", fault_class="MAJOR", fault_code="EVSE-MAJ-11"
    )
    assert read_charging_port(first_port["id"])["service_state"] == "OUT_OF_SERVICE"

    rows, meta = validate_paginated(
        api_client.list_host_site_stations(
            first_site["id"], make_host_site_manager_headers(first_site["id"])
        )
    )
    assert sorted(row["id"] for row in rows) == sorted(
        [first_station["id"], second_station["id"]]
    ), "ST-3 belongs to the other host site"
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api_client.list_station_charging_ports(
            first_station["id"], OPERATOR_HEADERS, {"service_state": "IN_SERVICE"}
        )
    )
    assert rows == [], "the only dispenser under ST-1 is out of service"
    assert meta["total_count"] == 0

    rows, meta = validate_paginated(
        api_client.list_station_charging_ports(first_station["id"], OPERATOR_HEADERS)
    )
    assert [row["id"] for row in rows] == [first_port["id"]], "the filter, not the scoping, hid it"
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api_client.list_station_charging_ports(second_station["id"], OPERATOR_HEADERS)
    )
    assert [row["id"] for row in rows] == [second_port["id"]]
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api_client.list_port_outage_events(second_port["id"], TECHNICIAN_HEADERS)
    )
    assert rows == [], "the MAJOR fault hangs off DS-1, not DS-2"
    assert meta["total_count"] == 0

    assert read_host_site(first_site["id"])["station_count"] == 2
    assert read_host_site(second_site["id"])["station_count"] == 1
