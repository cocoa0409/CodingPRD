"""Validation precedence within a business operation (PRD §2.8 + §3.6).

PRD §2.8 states the relative ordering of an operation's own business checks is
stated alongside that operation in §3; §3.6 lists check-in and checkout
preconditions in a fixed prose order. These tests pin the winning error when two
of those ordered checks fail simultaneously.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    setup_shop_with_barber_chair_shift,
    book_appointment,
    check_in,
    set_lines,
    set_clock,
    TEST_USERS,
)

OWNER = TEST_USERS["shop_owner_headers"]
RECEPTION = TEST_USERS["receptionist_headers"]


def test_shop_closed_reported_over_barber_not_active_on_checkin(api):
    """PRD §3.6: "Checking in a `BOOKED` appointment is a `Receptionist`-or-
    `ShopOwner` action requiring an `OPEN` shop (`ERR_SHOP_CLOSED`), the barber's
    `license_status` of `ACTIVE` (`ERR_BARBER_NOT_ACTIVE`), and the customer's
    `status` of `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`)."
    PRD §2.8: "Within an individual business operation, the relative ordering of
    its own business checks is stated alongside that operation in §3."

    Design: Difficulty/priority_pair_validation_conflict/shop_closed_beats_barber_not_active_on_checkin
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Conflict Shop", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    appt = book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    # Make BOTH preconditions fail: suspend the barber AND close the shop.
    validate_success(api.suspend_license(ctx["barber"]["id"], OWNER), 200)
    validate_success(api.close_shop(ctx["shop"]["id"], OWNER), 200)
    res = api.check_in_appointment(appt["id"], RECEPTION)
    validate_error(res, "ERR_SHOP_CLOSED")


def test_barber_not_active_reported_when_only_failing_checkin(api):
    """PRD §3.6: "Checking in a `BOOKED` appointment is a `Receptionist`-or-
    `ShopOwner` action requiring an `OPEN` shop (`ERR_SHOP_CLOSED`), the barber's
    `license_status` of `ACTIVE` (`ERR_BARBER_NOT_ACTIVE`), and the customer's
    `status` of `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`)."

    Design: Difficulty/priority_pair_validation_conflict/shop_closed_beats_barber_not_active_on_checkin
    """
    # Only the barber-active precondition fails (shop stays OPEN), so the loser
    # error of the precedence pair surfaces in isolation — confirming it is a real
    # candidate that the shop-closed check pre-empts when both fail.
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Conflict Shop", "tax_rate_pct": 0, "late_grace_minutes": 1000},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    appt = book_appointment(ctx, start_utc="2026-06-10T09:30:00Z")
    set_clock("2026-06-10T10:00:00Z")
    validate_success(api.suspend_license(ctx["barber"]["id"], OWNER), 200)
    still = validate_success(api.get_appointment(appt["id"], OWNER), 200)
    assert still["status"] == "BOOKED", still
    res = api.check_in_appointment(appt["id"], RECEPTION)
    validate_error(res, "ERR_BARBER_NOT_ACTIVE")


def test_item_delisted_reported_over_insufficient_stock_on_checkout(api):
    """PRD §3.6: "it enforces a battery of preconditions: the shop must be `OPEN`
    (`ERR_SHOP_CLOSED`); the barber's `license_status` must be `ACTIVE`
    (`ERR_BARBER_NOT_ACTIVE`); every catalog line must be `LISTED`
    (`ERR_ITEM_DELISTED`); every product line must have `stock_qty` at least its
    `qty` (`ERR_INSUFFICIENT_STOCK`)".
    PRD §2.8: "Within an individual business operation, the relative ordering of
    its own business checks is stated alongside that operation in §3."

    Design: Difficulty/priority_pair_validation_conflict/item_delisted_beats_insufficient_stock_on_checkout
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Stock Shop", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    product = get_success_data(api.create_product(
        {"shop_id": ctx["shop"]["id"], "name": "Pomade", "price_cents": 1200,
         "stock_qty": 1}, OWNER))
    appt = book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    checked = check_in(appt["id"])
    # Product line both over-stock (qty 5 > 1) AND about to be delisted.
    set_lines(
        checked["ticket_id"],
        service_line_ids=[ctx["service"]["id"]],
        product_lines=[{"product_sku_id": product["id"], "qty": 5}],
    )
    validate_success(api.delist_product(product["id"], OWNER), 200)
    res = api.checkout_ticket(checked["ticket_id"], RECEPTION)
    validate_error(res, "ERR_ITEM_DELISTED")


def test_insufficient_stock_reported_when_only_failing_checkout(api):
    """PRD §3.6: "it enforces a battery of preconditions: the shop must be `OPEN`
    (`ERR_SHOP_CLOSED`); the barber's `license_status` must be `ACTIVE`
    (`ERR_BARBER_NOT_ACTIVE`); every catalog line must be `LISTED`
    (`ERR_ITEM_DELISTED`); every product line must have `stock_qty` at least its
    `qty` (`ERR_INSUFFICIENT_STOCK`)".

    Design: Difficulty/priority_pair_validation_conflict/item_delisted_beats_insufficient_stock_on_checkout
    """
    # Product stays LISTED but is over-stock, so only the stock check fails — the
    # loser error of the precedence pair surfaces in isolation.
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Stock Shop", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    product = get_success_data(api.create_product(
        {"shop_id": ctx["shop"]["id"], "name": "Pomade", "price_cents": 1200,
         "stock_qty": 1}, OWNER))
    appt = book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    checked = check_in(appt["id"])
    set_lines(
        checked["ticket_id"],
        service_line_ids=[ctx["service"]["id"]],
        product_lines=[{"product_sku_id": product["id"], "qty": 5}],
    )
    res = api.checkout_ticket(checked["ticket_id"], RECEPTION)
    validate_error(res, "ERR_INSUFFICIENT_STOCK")
