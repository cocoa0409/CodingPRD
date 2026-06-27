"""Composite setup helpers for multi-step test prerequisites.

Most testable claims require the system to be in a specific state reached by a
chain of API calls (seed catalog/store/customer -> stock a row -> build/place an
order -> ready/fulfill). These helpers encapsulate those chains so each test can
focus on its assertion.

All helpers use get_success_data() (the lenient validator) for setup steps so a
broken precondition surfaces as a clear "Setup failed" rather than an obscure
assertion error. Every helper builds its preconditions from scratch: the test
harness restarts the server (empty DB) before each test.

Identity threading: the Customer role is entity-backed. Any ownership-gated call
(order create/place/cancel, price-match submit on own order, team-order
create/submit) is issued with make_customer_headers(customer_id) carrying the
real Customer.id, never the shared TEST_USERS["customer_headers"] fallback.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from .factories import (
    create_store_payload,
    create_sku_payload,
    create_customer_payload,
    create_store_inventory_payload,
    receive_payload,
    create_order_payload,
    create_order_line_payload,
    fulfill_payload,
    create_service_ticket_payload,
    create_fishing_license_payload,
    create_markdown_payload,
    create_price_match_claim_payload,
    create_team_order_payload,
    create_team_order_line_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
TECH = TEST_USERS["service_tech_headers"]
PRICE_ADMIN = TEST_USERS["price_admin_headers"]

# Monotonic counter so that helpers requesting their own customer get a unique
# email within a single test (the harness gives each test a fresh DB, but a
# single test may create several customers).
_email_counter = itertools.count(1)


def unique_email(prefix="cust"):
    return f"{prefix}{next(_email_counter)}@example.com"


# ---------------------------------------------------------------------------
# Tier 0: Primitive seed helpers
# ---------------------------------------------------------------------------
def create_store(name="Test Store", state_code="CA", **overrides):
    res = api_client.create_store(
        create_store_payload(name=name, state_code=state_code, **overrides), ADMIN
    )
    return get_success_data(res)


def create_sku(sport="BASEBALL", name="Test SKU", base_price_cents=5000,
               size_label="M", **overrides):
    payload = create_sku_payload(
        sport=sport, name=name, base_price_cents=base_price_cents,
        size_label=size_label, **overrides,
    )
    res = api_client.create_sku(payload, ADMIN)
    return get_success_data(res)


def create_customer(email=None, full_name="Test Customer", home_state_code="CA", **overrides):
    if email is None:
        email = unique_email()
    res = api_client.create_customer(
        create_customer_payload(
            email=email, full_name=full_name, home_state_code=home_state_code, **overrides
        ),
        ADMIN,
    )
    return get_success_data(res)


def create_inventory_row(store_id, sku_id):
    res = api_client.create_store_inventory(
        create_store_inventory_payload(store_id, sku_id), ADMIN
    )
    return get_success_data(res)


def stock_sku(store_id, sku_id, quantity):
    """Create a stock row and receive `quantity` units into it. Returns the row."""
    row = create_inventory_row(store_id, sku_id)
    if quantity > 0:
        res = api_client.receive_store_inventory(
            row["id"], receive_payload(quantity, row["version"]), ADMIN
        )
        row = get_success_data(res)
    return row


def get_inventory(inventory_id):
    return get_success_data(api_client.get_store_inventory(inventory_id, ADMIN))


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, ADMIN))


def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def get_service_ticket(ticket_id):
    return get_success_data(api_client.get_service_ticket(ticket_id, TECH))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: Single-SKU base scenario (store + sku + customer + stocked row)
# ---------------------------------------------------------------------------
def setup_base_scenario(sport="BASEBALL", base_price_cents=5000, size_label="M",
                        quantity=5, state_code="CA", home_state_code="CA",
                        sku_overrides=None):
    """Store + SKU (stocked qty) + customer. Returns dict of the entities.

    Keys: store, sku, customer, inventory, cust_headers.
    """
    store = create_store(state_code=state_code)
    sku = create_sku(
        sport=sport, base_price_cents=base_price_cents, size_label=size_label,
        **(sku_overrides or {}),
    )
    customer = create_customer(home_state_code=home_state_code)
    inventory = stock_sku(store["id"], sku["id"], quantity)
    return {
        "store": store,
        "sku": sku,
        "customer": customer,
        "inventory": inventory,
        "cust_headers": make_customer_headers(customer["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 2: Order builders
# ---------------------------------------------------------------------------
def create_draft_order(customer_id, store_id, fulfillment_type="BOPIS"):
    headers = make_customer_headers(customer_id)
    res = api_client.create_order(
        create_order_payload(customer_id, store_id, fulfillment_type), headers
    )
    return get_success_data(res)


def add_order_line(order_id, customer_id, sku_id, quantity=1, embroidery_text=None):
    headers = make_customer_headers(customer_id)
    extra = {}
    if embroidery_text is not None:
        extra["embroidery_text"] = embroidery_text
    res = api_client.create_order_line(
        order_id, create_order_line_payload(sku_id, quantity, **extra), headers
    )
    return get_success_data(res)


def place_order(order_id, customer_id):
    headers = make_customer_headers(customer_id)
    return get_success_data(api_client.place_order(order_id, headers))


def ready_order(order_id):
    return get_success_data(api_client.ready_order(order_id, ASSOCIATE))


def fulfill_order(order_id):
    """Re-read order version then fulfill (OCC-guarded). Returns fulfilled order."""
    current = get_order(order_id)
    res = api_client.fulfill_order(
        order_id, fulfill_payload(current["version"]), ASSOCIATE
    )
    return get_success_data(res)


def build_order_with_lines(customer_id, store_id, lines, fulfillment_type="BOPIS"):
    """Create a DRAFT order and add lines.

    `lines` is a list of dicts each like {"sku_id", "quantity", "embroidery_text"?}.
    Returns (order, [order_lines]).
    """
    order = create_draft_order(customer_id, store_id, fulfillment_type)
    created_lines = []
    for ln in lines:
        created_lines.append(
            add_order_line(
                order["id"], customer_id, ln["sku_id"],
                ln.get("quantity", 1), ln.get("embroidery_text"),
            )
        )
    return order, created_lines


def setup_placed_order(customer_id, store_id, lines, fulfillment_type="BOPIS"):
    """DRAFT order -> add lines -> place. Returns (placed_order, [order_lines])."""
    order, created_lines = build_order_with_lines(
        customer_id, store_id, lines, fulfillment_type
    )
    placed = place_order(order["id"], customer_id)
    return placed, created_lines


def setup_ready_order(customer_id, store_id, lines, fulfillment_type="BOPIS"):
    """DRAFT -> lines -> place -> ready. Returns (ready_order, [order_lines])."""
    placed, created_lines = setup_placed_order(
        customer_id, store_id, lines, fulfillment_type
    )
    ready = ready_order(placed["id"])
    return ready, created_lines


def setup_fulfilled_order(customer_id, store_id, lines, fulfillment_type="BOPIS"):
    """DRAFT -> lines -> place -> ready -> fulfill. Returns (fulfilled_order, [lines])."""
    ready, created_lines = setup_ready_order(
        customer_id, store_id, lines, fulfillment_type
    )
    fulfilled = fulfill_order(ready["id"])
    return fulfilled, created_lines


# ---------------------------------------------------------------------------
# Tier 3: Loyalty-tier raising (accumulate points via a prior fulfilled order)
# ---------------------------------------------------------------------------
def raise_customer_to_silver(store):
    """Create a customer who reaches SILVER (>=500 points) via one fulfilled order.

    A single base-50000 SKU line fulfilled accrues floor(50000/100) == 500 points.
    Returns (customer, headers). The store is reused; a dedicated SKU is created
    and stocked so this does not disturb the caller's inventory.
    """
    customer = create_customer(home_state_code=store["state_code"])
    sku = create_sku(sport="APPAREL", base_price_cents=50000, size_label="L",
                     name="Tier Raiser Coat")
    stock_sku(store["id"], sku["id"], 3)
    setup_fulfilled_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    refreshed = get_customer(customer["id"])
    return refreshed, make_customer_headers(customer["id"])


# ---------------------------------------------------------------------------
# Tier 4: Price-match claim setup
# ---------------------------------------------------------------------------
def submit_price_match_claim(order_id, order_line_id, customer_id, competitor_price_cents):
    headers = make_customer_headers(customer_id)
    res = api_client.create_price_match_claim(
        create_price_match_claim_payload(order_id, order_line_id, competitor_price_cents),
        headers,
    )
    return get_success_data(res)


def approve_price_match_claim(claim_id):
    return get_success_data(api_client.approve_price_match_claim(claim_id, PRICE_ADMIN))


# ---------------------------------------------------------------------------
# Tier 5: Service-ticket setup
# ---------------------------------------------------------------------------
def create_service_ticket(customer_id, store_id, service_type, part_sku_id=None):
    extra = {}
    if part_sku_id is not None:
        extra["part_sku_id"] = part_sku_id
    res = api_client.create_service_ticket(
        create_service_ticket_payload(customer_id, store_id, service_type, **extra),
        TECH,
    )
    return get_success_data(res)


def start_service_ticket(ticket_id):
    return get_success_data(api_client.start_service_ticket(ticket_id, TECH))


def setup_started_service_ticket(customer_id, store_id, service_type, part_sku_id=None):
    """Open a ticket and start it (IN_PROGRESS). Returns the started ticket."""
    ticket = create_service_ticket(customer_id, store_id, service_type, part_sku_id)
    return start_service_ticket(ticket["id"])


# ---------------------------------------------------------------------------
# Tier 6: Fishing-license setup
# ---------------------------------------------------------------------------
def issue_fishing_license(customer_id, issuing_store_id):
    res = api_client.create_fishing_license(
        create_fishing_license_payload(customer_id, issuing_store_id), ASSOCIATE
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 7: Markdown setup
# ---------------------------------------------------------------------------
def create_markdown(sku_id, markdown_kind, percent_off, effective_from, effective_until):
    res = api_client.create_markdown(
        create_markdown_payload(
            sku_id, markdown_kind, percent_off, effective_from, effective_until
        ),
        PRICE_ADMIN,
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 8: Team-order setup
# ---------------------------------------------------------------------------
def create_team_order(customer_id, store_id, team_name="Eagles"):
    headers = make_customer_headers(customer_id)
    res = api_client.create_team_order(
        create_team_order_payload(customer_id, store_id, team_name), headers
    )
    return get_success_data(res)


def add_team_order_line(team_order_id, customer_id, sku_id, quantity=1, embroidery_text=None):
    headers = make_customer_headers(customer_id)
    extra = {}
    if embroidery_text is not None:
        extra["embroidery_text"] = embroidery_text
    res = api_client.create_team_order_line(
        team_order_id, create_team_order_line_payload(sku_id, quantity, **extra), headers
    )
    return get_success_data(res)


def submit_team_order(team_order_id, customer_id):
    headers = make_customer_headers(customer_id)
    return get_success_data(api_client.submit_team_order(team_order_id, headers))


def setup_submitted_team_order(customer_id, store_id, lines, team_name="Eagles"):
    """Create team order -> add lines -> submit. Returns (submitted_team_order, [lines]).

    `lines` is a list of dicts like {"sku_id", "quantity", "embroidery_text"?}.
    """
    team_order = create_team_order(customer_id, store_id, team_name)
    created = []
    for ln in lines:
        created.append(
            add_team_order_line(
                team_order["id"], customer_id, ln["sku_id"],
                ln.get("quantity", 1), ln.get("embroidery_text"),
            )
        )
    submitted = submit_team_order(team_order["id"], customer_id)
    return submitted, created


def approve_team_order(team_order_id):
    return get_success_data(api_client.approve_team_order(team_order_id, ASSOCIATE))
