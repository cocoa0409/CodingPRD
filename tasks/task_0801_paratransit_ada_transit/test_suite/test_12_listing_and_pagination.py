"""Trip listing with rider filtering and limit/offset pagination.

Queue B (Corner): endpoints / reverse-reachability + pagination-with-filtering.
"""
from test_helpers import validate_paginated, TEST_USERS
import test_helpers as th

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_list_trips_filtered_by_rider_id(api):
    """PRD §2.3: "Each list response echoes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_trips_filter_by_rider_id_reverse_reachability
    """
    base = th.scenario_certified_rider_zone(api, clock=None)
    rider_id = base["rider"]["id"]
    za = base["zone_a"]["id"]
    trip = th.request_trip(api, rider_id, za, za)
    resp = api.list_trips(DISPATCHER, params={"rider_id": rider_id})
    data, meta = validate_paginated(resp)
    assert any(t["id"] == trip["id"] for t in data)
    assert meta["total_count"] == 1


def test_list_trips_pagination_limit_offset_has_more(api):
    """PRD §2.3: "`limit` is the maximum number of items to return; it defaults to 10,
    with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Each list response echoes `limit`, `offset`, `total_count`, and `has_more`
    in the `meta` object of the envelope."

    Design: Corner/endpoints/list_trips_pagination_limit_offset_has_more
    """
    base = th.scenario_certified_rider_zone(api, clock=None)
    rider_id = base["rider"]["id"]
    za = base["zone_a"]["id"]
    th.request_trip(api, rider_id, za, za, requested_pickup_at="2026-06-05T09:00:00Z")
    th.request_trip(api, rider_id, za, za, requested_pickup_at="2026-06-05T14:00:00Z")
    resp = api.list_trips(DISPATCHER, params={"rider_id": rider_id, "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
