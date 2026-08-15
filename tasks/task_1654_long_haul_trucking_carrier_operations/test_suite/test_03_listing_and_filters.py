"""List pagination, ordering, filters, and reverse-FK list resolution
(PRD §2.3, §3.3, §3.4)."""
from test_helpers import (
    api_client,
    create_driver,
    create_tractor,
    make_dispatcher_headers,
    make_driver_headers,
    post_check_call,
    post_duty_event,
    set_clock,
    setup_accepted_load,
    setup_dispatched_trip,
    tender_load,
    validate_paginated,
)

DISPATCHER = make_dispatcher_headers()


def test_drivers_list_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response
    envelope."
    PRD §2.3: "Unless an endpoint documents its own ordering, every list is
    returned in `created_at` ascending order, where `created_at` is the
    server-stamped creation timestamp with three fractional digits; no business
    ordering anywhere in the system is based on `id`."
    (The logical clock is advanced between creates so the created_at ordering
    is unambiguous under any conforming timestamp source.)

    Design: Corner/entities/drivers_list_pagination_envelope
    """
    set_clock("2026-08-01T06:00:00Z")
    p1 = create_driver(cdl_number="CDL-P1", full_name="P One")
    set_clock("2026-08-01T06:01:00Z")
    p2 = create_driver(cdl_number="CDL-P2", full_name="P Two")
    set_clock("2026-08-01T06:02:00Z")
    p3 = create_driver(cdl_number="CDL-P3", full_name="P Three")

    page0, meta0 = validate_paginated(
        api_client.list_drivers(DISPATCHER, params={"limit": 2, "offset": 0}))
    assert [d["id"] for d in page0] == [p1["id"], p2["id"]]
    assert meta0["total_count"] == 3
    assert meta0["has_more"] is True

    page1, meta1 = validate_paginated(
        api_client.list_drivers(DISPATCHER, params={"limit": 2, "offset": 2}))
    assert [d["id"] for d in page1] == [p3["id"]]
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is False


def test_loads_filtered_by_status(api):
    """PRD §2.3: "the load board accepts `status`, `customer_id`, and
    `lane_id` ... Each filter narrows the list to resources whose corresponding
    attribute equals the supplied value."

    Design: Corner/endpoints/loads_filtered_by_status
    """
    ctx = setup_accepted_load()
    accepted = ctx["load"]
    tendered = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])

    rows, meta = validate_paginated(
        api_client.list_loads(DISPATCHER, params={"status": "ACCEPTED"}))
    assert meta["total_count"] == 1
    assert [r["id"] for r in rows] == [accepted["id"]]
    assert tendered["id"] not in [r["id"] for r in rows]


def test_reverse_fk_lists_resolve(api):
    """PRD §3.4: "A driver's event history reads back in `occurred_at`
    ascending order."
    PRD §2.3: "Unless an endpoint documents its own ordering, every list is
    returned in `created_at` ascending order, where `created_at` is the
    server-stamped creation timestamp with three fractional digits; no business
    ordering anywhere in the system is based on `id`."
    (PRD §4's table defines the per-parent list endpoints exercised here.)

    Design: Corner/endpoints/reverse_fk_lists_resolve
    """
    ctx = setup_dispatched_trip(cdl_number="CDL-E4", unit_number="T-E4")
    driver_id = ctx["driver"]["id"]
    trip_id = ctx["trip"]["id"]
    set_clock("2026-08-01T07:00:00Z")
    duty = post_duty_event(driver_id, event_type="ON_DUTY",
                           occurred_at="2026-08-01T07:00:00Z", trip_id=trip_id)
    set_clock("2026-08-02T12:00:00Z")
    call = post_check_call(trip_id, driver_id, kind="ARRIVED_PICKUP",
                           occurred_at="2026-08-02T10:00:00Z", state_code="TX",
                           odometer_miles=100120)

    events, _ = validate_paginated(
        api_client.list_duty_events(driver_id, DISPATCHER))
    assert duty["id"] in [e["id"] for e in events]
    trips, _ = validate_paginated(
        api_client.list_load_trips(ctx["load"]["id"], DISPATCHER))
    assert [t["id"] for t in trips] == [trip_id]
    calls, _ = validate_paginated(
        api_client.list_trip_check_calls(trip_id, DISPATCHER))
    assert [c["id"] for c in calls] == [call["id"]]


def test_backhaul_empty_candidates_returns_empty_array(api):
    """PRD §3.3: "An empty board is not an error: the response is 200 with an
    empty array."

    Design: Corner/endpoints/backhaul_empty_candidates_returns_empty
    """
    tractor = create_tractor(unit_number="T-E5")
    rows, meta = validate_paginated(
        api_client.get_backhaul_candidates(DISPATCHER,
                                           params={"tractor_id": tractor["id"]}))
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
