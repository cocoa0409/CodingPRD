"""Composite setup helpers.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints, since every test runs against a fresh empty database. Fixtures use
get_success_data() (lenient) internally so setup failures surface clearly.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from . import factories as F

ADMIN = TEST_USERS["catalog_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
ANY = TEST_USERS["any_headers"]


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------
def create_active_product(msrp_cents=1000, category="PLUSH", age_grade_min_months=0,
                          safety_labels=None, is_exclusive=False, sku=None):
    """Create a product and activate it. Returns the activated Product dict."""
    payload = F.create_product_payload(
        msrp_cents=msrp_cents, category=category,
        age_grade_min_months=age_grade_min_months,
        safety_labels=safety_labels or ["NONE"], is_exclusive=is_exclusive,
    )
    if sku is not None:
        payload["sku"] = sku
    pid = get_success_data(api_client.create_product(payload, ADMIN))["id"]
    get_success_data(api_client.activate_product(pid, ADMIN))
    return get_success_data(api_client.get_product(pid, ANY))


def create_store(event_buffer_minutes=None):
    payload = F.create_store_payload()
    if event_buffer_minutes is not None:
        payload["event_buffer_minutes"] = event_buffer_minutes
    return get_success_data(api_client.create_store(payload, ADMIN))


def create_inventory(product_id, store_id, on_hand_qty=100):
    return get_success_data(api_client.create_inventory(
        F.create_inventory_payload(product_id, store_id, on_hand_qty), ASSOCIATE))


def create_customer(email=None):
    payload = F.create_customer_payload()
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_customer(payload, ASSOCIATE))


def create_allocation(product_id, store_id, allocated_qty=10,
                      season_start="2026-03-01T00:00:00Z",
                      season_end="2026-12-01T00:00:00Z"):
    return get_success_data(api_client.create_allocation(
        F.create_allocation_payload(product_id, store_id, allocated_qty,
                                    season_start, season_end), MANAGER))


def create_open_order(customer_id, store_id, fulfillment_type="BOPIS"):
    return get_success_data(api_client.create_order(
        F.create_order_payload(customer_id, store_id, fulfillment_type),
        make_customer_headers(customer_id)))


def add_line(order_id, customer_id, product_id, qty=1, recipient_age_months=60):
    return get_success_data(api_client.add_order_line(
        order_id, F.create_order_line_payload(product_id, qty, recipient_age_months),
        make_customer_headers(customer_id)))


# --------------------------------------------------------------------------
# Tier 2: catalog + store + inventory + customer scaffolds
# --------------------------------------------------------------------------
def setup_catalog(msrp_cents=1000, on_hand_qty=100, is_exclusive=False,
                  category="PLUSH", age_grade_min_months=0, safety_labels=None):
    """Active product + store + inventory + customer. Returns dict of entities."""
    product = create_active_product(msrp_cents=msrp_cents, category=category,
                                    age_grade_min_months=age_grade_min_months,
                                    safety_labels=safety_labels, is_exclusive=is_exclusive)
    store = create_store()
    inv = create_inventory(product["id"], store["id"], on_hand_qty)
    customer = create_customer()
    return {"product": product, "store": store, "inventory": inv, "customer": customer}


# --------------------------------------------------------------------------
# Tier 3: order lifecycle shortcuts
# --------------------------------------------------------------------------
def _pay_full(order_id):
    order = get_success_data(api_client.get_order(order_id, ANY))
    total = order["total_cents"]
    if total > 0:
        get_success_data(api_client.pay_order(order_id, {"amount_cents": total}, ASSOCIATE))


def create_ready_order(customer_id, store_id, product_id, qty=1, recipient_age_months=60):
    """Open -> add line -> submit -> mark-ready. Returns READY order dict."""
    order = create_open_order(customer_id, store_id)
    line = add_line(order["id"], customer_id, product_id, qty, recipient_age_months)
    get_success_data(api_client.submit_order(order["id"], make_customer_headers(customer_id)))
    get_success_data(api_client.mark_ready_order(order["id"], ASSOCIATE))
    order = get_success_data(api_client.get_order(order["id"], ANY))
    return order, line


def create_fulfilled_order(customer_id, store_id, product_id, qty=1, recipient_age_months=60):
    """Full lifecycle to FULFILLED (pays total in full). Returns (order, line)."""
    order, line = create_ready_order(customer_id, store_id, product_id, qty, recipient_age_months)
    _pay_full(order["id"])
    get_success_data(api_client.fulfill_order(order["id"], ASSOCIATE))
    order = get_success_data(api_client.get_order(order["id"], ANY))
    return order, line


def promote_customer_via_fulfillment(customer_id, store_id, product_id, qty):
    """Fulfill a BRONZE-tier warm-up order of `qty` units to accumulate lifetime_points.
    Product must be msrp 1000 non-exclusive with adequate inventory. Returns customer dict."""
    order = create_open_order(customer_id, store_id)
    add_line(order["id"], customer_id, product_id, qty, 60)
    get_success_data(api_client.submit_order(order["id"], make_customer_headers(customer_id)))
    get_success_data(api_client.mark_ready_order(order["id"], ASSOCIATE))
    _pay_full(order["id"])
    get_success_data(api_client.fulfill_order(order["id"], ASSOCIATE))
    return get_success_data(api_client.get_customer(customer_id, ANY))


# --------------------------------------------------------------------------
# Tier: special-order lifecycle
# --------------------------------------------------------------------------
def create_special_order_draft(customer_id, product_id, requested_qty=1):
    """Returns SpecialOrder dict in DRAFT (version captured in dict)."""
    return get_success_data(api_client.create_special_order(
        F.create_special_order_payload(customer_id, product_id, requested_qty), ASSOCIATE))


def create_quoted_special_order(customer_id, product_id, requested_qty=1,
                                unit_price_cents=5000, deposit_cents=2000):
    """Create special order + one quote. Returns SpecialOrder dict in QUOTED."""
    so = create_special_order_draft(customer_id, product_id, requested_qty)
    get_success_data(api_client.quote_special_order(
        so["id"], F.quote_payload(unit_price_cents, deposit_cents, so["version"]), MANAGER))
    return get_success_data(api_client.get_special_order(so["id"], ANY))


def create_approved_special_order(customer_id, product_id, requested_qty=1,
                                  unit_price_cents=5000, deposit_cents=2000):
    """Create special order -> quote -> customer approve. Returns APPROVED SpecialOrder dict."""
    so = create_special_order_draft(customer_id, product_id, requested_qty)
    get_success_data(api_client.quote_special_order(
        so["id"], F.quote_payload(unit_price_cents, deposit_cents, so["version"]), MANAGER))
    get_success_data(api_client.approve_special_order(so["id"], make_customer_headers(customer_id)))
    return get_success_data(api_client.get_special_order(so["id"], ANY))


# --------------------------------------------------------------------------
# Tier: recall
# --------------------------------------------------------------------------
def issue_recall_for(product_id):
    """Open + issue a recall for a product. Returns Recall dict in ISSUED."""
    recall = get_success_data(api_client.create_recall(F.create_recall_payload(product_id), ADMIN))
    get_success_data(api_client.issue_recall(recall["id"], ADMIN))
    return get_success_data(api_client.get_recall(recall["id"], ANY))


# --------------------------------------------------------------------------
# Tier: returns
# --------------------------------------------------------------------------
def create_requested_return(order_id, order_line_id, qty):
    """Request a return on a fulfilled order. Returns Return dict in REQUESTED."""
    return get_success_data(api_client.create_return(
        F.create_return_payload(order_id, [{"order_line_id": order_line_id, "qty": qty}]),
        ASSOCIATE))


def setup_fulfilled_order_with_return(msrp_cents=1000, qty=5, on_hand_qty=20,
                                      is_exclusive=False):
    """Full lifecycle to a FULFILLED order plus a REQUESTED return of the whole line.
    Returns dict with product, store, inventory, customer, order, line, ret."""
    ctx = setup_catalog(msrp_cents=msrp_cents, on_hand_qty=on_hand_qty, is_exclusive=is_exclusive)
    order, line = create_fulfilled_order(ctx["customer"]["id"], ctx["store"]["id"],
                                         ctx["product"]["id"], qty=qty)
    ret = create_requested_return(order["id"], line["id"], qty)
    ctx.update({"order": order, "line": line, "ret": ret})
    return ctx


# --------------------------------------------------------------------------
# Tier: events / registries
# --------------------------------------------------------------------------
def create_event(store_id, product_id, start_at="2026-04-01T10:00:00Z",
                 end_at="2026-04-01T11:00:00Z", capacity=5):
    return get_success_data(api_client.create_event(
        F.create_event_payload(store_id, product_id, start_at, end_at, capacity), ASSOCIATE))


def create_registry(customer_id, registry_type="WISHLIST"):
    return get_success_data(api_client.create_registry(
        F.create_registry_payload(customer_id, registry_type),
        make_customer_headers(customer_id)))
