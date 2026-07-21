"""Validation-priority conflicts, single-rule business validations, and the two
optimistic-concurrency guards.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_shopper_headers,
    set_clock,
    new_customer,
    new_product,
    new_variant,
    loyalty_adjust,
    place_order,
    pay_order,
    cancel_order,
    customer_version,
    pay_payload,
    setup_buyable,
)

AGENT = TEST_USERS["fulfillment_agent_headers"]


# ---- priority_pair_validation_conflict: pay_state_beats_fiscal ----

def test_second_pay_state_beats_redemption_cap(api):
    """PRD §3.4: "Payment is only allowed when the order's `payment_status` is
    `UNPAID`; a pay attempt against an order that is not unpaid is rejected with
    `ERR_ORDER_NOT_PAYABLE`."
    PRD §2.8: "then well-formedness of the request body (`ERR_VALIDATION`), then
    the state-transition preconditions, then the domain-specific business rules
    described in Section 3. Earlier checks always take precedence."

    Design: Difficulty/priority_pair_validation_conflict/pay_state_beats_fiscal
    """
    base = setup_buyable(api, buy_price_cents=5000, inventory_on_hand=5, category="NURSING")
    cust = base["customer"]["id"]
    order = place_order(api, cust, base["variant"]["id"], "BUY", quantity=1)
    pay_order(api, order["id"], cust, redeemed_points=0)  # now PAID
    cv = customer_version(api, cust)
    resp = api.pay_order(order["id"], pay_payload(cv, redeemed_points=5000),
                         make_shopper_headers(cust))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PAYABLE.value)


def test_second_pay_state_beats_insufficient_points(api):
    """PRD §3.4: "a pay attempt against an order that is not unpaid is rejected
    with `ERR_ORDER_NOT_PAYABLE`."
    PRD §2.8: "then the state-transition preconditions, then the domain-specific
    business rules described in Section 3. Earlier checks always take precedence."

    Design: Difficulty/priority_pair_validation_conflict/pay_state_beats_fiscal
    """
    base = setup_buyable(api, buy_price_cents=5000, inventory_on_hand=5, category="NURSING")
    cust = base["customer"]["id"]
    order = place_order(api, cust, base["variant"]["id"], "BUY", quantity=1)
    pay_order(api, order["id"], cust, redeemed_points=0)  # now PAID
    cv = customer_version(api, cust)
    resp = api.pay_order(order["id"], pay_payload(cv, redeemed_points=100),
                         make_shopper_headers(cust))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PAYABLE.value)


# ---- priority_pair_validation_conflict: order_referential_beats_constraint ----

def test_order_discontinued_beats_insufficient_stock(api):
    """PRD §3.3: "The variant's parent product must not be discontinued; ordering
    against a variant whose product `status` is `DISCONTINUED` is rejected with
    `ERR_PRODUCT_DISCONTINUED`."
    PRD §3.3: "For a purchase, the requested `quantity` must not exceed the
    variant's `inventory_on_hand`; if it does, the order is rejected with
    `ERR_INSUFFICIENT_STOCK`."

    Design: Difficulty/priority_pair_validation_conflict/order_referential_beats_constraint
    """
    cust = new_customer(api)
    product = new_product(api, category="MATERNITY", buy_price_cents=5000, status="DISCONTINUED")
    variant = new_variant(api, product["id"], inventory_on_hand=1)
    resp = api.create_order(
        {"customer_id": cust["id"], "variant_id": variant["id"], "order_type": "BUY",
         "expected_variant_version": variant["version"], "quantity": 5},
        make_shopper_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED.value)


def test_order_discontinued_beats_zero_stock(api):
    """PRD §3.3: "ordering against a variant whose product `status` is
    `DISCONTINUED` is rejected with `ERR_PRODUCT_DISCONTINUED`."
    PRD §3.3: "the requested `quantity` must not exceed the variant's
    `inventory_on_hand`; if it does, the order is rejected with
    `ERR_INSUFFICIENT_STOCK`."

    Design: Difficulty/priority_pair_validation_conflict/order_referential_beats_constraint
    """
    cust = new_customer(api)
    product = new_product(api, category="MATERNITY", buy_price_cents=5000, status="DISCONTINUED")
    variant = new_variant(api, product["id"], inventory_on_hand=0)
    resp = api.create_order(
        {"customer_id": cust["id"], "variant_id": variant["id"], "order_type": "BUY",
         "expected_variant_version": variant["version"], "quantity": 1},
        make_shopper_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED.value)


# ---- cross_entity_state_dependency: order_place_requires_product_active ----

def test_buy_order_on_discontinued_product_rejected(api):
    """PRD §3.3: "The variant's parent product must not be discontinued; ordering
    against a variant whose product `status` is `DISCONTINUED` is rejected with
    `ERR_PRODUCT_DISCONTINUED`."

    Design: Difficulty/cross_entity_state_dependency/order_place_requires_product_active
    """
    cust = new_customer(api)
    product = new_product(api, category="MATERNITY", buy_price_cents=6000, status="DISCONTINUED")
    variant = new_variant(api, product["id"], inventory_on_hand=10)  # ample stock
    resp = api.create_order(
        {"customer_id": cust["id"], "variant_id": variant["id"], "order_type": "BUY",
         "expected_variant_version": variant["version"], "quantity": 1},
        make_shopper_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED.value)


def test_rental_order_on_discontinued_product_rejected(api):
    """PRD §3.3: "ordering against a variant whose product `status` is
    `DISCONTINUED` is rejected with `ERR_PRODUCT_DISCONTINUED`."
    PRD §3.1: "a variant's `status` is initialized from — and thereafter mirrors
    — the parent product's status, so a variant of a discontinued product reads
    `DISCONTINUED`."

    Design: Difficulty/cross_entity_state_dependency/order_place_requires_product_active
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    cust = new_customer(api, due_date="2026-10-01T00:00:00Z")
    product = new_product(api, category="MATERNITY", rentable=True, buy_price_cents=10000,
                          rental_weekly_cents=1500, status="DISCONTINUED")
    variant = new_variant(api, product["id"], rental_units_total=2)
    resp = api.create_order(
        {"customer_id": cust["id"], "variant_id": variant["id"], "order_type": "RENTAL",
         "expected_variant_version": variant["version"], "rental_weeks": 2,
         "rental_start": "2026-07-01T00:00:00Z"},
        make_shopper_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED.value)


# ---- compensating_invariant: loyalty_points_conserved_redeem_then_cancel ----

def test_loyalty_points_conserved_redeem_600_then_cancel(api):
    """PRD §3.4: "the customer's `loyalty_points` is reduced by that many points;
    and a `LoyaltyLedger` entry with reason `REDEEMED` and a `points_delta` of
    the negative redeemed amount is appended."
    PRD §3.5: "those points are returned — the customer's `loyalty_points` is
    increased by the redeemed amount and a `LoyaltyLedger` entry with reason
    `REVERSAL_REDEEM` and a positive `points_delta` equal to the returned points
    is appended."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_redeem_then_cancel
    """
    cust = new_customer(api)
    loyalty_adjust(api, cust["id"], 1000)
    product = new_product(api, category="MATERNITY", buy_price_cents=10000)
    variant = new_variant(api, product["id"], inventory_on_hand=5)
    order = place_order(api, cust["id"], variant["id"], "BUY", quantity=1)
    pay_order(api, order["id"], cust["id"], redeemed_points=600)
    after_pay = validate_success(api.get_customer(cust["id"], make_shopper_headers(cust["id"])), 200)
    assert after_pay["loyalty_points"] == 400
    cancel_order(api, order["id"], cust["id"])
    after_cancel = validate_success(api.get_customer(cust["id"], make_shopper_headers(cust["id"])), 200)
    assert after_cancel["loyalty_points"] == 1000


def test_loyalty_points_conserved_full_redeem_then_cancel(api):
    """PRD §3.4: "the customer's `loyalty_points` is reduced by that many
    points."
    PRD §3.5: "the customer's `loyalty_points` is increased by the redeemed
    amount and a `LoyaltyLedger` entry with reason `REVERSAL_REDEEM` and a
    positive `points_delta` equal to the returned points is appended."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_redeem_then_cancel
    """
    cust = new_customer(api)
    loyalty_adjust(api, cust["id"], 500)
    product = new_product(api, category="MATERNITY", buy_price_cents=10000)
    variant = new_variant(api, product["id"], inventory_on_hand=5)
    order = place_order(api, cust["id"], variant["id"], "BUY", quantity=1)
    pay_order(api, order["id"], cust["id"], redeemed_points=500)
    after_pay = validate_success(api.get_customer(cust["id"], make_shopper_headers(cust["id"])), 200)
    assert after_pay["loyalty_points"] == 0
    cancel_order(api, order["id"], cust["id"])
    after_cancel = validate_success(api.get_customer(cust["id"], make_shopper_headers(cust["id"])), 200)
    assert after_cancel["loyalty_points"] == 500


# ---- Corner: rental_order_missing_due_date_rejected ----

def test_rental_order_missing_due_date_rejected(api):
    """PRD §3.3: "For a rental, the customer's `due_date` must be present (a
    rental placed while the customer's due date is null, or with `rental_start`
    missing, is rejected with `ERR_DUE_DATE_REQUIRED`)."

    Design: Corner/validations/rental_order_missing_due_date_rejected
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    cust = new_customer(api)  # no due_date
    product = new_product(api, category="MATERNITY", rentable=True, buy_price_cents=10000,
                          rental_weekly_cents=1500)
    variant = new_variant(api, product["id"], rental_units_total=2)
    resp = api.create_order(
        {"customer_id": cust["id"], "variant_id": variant["id"], "order_type": "RENTAL",
         "expected_variant_version": variant["version"], "rental_weeks": 2,
         "rental_start": "2026-07-01T00:00:00Z"},
        make_shopper_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUE_DATE_REQUIRED.value)


# ---- Corner: insufficient_stock_on_buy_rejected ----

def test_insufficient_stock_on_buy_rejected(api):
    """PRD §3.3: "For a purchase, the requested `quantity` must not exceed the
    variant's `inventory_on_hand`; if it does, the order is rejected with
    `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/validations/insufficient_stock_on_buy_rejected
    """
    base = setup_buyable(api, buy_price_cents=5000, inventory_on_hand=1, category="NURSING")
    resp = api.create_order(
        {"customer_id": base["customer"]["id"], "variant_id": base["variant"]["id"],
         "order_type": "BUY", "expected_variant_version": base["variant"]["version"],
         "quantity": 5},
        make_shopper_headers(base["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


# ---- Corner: redemption_exceeds_limit_on_pay_rejected ----

def test_redemption_exceeds_half_subtotal_cap_rejected(api):
    """PRD §3.4: "the cents they represent must not exceed half of the subtotal,
    where that half-subtotal cap is floored to a whole number of cents (otherwise
    `ERR_REDEMPTION_EXCEEDS_LIMIT`)."

    Design: Corner/validations/redemption_exceeds_limit_on_pay_rejected
    """
    cust = new_customer(api)
    loyalty_adjust(api, cust["id"], 6000)
    product = new_product(api, category="MATERNITY", buy_price_cents=10000)
    variant = new_variant(api, product["id"], inventory_on_hand=5)
    order = place_order(api, cust["id"], variant["id"], "BUY", quantity=1)
    cv = customer_version(api, cust["id"])
    resp = api.pay_order(order["id"], pay_payload(cv, redeemed_points=6000),
                         make_shopper_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_REDEMPTION_EXCEEDS_LIMIT.value)


# ---- Corner: insufficient_points_on_pay_rejected ----

def test_insufficient_points_on_pay_rejected(api):
    """PRD §3.4: "The requested `redeemed_points` must not exceed the customer's
    available `loyalty_points` (otherwise `ERR_INSUFFICIENT_POINTS`)."

    Design: Corner/validations/insufficient_points_on_pay_rejected
    """
    base = setup_buyable(api, buy_price_cents=5000, inventory_on_hand=5, category="NURSING")
    cust = base["customer"]["id"]
    order = place_order(api, cust, base["variant"]["id"], "BUY", quantity=1)
    cv = customer_version(api, cust)
    resp = api.pay_order(order["id"], pay_payload(cv, redeemed_points=100),
                         make_shopper_headers(cust))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


# ---- Corner: occ_stale_variant_version_on_order ----

def test_stale_variant_version_on_second_order_rejected(api):
    """PRD §2.6: "If that value does not equal the variant's current `version` —
    because an earlier order has already consumed a buyable unit or committed a
    rental unit and thereby advanced the variant's version past what the client
    saw — the create is rejected with `ERR_STALE_VARIANT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_variant_version_on_order
    """
    base = setup_buyable(api, buy_price_cents=5000, inventory_on_hand=10, category="NURSING")
    cust = base["customer"]["id"]
    stale_version = base["variant"]["version"]  # observed before any order
    place_order(api, cust, base["variant"]["id"], "BUY", quantity=1)  # bumps variant version
    resp = api.create_order(
        {"customer_id": cust, "variant_id": base["variant"]["id"], "order_type": "BUY",
         "expected_variant_version": stale_version, "quantity": 1},
        make_shopper_headers(cust),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VARIANT_VERSION.value)


# ---- Corner: occ_stale_customer_version_on_pay ----

def test_stale_customer_version_on_pay_rejected(api):
    """PRD §2.6: "If that value does not equal the customer's current `version` —
    because another write (an earlier redemption, a cancellation reversal, or an
    earned-points grant) has already moved the customer's balances and advanced
    the version — the payment is rejected with `ERR_STALE_CUSTOMER_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_customer_version_on_pay
    """
    cust = new_customer(api)
    stale_version = cust["version"]  # version 1 at registration
    product = new_product(api, category="NURSING", buy_price_cents=5000)
    variant = new_variant(api, product["id"], inventory_on_hand=5)
    order = place_order(api, cust["id"], variant["id"], "BUY", quantity=1)
    loyalty_adjust(api, cust["id"], 100)  # bumps Customer.version to 2
    resp = api.pay_order(order["id"], pay_payload(stale_version, redeemed_points=0),
                         make_shopper_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_CUSTOMER_VERSION.value)
