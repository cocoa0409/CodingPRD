"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup step failed" errors rather than confusing assertion failures.

The test harness restarts the API server before every test, so every fixture
builds its preconditions from scratch against an empty database, using only
PRD-declared endpoints. The logical clock resets to 2026-07-01T00:00:00Z per test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_member_payload, create_product_payload, create_product_stock_payload,
    create_inventory_item_payload, create_pre_order_payload, create_trade_in_payload,
    create_rental_payload, create_sale_payload, sale_line, create_station_payload,
    create_tournament_payload, payment_payload, adjustment_payload, grade_payload,
    clock_payload,
)
from .test_users import TEST_USERS

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── Primitive single-entity builders ─────────────────────────────────────
def create_member(full_name="Test Member", tier=None, email=None):
    payload = create_member_payload(full_name=full_name)
    if tier is not None:
        payload["tier"] = tier
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_member(payload, CLERK))


def create_product(**overrides):
    return get_success_data(api_client.create_product(create_product_payload(**overrides), CLERK))


def create_inventory_item(product_id, condition_grade="A", **overrides):
    payload = create_inventory_item_payload(condition_grade=condition_grade, **overrides)
    return get_success_data(api_client.create_inventory_item(product_id, payload, CLERK))


def create_stock(product_id, unit_price_cents=6000, deposit_cents=2000, total_count=1):
    payload = create_product_stock_payload(
        unit_price_cents=unit_price_cents, deposit_cents=deposit_cents, total_count=total_count)
    return get_success_data(api_client.create_product_stock(product_id, payload, MANAGER))


def release_stock(stock_id):
    return get_success_data(api_client.release_product_stock(stock_id, MANAGER))


def get_stock_version(stock_id):
    stock = get_success_data(api_client.get_product_stock(stock_id, CLERK))
    return stock["version"]


def place_pre_order(member_id, stock_id, expected_version=None, headers=CLERK):
    """Create a pre-order, auto-refreshing the pool version unless one is given."""
    if expected_version is None:
        expected_version = get_stock_version(stock_id)
    payload = create_pre_order_payload(member_id, stock_id, expected_version)
    return get_success_data(api_client.create_pre_order(payload, headers))


def pay_pre_order(pre_order_id, amount_cents, headers=CLERK):
    return get_success_data(
        api_client.pay_pre_order(pre_order_id, payment_payload(amount_cents), headers))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), MANAGER))


# ─── Tier: Pool + pre-order state progression ─────────────────────────────
def setup_embargoed_pool(unit_price_cents=6000, deposit_cents=2000, total_count=2):
    """Product + EMBARGOED ProductStock. Returns (product, stock)."""
    product = create_product()
    stock = create_stock(product["id"], unit_price_cents, deposit_cents, total_count)
    return product, stock


def setup_released_pool(unit_price_cents=6000, deposit_cents=2000, total_count=1):
    """Product + RELEASED ProductStock. Returns (product, stock_after_release)."""
    product = create_product()
    stock = create_stock(product["id"], unit_price_cents, deposit_cents, total_count)
    stock = release_stock(stock["id"])
    return product, stock


def setup_allocated_preorder(unit_price_cents=6000, deposit_cents=2000, total_count=1):
    """RELEASED pool + a member holding a single ALLOCATED pre-order.
    Returns (member, product, stock, pre_order)."""
    member = create_member()
    product, stock = setup_released_pool(unit_price_cents, deposit_cents, total_count)
    pre_order = place_pre_order(member["id"], stock["id"])
    return member, product, stock, pre_order


def setup_waitlisted_preorder(unit_price_cents=6000, deposit_cents=2000, total_count=2):
    """EMBARGOED pool + a member with one WAITLISTED pre-order.
    Returns (member, product, stock, pre_order)."""
    member = create_member()
    product, stock = setup_embargoed_pool(unit_price_cents, deposit_cents, total_count)
    pre_order = place_pre_order(member["id"], stock["id"])
    return member, product, stock, pre_order


def setup_allocated_paid_fulfilled_preorder():
    """RELEASED pool total=1; member with ALLOCATED, PAID_IN_FULL, then FULFILLED pre-order.
    Returns (member, product, stock, pre_order_after_fulfill)."""
    member, product, stock, pre_order = setup_allocated_preorder(
        unit_price_cents=6000, deposit_cents=2000, total_count=1)
    pay_pre_order(pre_order["id"], 6000)
    fulfilled = get_success_data(api_client.fulfill_pre_order(pre_order["id"], CLERK))
    return member, product, stock, fulfilled


# ─── Tier: Trade-in lifecycle shortcuts ───────────────────────────────────
def setup_submitted_tradein(base_trade_value_cents=10000, stated_grade="A",
                            payout_method="STORE_CREDIT"):
    """Member + product + a SUBMITTED trade-in. Returns (member, product, trade_in)."""
    member = create_member()
    product = create_product(base_trade_value_cents=base_trade_value_cents)
    payload = create_trade_in_payload(
        member["id"], product["id"], stated_grade=stated_grade, payout_method=payout_method)
    trade_in = get_success_data(api_client.create_trade_in(payload, CLERK))
    return member, product, trade_in


def setup_offered_tradein(base_trade_value_cents=10000, stated_grade="A",
                          final_grade="A", payout_method="STORE_CREDIT"):
    """Trade-in graded to final_grade (status OFFERED). Returns (member, product, trade_in)."""
    member, product, trade_in = setup_submitted_tradein(
        base_trade_value_cents, stated_grade, payout_method)
    trade_in = get_success_data(
        api_client.grade_trade_in(trade_in["id"], grade_payload(final_grade), CLERK))
    return member, product, trade_in


def setup_settled_tradein(base_trade_value_cents=10000, stated_grade="A",
                          final_grade="A", payout_method="STORE_CREDIT"):
    """Trade-in graded and accepted (status SETTLED). Returns (member, product, trade_in)."""
    member, product, trade_in = setup_offered_tradein(
        base_trade_value_cents, stated_grade, final_grade, payout_method)
    trade_in = get_success_data(api_client.accept_trade_in(trade_in["id"], CLERK))
    return member, product, trade_in


# ─── Tier: Rental lifecycle shortcuts ─────────────────────────────────────
def setup_available_item(daily_rental_rate_cents=500, condition_grade="A", **product_overrides):
    """Product (CONSOLE) + one AVAILABLE inventory unit. Returns (member, product, item)."""
    member = create_member()
    product = create_product(
        kind="CONSOLE", daily_rental_rate_cents=daily_rental_rate_cents, **product_overrides)
    item = create_inventory_item(product["id"], condition_grade)
    return member, product, item


def setup_reserved_rental(daily_rental_rate_cents=500,
                          start_at="2026-07-02T00:00:00Z", due_at="2026-07-05T00:00:00Z"):
    """Member + product + AVAILABLE item + a RESERVED rental over [start_at, due_at).
    Returns (member, product, item, rental)."""
    member, product, item = setup_available_item(daily_rental_rate_cents)
    payload = create_rental_payload(member["id"], item["id"], start_at, due_at)
    rental = get_success_data(api_client.create_rental(payload, CLERK))
    return member, product, item, rental


def setup_checked_out_rental(daily_rental_rate_cents=500,
                             start_at="2026-07-02T00:00:00Z", due_at="2026-07-05T00:00:00Z"):
    """Rental reserved then checked out (estimated pinned). Returns (member, product, item, rental)."""
    member, product, item, rental = setup_reserved_rental(
        daily_rental_rate_cents, start_at, due_at)
    rental = get_success_data(api_client.checkout_rental(rental["id"], CLERK))
    return member, product, item, rental


# ─── Tier: Sale prerequisites ─────────────────────────────────────────────
def setup_member_and_available_item(unit_price_cents=1000, tier=None, condition_grade="B"):
    """Member + product + one AVAILABLE inventory unit. Returns (member, product, item)."""
    member = create_member(tier=tier)
    product = create_product(base_price_cents=unit_price_cents)
    item = create_inventory_item(product["id"], condition_grade)
    return member, product, item


def make_sale(member_id, lines, redeem_store_credit_cents=None, headers=CLERK):
    payload = create_sale_payload(member_id, lines)
    if redeem_store_credit_cents is not None:
        payload["redeem_store_credit_cents"] = redeem_store_credit_cents
    return api_client.create_sale(payload, headers)


def grant_store_credit(member_id, amount_cents):
    """Manager grants store credit via a manual adjustment. Returns the ledger entry."""
    return get_success_data(
        api_client.adjust_store_credit(member_id, adjustment_payload(amount_cents), MANAGER))


# ─── Tier: Tournament setup ───────────────────────────────────────────────
def setup_tournament(max_participants=8, seat_capacity=8,
                     starts_at="2026-07-05T10:00:00Z", ends_at="2026-07-05T12:00:00Z",
                     registration_opens_at="2026-07-01T00:00:00Z",
                     registration_closes_at="2026-07-05T09:00:00Z", title="Test Cup"):
    """Station + one scheduled Tournament. Returns (station, tournament)."""
    station = get_success_data(
        api_client.create_station(create_station_payload(seat_capacity=seat_capacity), MANAGER))
    payload = create_tournament_payload(
        station["id"], title=title, starts_at=starts_at, ends_at=ends_at,
        registration_opens_at=registration_opens_at,
        registration_closes_at=registration_closes_at, max_participants=max_participants)
    tournament = get_success_data(api_client.create_tournament(payload, CLERK))
    return station, tournament
