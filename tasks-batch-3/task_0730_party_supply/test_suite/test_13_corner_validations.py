"""Corner queue — validations section.

Excluded stub (clearance_non_returnable) is owned by difficulty rule 5
instance A in test_05.
"""
from test_helpers import (
    validate_error, api_client, ApiErrorId,
    make_store_manager_headers, make_store_clerk_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku_with_stock, create_helium_tank,
    setup_draft_order, attach_helium, reserve_order, pay_order,
    create_event_package, create_event_booking, create_sku,
)


def test_seasonal_window_closed_on_reserve_returns_error():
    """PRD §2.9: "If any line of an order at reserve time references a
    SKU whose seasonal window is set, the server clock must lie within
    the closed interval [seasonal_window_start, seasonal_window_end].
    Reserving outside the window is rejected with
    ERR_SEASONAL_WINDOW_CLOSED."

    Design: Corner/validations/seasonal_window_closed_on_reserve_returns_error
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(
        unit_price_cents=800, on_hand=20, category="SEASONAL_HALLOWEEN",
        seasonal_window_start="2026-10-01T00:00:00Z",
        seasonal_window_end="2026-10-31T23:59:59Z",
    )
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    resp = api_client.reserve_order(
        order["id"], order["version"], make_store_clerk_headers()
    )
    validate_error(resp, ApiErrorId.ERR_SEASONAL_WINDOW_CLOSED)


def test_insufficient_stock_on_reserve_returns_error():
    """PRD §2.8: "Available inventory for a new reservation is defined
    per line as on_hand_qty minus reserved_qty. If any line — SKU-based
    or bundle-based — would exceed this availability at reserve time,
    the reservation is rejected with ERR_INSUFFICIENT_STOCK."

    Design: Corner/validations/insufficient_stock_on_reserve_returns_error
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=3)
    order = setup_draft_order(cust["id"], sku["id"], qty=5)
    resp = api_client.reserve_order(
        order["id"], order["version"], make_store_clerk_headers()
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)


def test_helium_insufficient_on_reserve_returns_error():
    """PRD §2.10: "If the sum of remaining_cubic_ft across all ACTIVE
    tanks falls short of the required amount, the reservation is
    rejected with ERR_HELIUM_INSUFFICIENT."

    Design: Corner/validations/helium_insufficient_on_reserve_returns_error
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=5)
    create_helium_tank(capacity=5)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    # required = 40 * 0.5 = 20 cu.ft; tank has only 5.
    attach_helium(order["id"], latex_count=40, foil_count=0)
    resp = api_client.reserve_order(
        order["id"], order["version"], make_store_clerk_headers()
    )
    validate_error(resp, ApiErrorId.ERR_HELIUM_INSUFFICIENT)


def test_clearance_pct_out_of_range_upper_returns_error():
    """PRD §3.1: "Moving a SKU from is_clearance false to is_clearance
    true requires the manager to supply a pct value that is strictly
    greater than zero and at most nine-tenths — a value outside this
    range is rejected with ERR_CLEARANCE_PCT_OUT_OF_RANGE."

    Design: Corner/validations/clearance_pct_out_of_range_returns_error
    """
    sku = create_sku(unit_price_cents=100, category="DECOR")
    resp = api_client.clearance_sku(
        sku["id"],
        {"pct": 0.95, "expected_sku_version": sku["version"]},
        make_store_manager_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_PCT_OUT_OF_RANGE)


def test_rental_category_invalid_on_non_tableware():
    """PRD §3.6: "The referenced SKU must have category equal to
    TABLEWARE; a contract that names any other category is rejected
    with ERR_RENTAL_CATEGORY_INVALID."

    Design: Corner/validations/rental_category_invalid_on_non_tableware_sku
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=10,
                                 category="BALLOON_LATEX")
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    resp = api_client.create_rental_contract(
        {"order_id": order["id"], "sku_id": sku["id"], "qty": 1,
         "rental_start": "2026-06-20T00:00:00Z",
         "rental_end": "2026-06-21T00:00:00Z"},
        make_store_clerk_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_RENTAL_CATEGORY_INVALID)


def test_event_lead_too_short_on_confirm():
    """PRD §3.8: "Confirming a booking transitions HELD to CONFIRMED.
    This is permitted only when the parent order's payment_status is
    DEPOSIT_HELD or PAID, and when event_date minus the server clock is
    at least min_lead_days — a shorter lead time is rejected with
    ERR_EVENT_LEAD_TOO_SHORT."

    Design: Corner/validations/event_lead_too_short_on_confirm
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=5)
    pkg = create_event_package(base_price_cents=30000, deposit_pct=0.20,
                                 min_lead_days=14)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    booking = create_event_booking(order["id"], pkg["id"],
                                    "2026-06-20T18:00:00Z")
    reserved = reserve_order(order["id"], order["version"])
    pay_order(reserved["id"], "FULL")
    # event_date - now = 5 days < min_lead_days=14.
    resp = api_client.confirm_event_booking(
        booking["id"], make_store_clerk_headers()
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_LEAD_TOO_SHORT)


def test_deposit_not_applicable_without_event_or_rental():
    """PRD §3.5: "When mode is DEPOSIT, the request records a partial
    payment: it is accepted only while the order is RESERVED and the
    order has either an attached EventBooking or an attached
    RentalContract; otherwise the request is rejected with
    ERR_DEPOSIT_NOT_APPLICABLE."

    Design: Corner/validations/deposit_not_applicable_without_event_or_rental
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=5)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    reserved = reserve_order(order["id"], order["version"])
    # Retail Order — no rental, no event booking.
    resp = api_client.pay_order(
        reserved["id"], "DEPOSIT", make_store_clerk_headers()
    )
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_APPLICABLE)
