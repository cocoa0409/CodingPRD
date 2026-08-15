"""Flight list filters (PRD §2.3)."""
from test_helpers import (
    ApiErrorId,
    create_aircraft,
    create_flight,
    setup_ops_env,
    TEST_USERS,
    validate_paginated,
    validate_success,
)

DISP = TEST_USERS["dispatcher_headers"]


def test_flights_list_filters_by_query_params(api):
    """PRD §2.3: "Several list endpoints also accept filter parameters named
    after the resource's own identifier or state fields — `status`,
    `base_id`, `route_id`, `aircraft_id`, `pilot_id`, `flight_id`,
    `booking_id`, `duty_date`, `contact_email`, `noise_class`, and
    `matched_route_id` — each narrowing the result set to rows matching the
    supplied value."

    Design: Corner/endpoints/flights_list_filters_by_query_params
    """
    env = setup_ops_env()
    a2 = create_aircraft(tail_number="N2")
    f1 = create_flight(env, "2026-08-03T14:00:00Z")
    f2 = create_flight(env, "2026-08-04T14:00:00Z", aircraft=a2)
    validate_success(
        api.flight_event(f1["id"], {"event_type": "CANCEL_OPS", "reason": "manual"},
                         DISP)
    )

    cancelled, meta = validate_paginated(
        api.list_flights(DISP, params={"status": "CANCELLED_OPS"})
    )
    assert meta["total_count"] == 1
    assert cancelled[0]["id"] == f1["id"]

    by_aircraft, meta = validate_paginated(
        api.list_flights(DISP, params={"aircraft_id": a2["id"]})
    )
    assert meta["total_count"] == 1
    assert by_aircraft[0]["id"] == f2["id"]

    by_route, meta = validate_paginated(
        api.list_flights(DISP, params={"route_id": env["route"]["id"]})
    )
    assert meta["total_count"] == 2
