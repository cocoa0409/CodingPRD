"""Coupon application validations, priority conflict, and OCC on order version."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, create_customer, create_product, create_inventory_lot,
    create_coupon, create_order, add_line, make_customer_headers,
)


def _apply(api, order_id, customer_id, code, expected_version):
    return api.apply_coupon(
        order_id,
        {"code": code, "expected_order_version": expected_version},
        make_customer_headers(customer_id),
    )


def test_coupon_min_basket_not_met(api):
    """PRD §3.3: "If the order's current running subtotal is below the coupon's
    min_basket_cents, the apply is rejected with ERR_COUPON_MIN_NOT_MET."

    Design: Corner/validations/coupon_min_basket_not_met
    """
    set_clock("2026-06-01T00:00:00Z")
    customer = create_customer()
    product = create_product(sell_mode="UNIT", unit_price_cents=500)
    create_inventory_lot(product["id"], on_hand_yards=50)
    coupon = create_coupon(discount_type="FIXED", value=100, min_basket_cents=10000, priority=1)
    order = create_order(customer["id"])
    add_line(order["id"], customer["id"], product["id"], requested_yards=1)
    resp = _apply(api, order["id"], customer["id"], coupon["code"], order["version"])
    validate_error(resp, ApiErrorId.ERR_COUPON_MIN_NOT_MET)


def test_coupon_not_stackable_second_apply(api):
    """PRD §3.3: "Applying a second or subsequent coupon requires that all coupons
    on the order be stackable; if any applied coupon is not stackable, the apply
    is rejected with ERR_COUPON_NOT_STACKABLE."

    Design: Corner/errors/coupon_not_stackable_second_apply
    """
    set_clock("2026-06-01T00:00:00Z")
    customer = create_customer()
    product = create_product(sell_mode="UNIT", unit_price_cents=5000)
    create_inventory_lot(product["id"], on_hand_yards=50)
    coupon_a = create_coupon(discount_type="PERCENT", value=0.1, stackable=True, priority=1)
    coupon_b = create_coupon(discount_type="FIXED", value=200, stackable=False, priority=2)
    order = create_order(customer["id"])
    add_line(order["id"], customer["id"], product["id"], requested_yards=1)
    applied = validate_success(_apply(api, order["id"], customer["id"], coupon_a["code"], order["version"]))
    resp = _apply(api, order["id"], customer["id"], coupon_b["code"], applied["version"])
    validate_error(resp, ApiErrorId.ERR_COUPON_NOT_STACKABLE)


def test_coupon_expired_beats_not_stackable(api):
    """PRD §2.8: "(6) business-temporal windows, namely that a workshop session is
    still open for registration and that a coupon is within its validity window;
    ... (10) coupon stackability"
    PRD §3.3: "At apply time the coupon's validity window is enforced: if the clock
    instant is before valid_from or at or after valid_to, the apply is rejected
    with ERR_COUPON_EXPIRED."

    Design: Difficulty/priority_pair_validation_conflict/coupon_expired_beats_not_stackable
    """
    set_clock("2026-06-15T00:00:00Z")
    customer = create_customer()
    product = create_product(sell_mode="UNIT", unit_price_cents=1000)
    create_inventory_lot(product["id"], on_hand_yards=50)
    coupon_a = create_coupon(discount_type="PERCENT", value=0.1, stackable=True, priority=1)
    coupon_b = create_coupon(
        discount_type="FIXED", value=100, stackable=False, priority=2,
        valid_from="2026-01-01T00:00:00Z", valid_to="2026-06-01T00:00:00Z",
    )
    order = create_order(customer["id"])
    add_line(order["id"], customer["id"], product["id"], requested_yards=5)
    applied = validate_success(_apply(api, order["id"], customer["id"], coupon_a["code"], order["version"]))
    # coupon_b is both expired (priority 6) and non-stackable (priority 10) -> expired wins.
    resp = _apply(api, order["id"], customer["id"], coupon_b["code"], applied["version"])
    validate_error(resp, ApiErrorId.ERR_COUPON_EXPIRED)


def test_expired_coupon_apply_rejected_standalone(api):
    """PRD §3.3: "At apply time the coupon's validity window is enforced: if the
    clock instant is before valid_from or at or after valid_to, the apply is
    rejected with ERR_COUPON_EXPIRED."

    Design: Difficulty/priority_pair_validation_conflict/coupon_expired_beats_not_stackable
    """
    set_clock("2026-06-15T00:00:00Z")
    customer = create_customer()
    product = create_product(sell_mode="UNIT", unit_price_cents=1000)
    create_inventory_lot(product["id"], on_hand_yards=50)
    coupon = create_coupon(
        discount_type="FIXED", value=100, stackable=True, priority=1,
        valid_from="2026-01-01T00:00:00Z", valid_to="2026-06-01T00:00:00Z",
    )
    order = create_order(customer["id"])
    add_line(order["id"], customer["id"], product["id"], requested_yards=5)
    resp = _apply(api, order["id"], customer["id"], coupon["code"], order["version"])
    validate_error(resp, ApiErrorId.ERR_COUPON_EXPIRED)


def test_coupon_apply_stale_version_conflict(api):
    """PRD §2.9: "If that value does not match the order's current version —
    because another writer has applied a coupon and advanced the order's version
    since the client last read it — the operation is rejected with
    ERR_STALE_VERSION (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/coupon_apply_stale_version_conflict
    """
    set_clock("2026-06-01T00:00:00Z")
    customer = create_customer()
    product = create_product(sell_mode="UNIT", unit_price_cents=2000)
    create_inventory_lot(product["id"], on_hand_yards=50)
    coupon_a = create_coupon(discount_type="PERCENT", value=0.1, stackable=True, priority=1)
    coupon_b = create_coupon(discount_type="PERCENT", value=0.1, stackable=True, priority=2)
    order = create_order(customer["id"])
    add_line(order["id"], customer["id"], product["id"], requested_yards=1)
    v0 = order["version"]
    validate_success(_apply(api, order["id"], customer["id"], coupon_a["code"], v0))
    # Second apply still carries the stale v0 -> version has advanced -> 412.
    resp = _apply(api, order["id"], customer["id"], coupon_b["code"], v0)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
