"""Commercial account credit line: the strict credit-limit boundary, the
account-must-be-ACTIVE gate, the state-beats-fiscal precedence, credit release on
cancel, and the optimistic-concurrency version guard."""
import pytest

from test_helpers import (
    validate_success, validate_error, api_client,
    new_commercial_account, new_active_account, activate_account, hold_account,
    get_account, place_commercial_order, new_stocked_product, cancel_order,
    order_line, create_commercial_order_payload, make_commercial_buyer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["store_admin_headers"]


# ─── Difficulty: boundary_precision_check / credit at and above limit ──────
def _account_and_product(limit):
    account = new_active_account(business_name="Edge Co",
                                 credit_limit_cents=limit, discount_tier="STANDARD")
    product, _lot = new_stocked_product(quantity=1000, sku_code="SYS-5",
                                        name="Vertical Rack", category="SYSTEM",
                                        unit_price_cents=40000)
    return account, product


def test_order_bringing_credit_to_exact_limit_accepted(api):
    """PRD §3.4: "the account's `credit_used_cents` plus this order's `total_cents`
    must not exceed its `credit_limit_cents`, where an exact-equality draw is
    permitted and only a strictly greater draw is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)".
    PRD §3.3: "it is the sum of `total_cents` across every order belonging to the
    account whose `fulfillment_status` is `CONFIRMED` or `SHIPPED`."

    Design: Difficulty/boundary_precision_check/commercial_credit_boundary_at_and_above_limit
    """
    # Each order's subtotal is held below the 500000 volume-bonus threshold
    # (PRD §3.4) so no commercial discount applies and net_total == subtotal,
    # letting the two draws fill the credit line to exactly its limit.
    account, product = _account_and_product(800_000)
    place_commercial_order(account, [order_line(product["id"], 10)])  # 400000
    account = get_account(account["id"])
    order_b = place_commercial_order(account, [order_line(product["id"], 10)])  # +400000
    assert order_b["fulfillment_status"] == "CONFIRMED"
    account = get_account(account["id"])
    assert account["credit_used_cents"] == 800_000


def test_order_above_limit_rejected(api):
    """PRD §3.4: "the account's `credit_used_cents` plus this order's `total_cents`
    must not exceed its `credit_limit_cents`, where an exact-equality draw is
    permitted and only a strictly greater draw is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)".

    Design: Difficulty/boundary_precision_check/commercial_credit_boundary_at_and_above_limit
    """
    # Sub-threshold subtotals (PRD §3.4) so net == subtotal; the two draws bring
    # credit to exactly the 800000 limit, and the third strictly exceeds it.
    account, product = _account_and_product(800_000)
    place_commercial_order(account, [order_line(product["id"], 10)])  # 400000
    account = get_account(account["id"])
    place_commercial_order(account, [order_line(product["id"], 10)])  # credit now 800000
    account = get_account(account["id"])
    buyer = make_commercial_buyer_headers(account["id"])
    res = api.create_commercial_order(
        account["id"],
        create_commercial_order_payload([order_line(product["id"], 1)], account["version"]),
        buyer,
    )
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED")


# ─── Difficulty: cross_entity_state_dependency / order requires ACTIVE ─────
def test_commercial_order_on_pending_account_rejected(api):
    """PRD §3.4: "the account must be `ACTIVE` or the placement is rejected with
    `ERR_ACCOUNT_NOT_ACTIVE`".
    PRD §3.3: "A new account starts with `credit_used_cents` of 0 and a `status`
    of `PENDING`."

    Design: Difficulty/cross_entity_state_dependency/commercial_order_requires_account_active
    """
    account = new_commercial_account(business_name="Pend Co", credit_limit_cents=500000)
    product, _lot = new_stocked_product(quantity=100, sku_code="SYS-6", name="Cloner",
                                        category="SYSTEM", unit_price_cents=6000)
    buyer = make_commercial_buyer_headers(account["id"])
    res = api.create_commercial_order(
        account["id"],
        create_commercial_order_payload([order_line(product["id"], 1)], account["version"]),
        buyer,
    )
    validate_error(res, "ERR_ACCOUNT_NOT_ACTIVE")


def test_commercial_order_after_activation_succeeds(api):
    """PRD §3.3: "A `StoreAdmin` activation of an account that is `PENDING` or
    `ON_HOLD` moves it to `ACTIVE`".
    PRD §3.4: "a commercial order is born with `order_type` of `COMMERCIAL`, is
    created directly in the `CONFIRMED` fulfillment state (reserving inventory
    immediately, as in Section 3.5), and leaves `customer_id` empty."

    Design: Difficulty/cross_entity_state_dependency/commercial_order_requires_account_active
    """
    account = new_commercial_account(business_name="Pend Co", credit_limit_cents=500000)
    product, _lot = new_stocked_product(quantity=100, sku_code="SYS-6b", name="Cloner",
                                        category="SYSTEM", unit_price_cents=6000)
    account = activate_account(account["id"])
    order = place_commercial_order(account, [order_line(product["id"], 1)])
    assert order["order_type"] == "COMMERCIAL"
    assert order["fulfillment_status"] == "CONFIRMED"


# ─── Difficulty: priority_pair / state (hold) beats fiscal (credit) ────────
def _account_at_limit_and_product():
    account = new_active_account(business_name="Hold Co",
                                 credit_limit_cents=120000, discount_tier="STANDARD")
    product, _lot = new_stocked_product(quantity=100, sku_code="SYS-4", name="Ebb Table",
                                        category="SYSTEM", unit_price_cents=40000)
    place_commercial_order(account, [order_line(product["id"], 3)])  # 120000 == limit
    return get_account(account["id"]), product


def test_held_account_over_limit_returns_account_not_active(api):
    """PRD §3.3: "Placing an `ACTIVE` account on hold moves it `ACTIVE → ON_HOLD`
    and blocks new commercial order placement while it remains held".
    PRD §3.4: "the account must be `ACTIVE` or the placement is rejected with
    `ERR_ACCOUNT_NOT_ACTIVE`; then every line must have sufficient stock (Section
    3.5) or the placement is rejected with `ERR_INSUFFICIENT_STOCK`; then the draw
    must fit the credit line".

    Design: Difficulty/priority_pair_validation_conflict/state_account_hold_beats_fiscal_credit_over_limit
    """
    account, product = _account_at_limit_and_product()
    held = hold_account(account["id"])
    buyer = make_commercial_buyer_headers(account["id"])
    res = api.create_commercial_order(
        account["id"],
        create_commercial_order_payload([order_line(product["id"], 3)], held["version"]),
        buyer,
    )
    validate_error(res, "ERR_ACCOUNT_NOT_ACTIVE")


def test_active_account_over_limit_returns_credit_error(api):
    """PRD §3.4: "the account must be `ACTIVE` or the placement is rejected with
    `ERR_ACCOUNT_NOT_ACTIVE`; then every line must have sufficient stock (Section
    3.5) or the placement is rejected with `ERR_INSUFFICIENT_STOCK`; then the draw
    must fit the credit line — the account's `credit_used_cents` plus this order's
    `total_cents` must not exceed its `credit_limit_cents`, where an exact-equality
    draw is permitted and only a strictly greater draw is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)".

    Design: Difficulty/priority_pair_validation_conflict/state_account_hold_beats_fiscal_credit_over_limit
    """
    account, product = _account_at_limit_and_product()
    buyer = make_commercial_buyer_headers(account["id"])
    res = api.create_commercial_order(
        account["id"],
        create_commercial_order_payload([order_line(product["id"], 3)], account["version"]),
        buyer,
    )
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED")


# ─── Difficulty: compensating_invariant / cancel releases commercial credit ─
def _placed_commercial_order():
    account = new_active_account(business_name="Cons Co",
                                 credit_limit_cents=1_000_000, discount_tier="STANDARD")
    product, _lot = new_stocked_product(quantity=100, sku_code="SYS-8", name="Res Tank",
                                        category="SYSTEM", unit_price_cents=20000)
    order = place_commercial_order(account, [order_line(product["id"], 10)])  # 200000
    return account, product, order


def test_cancel_commercial_order_releases_credit(api):
    """PRD §3.5: "For a commercial order, cancellation also increments the
    account's `version` by one and recomputes `credit_used_cents`, releasing the
    drawn credit."

    Design: Difficulty/compensating_invariant/place_then_cancel_conserves_commercial_credit
    """
    account, product, order = _placed_commercial_order()
    assert get_account(account["id"])["credit_used_cents"] == 200000
    cancel_order(order["id"])
    assert get_account(account["id"])["credit_used_cents"] == 0


def test_cancel_commercial_order_sets_cancelled(api):
    """PRD §3.5: "A `Customer` or `StoreAdmin` cancels an order that is `DRAFT` or
    `CONFIRMED`, moving it to `CANCELLED`."

    Design: Difficulty/compensating_invariant/place_then_cancel_conserves_commercial_credit
    """
    account, product, order = _placed_commercial_order()
    cancelled = cancel_order(order["id"])
    assert cancelled["fulfillment_status"] == "CANCELLED"


# ─── Corner: cross_cutting / OCC stale account version → 412 ───────────────
def test_stale_account_version_rejected(api):
    """PRD §2.8: "If that value does not equal the account's current `version` —
    because a prior commercial order already drew credit, or an administrator
    changed the account's tier or hold status in the meantime — the placement is
    rejected as stale with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_returns_412
    """
    account = new_active_account(business_name="Occ Co",
                                 credit_limit_cents=5_000_000, discount_tier="STANDARD")
    product, _lot = new_stocked_product(quantity=100, sku_code="SYS-Z", name="Z Sys",
                                        category="SYSTEM", unit_price_cents=10000)
    stale_version = account["version"]
    place_commercial_order(account, [order_line(product["id"], 1)], version=stale_version)
    buyer = make_commercial_buyer_headers(account["id"])
    res = api.create_commercial_order(
        account["id"],
        create_commercial_order_payload([order_line(product["id"], 1)], stale_version),
        buyer,
    )
    validate_error(res, "ERR_STALE_VERSION")
