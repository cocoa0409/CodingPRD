"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"setup failed" errors, not confusing assertion failures. Every helper builds its
preconditions from scratch (the harness resets the database before each test).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_class_session_payload,
    create_customer_payload,
    create_enrollment_payload,
    create_inventory_item_payload,
    create_product_payload,
    create_repair_ticket_payload,
    create_rental_payload,
    create_sales_order_payload,
    create_special_order_payload,
    create_subscription_payload,
)
from .test_users import TEST_USERS

SA = TEST_USERS["sales_associate_headers"]
ST = TEST_USERS["service_tech_headers"]
SM = TEST_USERS["store_manager_headers"]


# ─────────────────────────────── clock ────────────────────────────────
def set_clock(iso: str):
    """Set the logical clock to an explicit instant (PRD §2.5)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, SM))


# ─────────────────────────── single-entity builders ───────────────────
def new_customer(full_name="Test Customer", email="cust@example.com", credit=0):
    """Register a customer, optionally seeding store credit via a manager adjustment."""
    cust = get_success_data(
        api_client.create_customer(create_customer_payload(full_name=full_name, email=email), SA)
    )
    if credit:
        cust = get_success_data(
            api_client.adjust_store_credit(
                cust["id"], {"amount_cents": credit, "reason": "seed"}, SM
            )
        )
    return cust


def new_product(**overrides):
    """Create a catalog product as StoreManager."""
    return get_success_data(api_client.create_product(create_product_payload(**overrides), SM))


def recall_product(product_id, reason="Safety recall"):
    return get_success_data(
        api_client.recall_product(product_id, {"recall_reason": reason}, SM)
    )


def new_inventory_item(product_id, **overrides):
    """Intake a physical unit as StoreManager (enters IN_STOCK)."""
    return get_success_data(
        api_client.create_inventory_item(create_inventory_item_payload(product_id, **overrides), SM)
    )


def open_sales_order(customer_id, inventory_item_id, **overrides):
    """Open a RESERVED sales order (reserves the unit)."""
    return get_success_data(
        api_client.create_sales_order(
            create_sales_order_payload(customer_id, inventory_item_id, **overrides), SA
        )
    )


def complete_sale(order_id, **payload):
    return get_success_data(api_client.complete_sales_order(order_id, dict(payload), SA))


def new_class_session(**overrides):
    return get_success_data(
        api_client.create_class_session(create_class_session_payload(**overrides), SM)
    )


def enroll(session_id, customer_id):
    return get_success_data(
        api_client.create_enrollment(session_id, create_enrollment_payload(customer_id), SA)
    )


def new_subscription(customer_id, **overrides):
    return get_success_data(
        api_client.create_subscription(create_subscription_payload(customer_id, **overrides), SA)
    )


def new_special_order(customer_id, product_id, **overrides):
    return get_success_data(
        api_client.create_special_order(
            create_special_order_payload(customer_id, product_id, **overrides), SA
        )
    )


def new_rental(customer_id, inventory_item_id, **overrides):
    return get_success_data(
        api_client.create_rental(
            create_rental_payload(customer_id, inventory_item_id, **overrides), SA
        )
    )


# ─────────────────────── composite scenario builders ──────────────────
def setup_customer_product_item(
    credit=0,
    product_overrides=None,
    item_overrides=None,
    customer_name="Scenario Customer",
    customer_email="scenario@example.com",
):
    """Create one customer, one product, and one IN_STOCK inventory item of it.

    Returns (customer, product, item).
    """
    cust = new_customer(customer_name, customer_email, credit=credit)
    prod = new_product(**(product_overrides or {}))
    item = new_inventory_item(prod["id"], **(item_overrides or {}))
    return cust, prod, item


def setup_reserved_sales_order(
    credit=0,
    sale_price_cents=100000,
    trade_in_model=None,
    trade_in_condition=None,
    product_overrides=None,
    item_overrides=None,
    customer_name="SO Customer",
    customer_email="so@example.com",
):
    """Customer + product + IN_STOCK item + a RESERVED SalesOrder on that item.

    Returns (customer, product, item, sales_order).
    """
    cust, prod, item = setup_customer_product_item(
        credit=credit,
        product_overrides=product_overrides,
        item_overrides=item_overrides,
        customer_name=customer_name,
        customer_email=customer_email,
    )
    so_overrides = {"sale_price_cents": sale_price_cents}
    if trade_in_model is not None:
        so_overrides["trade_in_model"] = trade_in_model
    if trade_in_condition is not None:
        so_overrides["trade_in_condition"] = trade_in_condition
    so = open_sales_order(cust["id"], item["id"], **so_overrides)
    return cust, prod, item, so


def setup_repair_in_repair(
    is_warranty=False,
    labor_hours=2.5,
    part_prices=(3000, 4500),
    machine_category="SEWING_MACHINE",
    customer_name="Repair Customer",
    customer_email="repair@example.com",
):
    """A RepairTicket walked to IN_REPAIR with `part_prices` consumed onto it.

    Steps: customer + machine product + PART product + one PART unit per price +
    open ticket + quote(labor_hours) + approve + consume each part.
    Returns (customer, machine_product, ticket, part_item_ids).
    """
    cust = new_customer(customer_name, customer_email)
    machine = new_product(model_name="Repair Machine", category=machine_category, brand="Acme")
    part_ids = []
    if part_prices:
        part_prod = new_product(model_name="Repair Part", category="PART", brand="Acme")
        for idx, price in enumerate(part_prices):
            part = new_inventory_item(
                part_prod["id"],
                serial_number=None,
                acquisition_cost_cents=max(0, price // 3),
                list_price_cents=price,
            )
            part_ids.append(part["id"])

    ticket = get_success_data(
        api_client.create_repair_ticket(
            create_repair_ticket_payload(cust["id"], machine["id"], is_warranty=is_warranty), ST
        )
    )
    get_success_data(
        api_client.quote_repair_ticket(
            ticket["id"], {"diagnosis": "Diagnosed", "labor_hours": labor_hours}, ST
        )
    )
    get_success_data(api_client.approve_repair_ticket(ticket["id"], SA))
    for part_id in part_ids:
        get_success_data(
            api_client.consume_part(ticket["id"], {"inventory_item_id": part_id}, ST)
        )
    return cust, machine, ticket, part_ids


def setup_quoted_repair(
    labor_hours=1.0,
    machine_category="VACUUM",
    customer_name="Quote Customer",
    customer_email="quote@example.com",
):
    """A RepairTicket in AWAITING_APPROVAL after a single quote.

    Returns (customer, machine_product, ticket).
    """
    cust = new_customer(customer_name, customer_email)
    machine = new_product(model_name="Quote Machine", category=machine_category, brand="Acme")
    ticket = get_success_data(
        api_client.create_repair_ticket(
            create_repair_ticket_payload(cust["id"], machine["id"]), ST
        )
    )
    get_success_data(
        api_client.quote_repair_ticket(
            ticket["id"], {"diagnosis": "First diagnosis", "labor_hours": labor_hours}, ST
        )
    )
    return cust, machine, ticket


def setup_active_subscription_with_period(
    period_start="2026-07-01T00:00:00Z",
    monthly_fee_cents=3100,
    plan_tier="BASIC",
    tune_ups_included=2,
    customer_name="Sub Customer",
    customer_email="sub@example.com",
):
    """Set the clock to `period_start`, then create an ACTIVE subscription so its
    period runs from that instant. Returns (customer, subscription).
    """
    set_clock(period_start)
    cust = new_customer(customer_name, customer_email)
    sub = new_subscription(
        cust["id"],
        plan_tier=plan_tier,
        monthly_fee_cents=monthly_fee_cents,
        tune_ups_included=tune_ups_included,
    )
    return cust, sub


def setup_special_order(
    quantity=2,
    unit_price_cents=80000,
    deposit_cents=20000,
    customer_name="Special Customer",
    customer_email="special@example.com",
):
    """A REQUESTED SpecialOrder (version 1). Returns (customer, product, order)."""
    cust = new_customer(customer_name, customer_email)
    prod = new_product(model_name="Special Model", category="SEWING_MACHINE", brand="Acme")
    order = new_special_order(
        cust["id"], prod["id"],
        quantity=quantity, unit_price_cents=unit_price_cents, deposit_cents=deposit_cents,
    )
    return cust, prod, order
