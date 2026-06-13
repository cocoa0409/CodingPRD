"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors instead of confusing assertion failures.

Because the harness restarts the server before every test, each fixture builds
its full precondition chain from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_boutique_payload, create_customer_payload, create_style_payload,
    create_sku_variant_payload, create_markdown_schedule_payload,
    create_fitting_room_payload, create_hold_payload, create_stylist_payload,
    create_appointment_payload, create_sales_order_payload, create_order_line_payload,
    create_return_payload, create_special_order_payload, create_lookbook_payload,
    store_credit_grant_payload, clock_advance_payload, restock_payload,
)
from .test_users import TEST_USERS, make_customer_headers

MANAGER = TEST_USERS["store_manager_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
MERCH = TEST_USERS["merchandiser_headers"]


# ─── Tier 0: Atomic builders ──────────────────────────────────────────────

def create_boutique(**overrides):
    """Create a boutique. Returns the boutique entity."""
    res = api_client.create_boutique(create_boutique_payload(**overrides), MANAGER)
    return get_success_data(res)


def create_customer(boutique_id, **overrides):
    """Register a customer under a boutique. Returns the customer entity."""
    res = api_client.create_customer(create_customer_payload(boutique_id, **overrides), ASSOCIATE)
    return get_success_data(res)


def create_style(boutique_id, **overrides):
    """Create a style under a boutique. Returns the style entity."""
    res = api_client.create_style(create_style_payload(boutique_id, **overrides), MERCH)
    return get_success_data(res)


def create_variant(style_id, **overrides):
    """Add a SKU variant under a style. Returns the variant entity."""
    res = api_client.create_sku_variant(style_id, create_sku_variant_payload(**overrides), MERCH)
    return get_success_data(res)


def create_fitting_room(boutique_id, **overrides):
    res = api_client.create_fitting_room(create_fitting_room_payload(boutique_id, **overrides), ASSOCIATE)
    return get_success_data(res)


def create_stylist(boutique_id, **overrides):
    res = api_client.create_stylist(create_stylist_payload(boutique_id, **overrides), MANAGER)
    return get_success_data(res)


def grant_store_credit(customer_id, amount_cents):
    res = api_client.grant_store_credit(customer_id, store_credit_grant_payload(amount_cents), MANAGER)
    return get_success_data(res)


def advance_clock(boutique_id, to_business_date, **overrides):
    res = api_client.advance_clock(
        clock_advance_payload(boutique_id, to_business_date, **overrides), MANAGER)
    return get_success_data(res)


# ─── Tier 1: Common scenario bundles ──────────────────────────────────────

def setup_boutique_customer():
    """Boutique + one customer. Returns (boutique, customer)."""
    bq = create_boutique()
    cu = create_customer(bq["id"])
    return bq, cu


def setup_style_with_variant(boutique_id=None, style_overrides=None, variant_overrides=None,
                             on_hand=5, list_price_cents=5000):
    """A style with one variant. Returns (boutique, style, variant).

    Creates a boutique if none supplied.
    """
    style_overrides = dict(style_overrides or {})
    variant_overrides = dict(variant_overrides or {})
    if boutique_id is None:
        bq = create_boutique()
        boutique_id = bq["id"]
    else:
        bq = None
    style_overrides.setdefault("list_price_cents", list_price_cents)
    style = create_style(boutique_id, **style_overrides)
    variant_overrides.setdefault("on_hand", on_hand)
    variant = create_variant(style["id"], **variant_overrides)
    return bq, style, variant


def setup_basic_retail_scenario(tax_rate_bps=875, list_price_cents=5000, on_hand=5,
                                return_window_days=30):
    """Boutique + customer + style + one variant. The most common preamble.

    Returns (boutique, customer, style, variant).
    """
    bq = create_boutique(tax_rate_bps=tax_rate_bps, return_window_days=return_window_days)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=list_price_cents)
    variant = create_variant(style["id"], on_hand=on_hand)
    return bq, cu, style, variant


# ─── Tier 2: SalesOrder lifecycle shortcuts ───────────────────────────────

def open_order_with_line(customer_id, variant_id, qty=1):
    """Open a sales order and add one line. Returns (order, line)."""
    order = get_success_data(api_client.create_sales_order(
        create_sales_order_payload(customer_id), ASSOCIATE))
    line = get_success_data(api_client.create_order_line(
        order["id"], create_order_line_payload(variant_id, qty=qty), ASSOCIATE))
    return order, line


def create_authorized_order(customer_id, variant_id, qty=1):
    """Open → add line → authorize. Returns (order_after_authorize, line)."""
    order, line = open_order_with_line(customer_id, variant_id, qty=qty)
    authorized = get_success_data(api_client.authorize_order(order["id"], ASSOCIATE))
    return authorized, line


def create_captured_order(customer_id, variant_id, qty=1, redeem_store_credit=None):
    """Open → line → authorize → capture. Returns (order_after_capture, line)."""
    order, line = open_order_with_line(customer_id, variant_id, qty=qty)
    get_success_data(api_client.authorize_order(order["id"], ASSOCIATE))
    payload = {"redeem_store_credit": redeem_store_credit} if redeem_store_credit is not None else {}
    captured = get_success_data(api_client.capture_order(order["id"], ASSOCIATE, payload=payload))
    return captured, line


def create_completed_order(customer_id, variant_id, qty=1, redeem_store_credit=None):
    """Open → line → authorize → capture → complete. Returns (order_after_complete, line)."""
    order, line = open_order_with_line(customer_id, variant_id, qty=qty)
    get_success_data(api_client.authorize_order(order["id"], ASSOCIATE))
    payload = {"redeem_store_credit": redeem_store_credit} if redeem_store_credit is not None else {}
    get_success_data(api_client.capture_order(order["id"], ASSOCIATE, payload=payload))
    completed = get_success_data(api_client.complete_order(order["id"], ASSOCIATE))
    return completed, line


def setup_completed_order_scenario(tax_rate_bps=0, list_price_cents=5000, on_hand=5,
                                   return_window_days=30, qty=1):
    """Full chain: boutique + customer + style + variant + a completed order.

    Returns (boutique, customer, style, variant, order, line).
    """
    bq, cu, style, variant = setup_basic_retail_scenario(
        tax_rate_bps=tax_rate_bps, list_price_cents=list_price_cents,
        on_hand=on_hand, return_window_days=return_window_days)
    order, line = create_completed_order(cu["id"], variant["id"], qty=qty)
    return bq, cu, style, variant, order, line


def file_refund_return(order_id, line_id):
    """File a REFUND return against a completed order line. Returns the return."""
    return get_success_data(api_client.create_return(
        create_return_payload(order_id, line_id, resolution="REFUND"), ASSOCIATE))


def file_exchange_return(order_id, line_id, exchange_sku_variant_id):
    """File an EXCHANGE return. Returns the return."""
    return get_success_data(api_client.create_return(
        create_return_payload(order_id, line_id, resolution="EXCHANGE",
                              exchange_sku_variant_id=exchange_sku_variant_id), ASSOCIATE))


def setup_approved_refund_return(tax_rate_bps=875, list_price_cents=5000, return_window_days=30):
    """Completed order → REFUND return filed → approved.

    Returns (boutique, customer, style, variant, order, line, return_request).
    """
    bq, cu, style, variant, order, line = setup_completed_order_scenario(
        tax_rate_bps=tax_rate_bps, list_price_cents=list_price_cents,
        return_window_days=return_window_days)
    rr = file_refund_return(order["id"], line["id"])
    approved = get_success_data(api_client.approve_return(rr["id"], ASSOCIATE))
    return bq, cu, style, variant, order, line, approved


# ─── Tier 3: FittingRoomHold shortcuts ────────────────────────────────────

def create_hold(fitting_room_id, customer_id, sku_variant_id, start_minute=600,
                end_minute=660, headers=None):
    """Create an ACTIVE hold. Returns the hold entity."""
    payload = create_hold_payload(fitting_room_id, customer_id, sku_variant_id,
                                  start_minute=start_minute, end_minute=end_minute)
    res = api_client.create_hold(payload, headers or ASSOCIATE)
    return get_success_data(res)


def setup_room_with_hold(tax_rate_bps=875, on_hand=5, list_price_cents=5000):
    """Boutique + customer + style + variant + room + one ACTIVE hold.

    Returns (boutique, customer, style, variant, room, hold).
    """
    bq, cu, style, variant = setup_basic_retail_scenario(
        tax_rate_bps=tax_rate_bps, list_price_cents=list_price_cents, on_hand=on_hand)
    room = create_fitting_room(bq["id"])
    hold = create_hold(room["id"], cu["id"], variant["id"])
    return bq, cu, style, variant, room, hold


# ─── Tier 4: MarkdownSchedule shortcuts ───────────────────────────────────

def create_markdown(style_id, expected_style_version, phase="SEASONAL", markdown_pct=25,
                    effective_date=0):
    """Create a markdown schedule (DRAFT). Returns the schedule entity."""
    res = api_client.create_markdown_schedule(
        create_markdown_schedule_payload(
            style_id, expected_style_version, phase=phase,
            markdown_pct=markdown_pct, effective_date=effective_date),
        MERCH)
    return get_success_data(res)


def create_scheduled_markdown(style_id, expected_style_version, phase="SEASONAL",
                              markdown_pct=25, effective_date=0):
    """Create then schedule a markdown. Returns the schedule after SCHEDULED."""
    md = create_markdown(style_id, expected_style_version, phase=phase,
                         markdown_pct=markdown_pct, effective_date=effective_date)
    scheduled = get_success_data(api_client.schedule_markdown(md["id"], MERCH))
    return scheduled


def create_active_markdown(style_id, expected_style_version, phase="SEASONAL",
                           markdown_pct=25, effective_date=0):
    """Create → schedule → activate a markdown. Returns the schedule after ACTIVE."""
    md = create_scheduled_markdown(style_id, expected_style_version, phase=phase,
                                   markdown_pct=markdown_pct, effective_date=effective_date)
    active = get_success_data(api_client.activate_markdown(md["id"], MERCH))
    return active


# ─── Tier 5: Stylist / appointment shortcuts ──────────────────────────────

def create_appointment(stylist_id, customer_id, start_minute=600, end_minute=660, headers=None):
    """Request a styling appointment (REQUESTED). Returns the appointment."""
    res = api_client.create_appointment(
        create_appointment_payload(stylist_id, customer_id,
                                   start_minute=start_minute, end_minute=end_minute),
        headers or ASSOCIATE)
    return get_success_data(res)


def create_confirmed_appointment(stylist_id, customer_id, start_minute=600, end_minute=660):
    """Request → confirm an appointment. Returns the appointment after CONFIRMED."""
    ap = create_appointment(stylist_id, customer_id, start_minute=start_minute, end_minute=end_minute)
    confirmed = get_success_data(api_client.confirm_appointment(ap["id"], ASSOCIATE))
    return confirmed


# ─── Tier 6: SpecialOrder shortcuts ───────────────────────────────────────

def create_special_order(customer_id, source_sku_variant_id, qty=1, ship_to_state_code="WA",
                         headers=None):
    res = api_client.create_special_order(
        create_special_order_payload(customer_id, source_sku_variant_id, qty=qty,
                                     ship_to_state_code=ship_to_state_code),
        headers or ASSOCIATE)
    return get_success_data(res)


def create_sourced_special_order(customer_id, source_sku_variant_id, qty=1):
    """Place → source a special order. Returns the order after SOURCED."""
    so = create_special_order(customer_id, source_sku_variant_id, qty=qty)
    sourced = get_success_data(api_client.source_special_order(so["id"], ASSOCIATE))
    return sourced


# ─── Tier 7: Lookbook shortcuts ───────────────────────────────────────────

def create_lookbook(boutique_id, **overrides):
    res = api_client.create_lookbook(create_lookbook_payload(boutique_id, **overrides), MERCH)
    return get_success_data(res)


def create_published_lookbook(boutique_id, **overrides):
    """Create then publish a lookbook. Returns the lookbook after PUBLISHED."""
    lb = create_lookbook(boutique_id, **overrides)
    published = get_success_data(api_client.publish_lookbook(lb["id"], MERCH))
    return published


# ─── Helpers to drive a customer to a loyalty tier ────────────────────────

def push_customer_to_captured_spend(boutique_id, customer_id, target_cents):
    """Capture one order priced so net cash == target_cents (boutique tax 0).

    Requires the boutique to have tax_rate_bps == 0 and the customer to be
    STANDARD (so no loyalty discount) for net cash to equal the line total.
    Creates a fresh style/variant priced at target_cents and captures qty 1.
    Returns the captured order.
    """
    style = create_style(boutique_id, list_price_cents=target_cents)
    variant = create_variant(style["id"], on_hand=5)
    order, _ = create_captured_order(customer_id, variant["id"], qty=1)
    return order
