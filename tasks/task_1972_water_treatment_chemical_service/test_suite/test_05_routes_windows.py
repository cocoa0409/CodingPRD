"""Route stop visit windows: half-open overlap semantics, arrive guards, and
mark-missed timing."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_account,
    create_asset,
    create_published_route,
    create_route_stop_payload,
    create_test_route_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
CHEMIST = TEST_USERS["chemist_headers"]


def _route_with_stop(account_name="Window Co"):
    account = create_account(account_name=account_name)
    asset = create_asset(account["id"], asset_tag="CT-W", asset_type="COOLING_TOWER",
                         recirculation_rate_gpm=300, system_volume_gal=6000)
    route = validate_success(
        api_client.create_test_route(create_test_route_payload(account["id"]), CHEMIST),
        expected_status=201,
    )
    stop1 = validate_success(
        api_client.add_route_stop(
            route["id"],
            create_route_stop_payload(
                asset["id"], "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z", 1
            ),
            CHEMIST,
        ),
        expected_status=201,
    )
    return account, asset, route, stop1


def test_route_stop_adjacent_window_allowed(api):
    """PRD §3.4: "Stop windows on the same asset must not overlap under
    **half-open interval semantics**: a conflict exists when the new stop's
    `window_start` is strictly before an existing stop's `window_end` and that
    existing stop's `window_start` is strictly before the new stop's
    `window_end`. Back-to-back adjacency — the new `window_start` exactly
    equal to an existing `window_end` — is allowed."

    Design: Difficulty/resource_temporal_overlap/route_stop_half_open_adjacency_allowed_overlap_rejected
    """
    _, _, route, stop1 = _route_with_stop()
    asset_id = stop1["asset_id"]

    adjacent = validate_success(
        api_client.add_route_stop(
            route["id"],
            create_route_stop_payload(
                asset_id, "2026-08-02T10:00:00Z", "2026-08-02T12:00:00Z", 2
            ),
            CHEMIST,
        ),
        expected_status=201,
    )
    assert adjacent["status"] == "SCHEDULED"


def test_route_stop_one_minute_overlap_rejected(api):
    """PRD §3.4: "Only existing stops in `SCHEDULED` or `ARRIVED` status
    participate in the check; a violation is rejected with
    `ERR_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/route_stop_half_open_adjacency_allowed_overlap_rejected
    """
    _, _, route, stop1 = _route_with_stop()
    asset_id = stop1["asset_id"]
    validate_success(
        api_client.add_route_stop(
            route["id"],
            create_route_stop_payload(
                asset_id, "2026-08-02T10:00:00Z", "2026-08-02T12:00:00Z", 2
            ),
            CHEMIST,
        ),
        expected_status=201,
    )

    # Overlaps the second stop by one minute: 11:59 < 12:00 and 10:00 < 13:00.
    resp = api_client.add_route_stop(
        route["id"],
        create_route_stop_payload(
            asset_id, "2026-08-02T11:59:00Z", "2026-08-02T13:00:00Z", 3
        ),
        CHEMIST,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_CONFLICT)
    assert resp.status_code == 409

    stops, meta = validate_paginated(api_client.list_route_stops(route["id"], CHEMIST))
    assert meta["total_count"] == 2, "the rejected insert must not add a stop"


def test_arrive_outside_window_rejected_both_sides(api):
    """PRD §3.4: "the current clock must be at or after `window_start` and
    strictly before `window_end` (`ERR_OUTSIDE_VISIT_WINDOW`)". PRD §2.6 tier
    11: "arriving outside the half-open visit window bounded by `window_start`
    inclusive and `window_end` exclusive is `ERR_OUTSIDE_VISIT_WINDOW`".

    Design: Corner/endpoints/arrive_outside_window_rejected_both_sides
    """
    account = create_account(account_name="WinArrive Co")
    asset = create_asset(account["id"], asset_type="COOLING_TOWER",
                         recirculation_rate_gpm=300, system_volume_gal=6000)
    route, stops = create_published_route(
        account["id"],
        asset["id"],
        [("2026-08-02T00:00:00Z", "2026-08-02T06:00:00Z"),
         ("2026-08-02T06:00:00Z", "2026-08-02T12:00:00Z"),
         ("2026-08-02T12:00:00Z", "2026-08-02T18:00:00Z")],
    )

    # One second before window_start: rejected.
    set_clock("2026-08-01T23:59:59Z")
    resp_early = api_client.arrive_stop(stops[0]["id"], CHEMIST)
    validate_error(resp_early, ApiErrorId.ERR_OUTSIDE_VISIT_WINDOW)

    # Exactly at window_start: allowed.
    set_clock("2026-08-02T00:00:00Z")
    arrived = validate_success(api_client.arrive_stop(stops[0]["id"], CHEMIST))
    assert arrived["status"] == "ARRIVED"

    # Exactly at window_end of stop2 (12:00 == end, half-open excludes it).
    set_clock("2026-08-02T12:00:00Z")
    resp_end = api_client.arrive_stop(stops[1]["id"], CHEMIST)
    validate_error(resp_end, ApiErrorId.ERR_OUTSIDE_VISIT_WINDOW)
    stop2 = validate_success(api_client.get_stop(stops[1]["id"], CHEMIST))
    assert stop2["status"] == "SCHEDULED"


def test_mark_missed_before_window_end_rejected(api):
    """PRD §3.4: "A stop never visited in its window is marked missed —
    `SCHEDULED` → `MISSED` — which is permitted only once the clock has
    reached `window_end`, failing earlier with `ERR_WINDOW_NOT_ELAPSED`."

    Design: Corner/endpoints/mark_missed_before_window_end_rejected
    """
    account = create_account(account_name="Miss Co")
    asset = create_asset(account["id"], asset_type="COOLING_TOWER",
                         recirculation_rate_gpm=300, system_volume_gal=6000)
    route, stops = create_published_route(
        account["id"], asset["id"],
        [("2026-08-02T00:00:00Z", "2026-08-02T06:00:00Z")],
    )

    set_clock("2026-08-02T05:59:59Z")
    resp_early = api_client.mark_stop_missed(stops[0]["id"], CHEMIST)
    validate_error(resp_early, ApiErrorId.ERR_WINDOW_NOT_ELAPSED)
    assert resp_early.status_code == 422

    set_clock("2026-08-02T06:00:00Z")
    missed = validate_success(api_client.mark_stop_missed(stops[0]["id"], CHEMIST))
    assert missed["status"] == "MISSED"
