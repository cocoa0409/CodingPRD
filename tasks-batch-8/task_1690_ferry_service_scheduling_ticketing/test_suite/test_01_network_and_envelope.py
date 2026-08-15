"""Network definition basics: route defaults, list envelope/pagination,
404 handling, and route->sailings reverse reachability."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_route,
    assert_sailing,
    create_route,
    create_vessel,
    create_sailing,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_route_creation_applies_defaults(api, scheduler_admin_headers):
    """PRD §3.1: "A newly created route starts with `status` set to `ACTIVE`,
    which is the only route status in this version of the system."
    PRD §2.5: "`version` — an integer that starts at 1 and increments by 1 on
    every mutation of the resource, including system-driven mutations such as
    state-machine transitions and computed-counter recomputation."

    Design: Corner/entities/route_creation_applies_defaults
    """
    route = create_route(
        route_code="SEA-BI",
        origin_terminal="Seattle",
        destination_terminal="Bainbridge",
        crossing_minutes=35,
        turnaround_minutes=15,
    )
    assert_route(route)
    assert is_valid_uuid(route["id"]), "route id must be a server-minted UUID"

    fetched = validate_success(api.get_route(route["id"], scheduler_admin_headers))
    assert_route(fetched)
    assert fetched["status"] == "ACTIVE", (
        f"new route must start ACTIVE, got {fetched['status']}"
    )
    assert fetched["version"] == 1, (
        f"new route version must start at 1, got {fetched['version']}"
    )


def test_route_list_pagination_envelope(api, scheduler_admin_headers):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; when omitted it defaults to 10, and it accepts values from a
    minimum of 1 to a maximum of 100. The `offset` parameter sets how many
    items to skip before the returned window and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries four pagination
    fields: `limit`, `offset`, `total_count` (the full count of matching
    resources, not just the returned page), and `has_more` (whether additional
    items exist beyond the current window)."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/route_list_pagination_envelope
    """
    create_route(route_code="SEA-BI")

    resp = api.list_routes(scheduler_admin_headers)
    body = resp.json()
    assert body.get("response_type") == "array", (
        f"list response_type must be 'array', got {body.get('response_type')!r}"
    )
    data, meta = validate_paginated(resp)
    assert isinstance(meta.get("api_request_id"), str)
    assert isinstance(meta.get("api_request_timestamp"), str)
    assert len(data) == 1, f"expected exactly 1 route, got {len(data)}"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"default offset must be 0, got {meta['offset']}"


def test_get_nonexistent_vessel_returns_not_found(api, scheduler_admin_headers):
    """PRD §2.10: "The first identifier that does not correspond to an
    existing resource terminates the request with `ERR_NOT_FOUND` (HTTP 404),
    and no later segment is consulted."

    Design: Corner/entities/get_nonexistent_vessel_returns_not_found
    """
    resp = api.get_vessel(NON_EXISTENT_UUID, scheduler_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_route_sailings_reverse_reachability(api, scheduler_admin_headers):
    """PRD §4: "| GET | `/ferry/routes/{id}/sailings` | List sailings for a
    route | SchedulerAdmin, TerminalAgent, CrewPlanner, Customer |" — a
    sailing scheduled under one route is listed under that route and not
    under another.

    Design: Corner/entities/fk_reverse_reachability_route_sailings
    """
    route1 = create_route(route_code="SEA-BI", crossing_minutes=35)
    route2 = create_route(
        route_code="EDM-KIN",
        origin_terminal="Edmonds",
        destination_terminal="Kingston",
        crossing_minutes=30,
    )
    vessel = create_vessel(vessel_name="MV Kittitas")
    sailing = create_sailing(
        route1["id"], vessel["id"], departure_time="2026-09-01T10:00:00Z"
    )
    assert_sailing(sailing)

    data1, meta1 = validate_paginated(
        api.list_route_sailings(route1["id"], scheduler_admin_headers)
    )
    assert meta1["total_count"] == 1
    assert [s["id"] for s in data1] == [sailing["id"]]

    data2, meta2 = validate_paginated(
        api.list_route_sailings(route2["id"], scheduler_admin_headers)
    )
    assert meta2["total_count"] == 0
    assert data2 == []
