"""Order line pricing, totals, redemption capping, and confirm preconditions.

Difficulty: line_pricing_round_per_line_then_sum.
Corner: order_totals_redemption_capped_at_subtotal, promo_inactive_outside_window_no_discount,
confirm_totals_visible_in_same_response, confirm_empty_order_rejected.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    factories as F, fixtures as X,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INV = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["sales_clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: line_pricing_round_per_line_then_sum
# ---------------------------------------------------------------------------
def _two_line_promo_order():
    """ACTIVE 15% LIVE_PLANT promo; order with line A (qty=3 @ 499) + line B (qty=2 @ 1099)."""
    X.set_clock("2026-04-10T10:00:00Z")
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    pa = X.create_live_plant(nursery["id"], sku="PL-A", name="Fern",
                             hardiness_min_zone=1, hardiness_max_zone=13, unit_price_cents=499,
                             warranty_days=30, warranty_pct=50)
    pb = X.create_live_plant(nursery["id"], sku="PL-B", name="Maple",
                             hardiness_min_zone=1, hardiness_max_zone=13, unit_price_cents=1099,
                             warranty_days=30, warranty_pct=50)
    X.create_active_promotion(nursery["id"], name="Spring Days", category_scope="LIVE_PLANT",
                              discount_pct=15, starts_at="2026-04-01T00:00:00Z", ends_at="2026-05-01T00:00:00Z")
    order = X.create_order(account["id"])
    X.add_line(order["id"], pa["id"], qty=3)
    X.add_line(order["id"], pb["id"], qty=2)
    return order


def test_line_pricing_rounds_per_line_then_sums(api):
    """PRD §3.3: "This floor is applied per line, independently, before any totals
    are summed — the rounding order is round-per-line-then-sum and must not be
    reordered."

    Design: Difficulty/combinatorial_formula/line_pricing_round_per_line_then_sum
    """
    order = _two_line_promo_order()
    version = X.current_order_version(order["id"])
    confirmed = validate_success(api.confirm_order(order["id"], F.confirm_payload(version), CLERK))
    # round-per-line: floor(3*499*0.15)=224, floor(2*1099*0.15)=329 -> 553 (NOT 554).
    assert confirmed["promo_discount_cents"] == 553


def test_two_line_promo_gross_and_net_totals(api):
    """PRD §3.3: "The gross total is the sum over all lines of quantity times unit
    price."
    PRD §3.3: "The net total is the gross total minus the promotion discount minus
    the redemption value, floored at 0 so it can never go negative."

    Design: Difficulty/combinatorial_formula/line_pricing_round_per_line_then_sum
    """
    order = _two_line_promo_order()
    version = X.current_order_version(order["id"])
    confirmed = validate_success(api.confirm_order(order["id"], F.confirm_payload(version), CLERK))
    assert confirmed["gross_total_cents"] == 3695, "3*499 + 2*1099"
    assert confirmed["net_total_cents"] == 3142, "3695 - 553"


# ---------------------------------------------------------------------------
# Corner: order totals / pricing
# ---------------------------------------------------------------------------
def test_redemption_capped_at_post_discount_subtotal(api):
    """PRD §3.3: "The redemption value is the lesser of two quantities: the
    requested redemption points multiplied by the point value of 5 cents per point,
    and the post-discount subtotal (gross total minus promotion discount) —
    redemption can never exceed what remains after discounts."

    Design: Corner/calculations/order_totals_redemption_capped_at_subtotal
    """
    seed = X.setup_account_with_points(250)  # account holds 250 redeemable points
    nursery, account = seed["nursery"], seed["account"]
    small = X.create_product(nursery["id"], sku="DG-SM", name="Twine", unit_price_cents=600)
    order = X.create_order(account["id"])
    X.add_line(order["id"], small["id"], qty=1)
    version = X.current_order_version(order["id"])
    confirmed = validate_success(
        api.confirm_order(order["id"], F.confirm_payload(version, requested_redeem_points=200), CLERK)
    )
    assert confirmed["gross_total_cents"] == 600
    assert confirmed["redemption_cents"] == 600, "capped at subtotal, not 200*5=1000"
    assert confirmed["net_total_cents"] == 0


def test_promotion_inactive_outside_window_no_discount(api):
    """PRD §3.3: "the logical clock's "now" falls within the promotion's half-open
    active window — at or after `starts_at` and strictly before `ends_at`."

    Design: Corner/calculations/promo_inactive_outside_window_no_discount
    """
    X.set_clock("2026-06-10T10:00:00Z")
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_live_plant(nursery["id"], sku="PL-P", name="Petunia",
                                  lifecycle_class="ANNUAL", hardiness_min_zone=1, hardiness_max_zone=13,
                                  unit_price_cents=1000, warranty_days=0, warranty_pct=0)
    X.create_active_promotion(nursery["id"], name="Past Sale", category_scope="LIVE_PLANT",
                              discount_pct=20, starts_at="2026-04-01T00:00:00Z", ends_at="2026-05-01T00:00:00Z")
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=2)
    version = X.current_order_version(order["id"])
    confirmed = validate_success(api.confirm_order(order["id"], F.confirm_payload(version), CLERK))
    assert confirmed["promo_discount_cents"] == 0
    assert confirmed["net_total_cents"] == 2000


def test_confirm_response_carries_fresh_totals(api):
    """PRD §2.6: "Derived and computed fields are reconciled in real time as their
    inputs change".
    PRD §3.3: "The gross total is the sum over all lines of quantity times unit price."

    Design: Corner/consistency_model/confirm_totals_visible_in_same_response
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_product(nursery["id"], sku="DG-IMM", name="Saw", unit_price_cents=700)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=2)
    version = X.current_order_version(order["id"])
    confirmed = validate_success(api.confirm_order(order["id"], F.confirm_payload(version), CLERK))
    assert confirmed["gross_total_cents"] == 1400
    assert confirmed["promo_discount_cents"] == 0
    assert confirmed["net_total_cents"] == 1400
    assert confirmed["fulfillment_status"] == "CONFIRMED"


def test_confirm_empty_order_rejected(api):
    """PRD §3.3: "Confirmation is permitted only when the order has at least one
    line (otherwise `ERR_ORDER_EMPTY`)".

    Design: Corner/state_machines/confirm_empty_order_rejected
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    order = X.create_order(account["id"])
    resp = api.confirm_order(order["id"], F.confirm_payload(order["version"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_ORDER_EMPTY.value)
