"""Subscriptions and recurring shipments (PRD §3.8).

Covers estimate-vs-settled charge divergence across a price change and the
pause/resume cycle.
"""
from test_helpers import (
    validate_success, make_customer_headers, ADMIN,
    create_customer, create_product, create_subscription, set_clock,
)


class TestEstimateVsSettledDivergence:
    """dual_variant_calc / subscription_estimate_vs_settled_diverge —
    estimated_charge_cents freezes the box price at scheduling (5000) while
    settled_charge_cents re-reads it at ship after a price bump (5500)."""

    def _advance_shipment(self, api):
        customer = create_customer(account_type="RETAIL")
        box = create_product(base_price_cents=5000, shelf_life_days=60, unit_weight_g=250)
        sub = create_subscription(customer["id"], box["id"], 30, "2026-07-05T00:00:00Z")
        set_clock("2026-07-05T00:00:00Z")
        shipment = validate_success(api.advance_subscription(sub["id"], ADMIN), 201)
        return box, shipment

    def test_advance_estimates_charge_at_scheduling_price(self, api):
        """PRD §3.8: "its `estimated_charge_cents` is the box product's current
        `base_price_cents` read at scheduling time."

        Design: Difficulty/dual_variant_calc/subscription_estimate_vs_settled_diverge
        """
        _box, shipment = self._advance_shipment(api)
        assert shipment["estimated_charge_cents"] == 5000, shipment

    def test_ship_settles_at_changed_price_diverging_from_estimate(self, api):
        """PRD §3.8: "Shipping settles the charge: `settled_charge_cents` is the
        box product's `base_price_cents` re-read at ship time." PRD §3.8: "the
        settled charge equals the earlier estimate only when the box SKU's
        `base_price_cents` did not change in between; if it did, the settled
        figure is authoritative."

        Design: Difficulty/dual_variant_calc/subscription_estimate_vs_settled_diverge
        """
        box, shipment = self._advance_shipment(api)
        validate_success(api.update_product(box["id"], {"base_price_cents": 5500}, ADMIN))
        set_clock("2026-07-06T00:00:00Z")
        shipped = validate_success(api.ship_shipment(shipment["id"], ADMIN))
        assert shipped["estimated_charge_cents"] == 5000, shipped
        assert shipped["settled_charge_cents"] == 5500, shipped


def test_subscription_pause_then_resume(api):
    """PRD §3.8: "A subscription may be paused by its owner (`ACTIVE -> PAUSED`)
    and later resumed (`PAUSED -> ACTIVE`); this pause/resume cycle may repeat."

    Design: Corner/state_machines/subscription_pause_then_resume
    """
    customer = create_customer(account_type="RETAIL")
    box = create_product(base_price_cents=4000, shelf_life_days=60, unit_weight_g=200)
    sub = create_subscription(customer["id"], box["id"], 30, "2026-08-01T00:00:00Z")
    headers = make_customer_headers(customer["id"])
    validate_success(api.pause_subscription(sub["id"], headers))
    resumed = validate_success(api.resume_subscription(sub["id"], headers))
    assert resumed["status"] == "ACTIVE", resumed
