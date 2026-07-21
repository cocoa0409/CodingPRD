"""Composite setup helpers.

Every test runs against a freshly restarted (empty) server, so each helper
builds its preconditions from scratch using only PRD-declared endpoints. Helpers
use get_success_data() (lenient) so setup problems surface as clear "Setup
failed" errors rather than confusing assertion failures.

Identity threading: Shopper is entity_backed, so every ownership-gated call uses
make_shopper_headers(customer["id"]) with the real Customer.id — never the shared
TEST_USERS constant. Reads that don't need ownership (variant/customer version
probes) go through PlatformAdmin, an opaque role.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_shopper_headers,
)
from . import factories as f


ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["fulfillment_agent_headers"]
GUEST = TEST_USERS["guest_headers"]


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(api, to_iso8601: str):
    """Advance the logical clock to a supplied instant (PlatformAdmin only)."""
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# --------------------------------------------------------------------------
# Single-entity creators
# --------------------------------------------------------------------------
def new_customer(api, **overrides) -> dict:
    return get_success_data(api.create_customer(f.create_customer_payload(**overrides), GUEST))


def new_product(api, **overrides) -> dict:
    return get_success_data(api.create_product(f.create_product_payload(**overrides), ADMIN))


def new_variant(api, product_id, **overrides) -> dict:
    return get_success_data(
        api.create_variant(product_id, f.create_variant_payload(**overrides), ADMIN)
    )


def loyalty_adjust(api, customer_id, points_delta) -> dict:
    return get_success_data(
        api.create_loyalty_adjustment(
            customer_id, f.create_loyalty_adjustment_payload(points_delta), ADMIN
        )
    )


def new_subscription(api, customer_id, **overrides) -> dict:
    hdr = make_shopper_headers(customer_id)
    return get_success_data(
        api.create_subscription(f.create_subscription_payload(customer_id, **overrides), hdr)
    )


def new_fit_profile(api, customer_id, **overrides) -> dict:
    hdr = make_shopper_headers(customer_id)
    return get_success_data(
        api.create_fit_profile(f.create_fit_profile_payload(customer_id, **overrides), hdr)
    )


# --------------------------------------------------------------------------
# Version probes (opaque PlatformAdmin reads — no ownership needed)
# --------------------------------------------------------------------------
def variant_version(api, variant_id) -> int:
    return get_success_data(api.get_variant(variant_id, ADMIN))["version"]


def customer_version(api, customer_id) -> int:
    return get_success_data(api.get_customer(customer_id, ADMIN))["version"]


# --------------------------------------------------------------------------
# Order helpers
# --------------------------------------------------------------------------
def place_order(api, customer_id, variant_id, order_type, expected_variant_version=None,
                **overrides) -> dict:
    """Place a BUY/RENTAL order. If expected_variant_version is omitted, the
    current variant version is fetched so the OCC guard passes."""
    if expected_variant_version is None:
        expected_variant_version = variant_version(api, variant_id)
    hdr = make_shopper_headers(customer_id)
    return get_success_data(
        api.create_order(
            f.create_order_payload(customer_id, variant_id, order_type,
                                   expected_variant_version, **overrides),
            hdr,
        )
    )


def pay_order(api, order_id, customer_id, redeemed_points=0,
              expected_customer_version=None) -> dict:
    if expected_customer_version is None:
        expected_customer_version = customer_version(api, customer_id)
    hdr = make_shopper_headers(customer_id)
    return get_success_data(
        api.pay_order(order_id, f.pay_payload(expected_customer_version, redeemed_points), hdr)
    )


def cancel_order(api, order_id, customer_id) -> dict:
    hdr = make_shopper_headers(customer_id)
    return get_success_data(api.cancel_order(order_id, hdr))


def fulfill_order(api, order_id) -> dict:
    return get_success_data(api.fulfill_order(order_id, AGENT))


# --------------------------------------------------------------------------
# Rental helpers
# --------------------------------------------------------------------------
def rental_for_order(api, order_id, customer_id) -> dict:
    """Discover the Rental spawned by a RENTAL order via reverse listing."""
    hdr = make_shopper_headers(customer_id)
    resp = api.list_rentals(hdr, params={"order_id": order_id})
    data = get_success_data(resp)
    assert data, f"no rental found for order {order_id}"
    return data[0]


def activate_rental(api, rental_id) -> dict:
    return get_success_data(api.activate_rental(rental_id, AGENT))


def return_rental(api, rental_id) -> dict:
    return get_success_data(api.return_rental(rental_id, AGENT))


def convert_rental(api, rental_id, customer_id) -> dict:
    hdr = make_shopper_headers(customer_id)
    return get_success_data(api.convert_rental_to_buy(rental_id, hdr))


# --------------------------------------------------------------------------
# Subscription / capsule helpers
# --------------------------------------------------------------------------
def pack_capsule(api, subscription_id, item_variant_ids, ship_date="2026-08-01T00:00:00Z") -> dict:
    return get_success_data(
        api.create_capsule(subscription_id, f.create_capsule_payload(item_variant_ids, ship_date), AGENT)
    )


def ship_capsule(api, capsule_id) -> dict:
    return get_success_data(api.ship_capsule(capsule_id, AGENT))


def pause_subscription(api, subscription_id, customer_id) -> dict:
    hdr = make_shopper_headers(customer_id)
    return get_success_data(api.pause_subscription(subscription_id, hdr))


def cancel_subscription(api, subscription_id, customer_id) -> dict:
    hdr = make_shopper_headers(customer_id)
    return get_success_data(api.cancel_subscription(subscription_id, hdr))


# --------------------------------------------------------------------------
# Return helpers
# --------------------------------------------------------------------------
def request_return(api, order_id, customer_id, return_type="REFUND", reason="size") -> dict:
    hdr = make_shopper_headers(customer_id)
    return get_success_data(
        api.create_return(f.create_return_payload(order_id, return_type, reason), hdr)
    )


def approve_return(api, return_id) -> dict:
    return get_success_data(api.approve_return(return_id, AGENT))


def reject_return(api, return_id) -> dict:
    return get_success_data(api.reject_return(return_id, AGENT))


# ==========================================================================
# Tier 2/3 composites
# ==========================================================================
def setup_buyable(api, buy_price_cents=5000, inventory_on_hand=5, category="NURSING",
                  customer_overrides=None, product_overrides=None,
                  variant_overrides=None) -> dict:
    """Customer + ACTIVE product + one buyable variant.
    Returns {"customer","product","variant"}."""
    customer = new_customer(api, **(customer_overrides or {}))
    product = new_product(api, category=category, buy_price_cents=buy_price_cents,
                          **(product_overrides or {}))
    variant = new_variant(api, product["id"], inventory_on_hand=inventory_on_hand,
                          **(variant_overrides or {}))
    return {"customer": customer, "product": product, "variant": variant}


def setup_rentable(api, weekly_cents=2000, deposit_cents=12000, units=1,
                   due_date="2026-10-01T00:00:00Z", clock="2026-07-01T00:00:00Z",
                   customer_overrides=None) -> dict:
    """Clock set + customer with a due_date + rentable product + variant with a
    rental pool. Returns {"customer","product","variant"}."""
    if clock is not None:
        set_clock(api, clock)
    customer = new_customer(api, due_date=due_date, **(customer_overrides or {}))
    product = new_product(api, category="MATERNITY", rentable=True,
                          buy_price_cents=deposit_cents, rental_weekly_cents=weekly_cents)
    variant = new_variant(api, product["id"], rental_units_total=units)
    return {"customer": customer, "product": product, "variant": variant}


def setup_reserved_rental(api, weekly_cents=2000, deposit_cents=12000, units=1,
                          rental_weeks=4, rental_start="2026-07-01T00:00:00Z",
                          clock="2026-07-01T00:00:00Z") -> dict:
    """Rentable variant + a RENTAL order reserved (RESERVED rental, not activated).
    Returns {"customer","product","variant","order","rental"}."""
    base = setup_rentable(api, weekly_cents=weekly_cents, deposit_cents=deposit_cents,
                          units=units, clock=clock)
    order = place_order(api, base["customer"]["id"], base["variant"]["id"], "RENTAL",
                        rental_weeks=rental_weeks, rental_start=rental_start)
    rental = rental_for_order(api, order["id"], base["customer"]["id"])
    base["order"] = order
    base["rental"] = rental
    return base


def setup_active_rental(api, weekly_cents=2000, deposit_cents=12000, units=1,
                        rental_weeks=4, rental_start="2026-07-01T00:00:00Z",
                        clock="2026-07-01T00:00:00Z") -> dict:
    """Reserved rental then activated (ACTIVE). Returns same dict as
    setup_reserved_rental with rental refreshed to ACTIVE."""
    base = setup_reserved_rental(api, weekly_cents=weekly_cents, deposit_cents=deposit_cents,
                                 units=units, rental_weeks=rental_weeks,
                                 rental_start=rental_start, clock=clock)
    base["rental"] = activate_rental(api, base["rental"]["id"])
    return base


def setup_completed_buy_order(api, buy_price_cents=10000, inventory_on_hand=5,
                              redeemed_points=0, category="POSTPARTUM",
                              customer_overrides=None) -> dict:
    """A BUY order carried through pay + fulfill (COMPLETED: PAID & FULFILLED).
    Returns {"customer","product","variant","order"} with order refreshed."""
    base = setup_buyable(api, buy_price_cents=buy_price_cents,
                         inventory_on_hand=inventory_on_hand, category=category,
                         customer_overrides=customer_overrides)
    order = place_order(api, base["customer"]["id"], base["variant"]["id"], "BUY", quantity=1)
    pay_order(api, order["id"], base["customer"]["id"], redeemed_points=redeemed_points)
    base["order"] = fulfill_order(api, order["id"])
    return base


def setup_subscription(api, plan_tier="CAPSULE_BASIC", monthly_fee_cents=3000,
                       next_ship_date="2026-08-01T00:00:00Z") -> dict:
    """Customer + ACTIVE subscription. Returns {"customer","subscription"}."""
    customer = new_customer(api)
    sub = new_subscription(api, customer["id"], plan_tier=plan_tier,
                           monthly_fee_cents=monthly_fee_cents, next_ship_date=next_ship_date)
    return {"customer": customer, "subscription": sub}


def setup_packed_capsule(api, capsule_price_cents=4000, ship_date="2026-08-01T00:00:00Z",
                         item_count=1) -> dict:
    """ACTIVE subscription + a CAPSULE product with variants + a PACKED capsule.
    Returns {"customer","subscription","product","variants","capsule"}."""
    base = setup_subscription(api)
    product = new_product(api, category="CAPSULE", buy_price_cents=capsule_price_cents)
    variants = [new_variant(api, product["id"], size_label=lbl, trimester_fit=[i + 1])
                for i, lbl in enumerate(["S", "M", "L"][:item_count])]
    capsule = pack_capsule(api, base["subscription"]["id"],
                           [v["id"] for v in variants], ship_date=ship_date)
    base["product"] = product
    base["variants"] = variants
    base["capsule"] = capsule
    return base
