"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the server (empty DB) before every test, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Fixtures use
get_success_data() (lenient validator) so setup failures surface as clear "setup failed"
errors rather than confusing assertion failures.

Identity threading: Customer is entity_backed (PRD §2.1). After a customer is created,
every ownership-gated call uses make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_shop_payload, create_product_payload, create_pricing_tier_payload,
    create_finishing_option_payload, create_press_payload, create_customer_payload,
    create_order_payload, create_order_line_payload, create_artwork_payload,
    create_proof_payload, create_pickup_fulfillment_payload, create_ship_fulfillment_payload,
    create_press_booking_payload,
)
from .test_users import TEST_USERS, make_customer_headers

STAFF = TEST_USERS["shop_staff_headers"]
OPERATOR = TEST_USERS["production_operator_headers"]


# ─── Clock pinning ──────────────────────────────────────────────────────────
def pin_clock(to_iso8601: str):
    """Pin the system clock (PRD §3.9). Returns the response data."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, STAFF))


# ─── Tier 1/2: base config + actors ─────────────────────────────────────────
def create_shop(**overrides):
    """Create a shop with the given config overrides. Returns the Shop."""
    return get_success_data(api_client.create_shop(create_shop_payload(**overrides), STAFF))


def create_customer(shop_id, **overrides):
    """Register a customer under a shop. Returns the Customer."""
    return get_success_data(
        api_client.create_customer(create_customer_payload(shop_id, **overrides), STAFF))


def create_product(shop_id, **overrides):
    """Create a catalog product. Returns the Product."""
    return get_success_data(
        api_client.create_product(create_product_payload(shop_id, **overrides), STAFF))


def create_pricing_tier(product_id, min_quantity, discount_bps):
    return get_success_data(api_client.create_pricing_tier(
        create_pricing_tier_payload(product_id, min_quantity, discount_bps), STAFF))


def create_finishing_option(product_id, code, surcharge_kind, surcharge_cents):
    return get_success_data(api_client.create_finishing_option(
        create_finishing_option_payload(product_id, code, surcharge_kind, surcharge_cents), STAFF))


def create_press(shop_id, **overrides):
    return get_success_data(
        api_client.create_press(create_press_payload(shop_id, **overrides), STAFF))


def create_order(shop_id, customer_id):
    """Create a draft order as its owning customer."""
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_order(create_order_payload(shop_id, customer_id), headers))


def add_line(order_id, product_id, quantity, customer_id, **overrides):
    """Add a line to an order as its owning customer. Returns the OrderLine."""
    headers = make_customer_headers(customer_id)
    return get_success_data(api_client.create_order_line(
        create_order_line_payload(order_id, product_id, quantity, **overrides), headers))


def upload_and_pass_preflight(order_line_id, customer_id, **art_overrides):
    """Upload artwork (passing specs by default) and run preflight as ProductionOperator.
    Bubbles the line OPEN -> PREFLIGHT_OK. Returns the post-preflight Artwork."""
    cust_headers = make_customer_headers(customer_id)
    art = get_success_data(api_client.create_artwork(
        create_artwork_payload(order_line_id, **art_overrides), cust_headers))
    return get_success_data(api_client.run_preflight(art["id"], OPERATOR))


def add_pickup_fulfillment(order_id, customer_id):
    headers = make_customer_headers(customer_id)
    return get_success_data(api_client.create_fulfillment(
        create_pickup_fulfillment_payload(order_id), headers))


def add_ship_fulfillment(order_id, customer_id, ship_fee_cents=1500, ship_address="1 Main St"):
    headers = make_customer_headers(customer_id)
    return get_success_data(api_client.create_fulfillment(
        create_ship_fulfillment_payload(order_id, ship_fee_cents=ship_fee_cents,
                                         ship_address=ship_address), headers))


def read_order_version(order_id, customer_id):
    """Read the order's current version as its owning customer."""
    headers = make_customer_headers(customer_id)
    return get_success_data(api_client.get_order(order_id, headers))["version"]


# ─── Tier 3: confirm-ready orders ───────────────────────────────────────────
def setup_confirmable_copies_order(shop_overrides=None, product_overrides=None,
                                   quantity=10, line_overrides=None,
                                   clock_iso="2026-06-01T09:00:00Z", ship=False):
    """Build a confirm-ready order on a no-proof/no-press COPIES product:
    shop -> clock -> customer -> product -> order -> line -> artwork(PASS) -> fulfillment.
    Returns a dict with shop, customer, product, order, line, and the read order version.
    Does NOT confirm.
    """
    pin_clock(clock_iso)
    shop = create_shop(**(shop_overrides or {}))
    cust = create_customer(shop["id"])
    prod = create_product(shop["id"], category="COPIES", base_unit_price_cents=500,
                          requires_proof=False, requires_press=False,
                          **(product_overrides or {}))
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], quantity, cust["id"], **(line_overrides or {}))
    upload_and_pass_preflight(line["id"], cust["id"])
    if ship:
        add_ship_fulfillment(order["id"], cust["id"])
    else:
        add_pickup_fulfillment(order["id"], cust["id"])
    version = read_order_version(order["id"], cust["id"])
    return {"shop": shop, "customer": cust, "product": prod, "order": order,
            "line": line, "version": version}


def confirm_order(order_id, customer_id, version):
    """Confirm an order as its owning customer with the supplied expected version.
    Returns the response (not unwrapped) so callers can assert success or error."""
    headers = make_customer_headers(customer_id)
    return api_client.confirm_order(order_id, {"expected_order_version": version}, headers)


def setup_confirmed_copies_order(quantity=10, shop_overrides=None, product_overrides=None,
                                 clock_iso="2026-06-01T09:00:00Z"):
    """setup_confirmable_copies_order then confirm. Returns the dict plus the confirmed
    order data under key 'confirmed'."""
    ctx = setup_confirmable_copies_order(shop_overrides=shop_overrides,
                                         product_overrides=product_overrides,
                                         quantity=quantity, clock_iso=clock_iso)
    confirmed = get_success_data(
        confirm_order(ctx["order"]["id"], ctx["customer"]["id"], ctx["version"]))
    ctx["confirmed"] = confirmed
    return ctx


# ─── Tier 4: pricing scenarios (tiers + finishing) ──────────────────────────
def setup_priced_confirmable_order(base_unit_price_cents=1000, quantity=100,
                                   tier=(50, 1000), finishing=("LAMINATE", "PER_UNIT", 50),
                                   service_level="STANDARD", shop_overrides=None,
                                   clock_iso="2026-06-01T09:00:00Z"):
    """Confirm-ready COPIES order with one pricing tier and one finishing option applied.
    tier=(min_quantity, discount_bps); finishing=(code, kind, cents); pass tier=None or
    finishing=None to omit. Returns dict {shop, customer, product, order, line, version}.
    """
    pin_clock(clock_iso)
    shop = create_shop(**(shop_overrides or {}))
    cust = create_customer(shop["id"])
    prod = create_product(shop["id"], category="COPIES",
                          base_unit_price_cents=base_unit_price_cents,
                          requires_proof=False, requires_press=False)
    if tier is not None:
        create_pricing_tier(prod["id"], tier[0], tier[1])
    finishing_codes = []
    if finishing is not None:
        create_finishing_option(prod["id"], finishing[0], finishing[1], finishing[2])
        finishing_codes = [finishing[0]]
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], quantity, cust["id"],
                    finishing_codes=finishing_codes, service_level=service_level)
    upload_and_pass_preflight(line["id"], cust["id"])
    add_pickup_fulfillment(order["id"], cust["id"])
    version = read_order_version(order["id"], cust["id"])
    return {"shop": shop, "customer": cust, "product": prod, "order": order,
            "line": line, "version": version}


# ─── Banner / press scenarios ───────────────────────────────────────────────
def setup_banner_line(shop_overrides=None, unit_size=2, cleanup_buffer_minutes=30,
                      quantity=1, requires_press=True, with_press=True,
                      clock_iso="2026-06-01T09:00:00Z", pin=True):
    """A BANNER product line (requires_press) with preflight passed. Optionally registers
    a press. Returns dict {shop, customer, product, order, line, press(optional)}.
    """
    if pin:
        pin_clock(clock_iso)
    shop = create_shop(**(shop_overrides or {}))
    cust = create_customer(shop["id"])
    prod = create_product(shop["id"], category="BANNER", base_unit_price_cents=5000,
                          unit_size=unit_size, requires_proof=False,
                          requires_press=requires_press)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], quantity, cust["id"])
    upload_and_pass_preflight(line["id"], cust["id"])
    ctx = {"shop": shop, "customer": cust, "product": prod, "order": order, "line": line}
    if with_press:
        ctx["press"] = create_press(shop["id"], cleanup_buffer_minutes=cleanup_buffer_minutes)
    return ctx


def book_press(press_id, order_line_id, start_utc, end_utc):
    """Book press time as ProductionOperator. Returns the response (not unwrapped)."""
    return api_client.create_press_booking(
        create_press_booking_payload(press_id, order_line_id, start_utc, end_utc), OPERATOR)


# ─── Proof scenarios ────────────────────────────────────────────────────────
def setup_proof_line(shop_overrides=None, clock_iso="2026-06-01T09:00:00Z", pin=False):
    """A line on a requires_proof BANNER product, preflight passed (PREFLIGHT_OK).
    Returns dict {shop, customer, product, order, line}."""
    if pin:
        pin_clock(clock_iso)
    shop = create_shop(**(shop_overrides or {}))
    cust = create_customer(shop["id"])
    prod = create_product(shop["id"], category="BANNER", base_unit_price_cents=5000,
                          requires_proof=True, requires_press=False)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 1, cust["id"])
    upload_and_pass_preflight(line["id"], cust["id"])
    return {"shop": shop, "customer": cust, "product": prod, "order": order, "line": line}


def submit_proof(order_line_id):
    """Submit a proof round as ProductionOperator. Returns the Proof."""
    return get_success_data(
        api_client.create_proof(create_proof_payload(order_line_id), OPERATOR))


# ─── Full lifecycle to FULFILLED ────────────────────────────────────────────
def drive_order_to_fulfilled(quantity=10, clock_iso="2026-06-01T09:00:00Z"):
    """Confirm -> invoice -> pay -> start-production -> produce -> hand-off.
    Returns dict {shop, customer, product, order, line, fulfillment, total_cents}.
    """
    ctx = setup_confirmable_copies_order(quantity=quantity, clock_iso=clock_iso)
    cust_id = ctx["customer"]["id"]
    order_id = ctx["order"]["id"]
    confirmed = get_success_data(confirm_order(order_id, cust_id, ctx["version"]))
    total = confirmed["total_cents"]
    get_success_data(api_client.invoice_order(order_id, STAFF))
    cust_headers = make_customer_headers(cust_id)
    get_success_data(api_client.pay_order(order_id, {"amount_cents": total}, cust_headers))
    get_success_data(api_client.start_production(order_id, OPERATOR))
    get_success_data(api_client.produce_order_line(ctx["line"]["id"], OPERATOR))
    # Re-read the fulfillment id via list.
    ful_list = get_success_data(
        api_client.list_fulfillments(STAFF, params={"order_id": order_id}))
    fulfillment_id = ful_list[0]["id"] if isinstance(ful_list, list) and ful_list else None
    handed = None
    if fulfillment_id:
        handed = get_success_data(api_client.hand_off(fulfillment_id, STAFF))
    ctx["fulfillment"] = handed
    ctx["total_cents"] = total
    return ctx
