"""Composite setup helpers for the produce terminal market tests.

Every helper builds preconditions from scratch against an empty database using
only PRD-declared endpoints, using get_success_data so setup failures surface as
clear 'Setup failed' errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_commodity_payload,
    create_customer_payload,
    create_daily_price_payload,
    create_inspection_payload,
    create_labor_ticket_payload,
    create_payment_payload,
    create_purchase_lot_payload,
    create_ripening_booking_payload,
    create_ripening_room_payload,
    create_sales_order_payload,
    create_shipper_payload,
    create_shrink_record_payload,
    create_temperature_reading_payload,
    order_line,
    update_customer_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    BILLING_HEADERS,
    INSPECTOR_HEADERS,
    RECEIVER_HEADERS,
    SALES_HEADERS,
)

CLOCK_START = TEST_DEFAULTS["CLOCK_START"]
MARKET_DATE = TEST_DEFAULTS["MARKET_DATE"]
DELIVERY_DATE = TEST_DEFAULTS["DELIVERY_DATE"]


# --- Tier 0: primitives ------------------------------------------------------

def set_clock(to_iso8601=CLOCK_START):
    """Move the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN_HEADERS))


def create_commodity(**overrides):
    return get_success_data(
        api_client.create_commodity(create_commodity_payload(**overrides), ADMIN_HEADERS))


def create_shipper(**overrides):
    return get_success_data(
        api_client.create_shipper(create_shipper_payload(**overrides), ADMIN_HEADERS))


def post_daily_price(commodity_id, **overrides):
    return get_success_data(
        api_client.create_daily_price(
            create_daily_price_payload(commodity_id, **overrides), ADMIN_HEADERS))


def create_customer(**overrides):
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN_HEADERS))


def create_room(**overrides):
    return get_success_data(
        api_client.create_ripening_room(create_ripening_room_payload(**overrides),
                                        ADMIN_HEADERS))


def get_lot(lot_id):
    return get_success_data(api_client.get_purchase_lot(lot_id, RECEIVER_HEADERS))


def get_order(order_id):
    return get_success_data(api_client.get_sales_order(order_id, SALES_HEADERS))


def get_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, BILLING_HEADERS))


def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, ADMIN_HEADERS))


def get_shipper(shipper_id):
    return get_success_data(api_client.get_shipper(shipper_id, ADMIN_HEADERS))


def list_credit_memos(lot_id):
    return get_success_data(api_client.list_lot_credit_memos(lot_id, BILLING_HEADERS))


# --- Tier 1: market-day base and lot state progression -----------------------

def setup_market_day(commodity_overrides=None, low_price=8.00, high_price=12.00,
                     market_date=MARKET_DATE, clock=CLOCK_START):
    """Clock + commodity + shipper + posted daily price. Returns a dict of the three."""
    if clock is not None:
        set_clock(clock)
    commodity = create_commodity(**(commodity_overrides or {}))
    shipper = create_shipper()
    price = post_daily_price(commodity["id"], market_date=market_date,
                             low_price=low_price, high_price=high_price)
    return {"commodity": commodity, "shipper": shipper, "price": price}


def create_ordered_lot(shipper_id, commodity_id, **overrides):
    return get_success_data(
        api_client.create_purchase_lot(
            create_purchase_lot_payload(shipper_id, commodity_id, **overrides),
            RECEIVER_HEADERS))


def receive_lot(lot_id):
    return get_success_data(api_client.receive_lot(lot_id, RECEIVER_HEADERS))


def file_inspection(lot_id, **overrides):
    return get_success_data(
        api_client.create_inspection(create_inspection_payload(lot_id, **overrides),
                                     INSPECTOR_HEADERS))


def certify_inspection(inspection_id):
    return get_success_data(api_client.certify_inspection(inspection_id, INSPECTOR_HEADERS))


def create_received_lot(shipper_id, commodity_id, **overrides):
    """Lot walked ORDERED -> RECEIVED. Returns the received lot."""
    lot = create_ordered_lot(shipper_id, commodity_id, **overrides)
    return receive_lot(lot["id"])


def create_accepted_lot(shipper_id, commodity_id, defect_pct=0, **overrides):
    """Lot walked ORDERED -> RECEIVED -> INSPECTED -> ACCEPTED via a certified
    PASS inspection with the given defect_pct. Returns the accepted lot."""
    lot = create_received_lot(shipper_id, commodity_id, **overrides)
    inspection = file_inspection(lot["id"], defect_pct=defect_pct, result="PASS")
    certify_inspection(inspection["id"])
    return get_lot(lot["id"])


def create_disputed_lot(shipper_id, commodity_id, defect_pct=25, **overrides):
    """Lot driven RECEIVED -> FAIL inspection CERTIFIED -> DISPUTED.
    Returns (lot_after_dispute, fail_inspection)."""
    lot = create_received_lot(shipper_id, commodity_id, **overrides)
    inspection = file_inspection(lot["id"], inspected_grade="US2",
                                 defect_pct=defect_pct, result="FAIL")
    certify_inspection(inspection["id"])
    lot = get_success_data(
        api_client.dispute_lot(lot["id"], {"reason": "grade below contract"},
                               RECEIVER_HEADERS))
    return lot, inspection


def setup_accepted_lot(defect_pct=0, quantity=100, unit_price=10.00, clock=CLOCK_START,
                       **commodity_overrides):
    """Full market-day base plus one ACCEPTED lot. Returns dict with keys
    commodity, shipper, price, lot."""
    base = setup_market_day(clock=clock, **({"commodity_overrides": commodity_overrides}
                                            if commodity_overrides else {}))
    lot = create_accepted_lot(base["shipper"]["id"], base["commodity"]["id"],
                              defect_pct=defect_pct, quantity_units=quantity,
                              shipper_unit_price=unit_price)
    base["lot"] = lot
    return base


# --- Tier 2: orders ----------------------------------------------------------

def create_pending_order(customer_id, lot_id, quantity=1, unit_price=10.00,
                         delivery_date=DELIVERY_DATE, window_start="08:00",
                         window_end="10:00", pallet_count=None, headers=None):
    lines = [order_line(lot_id, quantity, unit_price)]
    payload = create_sales_order_payload(
        customer_id, lines, delivery_date=delivery_date,
        window_start=window_start, window_end=window_end)
    if pallet_count is not None:
        payload["pallet_count"] = pallet_count
    return get_success_data(
        api_client.create_sales_order(payload, headers or SALES_HEADERS))


def confirm_order(order_id):
    return get_success_data(api_client.confirm_order(order_id, SALES_HEADERS))


def create_confirmed_order(customer_id, lot_id, **kwargs):
    order = create_pending_order(customer_id, lot_id, **kwargs)
    return confirm_order(order["id"])


def create_delivered_order(customer_id, lot_id, **kwargs):
    order = create_confirmed_order(customer_id, lot_id, **kwargs)
    get_success_data(api_client.pick_order(order["id"], RECEIVER_HEADERS))
    return get_success_data(api_client.deliver_order(order["id"], RECEIVER_HEADERS))


def create_invoiced_order(customer_id, lot_id, **kwargs):
    """Delivered order + issued invoice. Returns (order_after_invoice, invoice)."""
    order = create_delivered_order(customer_id, lot_id, **kwargs)
    invoice = get_success_data(
        api_client.create_invoice({"sales_order_id": order["id"]}, BILLING_HEADERS))
    return get_order(order["id"]), invoice


# --- Tier 3: ripening bookings ----------------------------------------------

def create_booking(room_id, lot_id, start_time="2026-05-02T10:00:00Z",
                   end_time="2026-05-02T12:00:00Z", pallet_count=4,
                   ethylene_enabled=False, target_stage="STAGE_4"):
    return get_success_data(
        api_client.create_ripening_booking(
            create_ripening_booking_payload(
                room_id, lot_id, start_time=start_time, end_time=end_time,
                pallet_count=pallet_count, ethylene_enabled=ethylene_enabled,
                target_stage=target_stage),
            RECEIVER_HEADERS))


# --- Tier 4: shrink / credit memos ------------------------------------------

def create_shrink(lot_id, quantity=10, reason="DUMP"):
    return get_success_data(
        api_client.create_shrink_record(
            create_shrink_record_payload(lot_id, quantity=quantity, reason=reason),
            RECEIVER_HEADERS))


def approve_shrink(shrink_id):
    return get_success_data(api_client.approve_shrink_record(shrink_id, ADMIN_HEADERS))


def create_approved_shrink(lot_id, quantity=10, reason="DUMP"):
    """DRAFT shrink approved by MarketAdmin; CreditMemo ISSUED. Returns the
    approved shrink record (with credit_memo_id set)."""
    shrink = create_shrink(lot_id, quantity=quantity, reason=reason)
    return approve_shrink(shrink["id"])


# --- Tier 5: payments, day-close, dispute resolution -------------------------

def post_payment(invoice_id, amount_cents):
    return get_success_data(
        api_client.create_payment(create_payment_payload(invoice_id, amount_cents),
                                  BILLING_HEADERS))


def run_day_close():
    return get_success_data(api_client.run_day_close(ADMIN_HEADERS))


def resolve_dispute(lot_id, outcome, agreed_unit_price=None):
    payload = {"outcome": outcome}
    if agreed_unit_price is not None:
        payload["agreed_unit_price"] = agreed_unit_price
    return get_success_data(api_client.resolve_dispute(lot_id, payload, ADMIN_HEADERS))


def patch_customer(customer_id, expected_version, **fields):
    return get_success_data(
        api_client.update_customer(
            customer_id,
            update_customer_payload(expected_version, **fields),
            ADMIN_HEADERS))


# --- Composite scenarios -----------------------------------------------------

def setup_lot_with_certified_defect(defect_pct=20, quantity=100, unit_price=10.00):
    """Market day + lot whose PASS inspection with the given defect_pct is
    CERTIFIED (final landed cost has run). Returns dict with shipper, lot."""
    base = setup_accepted_lot(defect_pct=defect_pct, quantity=quantity,
                              unit_price=unit_price)
    return base


def setup_confirmed_order_on_accepted_lot(line_quantity=10, line_unit_price=10.00,
                                          customer_limit=1000000, pallet_count=None):
    """Market day + ACCEPTED lot + ACTIVE customer + one CONFIRMED order.
    Returns dict with shipper, lot, customer, order."""
    base = setup_accepted_lot(defect_pct=0)
    customer = create_customer(credit_limit_cents=customer_limit)
    order = create_confirmed_order(customer["id"], base["lot"]["id"],
                                   quantity=line_quantity, unit_price=line_unit_price,
                                   pallet_count=pallet_count)
    base["customer"] = customer
    base["order"] = order
    return base


def setup_invoiced_scenario(terms_days=10, pallet_count=1, line_quantity=1,
                            line_unit_price=50.00, customer_limit=1000000):
    """Market day + ACCEPTED lot + customer + order driven to DELIVERED and
    INVOICED. Returns dict with lot, customer, order, invoice."""
    base = setup_accepted_lot(defect_pct=0)
    customer = create_customer(credit_limit_cents=customer_limit, terms_days=terms_days)
    order, invoice = create_invoiced_order(
        customer["id"], base["lot"]["id"], quantity=line_quantity,
        unit_price=line_unit_price, pallet_count=pallet_count)
    base["customer"] = customer
    base["order"] = order
    base["invoice"] = invoice
    return base


def setup_credit_hold_scenario():
    """Full PACA trust-claim cascade scenario.

    Builds: ACCEPTED lot (100 @ 10.00); customer with terms 10 and a huge limit;
    order1 (1 @ 50.00, pallet 1, window 08:00-10:00) delivered and invoiced on
    2026-05-01 (total 7500, due 2026-05-11); order2 (2 @ 50.00, 10:00-12:00)
    CONFIRMED. Then day-close at 2026-05-12 marks the invoice PAST_DUE, and
    day-close at 2026-06-12 marks it TRUST_CLAIMED, suspending the customer and
    CREDIT-holding order2. Returns dict with lot, customer, order1, invoice1,
    order2, close1, close2.
    """
    base = setup_accepted_lot(defect_pct=0)
    customer = create_customer(credit_limit_cents=100000000, terms_days=10)
    lot_id = base["lot"]["id"]
    order1, invoice1 = create_invoiced_order(
        customer["id"], lot_id, quantity=1, unit_price=50.00, pallet_count=1,
        window_start="08:00", window_end="10:00")
    order2 = create_confirmed_order(
        customer["id"], lot_id, quantity=2, unit_price=50.00, pallet_count=1,
        window_start="10:00", window_end="12:00")
    set_clock("2026-05-12T09:00:00Z")
    close1 = run_day_close()
    set_clock("2026-06-12T09:00:00Z")
    close2 = run_day_close()
    base.update({
        "customer": customer,
        "order1": order1,
        "invoice1": invoice1,
        "order2": order2,
        "close1": close1,
        "close2": close2,
    })
    return base
