"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "setup failed" errors rather than confusing assertion failures.

Identity threading: a Shopper is entity_backed:Customer, so every cart operation
owned by a customer uses make_shopper_headers(customer["id"]). The opaque roles
(MerchantAdmin, PlatformOperator) use their shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_segment_payload,
    create_membership_payload,
    create_promotion_payload,
    create_coupon_payload,
    create_blackout_payload,
    create_exclusion_rule_payload,
    create_cart_payload,
    create_line_payload,
    apply_coupon_payload,
    checkout_payload,
    set_clock_payload,
    advance_clock_payload,
    DEFAULT_ACTIVE_FROM,
    DEFAULT_ACTIVE_UNTIL,
    DEFAULT_CLOCK,
)
from .test_users import TEST_USERS, make_shopper_headers


ADMIN = TEST_USERS["merchant_admin_headers"]
OPERATOR = TEST_USERS["platform_operator_headers"]


# ─── Clock ────────────────────────────────────────────────────────────────
def set_clock(now_utc=DEFAULT_CLOCK):
    """Set the system clock to an explicit instant."""
    return get_success_data(api_client.set_clock(set_clock_payload(now_utc=now_utc), OPERATOR))


def advance_clock(seconds: int):
    """Advance the clock and run the expiry sweep."""
    return get_success_data(api_client.advance_clock(advance_clock_payload(seconds), OPERATOR))


# ─── Tier 1: simple entity creation ─────────────────────────────────────────
def create_customer(**overrides):
    """Create a customer. Returns the customer dict."""
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), TEST_USERS["shopper_headers"]))


def create_segment(**overrides):
    return get_success_data(api_client.create_segment(create_segment_payload(**overrides), ADMIN))


def add_membership(segment_id, customer_id):
    return get_success_data(
        api_client.add_member(segment_id, create_membership_payload(customer_id), ADMIN)
    )


def create_promotion(promo_type="PERCENT_OFF", **overrides):
    """Create a promotion in DRAFT. Returns the promotion dict."""
    return get_success_data(api_client.create_promotion(create_promotion_payload(promo_type, **overrides), ADMIN))


def create_coupon(promotion_id, code=None, use_mode="MULTI_USE", **overrides):
    return get_success_data(
        api_client.create_coupon(promotion_id, create_coupon_payload(code, use_mode, **overrides), ADMIN)
    )


def create_blackout(promotion_id, starts_at, ends_at, **overrides):
    return get_success_data(
        api_client.create_blackout(promotion_id, create_blackout_payload(starts_at, ends_at, **overrides), ADMIN)
    )


def create_exclusion_rule(promotion_a_id, promotion_b_id, **overrides):
    return get_success_data(
        api_client.create_exclusion_rule(
            create_exclusion_rule_payload(promotion_a_id, promotion_b_id, **overrides), ADMIN
        )
    )


def activate_promotion(promotion_id):
    return get_success_data(api_client.activate_promotion(promotion_id, ADMIN))


def pause_promotion(promotion_id):
    return get_success_data(api_client.pause_promotion(promotion_id, ADMIN))


# ─── Tier 1: state-progressed promotion ─────────────────────────────────────
def create_active_promotion(promo_type="PERCENT_OFF", coupon_code=None,
                            coupon_use_mode="MULTI_USE", coupon_overrides=None,
                            **promo_overrides):
    """Create a DRAFT promotion, optionally add one coupon, then activate.

    Returns (promotion, coupon) — coupon is None when coupon_code is None.
    The promotion dict reflects the post-activate state (status ACTIVE).
    """
    promo = create_promotion(promo_type, **promo_overrides)
    coupon = None
    if coupon_code is not None:
        coupon = create_coupon(promo["id"], code=coupon_code, use_mode=coupon_use_mode,
                               **(coupon_overrides or {}))
    promo = activate_promotion(promo["id"])
    return promo, coupon


# ─── Tier 2: cart with lines ────────────────────────────────────────────────
def create_cart_for(customer_id):
    """Create an OPEN/UNPRICED cart owned by the given customer."""
    return get_success_data(
        api_client.create_cart(create_cart_payload(customer_id), make_shopper_headers(customer_id))
    )


def add_line(cart_id, customer_id, sku="A", unit_price_cents=1000, quantity=1):
    return get_success_data(
        api_client.add_line(cart_id, create_line_payload(sku, unit_price_cents, quantity),
                            make_shopper_headers(customer_id))
    )


def setup_cart_with_lines(customer_id, lines):
    """Create a cart and add each (sku, unit_price_cents, quantity) line.

    `lines` is a list of dicts or tuples. Returns (cart, [created_lines]).
    """
    cart = create_cart_for(customer_id)
    created = []
    for ln in lines:
        if isinstance(ln, dict):
            created.append(add_line(cart["id"], customer_id, **ln))
        else:
            sku, price, qty = ln
            created.append(add_line(cart["id"], customer_id, sku=sku, unit_price_cents=price, quantity=qty))
    return cart, created


def get_promotion(promotion_id, customer_id=None):
    """Read a promotion. Uses admin headers unless a shopper customer_id is given."""
    headers = make_shopper_headers(customer_id) if customer_id else ADMIN
    return get_success_data(api_client.get_promotion(promotion_id, headers))


def apply(cart_id, customer_id, code, expected_promotion_version=None):
    """Apply a coupon code to a cart as the owning shopper. Returns the application."""
    return get_success_data(
        api_client.apply_coupon(
            cart_id,
            apply_coupon_payload(code, expected_promotion_version=expected_promotion_version),
            make_shopper_headers(customer_id),
        )
    )


def reprice(cart_id, customer_id):
    return get_success_data(api_client.reprice(cart_id, make_shopper_headers(customer_id)))


def lock(cart_id, customer_id):
    return get_success_data(api_client.lock_cart(cart_id, make_shopper_headers(customer_id)))


def unlock(cart_id, customer_id):
    return get_success_data(api_client.unlock_cart(cart_id, make_shopper_headers(customer_id)))


def abandon(cart_id, customer_id):
    return get_success_data(api_client.abandon_cart(cart_id, make_shopper_headers(customer_id)))


def checkout(cart_id, customer_id, expected_cart_version):
    return get_success_data(
        api_client.checkout_cart(cart_id, checkout_payload(expected_cart_version),
                                 make_shopper_headers(customer_id))
    )


# ─── Tier 3: full lifecycle shortcuts ───────────────────────────────────────
def setup_priced_cart_with_coupon(customer_id, code, lines, expected_promotion_version=None):
    """Cart with lines + one APPLIED coupon application, repriced to PRICED.

    Returns (cart_after_reprice, application).
    """
    cart, _ = setup_cart_with_lines(customer_id, lines)
    app = apply(cart["id"], customer_id, code, expected_promotion_version=expected_promotion_version)
    cart = reprice(cart["id"], customer_id)
    return cart, app


def setup_locked_cart_with_coupon(customer_id, code, lines, expected_promotion_version=None):
    """Cart with lines + coupon applied + repriced + LOCKED (one RESERVED redemption).

    Returns the cart dict in LOCKED state (its version reflects the lock).
    """
    cart, _ = setup_priced_cart_with_coupon(customer_id, code, lines,
                                            expected_promotion_version=expected_promotion_version)
    locked = lock(cart["id"], customer_id)
    return locked


def checkout_full(customer_id, code, lines, expected_promotion_version=None):
    """Full happy-path: cart -> lines -> apply -> reprice -> lock -> checkout.

    Returns the CHECKED_OUT cart dict. Resolves the promotion version automatically
    when expected_promotion_version is not supplied (for budget-capped promos the
    caller should pass it explicitly).
    """
    locked = setup_locked_cart_with_coupon(customer_id, code, lines,
                                           expected_promotion_version=expected_promotion_version)
    return checkout(locked["id"], customer_id, locked["version"])


def get_cart_redemption(cart_id, customer_id):
    """Return the single redemption under a cart (first row), or None."""
    res = api_client.list_cart_redemptions(cart_id, make_shopper_headers(customer_id))
    data = get_success_data(res)
    if isinstance(data, list) and data:
        return data[0]
    return None
