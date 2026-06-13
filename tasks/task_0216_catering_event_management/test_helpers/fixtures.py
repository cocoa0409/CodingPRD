"""Composite setup helpers for the Catering Event Management API.

Every fixture builds its preconditions from scratch (the harness restarts the server with
an empty database before each test) using only PRD-declared endpoints. Fixtures use the
lenient get_success_data() validator so setup failures surface as clear "Setup failed" errors.

Identity threading: Client is entity_backed, so any Client-acted ownership-gated call uses
make_client_headers(client["id"]), never the shared TEST_USERS["client_headers"].
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_client_headers
from .factories import (
    create_client_payload,
    create_package_payload,
    create_venue_payload,
    create_route_payload,
    create_order_payload,
    create_add_on_payload,
    create_delivery_leg_payload,
    create_change_request_payload,
    DEFAULT_EVENT_START,
    DEFAULT_EVENT_END,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
CAPTAIN = TEST_USERS["captain_headers"]


# ---------------------------------------------------------------------------
# Clock / staff-pool control (test-driving surface, PRD §3.12)
# ---------------------------------------------------------------------------
def set_clock(iso: str):
    """Advance the logical server clock (CateringAdmin only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def set_staff_pool(total_staff: int):
    """Set the global staffing pool capacity (CateringAdmin only)."""
    return get_success_data(api_client.set_staff_pool({"total_staff": total_staff}, ADMIN))


# ---------------------------------------------------------------------------
# Catalog primitives
# ---------------------------------------------------------------------------
def create_package(**overrides) -> dict:
    return get_success_data(api_client.create_package(create_package_payload(**overrides), ADMIN))


def create_venue(**overrides) -> dict:
    return get_success_data(api_client.create_venue(create_venue_payload(**overrides), ADMIN))


def create_route(**overrides) -> dict:
    return get_success_data(api_client.create_route(create_route_payload(**overrides), ADMIN))


def create_client(**overrides) -> dict:
    return get_success_data(api_client.create_client(create_client_payload(**overrides), ADMIN))


def retire_package(package: dict) -> dict:
    return get_success_data(
        api_client.retire_package(
            package["id"], {"expected_package_version": package["version"]}, ADMIN
        )
    )


# ---------------------------------------------------------------------------
# Catalog bundle — package + venue + client. Most order tests start here.
# ---------------------------------------------------------------------------
def setup_catalog(package_overrides=None, venue_overrides=None, client_overrides=None) -> dict:
    """Create a package, venue, and client. Returns {package, venue, client}."""
    package = create_package(**(package_overrides or {}))
    venue = create_venue(**(venue_overrides or {}))
    client = create_client(**(client_overrides or {}))
    return {"package": package, "venue": venue, "client": client}


# ---------------------------------------------------------------------------
# Order creation (Tier 1: state progression)
# ---------------------------------------------------------------------------
def create_draft_order(catalog=None, package_overrides=None, venue_overrides=None,
                       client_overrides=None, **order_overrides) -> dict:
    """Create a DRAFT order. Returns {package, venue, client, order, client_headers}.

    order_overrides flows into the order create payload (booked_headcount, event_start,
    event_end, dietary_counts). The order is created by its owning Client (entity_backed).
    """
    cat = catalog or setup_catalog(package_overrides, venue_overrides, client_overrides)
    client = cat["client"]
    headers = make_client_headers(client["id"])
    order = get_success_data(
        api_client.create_order(
            create_order_payload(client["id"], cat["package"]["id"], cat["venue"]["id"],
                                 **order_overrides),
            headers,
        )
    )
    return {**cat, "order": order, "client_headers": headers}


def add_staffing(order_id: str, client_headers: dict, quantity: int, unit_cents: int = 8000,
                 **overrides) -> dict:
    """Attach a STAFFING add-on to a DRAFT order (Client-acted)."""
    return get_success_data(
        api_client.create_add_on(
            order_id, create_add_on_payload("STAFFING", unit_cents, quantity, **overrides),
            client_headers,
        )
    )


def confirm_order(order: dict) -> dict:
    """Confirm a DRAFT order (SalesCoordinator). Returns the confirmed order."""
    return get_success_data(
        api_client.confirm_order(order["id"], {"expected_order_version": order["version"]}, COORD)
    )


def guarantee_order(order: dict, guaranteed_headcount: int) -> dict:
    """Guarantee a CONFIRMED order (SalesCoordinator). Returns the guaranteed order."""
    return get_success_data(
        api_client.guarantee_order(
            order["id"],
            {"expected_order_version": order["version"], "guaranteed_headcount": guaranteed_headcount},
            COORD,
        )
    )


def invoice_order(order: dict) -> dict:
    """Invoice a GUARANTEED/DEPOSIT_HELD order (SalesCoordinator). Returns the invoiced order."""
    return get_success_data(
        api_client.invoice_order(order["id"], {"expected_order_version": order["version"]}, COORD)
    )


def pay_order(order: dict, client_headers: dict, amount_cents: int) -> dict:
    """Record a Client payment against the order ledger. Returns the updated order."""
    return get_success_data(
        api_client.pay_order(
            order["id"],
            {"expected_order_version": order["version"], "amount_cents": amount_cents},
            client_headers,
        )
    )


def settle_order(order: dict) -> dict:
    """Settle an INVOICED, fully-paid order (SalesCoordinator). Returns the settled order."""
    return get_success_data(
        api_client.settle_order(order["id"], {"expected_order_version": order["version"]}, COORD)
    )


def cancel_order(order: dict, client_headers: dict) -> dict:
    """Cancel an order (Client-acted, ownership-gated). Returns the cancelled order."""
    return get_success_data(
        api_client.cancel_order(order["id"], {"expected_order_version": order["version"]}, client_headers)
    )


# ---------------------------------------------------------------------------
# Tier 1/2 composite: confirmed & guaranteed orders
# ---------------------------------------------------------------------------
def setup_confirmed_order(clock="2026-06-01T00:00:00Z", staffing_qty=None, staff_pool=None,
                          package_overrides=None, venue_overrides=None, client_overrides=None,
                          **order_overrides) -> dict:
    """Clock set + catalog + DRAFT order (+ optional STAFFING add-on) → CONFIRMED.

    Returns {package, venue, client, order, client_headers}. `order` is the confirmed order.
    """
    set_clock(clock)
    if staff_pool is not None:
        set_staff_pool(staff_pool)
    ctx = create_draft_order(package_overrides=package_overrides, venue_overrides=venue_overrides,
                             client_overrides=client_overrides, **order_overrides)
    if staffing_qty is not None:
        add_staffing(ctx["order"]["id"], ctx["client_headers"], staffing_qty)
    ctx["order"] = confirm_order(ctx["order"])
    return ctx


def setup_guaranteed_order(guaranteed_headcount, clock="2026-06-01T00:00:00Z", staffing_qty=None,
                           staff_pool=None, package_overrides=None, venue_overrides=None,
                           client_overrides=None, **order_overrides) -> dict:
    """Confirmed order → GUARANTEED. Returns the same context dict with a guaranteed `order`."""
    ctx = setup_confirmed_order(clock=clock, staffing_qty=staffing_qty, staff_pool=staff_pool,
                                package_overrides=package_overrides, venue_overrides=venue_overrides,
                                client_overrides=client_overrides, **order_overrides)
    ctx["order"] = guarantee_order(ctx["order"], guaranteed_headcount)
    return ctx


def setup_invoiced_order(guaranteed_headcount, clock="2026-06-01T00:00:00Z", staffing_qty=None,
                         staff_pool=None, package_overrides=None, venue_overrides=None,
                         client_overrides=None, **order_overrides) -> dict:
    """Guaranteed order → INVOICED. Returns context with an invoiced `order`."""
    ctx = setup_guaranteed_order(guaranteed_headcount, clock=clock, staffing_qty=staffing_qty,
                                 staff_pool=staff_pool, package_overrides=package_overrides,
                                 venue_overrides=venue_overrides, client_overrides=client_overrides,
                                 **order_overrides)
    ctx["order"] = invoice_order(ctx["order"])
    return ctx


def setup_settled_order(guaranteed_headcount, clock="2026-06-01T00:00:00Z", staffing_qty=None,
                        staff_pool=None, package_overrides=None, venue_overrides=None,
                        client_overrides=None, **order_overrides) -> dict:
    """Invoiced order → pay full final_total_cents → SETTLED. Returns context with a settled `order`."""
    ctx = setup_invoiced_order(guaranteed_headcount, clock=clock, staffing_qty=staffing_qty,
                               staff_pool=staff_pool, package_overrides=package_overrides,
                               venue_overrides=venue_overrides, client_overrides=client_overrides,
                               **order_overrides)
    final = ctx["order"]["final_total_cents"]
    ctx["order"] = pay_order(ctx["order"], ctx["client_headers"], final)
    ctx["order"] = settle_order(ctx["order"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: change-request lifecycle shortcuts
# ---------------------------------------------------------------------------
def open_change_request(order_id: str, client_headers: dict, requested_headcount: int,
                        requested_event_start: str = DEFAULT_EVENT_START) -> dict:
    """Open a PROPOSED change request (Client-acted)."""
    return get_success_data(
        api_client.create_change_request(
            create_change_request_payload(order_id, requested_headcount, requested_event_start),
            client_headers,
        )
    )


def counter_change_request(cr_id: str, counter_headcount: int) -> dict:
    """Coordinator counters a PROPOSED change request → COUNTERED."""
    return get_success_data(
        api_client.counter_change_request(cr_id, {"counter_headcount": counter_headcount}, COORD)
    )


def setup_order_with_open_change(requested_headcount=90, clock="2026-06-01T00:00:00Z",
                                 guaranteed_headcount=None, **order_overrides) -> dict:
    """Confirmed (optionally guaranteed) order + one PROPOSED change request.

    Returns context with `order` and added key `change_request`.
    """
    if guaranteed_headcount is not None:
        ctx = setup_guaranteed_order(guaranteed_headcount, clock=clock, **order_overrides)
    else:
        ctx = setup_confirmed_order(clock=clock, **order_overrides)
    cr = open_change_request(ctx["order"]["id"], ctx["client_headers"], requested_headcount)
    ctx["change_request"] = cr
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: delivery-leg lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_leg(order_id: str, route_id: str, window_start: str, window_end: str,
               preceding_leg_id=None) -> dict:
    """Schedule a PLANNED delivery leg (SalesCoordinator). preceding_leg_id optional."""
    overrides = {}
    if preceding_leg_id is not None:
        overrides["preceding_leg_id"] = preceding_leg_id
    return get_success_data(
        api_client.create_delivery_leg(
            create_delivery_leg_payload(order_id, route_id, window_start, window_end, **overrides),
            COORD,
        )
    )


def route_version(route_id: str) -> int:
    """Fetch a route's current version (for expected_route_version on leg transitions)."""
    return get_success_data(api_client.get_route(route_id, CAPTAIN))["version"]


def dispatch_leg(leg_id: str, route_id: str) -> dict:
    """Dispatch a PLANNED leg (EventCaptain), reading the route version fresh."""
    return get_success_data(
        api_client.dispatch_delivery_leg(
            leg_id, {"expected_route_version": route_version(route_id)}, CAPTAIN
        )
    )


def deliver_leg(leg_id: str, route_id: str) -> dict:
    """Deliver a DISPATCHED leg (EventCaptain)."""
    return get_success_data(
        api_client.deliver_delivery_leg(
            leg_id, {"expected_route_version": route_version(route_id)}, CAPTAIN
        )
    )


def setup_guaranteed_order_with_route_and_leg(guaranteed_headcount=80, clock="2026-06-01T00:00:00Z",
                                              window_start="2026-09-01T15:00:00Z",
                                              window_end="2026-09-01T16:00:00Z",
                                              vehicle_capacity_legs=3, **order_overrides) -> dict:
    """Guaranteed order + a route + one PLANNED leg. Returns context with `route` and `leg`."""
    set_clock(clock)
    route = create_route(vehicle_capacity_legs=vehicle_capacity_legs)
    ctx = create_draft_order(**order_overrides)
    ctx["order"] = confirm_order(ctx["order"])
    ctx["order"] = guarantee_order(ctx["order"], guaranteed_headcount)
    leg = create_leg(ctx["order"]["id"], route["id"], window_start, window_end)
    ctx["route"] = route
    ctx["leg"] = leg
    return ctx
