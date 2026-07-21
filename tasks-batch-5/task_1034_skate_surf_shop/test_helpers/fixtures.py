"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness re-launches the server with an empty database before each
test). Helpers use get_success_data() (lenient) so setup failures surface as
clear "Setup failed" errors. Each takes the ApiClient `api` as first argument.

Identity threading: the Customer role is entity_backed, so any Customer-owned
call passes make_customer_headers(customer_id) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_customer_headers
from . import factories as f

SM = TEST_USERS["shop_manager_headers"]
BT = TEST_USERS["bench_tech_headers"]
SA = TEST_USERS["sales_associate_headers"]


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #
def set_clock(api, iso: str):
    """Advance the logical clock (ShopManager-only, PRD Section 2.9)."""
    return get_success_data(api.set_clock({"to_iso8601": iso}, SM))


# --------------------------------------------------------------------------- #
# Simple entity creators
# --------------------------------------------------------------------------- #
def create_customer(api, **overrides) -> dict:
    return get_success_data(api.create_customer(f.create_customer_payload(**overrides), SA))


def create_product(api, **overrides) -> dict:
    return get_success_data(api.create_product(f.create_product_payload(**overrides), SM))


def create_rentable_product(api, **overrides) -> dict:
    return get_success_data(api.create_product(f.create_rentable_product_payload(**overrides), SM))


def create_product_with_stock(api, on_hand: int, **overrides) -> dict:
    """Create a product then adjust its on_hand_qty to `on_hand`."""
    prod = create_product(api, **overrides)
    if on_hand:
        prod = get_success_data(
            api.adjust_inventory(prod["id"], {"delta_on_hand": on_hand}, SM)
        )
    return prod


def create_coach(api, **overrides) -> dict:
    return get_success_data(api.create_coach(f.create_coach_payload(**overrides), SM))


def create_rental_asset(api, product_id, **overrides) -> dict:
    return get_success_data(
        api.create_rental_asset(f.create_rental_asset_payload(product_id, **overrides), SM)
    )


def create_rentable_product_and_asset(api, product_overrides=None, asset_overrides=None):
    """Return (product, asset) — a rentable product with one physical unit."""
    prod = create_rentable_product(api, **(product_overrides or {}))
    asset = create_rental_asset(api, prod["id"], **(asset_overrides or {}))
    return prod, asset


# --------------------------------------------------------------------------- #
# Lessons
# --------------------------------------------------------------------------- #
def create_scheduled_lesson(api, coach_id, customer_id, **overrides) -> dict:
    return get_success_data(
        api.create_lesson(f.create_lesson_payload(coach_id, customer_id, **overrides), SA)
    )


def setup_coach_customer_lesson(api, lesson_overrides=None):
    """Return (coach, customer, lesson) with a single SCHEDULED lesson."""
    coach = create_coach(api)
    customer = create_customer(api)
    lesson = create_scheduled_lesson(
        api, coach["id"], customer["id"], **(lesson_overrides or {})
    )
    return coach, customer, lesson


# --------------------------------------------------------------------------- #
# Rentals
# --------------------------------------------------------------------------- #
def create_rental(api, customer_id, rental_asset_id, **overrides) -> dict:
    return get_success_data(
        api.create_rental(
            f.create_rental_payload(customer_id, rental_asset_id, **overrides), SA
        )
    )


def setup_reserved_rental(api, rental_overrides=None):
    """Rentable product + asset + customer + a RESERVED rental. Returns
    (product, asset, customer, rental)."""
    prod, asset = create_rentable_product_and_asset(api)
    customer = create_customer(api)
    rental = create_rental(api, customer["id"], asset["id"], **(rental_overrides or {}))
    return prod, asset, customer, rental


def setup_checked_out_rental(api, rental_overrides=None):
    """As setup_reserved_rental, then checkout. Returns
    (product, asset, customer, rental_after_checkout)."""
    prod, asset, customer, rental = setup_reserved_rental(api, rental_overrides)
    rental = get_success_data(api.checkout_rental(rental["id"], SA))
    return prod, asset, customer, rental


# --------------------------------------------------------------------------- #
# Board builds
# --------------------------------------------------------------------------- #
def create_draft_board_build(api, customer_id, components) -> dict:
    return get_success_data(
        api.create_board_build(f.create_board_build_payload(customer_id, components), BT)
    )


def setup_reserved_board_build(api, on_hand=8, qty=3, unit_price_cents=5000):
    """Customer + product (on_hand) + a build (single component qty) reserved.
    Returns (customer, product, build_after_reserve)."""
    customer = create_customer(api)
    prod = create_product_with_stock(api, on_hand, unit_price_cents=unit_price_cents)
    build = create_draft_board_build(
        api, customer["id"], [{"product_id": prod["id"], "qty": qty}]
    )
    build = get_success_data(api.reserve_board_build(build["id"], BT))
    return customer, prod, build


# --------------------------------------------------------------------------- #
# Service tickets
# --------------------------------------------------------------------------- #
def create_service_ticket(api, customer_id, parts, labor_cents) -> dict:
    return get_success_data(
        api.create_service_ticket(
            f.create_service_ticket_payload(customer_id, parts, labor_cents), BT
        )
    )


# --------------------------------------------------------------------------- #
# Trade-ins
# --------------------------------------------------------------------------- #
def create_trade_in(api, customer_id, mode="TRADE_IN", **overrides) -> dict:
    return get_success_data(
        api.create_trade_in(f.create_trade_in_payload(customer_id, mode, **overrides), SA)
    )


def setup_appraised_trade_in(api, appraised_value_cents, mode="TRADE_IN", **overrides):
    """Customer + a TradeIn appraised at `appraised_value_cents`. Returns
    (customer, trade_in_after_appraise)."""
    customer = create_customer(api)
    ti = create_trade_in(api, customer["id"], mode=mode, **overrides)
    ti = get_success_data(
        api.appraise_trade_in(ti["id"], {"appraised_value_cents": appraised_value_cents}, SM)
    )
    return customer, ti


def setup_listed_consignment(api, appraised_value_cents, list_price_cents):
    """Customer + a CONSIGNMENT appraised then accepted (LISTED). Returns
    (customer, trade_in_listed)."""
    customer, ti = setup_appraised_trade_in(
        api, appraised_value_cents, mode="CONSIGNMENT", list_price_cents=list_price_cents
    )
    ti = get_success_data(
        api.accept_trade_in(ti["id"], {}, make_customer_headers(customer["id"]))
    )
    return customer, ti


# --------------------------------------------------------------------------- #
# Special orders
# --------------------------------------------------------------------------- #
def create_special_order(api, customer_id, product_id, quantity=1) -> dict:
    return get_success_data(
        api.create_special_order(
            f.create_special_order_payload(customer_id, product_id, quantity), SA
        )
    )


def setup_quoted_special_order(api, quoted_price_cents=15000, quantity=1,
                               product_overrides=None):
    """Customer + product + a SpecialOrder quoted once (status QUOTED). Returns
    (customer, product, order_after_quote)."""
    customer = create_customer(api)
    prod = create_product(api, category="COMPLETE", **(product_overrides or {}))
    order = create_special_order(api, customer["id"], prod["id"], quantity)
    order = get_success_data(
        api.quote_special_order(order["id"], {"quoted_price_cents": quoted_price_cents}, SM)
    )
    return customer, prod, order


# --------------------------------------------------------------------------- #
# Events / entries
# --------------------------------------------------------------------------- #
def create_published_event(api, **overrides) -> dict:
    event = get_success_data(api.create_event(f.create_event_payload(**overrides), SM))
    event = get_success_data(api.publish_event(event["id"], SM))
    return event


def create_registered_entry(api, event_id, customer_id, **overrides) -> dict:
    """Register `customer_id` for `event_id` acting as that Customer (ownership)."""
    headers = make_customer_headers(customer_id)
    payload = f.create_event_entry_payload(event_id, customer_id, **overrides)
    return get_success_data(api.create_event_entry(payload, headers))


def setup_registered_entry(api, event_overrides=None, entry_overrides=None):
    """Customer + PUBLISHED event + one REGISTERED entry. Returns
    (customer, event, entry)."""
    customer = create_customer(api)
    event = create_published_event(api, **(event_overrides or {}))
    entry = create_registered_entry(
        api, event["id"], customer["id"], **(entry_overrides or {})
    )
    return customer, event, entry
