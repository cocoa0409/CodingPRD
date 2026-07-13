"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints — the test harness restarts the server (empty database) before every
test. Helpers use get_success_data() (lenient) so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: DeliveryLead and Customer are entity_backed roles. After a
crew or customer is created, ownership-gated calls in these helpers use
make_delivery_lead_headers(team_id) / make_customer_headers(customer_id) with the
real entity id — never a shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_depot_payload,
    create_dock_payload,
    create_team_payload,
    create_customer_payload,
    create_order_payload,
    reserve_window_payload,
    create_route_payload,
    add_stop_payload,
    book_dock_appointment_payload,
    record_attempt_payload,
)
from .test_users import TEST_USERS, make_delivery_lead_headers

_ADMIN = TEST_USERS["platform_admin_headers"]
_PLANNER = TEST_USERS["dispatch_planner_headers"]
_DOCK = TEST_USERS["dock_coordinator_headers"]


# --------------------------------------------------------------------------- #
# Single-step creators (return the created resource dict)
# --------------------------------------------------------------------------- #

def make_depot(api, **overrides) -> dict:
    return get_success_data(api.create_depot(create_depot_payload(**overrides), _ADMIN))


def make_dock(api, depot_id, **overrides) -> dict:
    return get_success_data(api.create_dock(create_dock_payload(depot_id, **overrides), _ADMIN))


def make_team(api, depot_id, **overrides) -> dict:
    return get_success_data(api.create_team(create_team_payload(depot_id, **overrides), _ADMIN))


def make_customer(api, **overrides) -> dict:
    return get_success_data(api.create_customer(create_customer_payload(**overrides), _ADMIN))


def make_order(api, customer_id, **overrides) -> dict:
    return get_success_data(api.create_order(create_order_payload(customer_id, **overrides), _PLANNER))


def make_route(api, depot_id, team_id, **overrides) -> dict:
    return get_success_data(api.create_route(create_route_payload(depot_id, team_id, **overrides), _PLANNER))


def reserve_order_window(api, order, team_id, **overrides) -> dict:
    """Reserve a window using the order's current version. `order` may be the
    order dict (version read from it) or the raw id (version fetched)."""
    if isinstance(order, dict):
        order_id = order["id"]
        version = order["version"]
    else:
        order_id = order
        version = get_success_data(api.get_order(order_id, _PLANNER))["version"]
    payload = reserve_window_payload(team_id, version, **overrides)
    return get_success_data(api.reserve_window(order_id, payload, _PLANNER))


def add_route_stop(api, route_id, order_id, window_id, **overrides) -> dict:
    return get_success_data(api.add_stop(route_id, add_stop_payload(order_id, window_id, **overrides), _PLANNER))


def book_appointment(api, route_id, dock_id, **overrides) -> dict:
    return get_success_data(
        api.book_dock_appointment(route_id, book_dock_appointment_payload(dock_id, **overrides), _DOCK)
    )


def dispatch(api, route_id) -> dict:
    return get_success_data(api.dispatch_route(route_id, _PLANNER))


def record_lead_attempt(api, order_id, team_id, outcome, **overrides) -> dict:
    """Record a delivery attempt as the owning crew (entity_backed DeliveryLead)."""
    headers = make_delivery_lead_headers(team_id)
    return get_success_data(
        api.record_attempt(order_id, record_attempt_payload(outcome, **overrides), headers)
    )


# --------------------------------------------------------------------------- #
# Composite scenario builders (return an id/resource namespace dict)
# --------------------------------------------------------------------------- #

def setup_network(api, team_overrides=None, customer_overrides=None) -> dict:
    """Depot + dock + one crew + one customer. Base for most scenarios."""
    depot = make_depot(api)
    dock = make_dock(api, depot["id"])
    team = make_team(api, depot["id"], **(team_overrides or {}))
    customer = make_customer(api, **(customer_overrides or {}))
    return {"depot": depot, "dock": dock, "team": team, "customer": customer}


def setup_scheduled_order(api, order_overrides=None, team_overrides=None) -> dict:
    """A CREATED order advanced to SCHEDULED with a RESERVED window.
    Returns namespace: depot, dock, team, customer, order, window."""
    net = setup_network(api, team_overrides=team_overrides)
    order = make_order(api, net["customer"]["id"], **(order_overrides or {}))
    window = reserve_order_window(api, order, net["team"]["id"])
    net["order"] = order
    net["window"] = window
    return net


def setup_routed_order(api, order_overrides=None, team_overrides=None,
                       route_overrides=None) -> dict:
    """A SCHEDULED order added as a PLANNED stop on a PLANNING route (order ROUTED).
    Returns namespace incl. route + stop."""
    ns = setup_scheduled_order(api, order_overrides=order_overrides, team_overrides=team_overrides)
    route = make_route(api, ns["depot"]["id"], ns["team"]["id"], **(route_overrides or {}))
    stop = add_route_stop(api, route["id"], ns["order"]["id"], ns["window"]["id"])
    ns["route"] = route
    ns["stop"] = stop
    return ns


def setup_out_for_delivery(api, order_overrides=None, team_overrides=None) -> dict:
    """Full preamble: order routed, dock appointment booked, route dispatched.
    Order ends OUT_FOR_DELIVERY. Returns namespace incl. route, stop, appointment."""
    ns = setup_routed_order(api, order_overrides=order_overrides, team_overrides=team_overrides)
    appt = book_appointment(api, ns["route"]["id"], ns["dock"]["id"])
    dispatch(api, ns["route"]["id"])
    ns["appointment"] = appt
    return ns


def setup_delivered_order(api, order_overrides=None, team_overrides=None,
                          attempt_overrides=None) -> dict:
    """Order carried through to DELIVERED via a DELIVERED attempt with valid POD.
    Returns namespace incl. attempt."""
    ns = setup_out_for_delivery(api, order_overrides=order_overrides, team_overrides=team_overrides)
    attempt_payload = {"placement": "THRESHOLD", "signature_captured": True, "photo_count": 1}
    if attempt_overrides:
        attempt_payload.update(attempt_overrides)
    attempt = record_lead_attempt(api, ns["order"]["id"], ns["team"]["id"], "DELIVERED", **attempt_payload)
    ns["attempt"] = attempt
    return ns


def setup_settled_order(api, order_overrides=None, team_overrides=None,
                        attempt_overrides=None) -> dict:
    """DELIVERED order then SETTLED onto the customer ledger."""
    ns = setup_delivered_order(api, order_overrides=order_overrides,
                               team_overrides=team_overrides, attempt_overrides=attempt_overrides)
    get_success_data(api.settle_order(ns["order"]["id"], _PLANNER))
    return ns


def setup_refused_once(api, order_overrides=None, team_overrides=None) -> dict:
    """Order dispatched then REFUSED once (reattempt_count 1, status REFUSED_RETRY,
    prior window RELEASED, stop SKIPPED, capacity released)."""
    ns = setup_out_for_delivery(api, order_overrides=order_overrides, team_overrides=team_overrides)
    record_lead_attempt(api, ns["order"]["id"], ns["team"]["id"], "REFUSED",
                        refusal_reason="customer changed mind")
    return ns
