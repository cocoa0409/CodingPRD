"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the server is relaunched before each test, so each test starts empty) and uses
get_success_data() so a setup failure surfaces as a clear "Setup failed" error
rather than a confusing assertion failure deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_PRICING, DEFAULT_SERVER_CLOCK
from .factories import (
    create_customer_payload,
    create_delivery_zone_payload,
    create_invoice_payload,
    create_payment_payload,
    create_pricing_config_payload,
    create_route_payload,
    create_stop_payload,
    create_work_order_payload,
    create_cooler_rental_payload,
    create_deliver_payload,
    create_skip_payload,
)
from .test_users import TEST_USERS, make_customer_self_headers

OPS_ADMIN = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]
BILLING_ADMIN = TEST_USERS["billing_admin_headers"]

MAY_PERIOD = ("2026-05-01", "2026-06-01")
JUNE_PERIOD = ("2026-06-01", "2026-07-01")


def _setup_failed(step: str, res):
    raise AssertionError(
        f"Setup failed at step '{step}': HTTP {res.status_code} — {res.text}"
    )


def _ok(res, step: str):
    data = get_success_data(res)
    if res.status_code >= 400:
        _setup_failed(step, res)
    return data


# ─── Tier 0: world bootstrap ──────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.4)."""
    return _ok(api_client.set_clock({"to_iso8601": to_iso8601}, OPS_ADMIN), "set_clock")


def create_standard_pricing_config(**overrides) -> dict:
    """Create the standard pricing configuration (PRD §3.1)."""
    return _ok(
        api_client.create_pricing_config(create_pricing_config_payload(**overrides), OPS_ADMIN),
        "create_pricing_config",
    )


def setup_zone(code: str = "NW-1", name: str = "Northwest 1", with_pricing: bool = True,
               clock: str = DEFAULT_SERVER_CLOCK, pricing_overrides: dict | None = None) -> dict:
    """Set the logical clock, create the standard pricing config, and one zone."""
    set_clock(clock)
    if with_pricing:
        create_standard_pricing_config(**(pricing_overrides or {}))
    return _ok(
        api_client.create_delivery_zone(create_delivery_zone_payload(code=code, name=name), OPS_ADMIN),
        "create_delivery_zone",
    )


def setup_customer(zone: dict | None = None, with_pricing: bool = True, **customer_overrides) -> dict:
    """Zone (+ pricing config) plus one customer. Returns {"zone", "customer"}."""
    if zone is None:
        zone = setup_zone(with_pricing=with_pricing)
    payload = create_customer_payload(zone["id"], **customer_overrides)
    customer = _ok(api_client.create_customer(payload, OPS_ADMIN), "create_customer")
    return {"zone": zone, "customer": customer}


# ─── Tier 1: routes / stops / state progression ───────

def create_route(zone_id: str, service_date: str, truck_capacity_bottles: int = 50,
                 driver_name: str = "Dave") -> dict:
    return _ok(
        api_client.create_route(
            create_route_payload(zone_id, service_date,
                                 truck_capacity_bottles=truck_capacity_bottles,
                                 driver_name=driver_name),
            DISPATCHER,
        ),
        "create_route",
    )


def plan_stop(route_id: str, customer_id: str, sequence_index: int = 1) -> dict:
    """Manually plan a stop for an AUTO customer (PRD §3.3)."""
    return _ok(
        api_client.create_stop(
            route_id, create_stop_payload(customer_id, sequence_index), DISPATCHER
        ),
        "plan_stop",
    )


def publish_route(route_id: str) -> dict:
    return _ok(api_client.publish_route(route_id, DISPATCHER), "publish_route")


def start_route(route_id: str, at_iso: str) -> dict:
    """Advance the logical clock onto the service date and start the route."""
    set_clock(at_iso)
    return _ok(api_client.start_route(route_id, DRIVER), "start_route")


def arrive_stop(stop_id: str) -> dict:
    return _ok(api_client.arrive_stop(stop_id, DRIVER), "arrive_stop")


def current_route_version(route_id: str) -> int:
    route = _ok(api_client.get_route(route_id, DRIVER), "get_route")
    return route["version"]


def get_route(route_id: str) -> dict:
    return _ok(api_client.get_route(route_id, DISPATCHER), "get_route")


def get_stop(stop_id: str) -> dict:
    return _ok(api_client.get_stop(stop_id, DISPATCHER), "get_stop")


def get_customer(customer_id: str) -> dict:
    return _ok(api_client.get_customer(customer_id, OPS_ADMIN), "get_customer")


def get_invoice(invoice_id: str) -> dict:
    return _ok(api_client.get_invoice(invoice_id, BILLING_ADMIN), "get_invoice")


def get_work_order(order_id: str) -> dict:
    return _ok(api_client.get_work_order(order_id, DISPATCHER), "get_work_order")


def get_cooler_rental(rental_id: str) -> dict:
    return _ok(api_client.get_cooler_rental(rental_id, OPS_ADMIN), "get_cooler_rental")


def deliver_arrived_stop(stop_id: str, route_id: str, actual_bottles_delivered: int,
                         actual_empties_collected: int) -> dict:
    """Record a delivery against an ARRIVED stop (OCC via expected_route_version)."""
    version = current_route_version(route_id)
    res = api_client.deliver_stop(
        stop_id,
        create_deliver_payload(version, actual_bottles_delivered, actual_empties_collected),
        DRIVER,
    )
    return _ok(res, "deliver_stop")


def arrive_and_deliver(stop_id: str, route_id: str, actual_bottles_delivered: int,
                       actual_empties_collected: int) -> dict:
    arrive_stop(stop_id)
    return deliver_arrived_stop(stop_id, route_id, actual_bottles_delivered,
                                actual_empties_collected)


# ─── Tier 2: full delivery chain via work order ───────

def deliver_via_work_order(customer_id: str, zone_id: str, requested_date: str,
                           quantity_bottles: int,
                           actual_bottles_delivered: int | None = None,
                           actual_empties_collected: int | None = None,
                           at_iso: str | None = None,
                           truck_capacity_bottles: int = 50) -> dict:
    """Work order (DELIVERY) -> route on requested_date -> schedule -> publish ->
    start -> arrive -> deliver. Defaults to a clean exchange (actuals == plan).

    Returns {"work_order", "route", "stop", "delivered_stop"}.
    """
    if actual_bottles_delivered is None:
        actual_bottles_delivered = quantity_bottles
    if actual_empties_collected is None:
        actual_empties_collected = quantity_bottles
    if at_iso is None:
        at_iso = f"{requested_date}T08:00:00Z"

    work_order = _ok(
        api_client.create_work_order(
            create_work_order_payload(customer_id, "DELIVERY", requested_date, quantity_bottles),
            DISPATCHER,
        ),
        "create_work_order",
    )
    route = create_route(zone_id, requested_date, truck_capacity_bottles=truck_capacity_bottles)
    scheduled = _ok(api_client.schedule_work_order(work_order["id"], DISPATCHER),
                    "schedule_work_order")
    stop_id = scheduled["linked_stop_id"]
    publish_route(route["id"])
    start_route(route["id"], at_iso)
    delivered = arrive_and_deliver(stop_id, route["id"],
                                   actual_bottles_delivered, actual_empties_collected)
    return {
        "work_order": scheduled,
        "route": route,
        "stop": get_stop(stop_id),
        "delivered_stop": delivered,
    }


# ─── Tier 3: invoices / payments ──────────────────────

def create_draft_invoice(customer_id: str, period_start: str, period_end: str,
                         due_date: str = "2026-07-15") -> dict:
    return _ok(
        api_client.create_invoice(
            create_invoice_payload(customer_id, period_start, period_end, due_date),
            BILLING_ADMIN,
        ),
        "create_invoice",
    )


def issue_invoice(invoice_id: str) -> dict:
    return _ok(api_client.issue_invoice(invoice_id, BILLING_ADMIN), "issue_invoice")


def create_and_issue_invoice(customer_id: str, period_start: str, period_end: str,
                             due_date: str = "2026-07-15") -> dict:
    invoice = create_draft_invoice(customer_id, period_start, period_end, due_date)
    return issue_invoice(invoice["id"])


def pay_invoice(invoice_id: str, amount_cents: int, method: str = "CARD") -> dict:
    """Create a payment and apply it. Returns the applied payment."""
    payment = _ok(
        api_client.create_payment(create_payment_payload(invoice_id, amount_cents, method=method),
                                  BILLING_ADMIN),
        "create_payment",
    )
    return _ok(api_client.apply_payment(payment["id"], BILLING_ADMIN), "apply_payment")


def setup_open_invoice(bottles: int = 1, requested_date: str = "2026-05-10",
                       period=MAY_PERIOD, due_date: str = "2026-06-15",
                       pricing_tier: str = "STANDARD", account_type: str = "OFFICE") -> dict:
    """Full chain: zone + WILL_CALL customer + delivery + issued invoice.

    A clean exchange (actuals == plan) keeps the invoice total at
    bottles * rate with no shortage charge. Returns
    {"zone", "customer", "route", "stop", "invoice"}.
    """
    world = setup_customer(
        account_type=account_type, service_mode="WILL_CALL", par_level_bottles=0,
        pricing_tier=pricing_tier,
    )
    zone, customer = world["zone"], world["customer"]
    delivery = deliver_via_work_order(customer["id"], zone["id"], requested_date, bottles)
    invoice = create_and_issue_invoice(customer["id"], period[0], period[1], due_date)
    return {
        "zone": zone,
        "customer": customer,
        "route": delivery["route"],
        "stop": delivery["stop"],
        "invoice": invoice,
    }


# ─── Tier 4: suspended customers / cooler rentals ─────

def setup_suspended_customer(delivery_date: str = "2026-05-05") -> dict:
    """Customer with an unpaid issued invoice (positive outstanding balance),
    then suspended. Returns {"zone", "customer", "invoice", "route", "stop"}."""
    scenario = setup_open_invoice(bottles=1, requested_date=delivery_date)
    customer_id = scenario["customer"]["id"]
    suspended = _ok(api_client.suspend_customer(customer_id, OPS_ADMIN), "suspend_customer")
    scenario["customer"] = suspended
    return scenario


def setup_cooler_rental(customer_id: str, monthly_rent_cents: int = 9000,
                        deposit_cents: int = 30000,
                        cooler_model: str = "FREESTANDING") -> dict:
    """Create a cooler rental and schedule its linked COOLER_INSTALL work order.
    Returns {"rental", "work_order"} with the work order SCHEDULED."""
    rental = _ok(
        api_client.create_cooler_rental(
            create_cooler_rental_payload(customer_id, monthly_rent_cents=monthly_rent_cents,
                                         deposit_cents=deposit_cents, cooler_model=cooler_model),
            OPS_ADMIN,
        ),
        "create_cooler_rental",
    )
    data, _meta = _ok_list(
        api_client.list_work_orders(DISPATCHER, params={"linked_rental_id": rental["id"]}),
        "list_work_orders",
    )
    if not data:
        raise AssertionError("Setup failed: no COOLER_INSTALL work order linked to rental")
    work_order = data[0]
    scheduled = _ok(api_client.schedule_work_order(work_order["id"], DISPATCHER),
                    "schedule_install_work_order")
    return {"rental": rental, "work_order": scheduled}


def _ok_list(res, step: str):
    data = get_success_data(res)
    if res.status_code >= 400:
        _setup_failed(step, res)
    if isinstance(data, dict) and "data" in data:
        return data["data"], data.get("meta", {})
    # get_success_data on a list envelope returns the list itself on some frameworks
    return data, {}


def install_rental(rental_id: str, at_iso: str) -> dict:
    """Advance the clock and mark the rental installed (driver)."""
    set_clock(at_iso)
    return _ok(api_client.install_cooler_rental(rental_id, DRIVER), "install_cooler_rental")


def setup_installed_rental(install_iso: str, monthly_rent_cents: int = 9000,
                           deposit_cents: int = 30000,
                           cooler_model: str = "FREESTANDING") -> dict:
    """Zone + WILL_CALL customer + cooler rental installed at install_iso.
    Returns {"zone", "customer", "rental", "work_order", "installed"}."""
    world = setup_customer(service_mode="WILL_CALL", par_level_bottles=0)
    customer = world["customer"]
    parts = setup_cooler_rental(customer["id"], monthly_rent_cents=monthly_rent_cents,
                                deposit_cents=deposit_cents, cooler_model=cooler_model)
    installed = install_rental(parts["rental"]["id"], install_iso)
    return {
        "zone": world["zone"],
        "customer": customer,
        "rental": parts["rental"],
        "work_order": parts["work_order"],
        "installed": installed,
    }


# ─── Tier 5: skip credits ─────────────────────────────

def setup_skip_credit(notified_before_cutoff: bool = True,
                      skip_clock: str = "2026-05-01T00:00:00Z") -> dict:
    """AUTO customer (par 2) + route on 2026-05-01 + planned stop, then skip it.
    A skip from PLANNED creates a SkipCredit for the customer (PRD §3.5).
    Returns {"zone", "customer", "route", "stop", "skip_credit"}."""
    world = setup_customer(account_type="OFFICE", service_mode="AUTO", par_level_bottles=2)
    zone, customer = world["zone"], world["customer"]
    route = create_route(zone["id"], "2026-05-01")
    stop = plan_stop(route["id"], customer["id"], sequence_index=1)
    _ok(
        api_client.skip_stop(
            stop["id"],
            create_skip_payload(skip_reason="customer not available",
                                notified_before_cutoff=notified_before_cutoff),
            DRIVER,
        ),
        "skip_stop",
    )
    data, _meta = _ok_list(api_client.list_customer_skip_credits(customer["id"], OPS_ADMIN),
                           "list_customer_skip_credits")
    if not data:
        raise AssertionError("Setup failed: skip did not create a SkipCredit")
    return {
        "zone": zone,
        "customer": customer,
        "route": route,
        "stop": get_stop(stop["id"]),
        "skip_credit": data[0],
    }


# ─── Convenience composites ───────────────────────────

def setup_two_customers(zone: dict | None = None, a_overrides: dict | None = None,
                        b_overrides: dict | None = None) -> dict:
    """Zone + two customers (A OFFICE, B HOME). Returns {"zone", "customer_a", "customer_b"}."""
    if zone is None:
        zone = setup_zone()
    a_payload = create_customer_payload(zone["id"], account_type="OFFICE",
                                        business_name="Customer A",
                                        billing_email="a@x.example")
    a_payload.update(a_overrides or {})
    b_payload = create_customer_payload(zone["id"], account_type="HOME",
                                        business_name="Customer B",
                                        billing_email="b@x.example")
    b_payload.update(b_overrides or {})
    a = _ok(api_client.create_customer(a_payload, OPS_ADMIN), "create_customer_a")
    b = _ok(api_client.create_customer(b_payload, OPS_ADMIN), "create_customer_b")
    return {"zone": zone, "customer_a": a, "customer_b": b}
