"""Composite setup helpers for multi-step test prerequisites.

Most interesting test claims require the system to be in a specific state that
takes 5-15 API calls to reach (create host -> product -> machine -> slot ->
driver -> route -> stop -> dispatch -> open visit -> reconcile, which fills the
slot via the FIFO lot cascade). These helpers encapsulate those chains.

All helpers use get_success_data() (lenient validator) so setup failures produce
clear "Setup step failed" errors instead of confusing assertion failures.

Identity threading: a RouteDriver is entity_backed:RouteDriverProfile and a
HostManager is entity_backed:HostSite, so every ownership-gated call uses the
per-instance header builder with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_host_site_payload, create_product_payload, create_machine_payload,
    create_slot_payload, create_driver_payload, create_route_payload,
    create_stop_payload, create_visit_payload, create_sale_payload,
    create_statement_payload, create_ticket_payload, counted_line,
)
from .test_users import (
    TEST_USERS, make_route_driver_headers, make_finance_clerk_headers,
    make_field_ops_headers,
)

FIELD_OPS = TEST_USERS["field_ops_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]

# A canonical clock instant; deterministic expiration math.
DEFAULT_CLOCK = "2026-06-01T00:00:00Z"


# ─── Atomic creators ──────────────────────────────────────────────────────

def set_clock(iso: str = DEFAULT_CLOCK):
    """Set the server logical clock to a UTC instant."""
    return get_success_data(api_client.set_clock(iso, FIELD_OPS))


def make_host(**overrides) -> dict:
    """Create a host site. Returns the host entity."""
    return get_success_data(api_client.create_host_site(create_host_site_payload(**overrides), FIELD_OPS))


def make_product(**overrides) -> dict:
    """Create a catalog product. Returns the product entity."""
    return get_success_data(api_client.create_product(create_product_payload(**overrides), FIELD_OPS))


def make_machine(host_id: str, **overrides) -> dict:
    """Place a machine at a host. Returns the machine entity."""
    return get_success_data(api_client.create_machine(create_machine_payload(host_id, **overrides), FIELD_OPS))


def make_slot(machine_id: str, product_id: str, **overrides) -> dict:
    """Add a planogram slot to a machine. Returns the slot entity."""
    payload = create_slot_payload(product_id, **overrides)
    return get_success_data(api_client.create_slot(machine_id, payload, FIELD_OPS))


def make_driver(**overrides) -> dict:
    """Create a route driver profile. Returns the driver entity."""
    return get_success_data(api_client.create_driver(create_driver_payload(**overrides), FIELD_OPS))


def make_route(driver_id: str, service_date: str, **overrides) -> dict:
    """Create a DRAFT restock route. Returns the route entity."""
    return get_success_data(api_client.create_route(create_route_payload(driver_id, service_date, **overrides), FIELD_OPS))


def make_stop(route_id: str, machine_id: str, window_start_min: int = 480, window_end_min: int = 540, **overrides) -> dict:
    """Add a stop to a DRAFT route. Returns the stop entity."""
    payload = create_stop_payload(machine_id, window_start_min, window_end_min, **overrides)
    return get_success_data(api_client.create_stop(route_id, payload, FIELD_OPS))


def dispatch(route_id: str) -> dict:
    return get_success_data(api_client.dispatch_route(route_id, FIELD_OPS))


def open_visit(route_stop_id: str, lines: list, expected_machine_version: int, driver_id: str) -> dict:
    """Open a DRAFT restock visit (RouteDriver, identity-threaded). Returns the visit."""
    headers = make_route_driver_headers(driver_id)
    payload = create_visit_payload(route_stop_id, lines, expected_machine_version)
    return get_success_data(api_client.create_visit(payload, headers))


def reconcile(visit_id: str, expected_machine_version: int, driver_id: str) -> dict:
    """Reconcile a visit (RouteDriver, identity-threaded). Returns the visit."""
    headers = make_route_driver_headers(driver_id)
    return get_success_data(api_client.reconcile_visit(visit_id, {"expected_machine_version": expected_machine_version}, headers))


def make_sale(machine_id: str, slot_id: str, quantity: int, payment_method: str = "CASHLESS", headers=None, **overrides) -> dict:
    """Record a sale. Returns the sale entity."""
    headers = headers or FIELD_OPS
    payload = create_sale_payload(machine_id, slot_id, quantity, payment_method, **overrides)
    return get_success_data(api_client.create_sale(payload, headers))


def make_statement(host_id: str, period_start: str, period_end: str) -> dict:
    """Open a commission statement (FinanceClerk). Returns the statement."""
    payload = create_statement_payload(host_id, period_start, period_end)
    return get_success_data(api_client.create_statement(payload, FINANCE))


def make_ticket(machine_id: str, issue_type: str = "JAM", blocking: bool = False) -> dict:
    """Open a service ticket. Returns the ticket entity."""
    payload = create_ticket_payload(issue_type=issue_type, blocking=blocking)
    return get_success_data(api_client.create_ticket(machine_id, payload, FIELD_OPS))


def machine_version(machine_id: str) -> int:
    """Read the machine's current version."""
    m = get_success_data(api_client.get_machine(machine_id, FIELD_OPS))
    return m["version"]


# ─── Tier 2: Entity Hierarchy ─────────────────────────────────────────────

def setup_host_machine_slot(
    *, clock: str = DEFAULT_CLOCK, host_overrides=None, product_overrides=None,
    machine_overrides=None, slot_overrides=None, driver_overrides=None,
    service_date=None,
):
    """Clock + host + product + machine + slot + driver + DRAFT route.

    Returns a dict with keys: host, product, machine, slot, driver, route.
    The route has no stops yet and is not dispatched. The slot is empty
    (on_hand 0). This is the shared backbone for most setups.
    """
    set_clock(clock)
    host = make_host(**(host_overrides or {}))
    product = make_product(**(product_overrides or {}))
    machine = make_machine(host["id"], **(machine_overrides or {}))
    slot = make_slot(machine["id"], product["id"], **(slot_overrides or {}))
    driver = make_driver(**(driver_overrides or {}))
    route = make_route(driver["id"], service_date or clock)
    return {
        "host": host, "product": product, "machine": machine,
        "slot": slot, "driver": driver, "route": route,
    }


def setup_stocked_slot(
    *, refill_units: int = 10, clock: str = DEFAULT_CLOCK, host_overrides=None,
    product_overrides=None, machine_overrides=None, slot_overrides=None,
    service_date=None,
):
    """Full chain to a slot stocked with `refill_units` units via one reconcile.

    Walks: host/product/machine/slot/driver/route -> add stop -> dispatch ->
    open visit -> reconcile (creates the InventoryLot, bumps Machine.version).

    Returns a dict with keys: host, product, machine, slot, driver, route,
    stop, visit, machine_version (the machine version AFTER the reconcile).
    """
    base = setup_host_machine_slot(
        clock=clock, host_overrides=host_overrides, product_overrides=product_overrides,
        machine_overrides=machine_overrides, slot_overrides=slot_overrides,
        service_date=service_date,
    )
    machine, slot, route, driver = base["machine"], base["slot"], base["route"], base["driver"]
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, refill_units)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])
    base.update({"stop": stop, "visit": visit, "machine_version": machine_version(machine["id"])})
    return base


# ─── Tier 3: Lifecycle shortcuts ──────────────────────────────────────────

def setup_dispatched_route_with_draft_visit(
    *, refill_units: int = 10, clock: str = DEFAULT_CLOCK, slot_overrides=None,
    service_date=None,
):
    """Dispatched route with a DRAFT (not yet reconciled) visit on a stocked
    machine state. Returns dict adding: stop, visit (DRAFT), machine_version
    (the version captured before any reconcile)."""
    base = setup_host_machine_slot(
        clock=clock, slot_overrides=slot_overrides, service_date=service_date,
    )
    machine, slot, route, driver = base["machine"], base["slot"], base["route"], base["driver"]
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, refill_units)], v0, driver["id"])
    base.update({"stop": stop, "visit": visit, "machine_version": v0})
    return base


def setup_reconciled_then_voidable_sale(
    *, refill_units: int = 10, quantity: int = 1, payment_method: str = "CASHLESS",
    clock: str = DEFAULT_CLOCK, slot_overrides=None, machine_overrides=None,
):
    """Stocked slot then one SETTLED sale (not voided). Returns dict adding:
    stop, visit, sale."""
    base = setup_stocked_slot(
        refill_units=refill_units, clock=clock, slot_overrides=slot_overrides,
        machine_overrides=machine_overrides,
    )
    sale = make_sale(base["machine"]["id"], base["slot"]["id"], quantity, payment_method)
    base["sale"] = sale
    return base


def setup_frozen_machine_with_stock(
    *, refill_units: int = 10, issue_type: str = "COIN_MECH", clock: str = DEFAULT_CLOCK,
):
    """Stocked machine then a blocking ticket that FROZEN-locks it. Returns dict
    adding: ticket."""
    base = setup_stocked_slot(refill_units=refill_units, clock=clock)
    ticket = make_ticket(base["machine"]["id"], issue_type=issue_type, blocking=True)
    base["ticket"] = ticket
    return base


# ─── Tier 4: Commission / statement scenarios ─────────────────────────────

def setup_statement_after_sales(
    *, host_overrides=None, slot_price_cents: int = 150, refill_units: int = 50,
    sale_quantities=(10,), clock: str = "2026-06-15T00:00:00Z",
    period_start: str = "2026-06-01T00:00:00Z", period_end: str = "2026-07-01T00:00:00Z",
    close_route: bool = False,
):
    """Host + stocked machine + N SETTLED cashless sales + an OPEN statement.

    Returns dict with: host, product, machine, slot, driver, route, stop, visit,
    sales (list), statement.
    """
    base = setup_stocked_slot(
        refill_units=refill_units, clock=clock,
        host_overrides=host_overrides,
        slot_overrides={"capacity": max(refill_units, sum(sale_quantities)), "par_level": max(refill_units, sum(sale_quantities)), "price_cents": slot_price_cents},
        product_overrides={"sku": "STMT-PROD"},
    )
    if close_route:
        get_success_data(api_client.close_route(base["route"]["id"], FIELD_OPS))
    sales = []
    for q in sale_quantities:
        sales.append(make_sale(base["machine"]["id"], base["slot"]["id"], q, "CASHLESS"))
    statement = make_statement(base["host"]["id"], period_start, period_end)
    base.update({"sales": sales, "statement": statement})
    return base
