"""Composite setup helpers for the Vinyl Records Shop tests.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of every test.
Setup calls use get_success_data() (lenient) so setup failures surface clearly.

Identity threading: after creating a Customer (entity_backed), any ownership-gated
call uses make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_headers,
)
from .factories import (
    create_customer_payload,
    create_product_payload,
    create_allocation_payload,
    create_inventory_item_payload,
    create_order_payload,
    create_trade_in_payload,
    create_trade_in_line_payload,
    create_preorder_payload,
    create_display_slot_payload,
    create_consignment_payload,
    create_dispute_payload,
    create_special_order_payload,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["store_clerk_headers"]
GRADER = TEST_USERS["grader_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitive creators
# ---------------------------------------------------------------------------
def register_customer(api=api_client, email=None, full_name="Test Buyer"):
    """Register a Customer. Returns the Customer dict."""
    if email is None:
        # Unique email per call within a test run.
        import uuid
        email = f"c-{uuid.uuid4().hex[:12]}@example.com"
    payload = create_customer_payload(email=email, full_name=full_name)
    return get_success_data(api.create_customer(payload, ANON))


def create_product(api=api_client, **overrides):
    """Create a Product (Manager). Returns Product dict."""
    payload = create_product_payload(**overrides)
    return get_success_data(api.create_product(payload, MANAGER))


def create_inventory_item(api=api_client, product_id=None, **overrides):
    """Add a physical copy (StoreClerk). Returns InventoryItem dict."""
    payload = create_inventory_item_payload(product_id=product_id, **overrides)
    return get_success_data(api.create_inventory_item(payload, CLERK))


def seed_store_credit(api=api_client, customer_id=None, delta_cents=0, reason="seed"):
    """Manager credit adjustment. Returns updated Customer dict."""
    return get_success_data(
        api.credit_adjustment(customer_id, {"delta_cents": delta_cents, "reason": reason}, MANAGER)
    )


def set_loyalty_points(api=api_client, customer_id=None, delta_points=0):
    """Test-driving: set/add loyalty points and recompute tier. Returns Customer dict."""
    return get_success_data(
        api.adjust_points({"customer_id": customer_id, "delta_points": delta_points}, MANAGER)
    )


def set_clock(api=api_client, to_iso8601="2026-03-01T00:00:00Z"):
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, MANAGER))


# ---------------------------------------------------------------------------
# Tier 1/2: order assembly
# ---------------------------------------------------------------------------
def open_order(api=api_client, customer=None, channel="ONLINE"):
    """Open an empty order owned by `customer` (dict). Returns Order dict."""
    payload = create_order_payload(customer_id=customer["id"], channel=channel)
    return get_success_data(
        api.create_order(payload, make_customer_headers(customer["id"]))
    )


def add_line(api=api_client, order=None, customer=None, item=None):
    """Add one line reserving `item` to `order`. Returns OrderLine dict."""
    return get_success_data(
        api.add_order_line(
            order["id"], {"inventory_item_id": item["id"]},
            make_customer_headers(customer["id"]),
        )
    )


def setup_order_with_items(api=api_client, channel="ONLINE", base_price_cents=3000,
                           is_used=False, condition_grade="NM", num_items=1,
                           customer=None):
    """
    Create a customer, a product, `num_items` copies, an order of `channel`, and
    add all copies as lines (fulfillment RESERVED). Returns
    (customer, product, items, order, lines).
    """
    if customer is None:
        customer = register_customer(api)
    product = create_product(api, base_price_cents=base_price_cents)
    items = [
        create_inventory_item(api, product_id=product["id"],
                              is_used=is_used, condition_grade=condition_grade)
        for _ in range(num_items)
    ]
    order = open_order(api, customer=customer, channel=channel)
    lines = [add_line(api, order=order, customer=customer, item=it) for it in items]
    return customer, product, items, order, lines


def setup_authorized_order(api=api_client, **kwargs):
    """setup_order_with_items + authorize payment. Returns the same tuple."""
    customer, product, items, order, lines = setup_order_with_items(api, **kwargs)
    get_success_data(api.authorize_payment(order["id"], make_customer_headers(customer["id"])))
    return customer, product, items, order, lines


def setup_paid_order(api=api_client, credit_applied_cents=None, **kwargs):
    """setup_authorized_order + capture payment (StoreClerk). Returns the tuple."""
    customer, product, items, order, lines = setup_authorized_order(api, **kwargs)
    payload = {} if credit_applied_cents is None else {"credit_applied_cents": credit_applied_cents}
    get_success_data(api.capture_payment(order["id"], payload, CLERK))
    return customer, product, items, order, lines


# ---------------------------------------------------------------------------
# Tier 3: trade-in lifecycle
# ---------------------------------------------------------------------------
def setup_trade_in_with_lines(api=api_client, payout_method="CREDIT", lines=None,
                              customer=None):
    """
    Create a customer + DRAFT trade-in with the given lines.
    `lines` is a list of dicts (format, claimed_grade, base_value_cents).
    Returns (customer, trade_in, line_dicts) where line_dicts are the created lines.
    """
    if customer is None:
        customer = register_customer(api)
    hdr = make_customer_headers(customer["id"])
    ti = get_success_data(
        api.create_trade_in(create_trade_in_payload(
            customer_id=customer["id"], payout_method=payout_method), hdr)
    )
    if lines is None:
        lines = [{"format": "VINYL", "claimed_grade": "NM", "base_value_cents": 1000}]
    created = []
    for ln in lines:
        created.append(get_success_data(
            api.add_trade_in_line(ti["id"], create_trade_in_line_payload(**ln), hdr)
        ))
    return customer, ti, created


def submit_trade_in(api=api_client, customer=None, trade_in=None):
    return get_success_data(
        api.submit_trade_in(trade_in["id"], make_customer_headers(customer["id"]))
    )


def setup_trade_in_under_inspection(api=api_client, payout_method="CREDIT", lines=None,
                                    customer=None):
    """Trade-in submitted then moved to UNDER_INSPECTION. Returns (customer, ti, line_dicts)."""
    customer, ti, created = setup_trade_in_with_lines(
        api, payout_method=payout_method, lines=lines, customer=customer)
    submit_trade_in(api, customer=customer, trade_in=ti)
    get_success_data(api.start_inspection(ti["id"], GRADER))
    return customer, ti, created


def setup_trade_in_inspected(api=api_client, payout_method="CREDIT", lines=None,
                             inspected_grades=None, customer=None):
    """
    Trade-in under inspection with inspected_grade set on each line (parallel to
    `inspected_grades`). If inspected_grades is None each line's claimed_grade is used.
    Returns (customer, ti, line_dicts).
    """
    customer, ti, created = setup_trade_in_under_inspection(
        api, payout_method=payout_method, lines=lines, customer=customer)
    if inspected_grades is None:
        inspected_grades = [ln["claimed_grade"] for ln in (lines or [])] or ["NM"]
    for line, grade in zip(created, inspected_grades):
        get_success_data(
            api.set_inspected_grade(line["id"], {"inspected_grade": grade}, GRADER)
        )
    return customer, ti, created


def setup_trade_in_approved(api=api_client, payout_method="CREDIT", lines=None,
                            inspected_grades=None, customer=None):
    """Fully approved trade-in. Returns (customer, ti_after_approve, line_dicts)."""
    customer, ti, created = setup_trade_in_inspected(
        api, payout_method=payout_method, lines=lines,
        inspected_grades=inspected_grades, customer=customer)
    approved = get_success_data(api.approve_trade_in(ti["id"], GRADER))
    return customer, approved, created


# ---------------------------------------------------------------------------
# Tier 4: allocation / pre-order pools
# ---------------------------------------------------------------------------
def create_rsd_allocation(api=api_client, allocation_total=1,
                          window_open_at="2026-03-01T00:00:00Z",
                          window_close_at="2026-12-01T00:00:00Z",
                          pickup_concurrency=None, base_price_cents=4000):
    """
    Create an RSD-exclusive product + an allocation pool.
    Returns (product, allocation).
    """
    product = create_product(api, base_price_cents=base_price_cents, is_rsd_exclusive=True)
    alloc_payload = create_allocation_payload(
        allocation_total=allocation_total,
        window_open_at=window_open_at, window_close_at=window_close_at,
    )
    if pickup_concurrency is not None:
        alloc_payload["pickup_concurrency"] = pickup_concurrency
    allocation = get_success_data(api.create_allocation(product["id"], alloc_payload, MANAGER))
    return product, allocation


def create_preorder(api=api_client, customer=None, product=None, allocation=None,
                    expected_allocation_version=None, pickup_window_start="2026-04-01T09:00:00Z",
                    pickup_window_end="2026-04-01T17:00:00Z"):
    """
    Create a pre-order for `customer` reserving from `allocation`. If
    expected_allocation_version is None, the current allocation version is fetched first.
    Returns the PreOrder dict.
    """
    if expected_allocation_version is None:
        cur = get_success_data(api.get_allocation(allocation["id"], MANAGER))
        expected_allocation_version = cur["version"]
    payload = create_preorder_payload(
        customer_id=customer["id"], product_id=product["id"],
        allocation_id=allocation["id"],
        expected_allocation_version=expected_allocation_version,
        pickup_window_start=pickup_window_start, pickup_window_end=pickup_window_end,
    )
    return get_success_data(
        api.create_preorder(payload, make_customer_headers(customer["id"]))
    )


def current_allocation_version(api=api_client, allocation=None):
    return get_success_data(api.get_allocation(allocation["id"], MANAGER))["version"]


# ---------------------------------------------------------------------------
# Tier 2/3: consignments & display slots
# ---------------------------------------------------------------------------
def create_display_slot(api=api_client, slot_label="Front Window A", is_active=True):
    payload = create_display_slot_payload(slot_label=slot_label, is_active=is_active)
    return get_success_data(api.create_display_slot(payload, MANAGER))


def create_consignment(api=api_client, consignor=None, product=None, list_price_cents=5000,
                       condition_grade="VG", display_slot_id=None,
                       display_start=None, display_end=None):
    """Create a DRAFT consignment (with linked used InventoryItem). Returns Consignment dict."""
    payload = create_consignment_payload(
        consignor_id=consignor["id"], product_id=product["id"],
        list_price_cents=list_price_cents, condition_grade=condition_grade,
    )
    if display_slot_id is not None:
        payload["display_slot_id"] = display_slot_id
    if display_start is not None:
        payload["display_start"] = display_start
    if display_end is not None:
        payload["display_end"] = display_end
    return get_success_data(api.create_consignment(payload, MANAGER))


def get_consignment_item(api=api_client, consignment=None):
    """Return the linked InventoryItem dict for a consignment."""
    resp = api.list_inventory_items(MANAGER, params={"consignment_id": consignment["id"]})
    data = get_success_data(resp)
    items = data if isinstance(data, list) else data.get("data", data)
    return items[0]


def setup_active_consignment(api=api_client, list_price_cents=10000, condition_grade="VG_PLUS",
                             base_price_cents=3000, slot_label="Front Window A",
                             display_start="2026-03-01T00:00:00Z",
                             display_end="2026-03-10T00:00:00Z", consignor=None, product=None):
    """
    Consignor + product + display slot + ACTIVE consignment (item ON_DISPLAY).
    Returns (consignor, product, slot, consignment, item).
    """
    if consignor is None:
        consignor = register_customer(api, full_name="Consignor")
    if product is None:
        product = create_product(api, base_price_cents=base_price_cents)
    slot = create_display_slot(api, slot_label=slot_label)
    cons = create_consignment(
        api, consignor=consignor, product=product, list_price_cents=list_price_cents,
        condition_grade=condition_grade, display_slot_id=slot["id"],
        display_start=display_start, display_end=display_end,
    )
    get_success_data(api.activate_consignment(cons["id"], MANAGER))
    item = get_consignment_item(api, consignment=cons)
    return consignor, product, slot, cons, item


# ---------------------------------------------------------------------------
# Tier 3: grading disputes
# ---------------------------------------------------------------------------
def create_used_item(api=api_client, base_price_cents=2500, condition_grade="VG"):
    """Create a product + a used InventoryItem. Returns (product, item)."""
    product = create_product(api, base_price_cents=base_price_cents)
    item = create_inventory_item(api, product_id=product["id"],
                                 is_used=True, condition_grade=condition_grade)
    return product, item


def open_dispute(api=api_client, customer=None, item=None, claimed_grade="VG_PLUS"):
    payload = create_dispute_payload(
        inventory_item_id=item["id"], customer_id=customer["id"], claimed_grade=claimed_grade)
    return get_success_data(
        api.create_dispute(payload, make_customer_headers(customer["id"]))
    )


def setup_dispute_under_review(api=api_client, base_price_cents=2500, item_grade="VG",
                               claimed_grade="VG_PLUS", customer=None, item=None):
    """Used item + OPEN dispute moved to UNDER_REVIEW. Returns (customer, product, item, dispute)."""
    if customer is None:
        customer = register_customer(api, full_name="Disputer")
    product = None
    if item is None:
        product, item = create_used_item(api, base_price_cents=base_price_cents,
                                         condition_grade=item_grade)
    dispute = open_dispute(api, customer=customer, item=item, claimed_grade=claimed_grade)
    get_success_data(api.start_review(dispute["id"], GRADER))
    return customer, product, item, dispute


# ---------------------------------------------------------------------------
# Tier 3: special orders
# ---------------------------------------------------------------------------
def create_special_order(api=api_client, customer=None, description="rare pressing",
                         deposit_cents=0, product_id=None):
    if customer is None:
        customer = register_customer(api, full_name="Special")
    payload = create_special_order_payload(
        customer_id=customer["id"], description=description, deposit_cents=deposit_cents)
    if product_id is not None:
        payload["product_id"] = product_id
    so = get_success_data(
        api.create_special_order(payload, make_customer_headers(customer["id"]))
    )
    return customer, so
