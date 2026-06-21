"""Composite setup helpers.

These encapsulate the multi-step preambles that test claims share — advancing
the clock, creating departments/products, running the DSD receiving workflow to
stock a product, building members, and opening/finalizing sales. Each fixture
uses get_success_data() internally so setup failures surface as clear errors.

Identity threading: LoyaltyMember is the only entity_backed role; ownership-gated
member calls use make_member_headers(member_id).
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_member_headers,
)
from . import factories

SM = TEST_USERS["store_manager_headers"]
RC = TEST_USERS["receiving_clerk_headers"]
PM = TEST_USERS["price_manager_headers"]
CSH = TEST_USERS["cashier_headers"]
AUD = TEST_USERS["inventory_auditor_headers"]

# Monotonic counters so repeated calls within one test produce unique
# reference_code / sku / plu / email / department code values. Each pytest test
# runs against a fresh server+DB, so collisions only matter within a single test.
_ref_counter = itertools.count(1)
_sku_counter = itertools.count(1)
_plu_counter = itertools.count(4000)
_email_counter = itertools.count(1)
_dept_counter = itertools.count(1)


def _next_ref():
    return f"REF-{next(_ref_counter):05d}"


def _next_sku():
    return f"SKU-{next(_sku_counter):05d}"


def _next_plu():
    return str(next(_plu_counter))


def _next_email():
    return f"member{next(_email_counter):05d}@example.com"


def _int_to_letters(n, width=5):
    """Map a positive integer to a fixed-width A-Z string (base-26), so the
    generated department code contains only letters as the PRD requires
    (codes are 'letters A through Z and underscores only')."""
    letters = []
    n -= 1
    for _ in range(width):
        letters.append(chr(ord("A") + (n % 26)))
        n //= 26
    return "".join(reversed(letters))


def _next_dept_code():
    return f"DEPT_{_int_to_letters(next(_dept_counter))}"


# ---------------------------------------------------------------------------
# Tier 1: Clock + base catalog
# ---------------------------------------------------------------------------
def advance_clock(to_iso8601):
    """Advance the server logical clock to an absolute ISO 8601 instant."""
    return get_success_data(api_client.advance_clock(to_iso8601, SM))


def create_department(code=None, **overrides):
    """Create a department. Returns the department dict."""
    payload = factories.create_department_payload(
        code=code or _next_dept_code(), **overrides
    )
    return get_success_data(api_client.create_department(payload, SM))


def create_product(department_id=None, **overrides):
    """Create an each-sold product (auto department if none given). Returns product dict."""
    if department_id is None:
        department_id = create_department()["id"]
    if "sku" not in overrides and not overrides.get("sell_by_weight"):
        overrides["sku"] = _next_sku()
    payload = factories.create_product_payload(department_id, **overrides)
    return get_success_data(api_client.create_product(payload, PM))


def create_weighed_product(department_id=None, **overrides):
    """Create a weighed product (auto department if none given). Returns product dict."""
    if department_id is None:
        department_id = create_department()["id"]
    if "plu" not in overrides:
        overrides["plu"] = _next_plu()
    payload = factories.create_weighed_product_payload(department_id, **overrides)
    return get_success_data(api_client.create_product(payload, PM))


# ---------------------------------------------------------------------------
# Tier 2/3: DSD receiving workflow — the canonical way to stock a product
# ---------------------------------------------------------------------------
def receive_lot(product_id, qty, unit_cost_cents=100, expiration_date=None,
                expected_total_cents=None, override_variance=True,
                ordered_qty=None, expected_product_version=None):
    """Run the full receive workflow for a SINGLE-line shipment: create shipment,
    add one line, start-receiving, receive (creating one ACTIVE lot of `qty`).

    By default uses StoreManager + override_variance=true so an arbitrary
    expected_total never trips the variance gate. The receive reads the
    product's current version unless expected_product_version is supplied.
    Returns (shipment, line).
    """
    ordered = ordered_qty if ordered_qty is not None else qty
    if expected_total_cents is None:
        expected_total_cents = qty * unit_cost_cents
    ship = get_success_data(api_client.create_shipment(
        factories.create_shipment_payload(
            reference_code=_next_ref(), expected_total_cents=expected_total_cents
        ), RC))
    line_payload = factories.create_shipment_line_payload(
        product_id, ordered_qty=ordered, unit_cost_cents=unit_cost_cents, accepted_qty=qty
    )
    if expiration_date is not None:
        line_payload["expiration_date"] = expiration_date
    line = get_success_data(api_client.add_shipment_line(ship["id"], line_payload, RC))
    get_success_data(api_client.start_receiving(ship["id"], RC))
    if expected_product_version is None:
        expected_product_version = get_success_data(
            api_client.get_product(product_id, RC))["version"]
    recv_payload = {"expected_product_version": expected_product_version}
    actor = RC
    if override_variance:
        recv_payload["override_variance"] = True
        actor = SM
    ship = get_success_data(api_client.receive_shipment(ship["id"], recv_payload, actor))
    return ship, line


def stock_each_product(qty=10, unit_cost_cents=100, reorder_point_qty=0,
                       unit_price_cents=100, department_id=None, **product_overrides):
    """Create an each-sold product and receive `qty` into a single ACTIVE lot.
    Returns (product, lot)."""
    product = create_product(
        department_id=department_id, unit_price_cents=unit_price_cents,
        reorder_point_qty=reorder_point_qty, **product_overrides
    )
    receive_lot(product["id"], qty, unit_cost_cents=unit_cost_cents)
    product = get_success_data(api_client.get_product(product["id"], PM))
    lot = get_success_data(
        api_client.list_inventory_lots(AUD, params={"product_id": product["id"]})
    )
    # list returns array data
    lot0 = lot[0] if isinstance(lot, list) else lot["data"][0]
    return product, lot0


def get_single_lot(product_id):
    """Return the first inventory lot for a product."""
    data = get_success_data(
        api_client.list_inventory_lots(AUD, params={"product_id": product_id})
    )
    lots = data if isinstance(data, list) else data["data"]
    return lots[0]


def list_lots(product_id):
    data = get_success_data(
        api_client.list_inventory_lots(AUD, params={"product_id": product_id})
    )
    return data if isinstance(data, list) else data["data"]


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------
def open_sale(member_id=None):
    """Open a POS sale (optionally on a member). Returns the sale dict."""
    payload = factories.create_sale_payload()
    if member_id is not None:
        payload["member_id"] = member_id
    return get_success_data(api_client.create_sale(payload, CSH))


def add_each_line(sale_id, product_id, quantity):
    return get_success_data(api_client.add_line_item(
        sale_id, {"product_id": product_id, "quantity": quantity}, CSH))


def add_weighed_line(sale_id, product_id, weight_milli):
    return get_success_data(api_client.add_line_item(
        sale_id, {"product_id": product_id, "weight_milli": weight_milli}, CSH))


def open_sale_with_each_line(product_id, quantity, member_id=None):
    """Open a sale and add one each-sold line. Returns (sale, line)."""
    sale = open_sale(member_id=member_id)
    line = add_each_line(sale["id"], product_id, quantity)
    return sale, line


def finalize_sale(sale_id, clipped_coupon_id=None):
    payload = {}
    if clipped_coupon_id is not None:
        payload["clipped_coupon_id"] = clipped_coupon_id
    return get_success_data(api_client.finalize_sale(sale_id, payload, CSH))


# ---------------------------------------------------------------------------
# Pricing — price plans and promotions
# ---------------------------------------------------------------------------
def create_price_plan(product_id, ad_price_cents, effective_start, effective_end,
                      expected_product_version=None):
    """Create a price plan. Reads the product's current version if not given.
    Returns the price plan dict."""
    if expected_product_version is None:
        expected_product_version = get_success_data(
            api_client.get_product(product_id, PM))["version"]
    payload = factories.create_price_plan_payload(
        product_id, expected_product_version,
        ad_price_cents=ad_price_cents,
        effective_start=effective_start, effective_end=effective_end,
    )
    return get_success_data(api_client.create_price_plan(payload, PM))


def create_promotion(product_id, **overrides):
    """Create a promotion. Returns the promotion dict."""
    payload = factories.create_promotion_payload(product_id, **overrides)
    return get_success_data(api_client.create_promotion(payload, PM))


def create_coupon(product_id, code=None, **overrides):
    payload = factories.create_coupon_payload(
        product_id, code=code or f"CPN{next(_ref_counter):05d}", **overrides)
    return get_success_data(api_client.create_coupon(payload, PM))


# ---------------------------------------------------------------------------
# Members and clips
# ---------------------------------------------------------------------------
def create_member(email=None, full_name="Test Shopper", **overrides):
    payload = factories.create_member_payload(
        email=email or _next_email(), full_name=full_name, **overrides)
    return get_success_data(api_client.create_member(payload, CSH))


def clip_coupon(member_id, coupon_id):
    """Cashier clips a coupon onto a member's account. Returns the clip dict."""
    return get_success_data(
        api_client.clip_coupon(member_id, {"coupon_id": coupon_id}, CSH))


def create_member_with_clip(coupon_id, email=None):
    """Create a member and clip a coupon onto its account. Returns (member, clip)."""
    member = create_member(email=email)
    clip = clip_coupon(member["id"], coupon_id)
    return member, clip


# ---------------------------------------------------------------------------
# Tier 4: GOLD-tier member via a large finalized+paid purchase
# ---------------------------------------------------------------------------
def make_gold_member():
    """Create a member and push lifetime_spend to >= GOLD threshold (200000)
    via a finalized + paid purchase of a high-value product.
    Returns the member dict (re-read, so tier == GOLD)."""
    product, _ = stock_each_product(qty=2, unit_cost_cents=2000, unit_price_cents=100000)
    member = create_member()
    sale, _ = open_sale_with_each_line(product["id"], 2, member_id=member["id"])
    finalize_sale(sale["id"])
    get_success_data(api_client.pay_sale(sale["id"], CSH))
    return get_success_data(api_client.get_member(member["id"], CSH))


# ---------------------------------------------------------------------------
# Tier 5: Cycle counts and EOD
# ---------------------------------------------------------------------------
def open_cycle_count(department_id, product_id):
    return get_success_data(api_client.create_cycle_count(
        factories.create_cycle_count_payload(department_id, product_id), AUD))


def submit_cycle_count(cc_id, counted_qty):
    return get_success_data(api_client.submit_cycle_count(
        cc_id, {"counted_qty": counted_qty}, AUD))


def open_eod(department_id, business_date="2026-06-05T00:00:00Z"):
    return get_success_data(api_client.create_eod(
        factories.create_eod_payload(department_id, business_date=business_date), AUD))
