"""Composite setup helpers.

Every fixture below builds preconditions from scratch using only PRD-declared
endpoints — the test harness restarts the server before each test so no state
carries over.

Identity threading: after creating an entity_backed:Customer or
entity_backed:DeliveryDriver entity, all ownership-gated calls in this file use
make_<role>_headers(entity.id) — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers, make_delivery_driver_headers


# =============================================================================
# Base primitives
# =============================================================================

def set_clock(iso: str):
    resp = api_client.set_clock(iso, TEST_USERS["manager_headers"])
    get_success_data(resp)


def register_customer(email: str = "u@example.com", full_name: str = "U", delivery_zone: str = "ZONE_A",
                      address_line: str = "1 X") -> dict:
    resp = api_client.register_customer(
        {"email": email, "full_name": full_name, "delivery_zone": delivery_zone, "address_line": address_line},
        TEST_USERS["anonymous_headers"],
    )
    return get_success_data(resp)


def create_driver(name: str = "D", daily_capacity_minutes: int = None) -> dict:
    payload = {"name": name}
    if daily_capacity_minutes is not None:
        payload["daily_capacity_minutes"] = daily_capacity_minutes
    resp = api_client.create_delivery_driver(payload, TEST_USERS["manager_headers"])
    return get_success_data(resp)


def create_plant(
    name: str = "P",
    light_tag: str = "MEDIUM",
    care_tag: str = "EASY",
    weight_class: str = "LIGHT",
    unit_price_cents: int = 3000,
    warranty_days: int = 30,
) -> dict:
    resp = api_client.create_plant(
        {
            "name": name,
            "light_tag": light_tag,
            "care_tag": care_tag,
            "weight_class": weight_class,
            "unit_price_cents": unit_price_cents,
            "warranty_days": warranty_days,
        },
        TEST_USERS["manager_headers"],
    )
    return get_success_data(resp)


def intake_stock_unit(plant_id: str, acquisition_date: str = "2026-03-25T00:00:00Z") -> dict:
    resp = api_client.intake_stock_unit(
        plant_id, {"acquisition_date": acquisition_date}, TEST_USERS["shop_staff_headers"]
    )
    return get_success_data(resp)


def create_order(customer_id: str, plant_ids_qtys: list, delivery_zone: str = "ZONE_A",
                 gift_flag: bool = False, applied_redemption_cents: int = 0) -> dict:
    """plant_ids_qtys: list of (plant_id, qty) tuples."""
    payload = {
        "customer_id": customer_id,
        "delivery_zone": delivery_zone,
        "gift_flag": gift_flag,
        "applied_redemption_cents": applied_redemption_cents,
        "lines": [{"plant_id": p, "qty": q} for (p, q) in plant_ids_qtys],
    }
    resp = api_client.create_order(payload, make_customer_headers(customer_id))
    return get_success_data(resp)


def pay_order(order_id: str, customer_id: str) -> dict:
    resp = api_client.pay_order(order_id, make_customer_headers(customer_id))
    return get_success_data(resp)


def dispatch_order(order_id: str, driver_id: str, window_start_at: str, window_end_at: str) -> dict:
    resp = api_client.dispatch_order(
        order_id,
        {"driver_id": driver_id, "window_start_at": window_start_at, "window_end_at": window_end_at},
        TEST_USERS["shop_staff_headers"],
    )
    return get_success_data(resp)


def deliver(delivery_id: str, driver_id: str) -> dict:
    resp = api_client.deliver_delivery(delivery_id, make_delivery_driver_headers(driver_id))
    return get_success_data(resp)


def get_orderline_id_for_order(order_id: str, customer_id: str) -> str:
    """Return the first OrderLine.id for the given order via the reverse-reachability
    filtered-list endpoint."""
    resp = api_client.list_order_lines(
        make_customer_headers(customer_id), params={"order_id": order_id}
    )
    # /order-lines returns response_type=array; the array lives at $.data
    data = get_success_data(resp)
    if isinstance(data, list):
        return data[0]["id"]
    # tolerate a nested envelope form: {"data": [...]}
    inner = data.get("data") if isinstance(data, dict) else None
    if isinstance(inner, list):
        return inner[0]["id"]
    # last resort: assume it's an object with an id
    return data["id"]


def append_care_log(stock_unit_id: str, entry_type: str, note: str = "") -> dict:
    resp = api_client.append_care_log(
        stock_unit_id, {"entry_type": entry_type, "note": note}, TEST_USERS["horticulturist_headers"]
    )
    return get_success_data(resp)


# =============================================================================
# Tier 2: Entity hierarchy shortcuts
# =============================================================================

def setup_customer_driver_plant(
    email: str = "u@example.com",
    delivery_zone: str = "ZONE_A",
    plant_unit_price_cents: int = 3000,
    plant_weight_class: str = "LIGHT",
    plant_light_tag: str = "MEDIUM",
    plant_care_tag: str = "EASY",
    plant_warranty_days: int = 30,
    driver_capacity_minutes: int = None,
) -> tuple:
    """Register a customer + create a driver + create one plant with 1 stock unit.

    Returns (customer, driver, plant, stock_unit).
    """
    customer = register_customer(email=email, delivery_zone=delivery_zone)
    driver = create_driver(daily_capacity_minutes=driver_capacity_minutes)
    plant = create_plant(
        name="P",
        light_tag=plant_light_tag,
        care_tag=plant_care_tag,
        weight_class=plant_weight_class,
        unit_price_cents=plant_unit_price_cents,
        warranty_days=plant_warranty_days,
    )
    stock = intake_stock_unit(plant["id"])
    return customer, driver, plant, stock


# =============================================================================
# Tier 3: Full-lifecycle shortcuts
# =============================================================================

def create_and_deliver_order(
    customer_id: str,
    driver_id: str,
    plant_id: str,
    dispatch_window_start: str = "2026-04-02T09:00:00Z",
    dispatch_window_end: str = "2026-04-02T10:00:00Z",
    deliver_at_clock_iso: str = None,
    delivery_zone: str = "ZONE_A",
    qty: int = 1,
) -> tuple:
    """Create → pay → dispatch → (optionally advance clock) → deliver.

    Returns (order, delivery). The delivery is in DELIVERED state.
    """
    order = create_order(customer_id, [(plant_id, qty)], delivery_zone=delivery_zone)
    pay_order(order["id"], customer_id)
    delivery = dispatch_order(order["id"], driver_id, dispatch_window_start, dispatch_window_end)
    if deliver_at_clock_iso:
        set_clock(deliver_at_clock_iso)
    delivery = deliver(delivery["id"], driver_id)
    return order, delivery


def setup_delivered_orderline(
    email: str = "u@example.com",
    delivery_zone: str = "ZONE_A",
    plant_unit_price_cents: int = 5000,
    plant_warranty_days: int = 30,
    delivery_date_iso: str = "2026-04-05T10:00:00Z",
    dispatch_window_start: str = "2026-04-05T09:00:00Z",
    dispatch_window_end: str = "2026-04-05T11:00:00Z",
    initial_clock_iso: str = "2026-04-01T00:00:00Z",
) -> dict:
    """Complete flow through DELIVERED. Returns a dict:
    {customer, driver, plant, stock_unit, order, delivery, orderline_id}.
    """
    set_clock(initial_clock_iso)
    customer, driver, plant, stock = setup_customer_driver_plant(
        email=email,
        delivery_zone=delivery_zone,
        plant_unit_price_cents=plant_unit_price_cents,
        plant_warranty_days=plant_warranty_days,
    )
    order = create_order(customer["id"], [(plant["id"], 1)], delivery_zone=delivery_zone)
    pay_order(order["id"], customer["id"])
    delivery = dispatch_order(
        order["id"], driver["id"], dispatch_window_start, dispatch_window_end
    )
    set_clock(delivery_date_iso)
    delivery = deliver(delivery["id"], driver["id"])
    orderline_id = get_orderline_id_for_order(order["id"], customer["id"])
    return {
        "customer": customer,
        "driver": driver,
        "plant": plant,
        "stock_unit": stock,
        "order": order,
        "delivery": delivery,
        "orderline_id": orderline_id,
    }


# =============================================================================
# Tier 5: Terminal/scenario builders (special-order revision cycle)
# =============================================================================

def setup_special_order_at_revision_count(customer_id: str, revision_count: int) -> dict:
    """Drive a SpecialOrder through revision_count re-quote turnarounds.

    The revision cycle is: REQUESTED -quote-> QUOTED -re_quote-> RE_QUOTED
    (revision_count += 1) -quote-> QUOTED -re_quote-> RE_QUOTED (revision_count += 1) ...

    Returns the SpecialOrder in status=QUOTED (or REQUESTED if revision_count==0
    and no quote called).
    """
    resp = api_client.create_special_order(
        {"customer_id": customer_id, "service_type": "PROCUREMENT", "sku_description": "seed"},
        make_customer_headers(customer_id),
    )
    so = get_success_data(resp)
    if revision_count == 0:
        # Take the first quote so status becomes QUOTED with revision_count=0.
        resp = api_client.quote_special_order(
            so["id"], {"quoted_price_cents": 10000}, TEST_USERS["manager_headers"]
        )
        return get_success_data(resp)
    # First quote -> QUOTED (revision_count 0)
    resp = api_client.quote_special_order(
        so["id"], {"quoted_price_cents": 10000}, TEST_USERS["manager_headers"]
    )
    so = get_success_data(resp)
    for i in range(revision_count):
        resp = api_client.requote_special_order(
            so["id"], {"quoted_price_cents": 10000 + 1000 * (i + 1)}, TEST_USERS["manager_headers"]
        )
        so = get_success_data(resp)
        # After re-quote status = RE_QUOTED. Bring back to QUOTED unless this was the last cycle
        if i < revision_count - 1:
            resp = api_client.quote_special_order(
                so["id"], {"quoted_price_cents": 10000 + 1000 * (i + 1) + 100}, TEST_USERS["manager_headers"]
            )
            so = get_success_data(resp)
    return so
