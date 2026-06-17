"""Composite setup helpers.

These encapsulate the multi-step API sequences that most test claims need before
they can assert anything: standing up a store, cataloguing a product, seeding
on-hand stock through a posted count sheet, opening a cash drawer, creating and
settling sales, and so on. Every helper builds its preconditions from scratch
using only PRD-declared endpoints, because the server database is empty at the
start of every test.

All helpers use get_success_data() (the lenient 2xx validator) for setup calls so
that a setup failure surfaces as a clear error rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS

SM = TEST_USERS["store_manager_headers"]
CA = TEST_USERS["cashier_headers"]
IC = TEST_USERS["inventory_clerk_headers"]


# ─── Primitive creators ──────────────────────────────────────────────────────

def create_store(code, tax_rate_bps=0, name="Test Store", **overrides):
    """Create a store. Returns the Store dict (posture LOCKED, version 1)."""
    payload = {"name": name, "code": code, "tax_rate_bps": tax_rate_bps}
    payload.update(overrides)
    return get_success_data(api_client.create_store(payload, SM))


def create_product(sku, barcode, list_price_cents=1000, name="P", **overrides):
    """Create a catalog product. Returns the Product dict."""
    payload = {"sku": sku, "barcode": barcode, "name": name,
               "list_price_cents": list_price_cents}
    payload.update(overrides)
    return get_success_data(api_client.create_product(payload, SM))


def create_inventory_item(store_id, product_id, reorder_point=0, reorder_qty=0):
    """Create a per-store stock record (on_hand 0, reserved 0). Returns InventoryItem."""
    payload = {"store_id": store_id, "product_id": product_id,
               "reorder_point": reorder_point, "reorder_qty": reorder_qty}
    return get_success_data(api_client.create_inventory_item(payload, IC))


def seed_on_hand(inventory_item_id, qty):
    """Set an inventory item's on_hand_qty to `qty` by opening and posting a count
    sheet (the only way to inject physical stock). Returns the posted CountSheet."""
    cs = get_success_data(
        api_client.create_count_sheet(
            {"inventory_item_id": inventory_item_id, "counted_qty": qty}, IC))
    return get_success_data(api_client.post_count_sheet(cs["id"], IC))


def create_inventory_item_with_stock(store_id, product_id, on_hand,
                                     reorder_point=0, reorder_qty=0):
    """Create an inventory item and seed it to `on_hand` units via a posted count.
    Returns the inventory item id."""
    inv = create_inventory_item(store_id, product_id, reorder_point, reorder_qty)
    if on_hand:
        seed_on_hand(inv["id"], on_hand)
    return inv["id"]


def open_cash_session(store_id, opening_float_cents=0):
    """Open a cash drawer session (store posture -> DRAWER_OPEN). Returns the session."""
    return get_success_data(
        api_client.create_cash_session(
            {"store_id": store_id, "opening_float_cents": opening_float_cents}, SM))


def create_loyalty_account(phone, customer_name="C"):
    """Enroll a loyalty member (points 0, tier STANDARD). Returns LoyaltyAccount."""
    return get_success_data(
        api_client.create_loyalty_account(
            {"customer_name": customer_name, "phone": phone}, SM))


def grant_points(loyalty_account_id, add_points):
    """Grant points directly (credits points_balance + lifetime_points, recomputes
    tier). Returns the updated LoyaltyAccount."""
    return get_success_data(
        api_client.grant_loyalty(
            {"loyalty_account_id": loyalty_account_id, "add_points": add_points}, SM))


def create_promotion(code, kind, value, min_subtotal_cents=0, stackable=False):
    """Create a promotion (status ACTIVE). Returns the Promotion."""
    return get_success_data(api_client.create_promotion(
        {"code": code, "kind": kind, "value": value,
         "min_subtotal_cents": min_subtotal_cents, "stackable": stackable}, SM))


def advance_clock(to_iso8601):
    """Advance the logical clock; sweeps ACTIVE layaways past due into DELINQUENT."""
    return api_client.advance_clock({"to_iso8601": to_iso8601}, SM)


# ─── Sale builders ───────────────────────────────────────────────────────────

def create_sale(store_id, lines, kind="SALE", **overrides):
    """Create (and price) a DRAFT sale. `lines` is a list of {product_id, quantity}.
    Returns the Sale dict."""
    payload = {"store_id": store_id, "kind": kind, "lines": lines}
    payload.update(overrides)
    return get_success_data(api_client.create_sale(payload, CA))


def add_tender(sale_id, method, amount_cents, expected_sale_version):
    """Append a tender. Returns the raw response (caller decides how to validate)."""
    return api_client.create_tender(
        sale_id,
        {"method": method, "amount_cents": amount_cents,
         "expected_sale_version": expected_sale_version}, CA)


def settle_sale_cash(store_id, lines, **sale_overrides):
    """Create a SALE and settle it in one CASH tender for exactly its total_due.
    Returns the re-read settled Sale dict (settlement_status SETTLED).

    Used as the precondition builder for RETURN/EXCHANGE tests that need a settled
    original SALE."""
    sale = create_sale(store_id, lines, kind="SALE", **sale_overrides)
    total = sale["total_due_cents"]
    get_success_data(add_tender(sale["id"], "CASH", total, sale["version"]))
    return get_success_data(api_client.get_sale(sale["id"], CA))


def create_tendering_sale(store_id, lines, partial_amount, method="CARD",
                          **sale_overrides):
    """Create a SALE and append ONE partial tender so it sits in TENDERING (still
    PENDING on the stock axis). Returns the re-read Sale dict."""
    sale = create_sale(store_id, lines, kind="SALE", **sale_overrides)
    get_success_data(add_tender(sale["id"], method, partial_amount, sale["version"]))
    return get_success_data(api_client.get_sale(sale["id"], CA))


# ─── Composite scenario builders ─────────────────────────────────────────────

def setup_store_product_stock(store_code, sku, barcode, on_hand=5,
                              list_price_cents=1000, tax_rate_bps=0,
                              reorder_point=0, reorder_qty=0,
                              open_session=True, opening_float_cents=0,
                              **store_overrides):
    """The most common preamble: a store, a catalogued product, an inventory item
    seeded to `on_hand` units, and (optionally) an OPEN cash session.

    Returns a dict with keys: store, product, inventory_item_id, session (or None).
    """
    store = create_store(store_code, tax_rate_bps=tax_rate_bps, **store_overrides)
    product = create_product(sku, barcode, list_price_cents=list_price_cents)
    inv_id = create_inventory_item_with_stock(
        store["id"], product["id"], on_hand, reorder_point, reorder_qty)
    session = None
    if open_session:
        session = open_cash_session(store["id"], opening_float_cents)
    return {
        "store": store,
        "product": product,
        "inventory_item_id": inv_id,
        "session": session,
    }


def get_inventory_item(inventory_item_id, headers=None):
    """Re-read an inventory item to observe its current derived fields."""
    return get_success_data(
        api_client.get_inventory_item(inventory_item_id, headers or IC))


def get_sale(sale_id, headers=None):
    """Re-read a sale."""
    return get_success_data(api_client.get_sale(sale_id, headers or CA))


def get_loyalty_account(loyalty_account_id, headers=None):
    """Re-read a loyalty account."""
    return get_success_data(
        api_client.get_loyalty_account(loyalty_account_id, headers or SM))


def get_cash_session(session_id, headers=None):
    """Re-read a cash drawer session."""
    return get_success_data(api_client.get_cash_session(session_id, headers or SM))


def get_layaway(layaway_id, headers=None):
    """Re-read a layaway."""
    return get_success_data(api_client.get_layaway(layaway_id, headers or SM))


def get_transfer(transfer_id, headers=None):
    """Re-read a transfer."""
    return get_success_data(api_client.get_transfer(transfer_id, headers or IC))


# ─── Layaway builders ────────────────────────────────────────────────────────

def create_layaway(store_id, product_id, customer_id, quantity, due_date,
                   initial_deposit_cents=None):
    """Create a layaway (reserves stock, locks price). Returns the Layaway dict."""
    payload = {"store_id": store_id, "product_id": product_id,
               "customer_id": customer_id, "quantity": quantity, "due_date": due_date}
    if initial_deposit_cents is not None:
        payload["initial_deposit_cents"] = initial_deposit_cents
    return get_success_data(api_client.create_layaway(payload, CA))


def layaway_payment(layaway_id, amount_cents, expected_layaway_version):
    """Record a layaway deposit. Returns the raw response."""
    return api_client.create_layaway_payment(
        layaway_id,
        {"amount_cents": amount_cents,
         "expected_layaway_version": expected_layaway_version}, CA)


def setup_layaway(store_code, sku, barcode, quantity=1, on_hand=5,
                  list_price_cents=1000, due_date="2030-12-31T00:00:00Z",
                  initial_deposit_cents=0, reorder_point=0, reorder_qty=0):
    """Store + product + stock + loyalty member + an ACTIVE layaway reserving
    `quantity` units. Returns dict: store, product, inventory_item_id, account, layaway.
    """
    store = create_store(store_code, tax_rate_bps=0)
    product = create_product(sku, barcode, list_price_cents=list_price_cents)
    inv_id = create_inventory_item_with_stock(
        store["id"], product["id"], on_hand, reorder_point, reorder_qty)
    account = create_loyalty_account(phone=f"phone-{store_code}")
    layaway = create_layaway(store["id"], product["id"], account["id"],
                             quantity, due_date, initial_deposit_cents)
    return {
        "store": store,
        "product": product,
        "inventory_item_id": inv_id,
        "account": account,
        "layaway": layaway,
    }


# ─── Transfer builders ───────────────────────────────────────────────────────

def create_transfer(from_store_id, to_store_id, product_id, quantity):
    """Request a transfer (status REQUESTED, no stock effect). Returns the Transfer."""
    return get_success_data(api_client.create_transfer(
        {"from_store_id": from_store_id, "to_store_id": to_store_id,
         "product_id": product_id, "quantity": quantity}, IC))


def dispatch_transfer(transfer_id, expected_transfer_version):
    """Dispatch a transfer (reserves source stock). Returns the raw response."""
    return api_client.dispatch_transfer(
        transfer_id, {"expected_transfer_version": expected_transfer_version}, IC)


def setup_transfer_pair(code_a, code_b, sku, barcode, source_on_hand=10,
                        dest_on_hand=0, quantity=3, list_price_cents=100):
    """Two stores A and B, a shared product, an inventory item at each, source
    seeded to `source_on_hand`, and a REQUESTED transfer A->B for `quantity`.

    Returns dict: store_a, store_b, product, inv_a_id, inv_b_id, transfer.
    """
    store_a = create_store(code_a, tax_rate_bps=0, name="A")
    store_b = create_store(code_b, tax_rate_bps=0, name="B")
    product = create_product(sku, barcode, list_price_cents=list_price_cents)
    inv_a_id = create_inventory_item_with_stock(
        store_a["id"], product["id"], source_on_hand)
    inv_b_id = create_inventory_item_with_stock(
        store_b["id"], product["id"], dest_on_hand)
    transfer = create_transfer(store_a["id"], store_b["id"], product["id"], quantity)
    return {
        "store_a": store_a,
        "store_b": store_b,
        "product": product,
        "inv_a_id": inv_a_id,
        "inv_b_id": inv_b_id,
        "transfer": transfer,
    }


def setup_dispatched_transfer(code_a, code_b, sku, barcode, source_on_hand=10,
                              dest_on_hand=0, quantity=3, list_price_cents=100):
    """Like setup_transfer_pair but already advanced to DISPATCHED. Returns the same
    dict, with `transfer` re-read in its DISPATCHED state."""
    s = setup_transfer_pair(code_a, code_b, sku, barcode, source_on_hand,
                            dest_on_hand, quantity, list_price_cents)
    get_success_data(dispatch_transfer(s["transfer"]["id"], s["transfer"]["version"]))
    s["transfer"] = get_transfer(s["transfer"]["id"])
    return s
