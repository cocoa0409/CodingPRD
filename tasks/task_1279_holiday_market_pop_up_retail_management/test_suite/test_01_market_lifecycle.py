"""Market lifecycle: creation defaults, reads, pagination, auth, OCC open,
cancel cascade, and conditional weather-alert clearing."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID, TEST_USERS, validate_error, validate_paginated,
    validate_success, is_valid_uuid,
    assert_market,
    create_market_payload, create_market, set_clock, get_market,
    setup_accepted_application, setup_active_assignment, setup_open_market,
    open_market, run_ops,
    create_draft_application, submit_application, create_booth_entity,
    create_assignment_for, create_vendor_entity,
)

OPERATOR = TEST_USERS["market_operator_headers"]


def test_create_market_returns_201_with_system_defaults(api, market_operator_headers):
    """PRD §3.1: "A newly created market starts in `SETUP` posture with
    `run_ops_index` 0, `total_accepted_vendors` 0, and `total_booths_committed` 0."
    PRD §3.1: "`jury_quorum` (default 3, the minimum number of jury scores
    required before an application can be decided)".

    Design: Corner/entities/market_creation_returns_201_with_defaults
    """
    set_clock("2026-08-01T00:00:00Z")
    payload = create_market_payload(name="CornerM", season_code="C-1")
    market = validate_success(api.create_market(payload, market_operator_headers), 201)
    assert_market(market)
    assert market["posture"] == "SETUP"
    assert market["run_ops_index"] == 0
    assert market["jury_quorum"] == 3, "jury_quorum must default to 3 when omitted"
    assert market["total_accepted_vendors"] == 0
    assert market["total_booths_committed"] == 0


def test_get_market_nonexistent_returns_404(api, market_operator_headers):
    """PRD §2.8: "If any path-templated resource does not exist — or exists but
    is scoped to a different market than the one named — the request is rejected
    with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/market_get_returns_404_for_nonexistent
    """
    set_clock("2026-08-01T00:00:00Z")
    res = api.get_market(NON_EXISTENT_UUID, market_operator_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_list_markets_pagination_meta(api, market_operator_headers):
    """PRD §2.3: "The `meta` envelope on list responses carries `limit`,
    `offset`, `total_count`, and `has_more`."
    PRD §2.3: "`limit` defaults to 10, has a minimum of 1, and has a maximum of
    100."

    Design: Corner/entities/market_list_pagination_fields
    """
    set_clock("2026-08-01T00:00:00Z")
    api.create_market(create_market_payload(name="L1", season_code="L-1"),
                      market_operator_headers)
    api.create_market(create_market_payload(name="L2", season_code="L-2"),
                      market_operator_headers)

    data, meta = validate_paginated(
        api.list_markets(market_operator_headers, params={"limit": 1, "offset": 0}))
    assert len(data) == 1, f"limit=1 must return exactly 1 row, got {len(data)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_new_market_starts_in_setup(api, market_operator_headers):
    """PRD §3.1: "A newly created market starts in `SETUP` posture with
    `run_ops_index` 0, `total_accepted_vendors` 0, and `total_booths_committed` 0."

    Design: Corner/state_machines/market_initial_state_setup
    """
    market = create_market({"name": "SM4", "season_code": "SM4-1"},
                           clock="2026-08-01T00:00:00Z")
    assert market["posture"] == "SETUP"


def test_create_market_returns_server_minted_uuid(api, market_operator_headers):
    """PRD §2.4: "Every persisted resource carries an `id` field: a
    server-minted UUID with no type prefix."

    Design: Corner/endpoints/bulk_schedule_not_implemented
    """
    set_clock("2026-08-01T00:00:00Z")
    market = validate_success(
        api.create_market(create_market_payload(name="EM", season_code="EM-1"),
                          market_operator_headers), 201)
    assert market["id"] is not None
    assert is_valid_uuid(market["id"]), f"id must be a server-minted UUID, got {market['id']}"


def test_market_summary_reflects_acceptance_and_activation(api, market_operator_headers):
    """PRD §3.3: "On `ACCEPTED`, the market's `total_accepted_vendors` increments
    by 1, and if the vendor's `status` is currently `PROSPECT`, it transitions to
    `APPROVED`."
    PRD §3.4: "On activation, the booth's `status` transitions to `RESERVED` and
    the market's `total_booths_committed` increments by 1."

    Design: Corner/endpoints/computed_read_market_summary
    """
    ctx = setup_active_assignment()
    market = validate_success(api.get_market(ctx["market"]["id"], market_operator_headers), 200)
    assert market["total_accepted_vendors"] == 1
    assert market["total_booths_committed"] == 1


def test_open_market_with_stale_version_rejected(api, market_operator_headers):
    """PRD §2.7: "If the market's current `version` does not match
    `expected_market_version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412), preventing an operator working from a stale market snapshot from
    re-opening after another operator has already transitioned the market forward."
    PRD §2.4: "Every resource carries `version`, an integer that starts at 1 and
    increments by 1 on every mutation."

    Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_market_version
    """
    ctx = setup_active_assignment()
    market_id = ctx["market"]["id"]
    set_clock("2026-12-05T00:00:00Z")
    observed = get_market(market_id)
    run_ops(market_id)  # mutates the market (run_ops_index) -> version advances
    res = api.open_market(market_id,
                          {"expected_market_version": observed["version"]},
                          market_operator_headers)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_cancel_market_cascades_to_applications_and_assignments(api, market_operator_headers):
    """PRD §3.8: "Cancellation transitions the market to `CANCELLED`, all
    applications in `DRAFT`, `SUBMITTED`, `UNDER_JURY`, or `WAITLISTED` to
    `WITHDRAWN`, and all assignments in `PENDING_PAYMENT` or `ACTIVE` to
    `FORFEITED`."

    Design: Corner/state_machines/market_cancel_cascade_down
    """
    market = create_market({"name": "SM5", "season_code": "SM5-1"})
    vendor = create_vendor_entity(legal_name="SV5", category="CRAFT")
    app = create_draft_application(market["id"], vendor["id"])
    app = submit_application(market["id"], app["id"], vendor["id"])
    assert app["status"] == "SUBMITTED"
    booth = create_booth_entity(market["id"], booth_code="ST-5")
    asg = create_assignment_for(market["id"], booth["id"], app["id"])
    assert asg["status"] == "PENDING_PAYMENT"

    cancelled = validate_success(api.cancel_market(market["id"], market_operator_headers), 200)
    assert cancelled["posture"] == "CANCELLED"

    app_after = validate_success(
        api.get_application(market["id"], app["id"], market_operator_headers), 200)
    assert app_after["status"] == "WITHDRAWN"
    asg_after = validate_success(
        api.get_assignment(market["id"], asg["id"], market_operator_headers), 200)
    assert asg_after["status"] == "FORFEITED"


def test_clear_weather_alert_from_open_rejected(api, market_operator_headers):
    """PRD §3.7: "When the market is in `WEATHER_ALERT` and no weather event in
    the past 6 hours has `triggers_alert` true, an operator may clear the alert,
    transitioning the market back to `OPEN`, re-activating all `SUSPENDED` POS
    devices to `ACTIVE`, and incrementing `Market.version` by 1."
    PRD §2.9: "Then entity state validity (`ERR_INVALID_STATE`)."

    Design: Corner/endpoints/conditional_action_clear_weather_alert_requires_open
    """
    ctx = setup_open_market()
    market = get_market(ctx["market"]["id"])
    assert market["posture"] == "OPEN"
    res = api.clear_weather_alert(ctx["market"]["id"], market_operator_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "All requests must carry two HTTP headers: `X-User-ID` and
    `X-User-Role`. A request missing either header, or carrying a role not listed
    below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_missing_headers_returns_401
    """
    res = api._request("GET", "/markets", headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_role_not_permitted_for_endpoint_returns_403(api, jury_member_headers):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /markets is authorized for `MarketOperator` only.

    Design: Corner/validations/unauthorized_role_returns_403
    """
    set_clock("2026-08-01T00:00:00Z")
    payload = create_market_payload(name="X", season_code="X-1")
    res = api.create_market(payload, jury_member_headers)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
