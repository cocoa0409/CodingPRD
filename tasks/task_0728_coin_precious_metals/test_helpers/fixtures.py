"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: the Customer role is entity_backed. Any ownership-gated
Customer call (layaway deposit/cancel) uses make_customer_headers(customer_id)
with the real Customer.id — never the shared TEST_USERS["customer_headers"].
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_spot_rate_payload,
    create_product_payload,
    create_inventory_lot_payload,
    create_customer_payload,
    create_ira_account_payload,
    create_sell_order_payload,
    create_buy_order_payload,
    create_layaway_payload,
    deposit_payload,
    create_consignment_payload,
    list_consignment_payload,
    record_sale_payload,
    create_auction_session_payload,
)
from .test_users import TEST_USERS, make_customer_headers

TRADER = TEST_USERS["trader_headers"]
SALES = TEST_USERS["sales_agent_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Tier 1/2: Base building blocks ───────────────────────────────────

def set_spot_rate(metal="GOLD", price_per_troy_oz_cents=200_000):
    """Create the live spot rate for a metal. Returns the SpotRate dict."""
    res = api_client.create_spot_rate(
        create_spot_rate_payload(metal=metal, price_per_troy_oz_cents=price_per_troy_oz_cents),
        TRADER,
    )
    return get_success_data(res)


def create_product(**overrides):
    """Create a catalog product. Returns the Product dict."""
    res = api_client.create_product(create_product_payload(**overrides), TRADER)
    return get_success_data(res)


def create_inventory_lot(product_id, total_qty=5, acquisition_unit_cost_cents=100_000):
    """Record a physical inventory lot. Returns the InventoryLot dict."""
    res = api_client.create_inventory_lot(
        create_inventory_lot_payload(
            product_id, total_qty=total_qty,
            acquisition_unit_cost_cents=acquisition_unit_cost_cents,
        ),
        TRADER,
    )
    return get_success_data(res)


def create_customer(full_name="Test Customer", id_document_on_file=None, as_role=SALES):
    """Create a customer. Returns the Customer dict."""
    extra = {} if id_document_on_file is None else {"id_document_on_file": id_document_on_file}
    res = api_client.create_customer(create_customer_payload(full_name=full_name, **extra), as_role)
    return get_success_data(res)


def create_auction_session(room="ROOM-A", scheduled_start="2026-04-01T10:00:00Z",
                           scheduled_end="2026-04-01T12:00:00Z"):
    """Schedule a SCHEDULED auction session. Returns the AuctionSession dict."""
    res = api_client.create_auction_session(
        create_auction_session_payload(room=room, scheduled_start=scheduled_start,
                                        scheduled_end=scheduled_end),
        SALES,
    )
    return get_success_data(res)


def setup_spot_product_lot(spot=200_000, product_overrides=None, total_qty=5,
                           acquisition_unit_cost_cents=100_000, metal="GOLD"):
    """GOLD spot + one product + one lot. Returns (spot_rate, product, lot)."""
    spot_rate = set_spot_rate(metal=metal, price_per_troy_oz_cents=spot)
    product = create_product(**(product_overrides or {}))
    lot = create_inventory_lot(product["id"], total_qty=total_qty,
                               acquisition_unit_cost_cents=acquisition_unit_cost_cents)
    return spot_rate, product, lot


# ─── Sell orders ──────────────────────────────────────────────────────

def create_placed_sell_order(product_id, customer_id, quantity=1, ira_account_id=None):
    """Place a sell order (PLACED). Returns the SellOrder dict."""
    extra = {} if ira_account_id is None else {"ira_account_id": ira_account_id}
    res = api_client.create_sell_order(
        create_sell_order_payload(customer_id, product_id, quantity=quantity, **extra),
        SALES,
    )
    return get_success_data(res)


# ─── Buy orders ───────────────────────────────────────────────────────

def create_placed_buy_order(product_id, customer_id, quantity=1):
    """Place a buy order (PLACED). Returns the BuyOrder dict."""
    res = api_client.create_buy_order(
        create_buy_order_payload(customer_id, product_id, quantity=quantity),
        SALES,
    )
    return get_success_data(res)


# ─── Layaways ─────────────────────────────────────────────────────────

def create_active_layaway(product_id, inventory_lot_id, customer_id, quantity=1):
    """Open a layaway (ACTIVE, reserves inventory, locks price). Returns the Layaway dict."""
    res = api_client.create_layaway(
        create_layaway_payload(customer_id, product_id, inventory_lot_id, quantity=quantity),
        SALES,
    )
    return get_success_data(res)


def setup_layaway(spot=200_000, product_overrides=None, total_qty=5,
                  acquisition_unit_cost_cents=100_000, quantity=2,
                  customer_name="Layaway Holder", id_document_on_file=None):
    """Full chain to an ACTIVE layaway.

    Returns dict with keys: product, lot, customer, layaway.
    """
    _, product, lot = setup_spot_product_lot(
        spot=spot, product_overrides=product_overrides, total_qty=total_qty,
        acquisition_unit_cost_cents=acquisition_unit_cost_cents,
    )
    customer = create_customer(full_name=customer_name, id_document_on_file=id_document_on_file)
    layaway = create_active_layaway(product["id"], lot["id"], customer["id"], quantity=quantity)
    return {"product": product, "lot": lot, "customer": customer, "layaway": layaway}


def deposit_on_layaway(layaway_id, amount_cents, expected_version, customer_id):
    """Apply a deposit as the owning Customer. Returns the Layaway dict."""
    res = api_client.deposit_layaway(
        layaway_id,
        deposit_payload(amount_cents, expected_version),
        make_customer_headers(customer_id),
    )
    return get_success_data(res)


# ─── Consignments / auctions / settlements ────────────────────────────

def create_intake_consignment(customer_id, reserve_price_cents=50_000,
                              commission_pct=0.10, buyer_premium_pct=0.05,
                              description="Consigned item"):
    """Intake a consignment (INTAKE). Returns the Consignment dict."""
    res = api_client.create_consignment(
        create_consignment_payload(
            customer_id, description=description, reserve_price_cents=reserve_price_cents,
            commission_pct=commission_pct, buyer_premium_pct=buyer_premium_pct,
        ),
        SALES,
    )
    return get_success_data(res)


def setup_listed_consignment(room="ROOM-A", reserve_price_cents=50_000,
                             commission_pct=0.10, buyer_premium_pct=0.05,
                             customer_name="Consignor",
                             scheduled_start="2026-04-01T10:00:00Z",
                             scheduled_end="2026-04-01T12:00:00Z",
                             description="Consigned item"):
    """Customer + SCHEDULED session + consignment listed into it.

    Returns dict with keys: customer, session, consignment, listed_version.
    """
    customer = create_customer(full_name=customer_name)
    session = create_auction_session(room=room, scheduled_start=scheduled_start,
                                     scheduled_end=scheduled_end)
    consignment = create_intake_consignment(
        customer["id"], reserve_price_cents=reserve_price_cents,
        commission_pct=commission_pct, buyer_premium_pct=buyer_premium_pct,
        description=description,
    )
    listed = get_success_data(
        api_client.list_consignment(
            consignment["id"], list_consignment_payload(session["id"]), SALES,
        )
    )
    return {
        "customer": customer,
        "session": session,
        "consignment": consignment,
        "listed_version": listed["version"],
        "listed": listed,
    }


def record_sale(consignment_id, hammer_price_cents, expected_version):
    """Record a winning hammer price on a LISTED consignment. Returns Consignment dict."""
    res = api_client.record_sale_consignment(
        consignment_id,
        record_sale_payload(hammer_price_cents, expected_version),
        SALES,
    )
    return get_success_data(res)


def setup_sold_consignment(reserve_price_cents=50_000, commission_pct=0.10,
                           buyer_premium_pct=0.05, hammer_price_cents=100_000,
                           room="ROOM-A", customer_name="Consignor"):
    """Full chain to a SOLD consignment (ready for settlement).

    Returns dict with keys: customer, session, consignment (SOLD), sold_version.
    """
    ctx = setup_listed_consignment(
        room=room, reserve_price_cents=reserve_price_cents, commission_pct=commission_pct,
        buyer_premium_pct=buyer_premium_pct, customer_name=customer_name,
    )
    sold = record_sale(ctx["consignment"]["id"], hammer_price_cents, ctx["listed_version"])
    ctx["consignment"] = sold
    ctx["sold_version"] = sold["version"]
    return ctx


# ─── IRA accounts ─────────────────────────────────────────────────────

def create_pending_ira(customer_id, custodian_name="Test Trust", custodian_account_ref="TC-1"):
    """Open a PENDING IRA account. Returns the IRAAccount dict."""
    res = api_client.create_ira_account(
        create_ira_account_payload(customer_id, custodian_name=custodian_name,
                                   custodian_account_ref=custodian_account_ref),
        COMPLIANCE,
    )
    return get_success_data(res)


def create_active_ira(customer_id, custodian_name="Test Trust", custodian_account_ref="TC-1"):
    """Open then approve an IRA account (ACTIVE). Requires the customer to
    have id_document_on_file == true. Returns the IRAAccount dict."""
    ira = create_pending_ira(customer_id, custodian_name, custodian_account_ref)
    approved = get_success_data(api_client.approve_ira_account(ira["id"], COMPLIANCE))
    return approved
