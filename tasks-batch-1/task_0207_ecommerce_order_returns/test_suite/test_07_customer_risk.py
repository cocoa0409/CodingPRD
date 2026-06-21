"""Customer return-risk score: lifetime vs trailing-window variants (PRD §3.9).

Difficulty queue: dual_variant_calc (lifetime score diverges from windowed score).
"""
import pytest

from test_helpers import fixtures as fx, validate_success


def _build_customer_with_old_purchase_and_recent_refund(api):
    """Customer captures a grand_total-11042 order dated 2026-01-01, then receives a
    2437-cent cash refund settled at 2026-06-05. Returns the customer dict."""
    fx.set_clock("2026-01-01T00:00:00Z")
    customer = fx.create_customer()
    warehouse = fx.create_warehouse()
    p1 = fx.create_product(unit_price_cents=2599, tax_rate_bps=875,
                           restocking_fee_bps=1500, return_window_days=365)
    p2 = fx.create_product(unit_price_cents=1499, tax_rate_bps=875,
                           return_window_days=365)
    fx.stock_inventory(p1["id"], warehouse["id"], 100)
    fx.stock_inventory(p2["id"], warehouse["id"], 100)

    order = fx.create_cart(customer["id"], promo_flat_cents=0)
    line1 = fx.add_line(order["id"], customer["id"], p1["id"], 2)
    fx.add_line(order["id"], customer["id"], p2["id"], 3)
    fx.checkout(order["id"], customer["id"])
    fx.capture(order["id"])

    shipment, _ = fx.create_pending_shipment(order["id"], warehouse["id"], line1["id"], 2)
    fx.get_success_data(api.ship_shipment(shipment["id"], fx.OP))
    fx.get_success_data(api.deliver_shipment(shipment["id"], fx.OP))

    # Refund settled at 2026-06-05 (inside a later 90-day window).
    fx.set_clock("2026-06-05T00:00:00Z")
    fx.open_approve_settle_return(
        order["id"], customer["id"], "NO_LONGER_WANTED", "REFUND",
        [{"order_line_id": line1["id"], "return_qty": 1}])
    return customer


def test_lifetime_return_risk_score(api):
    """PRD §3.9: "The lifetime score is the customer's lifetime_refunded_cents
    divided by their lifetime_purchased_cents, rounded half up to four decimal
    places; when lifetime purchases are 0 the score is 0."

    Design: Difficulty/dual_variant_calc/customer_risk_lifetime_vs_trailing_window_diverge
    """
    customer = _build_customer_with_old_purchase_and_recent_refund(api)
    resp = api.get_customer_risk(customer["id"], fx.ADMIN)
    data = validate_success(resp, 200)
    assert data["return_risk_score"] == pytest.approx(0.2207, abs=1e-9), \
        "2437 refunded / 11042 purchased = 0.2207"


def test_trailing_window_return_risk_diverges_from_lifetime(api):
    """PRD §3.9: "A StoreAdmin may also request a trailing-window variant of this
    score by supplying a window_days query parameter: the numerator and denominator
    are then restricted to orders captured and refunds settled on or after the
    current clock minus that many days (comparing each order's and refund's
    created_at against that cutoff), which yields a different score than the lifetime
    figure".
    PRD §3.9: "when lifetime purchases are 0 the score is 0."

    Design: Difficulty/dual_variant_calc/customer_risk_lifetime_vs_trailing_window_diverge
    """
    customer = _build_customer_with_old_purchase_and_recent_refund(api)

    lifetime_resp = api.get_customer_risk(customer["id"], fx.ADMIN)
    lifetime = validate_success(lifetime_resp, 200)["return_risk_score"]

    window_resp = api.get_customer_risk(customer["id"], fx.ADMIN,
                                        params={"window_days": 90})
    window = validate_success(window_resp, 200)["return_risk_score"]

    assert window == pytest.approx(0, abs=1e-9), \
        "purchase dated 2026-01-01 is outside the 90-day window from clock 2026-06-05 → windowed purchased 0 → score 0"
    assert lifetime != window, "the two variants return different numbers"
