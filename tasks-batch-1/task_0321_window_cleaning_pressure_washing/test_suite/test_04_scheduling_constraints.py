"""Routing and scheduling constraints: window overlap, whole-day crew exclusivity,
capacity, region/date match, weather holds, skill coverage, and the priority
ordering that decides which error fires when two checks fail at once.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_account, create_property, create_sent_quote,
    setup_active_agreement, setup_scheduled_visit, setup_dispatched_visit,
    create_crew, create_route, commit_visit, activate_agreement,
    setup_pending_agreement, post_deposit,
    TEST_USERS, make_customer_headers,
)

BILLING = TEST_USERS["billing_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
FIELD_CREW = TEST_USERS["field_crew_headers"]


def _commit_raw(api, route_id, visit_id):
    """Read the current route version, then attempt a commit (returns Response)."""
    route = validate_success(api.get_route(route_id, DISPATCHER), 200)
    return api.commit_visit(route_id,
                            {"visit_id": visit_id, "expected_route_version": route["version"]},
                            DISPATCHER)


# ===========================================================================
# Queue A — resource_temporal_overlap
# ===========================================================================
def test_overlapping_visit_window_rejected(api):
    """PRD §3.4: "The visit's service window must not overlap any visit already on
    the route whose schedule status is `SCHEDULED`, `DISPATCHED`, or `IN_PROGRESS`;
    because windows are half-open intervals, two windows that merely touch at an
    endpoint do not overlap, but any true overlap is rejected with
    `ERR_VISIT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/route_visit_window_overlap_half_open_minute_windows
    """
    # First visit [540,660) committed; second visit [600,720) overlaps it.
    account, prop, agreement, va, crew, route = setup_scheduled_visit(
        region_code="NORTH", schedule_kind="ONE_TIME", service_date="2026-07-01",
        window_start_min=540, window_end_min=660,
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    # Build a second visit on the same account/region/date at [600,720).
    prop2 = create_property(account["id"], pane_count=60, glass_sqft=100.0, stories=2)
    quote2 = create_sent_quote(account["id"], prop2["id"],
                               pricing_basis="PANE_COUNT", addon_codes=["GUTTER"])
    validate_success(api.accept_quote(quote2["id"], make_customer_headers(account["id"])), 200)
    agr2 = validate_success(api.create_service_agreement(
        {"quote_id": quote2["id"], "schedule_kind": "ONE_TIME"}, BILLING), 201)
    activate_agreement(agr2["id"], planned_date="2026-07-01",
                       window_start_min=600, window_end_min=720)
    vb = _first_visit(api, agr2["id"])

    res = _commit_raw(api, route["id"], vb["id"])
    validate_error(res, "ERR_VISIT_WINDOW_OVERLAP", expected_status=409)


def test_overlapping_window_does_not_change_route_booked_minutes(api):
    """PRD §3.4: "The visit's service window must not overlap any visit already on
    the route whose schedule status is `SCHEDULED`, `DISPATCHED`, or `IN_PROGRESS`
    ... any true overlap is rejected with `ERR_VISIT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/route_visit_window_overlap_half_open_minute_windows
    """
    account, prop, agreement, va, crew, route = setup_scheduled_visit(
        region_code="NORTH", schedule_kind="ONE_TIME", service_date="2026-07-01",
        window_start_min=540, window_end_min=660,
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    prop2 = create_property(account["id"], pane_count=60, glass_sqft=100.0, stories=2)
    quote2 = create_sent_quote(account["id"], prop2["id"],
                               pricing_basis="PANE_COUNT", addon_codes=["GUTTER"])
    validate_success(api.accept_quote(quote2["id"], make_customer_headers(account["id"])), 200)
    agr2 = validate_success(api.create_service_agreement(
        {"quote_id": quote2["id"], "schedule_kind": "ONE_TIME"}, BILLING), 201)
    activate_agreement(agr2["id"], planned_date="2026-07-01",
                       window_start_min=600, window_end_min=720)
    vb = _first_visit(api, agr2["id"])

    _commit_raw(api, route["id"], vb["id"])  # rejected
    route_after = validate_success(api.get_route(route["id"], DISPATCHER), 200)
    # Only the first 120-minute visit counts; the overlapping commit was rejected.
    assert route_after["booked_minutes"] == 120


def test_crew_double_booked_same_day_rejected(api):
    """PRD §2.8: "A single crew may hold at most one route per calendar
    `service_date` that is not yet `CLOSED`. Two routes for the same crew on the
    same calendar date collide regardless of any minute-level window, and the
    second attempt is rejected with `ERR_CREW_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/crew_double_booked_whole_day_exclusivity
    """
    crew = create_crew(region_code="NORTH", skill_codes=[], daily_capacity_minutes=600)
    create_route(crew["id"], region_code="NORTH", service_date="2026-07-01")
    res = api.create_route(
        {"crew_id": crew["id"], "region_code": "NORTH", "service_date": "2026-07-01"},
        DISPATCHER)
    validate_error(res, "ERR_CREW_DOUBLE_BOOKED", expected_status=409)


def test_crew_second_route_on_different_day_allowed(api):
    """PRD §2.8: "A single crew may hold at most one route per calendar
    `service_date` that is not yet `CLOSED`."

    Design: Difficulty/resource_temporal_overlap/crew_double_booked_whole_day_exclusivity
    """
    crew = create_crew(region_code="NORTH", skill_codes=[], daily_capacity_minutes=600)
    create_route(crew["id"], region_code="NORTH", service_date="2026-07-01")
    # A different calendar date is not exclusive — the second route is allowed.
    second = validate_success(api.create_route(
        {"crew_id": crew["id"], "region_code": "NORTH", "service_date": "2026-07-02"},
        DISPATCHER), 201)
    assert second["status"] == "PLANNING"


# ===========================================================================
# Queue A — boundary_precision_check (window half-open touching)
# ===========================================================================
def test_abutting_visit_windows_commit_successfully(api):
    """PRD §3.4: "because windows are half-open intervals, two windows that merely
    touch at an endpoint do not overlap".

    Design: Difficulty/boundary_precision_check/window_overlap_half_open_touching_endpoints_allowed
    """
    account, prop, agreement, va, crew, route = setup_scheduled_visit(
        region_code="NORTH", schedule_kind="ONE_TIME", service_date="2026-07-01",
        window_start_min=540, window_end_min=660,
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    prop2 = create_property(account["id"], pane_count=60, glass_sqft=100.0, stories=2)
    quote2 = create_sent_quote(account["id"], prop2["id"],
                               pricing_basis="PANE_COUNT", addon_codes=["GUTTER"])
    validate_success(api.accept_quote(quote2["id"], make_customer_headers(account["id"])), 200)
    agr2 = validate_success(api.create_service_agreement(
        {"quote_id": quote2["id"], "schedule_kind": "ONE_TIME"}, BILLING), 201)
    activate_agreement(agr2["id"], planned_date="2026-07-01",
                       window_start_min=660, window_end_min=780)
    vb = _first_visit(api, agr2["id"])

    committed = validate_success(_commit_raw(api, route["id"], vb["id"]), 201)
    assert committed["schedule_status"] == "SCHEDULED"
    route_after = validate_success(api.get_route(route["id"], DISPATCHER), 200)
    assert route_after["booked_minutes"] == 240


def test_abutting_visit_commits_when_endpoints_touch(api):
    """PRD §3.4: "two windows that merely touch at an endpoint do not overlap, but
    any true overlap is rejected with `ERR_VISIT_WINDOW_OVERLAP`."

    Design: Difficulty/boundary_precision_check/window_overlap_half_open_touching_endpoints_allowed
    """
    # Existing visit holds [660,780); a new visit at [540,660) touches at 660.
    account, prop, agreement, va, crew, route = setup_scheduled_visit(
        region_code="NORTH", schedule_kind="ONE_TIME", service_date="2026-07-01",
        window_start_min=660, window_end_min=780,
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    prop2 = create_property(account["id"], pane_count=60, glass_sqft=100.0, stories=2)
    quote2 = create_sent_quote(account["id"], prop2["id"],
                               pricing_basis="PANE_COUNT", addon_codes=["GUTTER"])
    validate_success(api.accept_quote(quote2["id"], make_customer_headers(account["id"])), 200)
    agr2 = validate_success(api.create_service_agreement(
        {"quote_id": quote2["id"], "schedule_kind": "ONE_TIME"}, BILLING), 201)
    activate_agreement(agr2["id"], planned_date="2026-07-01",
                       window_start_min=540, window_end_min=660)
    vb = _first_visit(api, agr2["id"])

    committed = validate_success(_commit_raw(api, route["id"], vb["id"]), 201)
    assert committed["schedule_status"] == "SCHEDULED"


# ===========================================================================
# Queue A — priority_pair_validation_conflict
# ===========================================================================
def test_agreement_not_active_beats_capacity_exceeded(api):
    """PRD §3.9: "Quote-expiry (`ERR_QUOTE_EXPIRED`) precedes agreement-active
    (`ERR_AGREEMENT_NOT_ACTIVE`), which precedes route-planning
    (`ERR_ROUTE_NOT_PLANNING`)".
    PRD §3.9: "The fiscal checks — route capacity (`ERR_ROUTE_CAPACITY_EXCEEDED`)
    and deposit-met (`ERR_DEPOSIT_NOT_MET`) — come next".

    Design: Difficulty/priority_pair_validation_conflict/commit_state_beats_fiscal_agreement_not_active_vs_capacity
    """
    # Visit duration 120 > crew capacity 100 (fiscal), AND agreement paused (state).
    account, prop, agreement, visit = setup_active_agreement(
        schedule_kind="ONE_TIME", region_code="NORTH",
        window_start_min=540, window_end_min=660,
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    cust = make_customer_headers(account["id"])
    validate_success(api.pause_agreement(agreement["id"], cust), 200)

    crew = create_crew(region_code="NORTH", skill_codes=[], daily_capacity_minutes=100)
    route = create_route(crew["id"], region_code="NORTH", service_date="2026-07-01")
    res = _commit_raw(api, route["id"], visit["id"])
    validate_error(res, "ERR_AGREEMENT_NOT_ACTIVE", expected_status=409)


def test_agreement_not_active_fires_at_409_over_fiscal_violation(api):
    """PRD §3.9: "Quote-expiry (`ERR_QUOTE_EXPIRED`) precedes agreement-active
    (`ERR_AGREEMENT_NOT_ACTIVE`), which precedes route-planning
    (`ERR_ROUTE_NOT_PLANNING`)".

    Design: Difficulty/priority_pair_validation_conflict/commit_state_beats_fiscal_agreement_not_active_vs_capacity
    """
    # Same double-violation (paused agreement + capacity 100 < duration 120),
    # asserting the conflict-status conjunction: the state error wins at HTTP 409,
    # never the 422 fiscal error.
    account, prop, agreement, visit = setup_active_agreement(
        schedule_kind="ONE_TIME", region_code="NORTH",
        window_start_min=540, window_end_min=660,
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    cust = make_customer_headers(account["id"])
    validate_success(api.pause_agreement(agreement["id"], cust), 200)
    crew = create_crew(region_code="NORTH", skill_codes=[], daily_capacity_minutes=100)
    route = create_route(crew["id"], region_code="NORTH", service_date="2026-07-01")
    res = _commit_raw(api, route["id"], visit["id"])
    assert res.status_code == 409, "state error (409) wins over fiscal error (422)"
    validate_error(res, "ERR_AGREEMENT_NOT_ACTIVE")


def test_crew_skill_missing_beats_window_overlap(api):
    """PRD §3.9: "After those state guards come the business-safety checks — crew
    skill coverage (`ERR_CREW_SKILL_MISSING`) ... — then the business-constraint and
    temporal checks: region match (`ERR_REGION_MISMATCH`), date match
    (`ERR_DATE_MISMATCH`), window overlap (`ERR_VISIT_WINDOW_OVERLAP`)".

    Design: Difficulty/priority_pair_validation_conflict/commit_safety_beats_temporal_skill_missing_vs_window_overlap
    """
    # Crew lacks SOFT_WASH (safety). A simple visit holds [540,660); the soft-wash
    # visit's window [600,720) overlaps it (temporal). Safety must win.
    account = create_account(region_code="EAST")
    p_simple = create_property(account["id"], pane_count=60, glass_sqft=100.0, stories=2)
    p_sw = create_property(account["id"], pane_count=80, glass_sqft=100.0,
                           stories=4, soft_wash_sqft=400.0)

    q1 = create_sent_quote(account["id"], p_simple["id"],
                           pricing_basis="PANE_COUNT", addon_codes=["GUTTER"])
    cust = make_customer_headers(account["id"])
    validate_success(api.accept_quote(q1["id"], cust), 200)
    agr1 = validate_success(api.create_service_agreement(
        {"quote_id": q1["id"], "schedule_kind": "ONE_TIME"}, BILLING), 201)
    activate_agreement(agr1["id"], planned_date="2026-07-01",
                       window_start_min=540, window_end_min=660)
    v_simple = _first_visit(api, agr1["id"])

    q2 = create_sent_quote(account["id"], p_sw["id"],
                           pricing_basis="PANE_COUNT", addon_codes=["SOFT_WASH"])
    validate_success(api.accept_quote(q2["id"], cust), 200)
    agr2 = validate_success(api.create_service_agreement(
        {"quote_id": q2["id"], "schedule_kind": "ONE_TIME"}, BILLING), 201)
    post_deposit(account["id"], agr2["id"], 9000)
    activate_agreement(agr2["id"], planned_date="2026-07-01",
                       window_start_min=600, window_end_min=720)
    v_sw = _first_visit(api, agr2["id"])

    crew = create_crew(region_code="EAST", skill_codes=["HIGH_RISE"], daily_capacity_minutes=600)
    route = create_route(crew["id"], region_code="EAST", service_date="2026-07-01")
    validate_success(_commit_raw(api, route["id"], v_simple["id"]), 201)

    res = _commit_raw(api, route["id"], v_sw["id"])
    validate_error(res, "ERR_CREW_SKILL_MISSING", expected_status=422)


def test_skill_missing_wins_so_window_overlap_not_reported(api):
    """PRD §3.9: "After those state guards come the business-safety checks — crew
    skill coverage (`ERR_CREW_SKILL_MISSING`) ... — then the business-constraint and
    temporal checks: region match (`ERR_REGION_MISMATCH`), date match
    (`ERR_DATE_MISMATCH`), window overlap (`ERR_VISIT_WINDOW_OVERLAP`)".

    Design: Difficulty/priority_pair_validation_conflict/commit_safety_beats_temporal_skill_missing_vs_window_overlap
    """
    account = create_account(region_code="EAST")
    p_simple = create_property(account["id"], pane_count=60, glass_sqft=100.0, stories=2)
    p_sw = create_property(account["id"], pane_count=80, glass_sqft=100.0,
                           stories=4, soft_wash_sqft=400.0)
    cust = make_customer_headers(account["id"])

    q1 = create_sent_quote(account["id"], p_simple["id"],
                           pricing_basis="PANE_COUNT", addon_codes=["GUTTER"])
    validate_success(api.accept_quote(q1["id"], cust), 200)
    agr1 = validate_success(api.create_service_agreement(
        {"quote_id": q1["id"], "schedule_kind": "ONE_TIME"}, BILLING), 201)
    activate_agreement(agr1["id"], planned_date="2026-07-01",
                       window_start_min=540, window_end_min=660)
    v_simple = _first_visit(api, agr1["id"])

    q2 = create_sent_quote(account["id"], p_sw["id"],
                           pricing_basis="PANE_COUNT", addon_codes=["SOFT_WASH"])
    validate_success(api.accept_quote(q2["id"], cust), 200)
    agr2 = validate_success(api.create_service_agreement(
        {"quote_id": q2["id"], "schedule_kind": "ONE_TIME"}, BILLING), 201)
    post_deposit(account["id"], agr2["id"], 9000)
    activate_agreement(agr2["id"], planned_date="2026-07-01",
                       window_start_min=600, window_end_min=720)
    v_sw = _first_visit(api, agr2["id"])

    crew = create_crew(region_code="EAST", skill_codes=["HIGH_RISE"], daily_capacity_minutes=600)
    route = create_route(crew["id"], region_code="EAST", service_date="2026-07-01")
    validate_success(_commit_raw(api, route["id"], v_simple["id"]), 201)

    res = _commit_raw(api, route["id"], v_sw["id"])
    # Safety error wins at 422; the temporal overlap (409) is never the reported id.
    body = res.json()
    assert body["data"]["error_id"] == "ERR_CREW_SKILL_MISSING"
    assert body["data"]["error_id"] != "ERR_VISIT_WINDOW_OVERLAP"


# ===========================================================================
# Queue B — validations / endpoints / errors
# ===========================================================================
def test_activate_below_required_deposit_rejected(api):
    """PRD §3.2: "once the sum of the account's `HELD` deposits standing against
    this agreement reaches at least the agreement's `required_deposit_cents`. If
    that threshold is not met, activation is rejected with `ERR_DEPOSIT_NOT_MET`."

    Design: Corner/validations/activate_agreement_below_required_deposit_returns_deposit_not_met
    """
    account, prop, quote, agreement = setup_pending_agreement(
        schedule_kind="ONE_TIME", region_code="EAST",
        property_overrides={"pane_count": 80, "glass_sqft": 100.0, "stories": 4, "soft_wash_sqft": 400.0},
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["SOFT_WASH"]})
    # required_deposit = round(35400*0.25) = 8850; post only 5000.
    assert agreement["required_deposit_cents"] == 8850
    post_deposit(account["id"], agreement["id"], 5000)
    res = api.activate_agreement(agreement["id"],
                                 {"first_visit_planned_date": "2026-07-01",
                                  "first_visit_window_start_min": 540,
                                  "first_visit_window_end_min": 660}, BILLING)
    validate_error(res, "ERR_DEPOSIT_NOT_MET", expected_status=422)


def test_commit_visit_region_mismatch_rejected(api):
    """PRD §3.4: "The visit's region — its account's `region_code` — must equal the
    route's `region_code`, or the commit is rejected with `ERR_REGION_MISMATCH`."

    Design: Corner/validations/commit_visit_wrong_region_returns_region_mismatch
    """
    account, prop, agreement, visit = setup_active_agreement(
        schedule_kind="ONE_TIME", region_code="NORTH",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    crew = create_crew(region_code="SOUTH", skill_codes=[], daily_capacity_minutes=600)
    route = create_route(crew["id"], region_code="SOUTH", service_date="2026-07-01")
    res = _commit_raw(api, route["id"], visit["id"])
    validate_error(res, "ERR_REGION_MISMATCH", expected_status=422)


def test_commit_visit_date_mismatch_rejected(api):
    """PRD §3.4: "The visit's `planned_date` must equal the route's `service_date`,
    or the commit is rejected with `ERR_DATE_MISMATCH`."

    Design: Corner/validations/commit_visit_date_mismatch_returns_date_mismatch
    """
    account, prop, agreement, visit = setup_active_agreement(
        schedule_kind="ONE_TIME", region_code="NORTH",
        planned_date="2026-07-01",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    crew = create_crew(region_code="NORTH", skill_codes=[], daily_capacity_minutes=600)
    route = create_route(crew["id"], region_code="NORTH", service_date="2026-07-08")
    res = _commit_raw(api, route["id"], visit["id"])
    validate_error(res, "ERR_DATE_MISMATCH", expected_status=422)


def test_commit_visit_capacity_exceeded_rejected(api):
    """PRD §3.4: "Adding the visit's duration to the route's current
    `booked_minutes` must not exceed the crew's `daily_capacity_minutes`, or the
    commit is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`."

    Design: Corner/validations/capacity_exceeded_alone_returns_route_capacity_exceeded
    """
    account, prop, agreement, visit = setup_active_agreement(
        schedule_kind="ONE_TIME", region_code="NORTH",
        window_start_min=540, window_end_min=660,
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    crew = create_crew(region_code="NORTH", skill_codes=[], daily_capacity_minutes=100)
    route = create_route(crew["id"], region_code="NORTH", service_date="2026-07-01")
    res = _commit_raw(api, route["id"], visit["id"])
    validate_error(res, "ERR_ROUTE_CAPACITY_EXCEEDED", expected_status=422)


def test_dispatch_empty_route_rejected(api):
    """PRD §3.4: "and at least one visit is committed to it (otherwise
    `ERR_EMPTY_ROUTE`)."

    Design: Corner/endpoints/dispatch_empty_route_returns_empty_route
    """
    crew = create_crew(region_code="NORTH", skill_codes=[], daily_capacity_minutes=600)
    route = create_route(crew["id"], region_code="NORTH", service_date="2026-07-01")
    res = api.dispatch_route(route["id"], DISPATCHER)
    validate_error(res, "ERR_EMPTY_ROUTE", expected_status=422)


def test_close_route_with_open_visits_rejected(api):
    """PRD §3.4: "A `DISPATCHED` route is closed, moving to `CLOSED`, only when no
    committed visit remains in `DISPATCHED` or `IN_PROGRESS` — every committed visit
    must be `COMPLETED` or `CANCELLED` — otherwise the close is rejected with
    `ERR_OPEN_VISITS_EXIST`."

    Design: Corner/endpoints/close_route_with_open_visits_returns_open_visits_exist
    """
    account, prop, agreement, visit, crew, route = setup_dispatched_visit(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    # Visit is DISPATCHED (not started), so close must fail.
    res = api.close_route(route["id"], DISPATCHER)
    validate_error(res, "ERR_OPEN_VISITS_EXIST", expected_status=409)


def test_weather_reschedule_without_hold_rejected(api):
    """PRD §3.6: "It is permitted only when the visit is in schedule status
    `SCHEDULED` and a `SUSPEND`-severity advisory whose `region_code` matches the
    route's region covers the visit's `planned_date`; absent such a hold, the
    reschedule is rejected with `ERR_NO_WEATHER_HOLD`."

    Design: Corner/errors/weather_reschedule_without_hold_returns_no_weather_hold
    """
    account, prop, agreement, visit, crew, route = setup_scheduled_visit(
        region_code="NORTH", schedule_kind="ONE_TIME", service_date="2026-07-01",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    res = api.weather_reschedule_visit(visit["id"], {"new_planned_date": "2026-07-08"}, DISPATCHER)
    validate_error(res, "ERR_NO_WEATHER_HOLD", expected_status=409)


def _first_visit(api, agreement_id):
    res = api.list_agreement_visits(agreement_id, BILLING)
    return res.json()["data"][0]
