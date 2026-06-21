"""State-machine transitions: quote cyclic revision, the work-order parallel axes,
and the invalid / terminal / precondition guards across quote, system, plan, route,
and work-order lifecycles.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_customer_property,
    setup_customer_property_system,
    setup_sent_quote,
    create_customer,
    create_property,
    create_system,
    create_technician,
    create_work_order,
    create_route,
    create_route_stop,
    schedule_work_order,
    make_technician_headers,
    make_customer_headers,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Queue A — non_linear_state_machine
# ===========================================================================
def test_quote_cyclic_send_request_changes_revise_resend(api):
    """PRD §3.3: "They may request changes, moving the quote `SENT → CHANGES_REQUESTED`".
    PRD §3.3: "the Dispatcher revises the quote by submitting a fresh `line_items` array,
    which replaces the prior list and moves the quote `CHANGES_REQUESTED → DRAFT`... and
    recomputes `estimated_total_cents` by the same estimated rule. This send-then-revise
    loop may cycle." PRD §3.3: "A Dispatcher sends a quote to the customer, moving it
    `DRAFT → SENT`... On a successful send, the quote's `estimated_total_cents` is recomputed."

    Design: Difficulty/non_linear_state_machine/quote_cyclic_revision_loop
    """
    _cust, prop = setup_customer_property(company_name="Loop Co")
    cust = _cust
    quote = validate_success(api.create_quote(
        {"property_id": prop["id"], "quote_type": "INSTALL",
         "line_items": [{"description": "heads", "quantity": 1, "unit_rate_cents": 5000}]},
        DISPATCHER), expected_status=201)
    validate_success(api.send_quote(quote["id"], DISPATCHER))
    cust_headers = make_customer_headers(cust["id"])
    validate_success(api.request_changes_quote(quote["id"], cust_headers))
    validate_success(api.revise_quote_line_items(
        quote["id"], {"line_items": [{"description": "heads", "quantity": 2, "unit_rate_cents": 50}]},
        DISPATCHER))
    resent = validate_success(api.send_quote(quote["id"], DISPATCHER))

    assert resent["quote_state"] == "SENT", f"quote_state should be SENT, got {resent['quote_state']}"
    assert resent["estimated_total_cents"] == 108, (
        f"estimated_total_cents should be recomputed to 108, got {resent['estimated_total_cents']}")


def test_workorder_arrive_advances_both_status_axes(api):
    """PRD §3.4: "Arriving on site advances `EN_ROUTE → ON_SITE`". PRD §3.4: "Arrival also
    has a cross-axis side effect: it automatically advances `completion_status` from
    `PENDING` to `IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/workorder_parallel_dispatch_and_completion_dimensions
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Par Co")
    tech = create_technician(full_name="Pat Par")
    wo_id, _route_id, _ = schedule_work_order(
        sys["id"], tech["id"], job_type="LEAK_REPAIR", estimated_cost_cents=4000,
        route_date="2026-05-01")
    tech_headers = make_technician_headers(tech["id"])
    validate_success(api.depart_work_order(wo_id, tech_headers))
    wo = validate_success(api.arrive_work_order(wo_id, tech_headers))

    assert wo["dispatch_status"] == "ON_SITE", (
        f"dispatch_status should be ON_SITE, got {wo['dispatch_status']}")
    assert wo["completion_status"] == "IN_PROGRESS", (
        f"completion_status should auto-advance to IN_PROGRESS, got {wo['completion_status']}")


# ===========================================================================
# Queue B — state_machines section
# ===========================================================================
def test_send_already_sent_quote_returns_not_draft(api):
    """PRD §3.3: "Sending requires that the quote currently be in `DRAFT` (otherwise
    `ERR_QUOTE_NOT_DRAFT`)".

    Design: Corner/state_machines/send_quote_from_already_sent_returns_not_draft
    """
    _cust, prop = setup_customer_property(company_name="Inv Q Co")
    quote = setup_sent_quote(prop["id"], quote_type="INSTALL")
    resp = api.send_quote(quote["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_DRAFT.value)


def test_decommission_already_decommissioned_system_rejected(api):
    """PRD §3.5: "It is permitted only when the system's `lifecycle_state` is `OPERATIONAL`
    (otherwise `ERR_SYSTEM_ALREADY_DECOMMISSIONED`), after which the system moves to the
    terminal `DECOMMISSIONED`."

    Design: Corner/state_machines/decommission_already_decommissioned_system_rejected
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Term Co")
    validate_success(api.decommission_system(sys["id"], DISPATCHER))
    resp = api.decommission_system(sys["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_SYSTEM_ALREADY_DECOMMISSIONED.value)


def test_arrive_before_depart_returns_not_en_route(api):
    """PRD §3.4: "Arriving on site advances `EN_ROUTE → ON_SITE`; it requires
    `dispatch_status` to be `EN_ROUTE` (otherwise `ERR_WORKORDER_NOT_EN_ROUTE`)".

    Design: Corner/state_machines/arrive_before_depart_returns_not_en_route
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Arr Co")
    tech = create_technician(full_name="Arr Tech")
    wo_id, _route_id, _ = schedule_work_order(
        sys["id"], tech["id"], job_type="LEAK_REPAIR", route_date="2026-05-06")
    tech_headers = make_technician_headers(tech["id"])
    resp = api.arrive_work_order(wo_id, tech_headers)
    validate_error(resp, ApiErrorId.ERR_WORKORDER_NOT_EN_ROUTE.value)


def test_pause_already_paused_plan_returns_not_active(api):
    """PRD §3.7: "A Dispatcher pauses an active plan, moving `ACTIVE → PAUSED` (permitted
    only when the plan is `ACTIVE`, otherwise `ERR_PLAN_NOT_ACTIVE`)".

    Design: Corner/state_machines/pause_already_paused_plan_returns_not_active
    """
    _cust, prop = setup_customer_property(company_name="Plz Co")
    plan = validate_success(api.create_plan(
        {"property_id": prop["id"], "tier": "BASIC", "visits_per_year": 4}, DISPATCHER),
        expected_status=201)
    validate_success(api.pause_plan(plan["id"], DISPATCHER))
    resp = api.pause_plan(plan["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value)


def test_close_route_still_in_planning_rejected(api):
    """PRD §3.6: "Later the Dispatcher closes the route, moving `DISPATCHED → CLOSED`,
    which requires the route to be `DISPATCHED` (otherwise `ERR_ROUTE_NOT_DISPATCHED`)."

    Design: Corner/state_machines/close_route_not_dispatched_rejected
    """
    tech = create_technician(full_name="Cl Tech")
    route = create_route(tech["id"], route_date="2026-05-07")
    resp = api.close_route(route["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_DISPATCHED.value)


def test_dispatch_empty_route_rejected(api):
    """PRD §3.6: "the Dispatcher dispatches it, moving `PLANNING → DISPATCHED`; this
    requires the route to be in `PLANNING` (otherwise `ERR_ROUTE_NOT_PLANNING`) and to
    carry at least one scheduled stop, that is `stops_used` of at least 1 (otherwise
    `ERR_EMPTY_ROUTE`)."

    Design: Corner/state_machines/dispatch_empty_route_rejected
    """
    tech = create_technician(full_name="Emp R Tech")
    route = create_route(tech["id"], route_date="2026-05-08")
    resp = api.dispatch_route(route["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_EMPTY_ROUTE.value)


def test_complete_workorder_not_in_progress_rejected(api):
    """PRD §3.4: "Completion requires `completion_status` to be `IN_PROGRESS` (otherwise
    `ERR_WORKORDER_NOT_IN_PROGRESS`)".

    Design: Corner/state_machines/complete_workorder_not_on_site_rejected
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Comp2 Co")
    tech = create_technician(full_name="Comp2 Tech")
    wo_id, _route_id, _ = schedule_work_order(
        sys["id"], tech["id"], job_type="LEAK_REPAIR", route_date="2026-05-09")
    tech_headers = make_technician_headers(tech["id"])
    resp = api.complete_work_order(
        wo_id, {"actual_labor_cents": 1000, "actual_parts_cents": 500}, tech_headers)
    validate_error(resp, ApiErrorId.ERR_WORKORDER_NOT_IN_PROGRESS.value)


# ===========================================================================
# Queue B — consistency_model
# ===========================================================================
def test_approve_quote_returns_linked_work_order_immediately(api):
    """PRD §3.3: "On approval the system spawns a work order on the property's first
    operational system... and records the originating quote in its `origin_quote_id`. The
    quote's `linked_work_order_id` is set to the new work order's `id`."

    Design: Corner/consistency_model/approve_quote_visible_workorder_in_same_response
    """
    cust = create_customer(company_name="Imm Co")
    prop = create_property(cust["id"])
    create_system(prop["id"])  # first OPERATIONAL system for the spawn target
    quote = validate_success(api.create_quote(
        {"property_id": prop["id"], "quote_type": "INSTALL",
         "line_items": [{"description": "heads", "quantity": 1, "unit_rate_cents": 5000}]},
        DISPATCHER), expected_status=201)
    validate_success(api.send_quote(quote["id"], DISPATCHER))
    cust_headers = make_customer_headers(cust["id"])
    approved = validate_success(api.approve_quote(quote["id"], cust_headers))

    assert approved["quote_state"] == "APPROVED"
    assert approved["linked_work_order_id"] is not None, "linked_work_order_id must be set"
    wo = validate_success(api.get_work_order(approved["linked_work_order_id"], DISPATCHER))
    assert wo["origin_quote_id"] == quote["id"], (
        f"work order origin_quote_id should be {quote['id']}, got {wo['origin_quote_id']}")
