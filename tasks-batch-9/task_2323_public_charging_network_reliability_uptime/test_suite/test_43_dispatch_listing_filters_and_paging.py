"""The dispatch collection's filters compose, and its pages sit inside them."""
from test_helpers import (
    PROGRAM_ADMIN_HEADERS,
    TECHNICIAN_1,
    TECHNICIAN_2,
    TECHNICIAN_3,
    TECHNICIAN_UNASSIGNED,
    api_client,
    assert_pagination_meta,
    create_dispatch,
    ingest_and_classify_outage,
    post_progress,
    setup_operational_station,
    validate_paginated,
)


def test_the_port_and_state_filters_bound_the_page_and_the_total_alike():
    """A total_count describing the table rather than the filtered set is invisible
    at the default page size.

    PRD §2.3: "`limit` is the maximum number of items returned; it defaults to 10
    ... `offset` is the number of items skipped before the page begins; it defaults
    to 0".  PRD §2.3: "Unless a specific endpoint states otherwise, every list
    endpoint returns its resources sorted by `created_at` in ascending order.
    Every list response carries `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope."  PRD §2.3 on this collection's
    filters: "The maintenance-dispatch collection accepts `outage_event_id`,
    `port_id`, `state`, and `technician_user_id`", all of them "optional and all of
    them exact-match on the named field".

    Design: Corner/endpoints/dispatch_listing_filters_by_port_and_state_and_paginates
    """
    scenario = setup_operational_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        port_count=2,
        committed_service_capacity_kw=800.00,
    )
    first_port = scenario["ports"][0]["id"]
    second_port = scenario["ports"][1]["id"]

    outage_one = ingest_and_classify_outage(
        first_port, "2026-08-01T00:00:00Z", fault_class="MINOR", fault_code="OCPP-MIN-01"
    )
    outage_two = ingest_and_classify_outage(
        first_port, "2026-08-01T00:00:00Z", fault_class="MINOR", fault_code="OCPP-MIN-02"
    )
    outage_three = ingest_and_classify_outage(
        second_port, "2026-08-01T00:00:00Z", fault_class="MINOR", fault_code="OCPP-MIN-03"
    )

    first_dispatch = create_dispatch(
        outage_one["id"],
        first_port,
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T03:00:00Z",
        technician_user_id=TECHNICIAN_1,
    )
    second_dispatch = create_dispatch(
        outage_two["id"],
        first_port,
        window_start_at="2026-08-01T03:00:00Z",
        window_end_at="2026-08-01T05:00:00Z",
        technician_user_id=TECHNICIAN_2,
    )
    third_dispatch = create_dispatch(
        outage_three["id"],
        second_port,
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T05:00:00Z",
        technician_user_id=TECHNICIAN_3,
    )
    post_progress(third_dispatch["id"], "EN_ROUTE", TECHNICIAN_3)

    rows, meta = validate_paginated(
        api_client.list_maintenance_dispatches(
            PROGRAM_ADMIN_HEADERS,
            {"port_id": first_port, "state": "CREATED", "limit": 1, "offset": 0},
        )
    )
    assert [row["id"] for row in rows] == [first_dispatch["id"]], "sorted by created_at ascending"
    assert_pagination_meta(meta, limit=1, offset=0, total_count=2, has_more=True)

    rows, meta = validate_paginated(
        api_client.list_maintenance_dispatches(
            PROGRAM_ADMIN_HEADERS,
            {"port_id": first_port, "state": "CREATED", "limit": 1, "offset": 1},
        )
    )
    assert [row["id"] for row in rows] == [second_dispatch["id"]]
    assert_pagination_meta(meta, limit=1, offset=1, total_count=2, has_more=False)

    rows, meta = validate_paginated(
        api_client.list_maintenance_dispatches(PROGRAM_ADMIN_HEADERS, {"state": "EN_ROUTE"})
    )
    assert [row["id"] for row in rows] == [third_dispatch["id"]], "the state filter crosses ports"
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api_client.list_maintenance_dispatches(
            PROGRAM_ADMIN_HEADERS, {"technician_user_id": TECHNICIAN_UNASSIGNED}
        )
    )
    assert rows == [], "a filter matching nothing is an empty page, not an error"
    assert meta["total_count"] == 0
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_maintenance_dispatches(PROGRAM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 3, "the unfiltered collection still holds all three"
    assert len(rows) == 3
