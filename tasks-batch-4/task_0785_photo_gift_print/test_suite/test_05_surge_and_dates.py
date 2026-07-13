"""Dual-variant promised ship date, surge capacity admission/release, placement promo window."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_approved_project, place_order, pay_order, cancel_order,
    set_clock, create_surge_window, create_promotion, create_promo_window,
)


class TestPromisedShipDateVariants:
    """Quote ignores surge (estimated); payment applies the real surge extension (scheduled)."""

    def test_quote_estimated_date_ignores_surge(self, api):
        """PRD 3.4: "In a quote, the surge extension is always 0 — the estimate ignores holiday surge
        entirely and returns the base turnaround."

        Design: Difficulty/dual_variant_calc/promised_ship_date_estimated_vs_scheduled_surge
        """
        set_clock("2026-06-05T00:00:00Z")
        create_surge_window(name="Summer", starts_at="2026-06-01T00:00:00Z", ends_at="2026-06-10T00:00:00Z",
                            turnaround_extra_days=4, capacity_per_day=100, product_type_scope="PHOTOBOOK")
        ctx = setup_approved_project()  # PHOTOBOOK base 1000, production_days 3
        data = validate_success(
            api.quote_project(ctx["proj"]["id"], {"quantity": 10, "finish": "MATTE", "ship_method": "STANDARD"}, ctx["headers"]), 200
        )
        # 2026-06-05 + prod 3 + surge 0 (quote) + transit 5 (STANDARD) = 2026-06-13
        assert data["promised_ship_date"] == "2026-06-13", f"got {data['promised_ship_date']}"

    def test_paid_order_scheduled_date_includes_surge(self, api):
        """PRD 3.5: "The scheduled promised ship date uses the same calendar arithmetic as the quote,
        except the surge extension is real: if a surge window covers the scheduled production date for
        the order's product type (using the half-open coverage rule), the promised date is extended by
        that window's turnaround_extra_days; otherwise the extension is 0."

        Design: Difficulty/dual_variant_calc/promised_ship_date_estimated_vs_scheduled_surge
        """
        set_clock("2026-06-05T00:00:00Z")
        create_surge_window(name="Summer", starts_at="2026-06-01T00:00:00Z", ends_at="2026-06-10T00:00:00Z",
                            turnaround_extra_days=4, capacity_per_day=100, product_type_scope="PHOTOBOOK")
        ctx = setup_approved_project()
        order = place_order(ctx, quantity=10, finish="MATTE", ship_method="STANDARD", payment_method="CARD")
        paid = pay_order(order, ctx["headers"])
        # 2026-06-05 + prod 3 + surge 4 + transit 5 = 2026-06-17
        assert paid["promised_ship_date"] == "2026-06-17", f"got {paid['promised_ship_date']}"


class TestSurgeCapacityConservation:
    """A full surge day rejects further payment; cancelling frees the capacity again."""

    def _full_day_setup(self):
        set_clock("2026-06-05T00:00:00Z")
        create_surge_window(name="Peak", starts_at="2026-06-01T00:00:00Z", ends_at="2026-06-10T00:00:00Z",
                            turnaround_extra_days=0, capacity_per_day=5, product_type_scope="PHOTOBOOK")
        ctx = setup_approved_project()
        order1 = place_order(ctx, quantity=5, finish="MATTE", ship_method="STANDARD", payment_method="CARD")
        pay_order(order1, ctx["headers"])  # consumes the whole 5-unit day
        order2 = place_order(ctx, quantity=1, finish="MATTE", ship_method="STANDARD", payment_method="CARD")
        return ctx, order1, order2

    def test_payment_into_full_day_rejected(self, api):
        """PRD 3.5: "The remaining capacity is the day's capacity minus that used amount, and payment
        is refused with ERR_SURGE_CAPACITY_FULL when the order's quantity exceeds the remaining
        capacity."

        Design: Difficulty/compensating_invariant/surge_capacity_conserved_schedule_then_cancel
        """
        ctx, order1, order2 = self._full_day_setup()
        res = api.pay_order(order2["id"], ctx["headers"])
        validate_error(res, "ERR_SURGE_CAPACITY_FULL", 409)

    def test_cancel_frees_capacity_for_retry(self, api):
        """PRD 3.5: "Cancelling an order later removes its job's quantity from the used sum, restoring
        the day's remaining capacity."

        Design: Difficulty/compensating_invariant/surge_capacity_conserved_schedule_then_cancel
        """
        ctx, order1, order2 = self._full_day_setup()
        api.pay_order(order2["id"], ctx["headers"])  # fails: full
        cancel_order(order1, ctx["headers"], "CARD")  # releases 5 units
        retried = validate_success(api.pay_order(order2["id"], ctx["headers"]), 200)
        assert retried["fulfillment_status"] == "IN_PRODUCTION", f"got {retried['fulfillment_status']}"
        assert retried["payment_status"] == "PAID"


class TestPlacementPromoWindow:

    def test_promo_window_closed_at_placement_rejected(self, api):
        """PRD 3.5: "each promotion must have an open promo window at the current logical clock
        instant — an interval [starts_at, ends_at] that includes the clock — else ERR_PROMO_NOT_ACTIVE"

        Design: Corner/validations/corner_promo_not_active_at_placement
        """
        set_clock("2026-07-01T00:00:00Z")
        ctx = setup_approved_project()
        promo = create_promotion("SEASON", "PERCENT", 20, min_subtotal_cents=0, stackable=True, per_customer_limit=9)
        create_promo_window(promo["id"], "2026-06-01T00:00:00Z", "2026-06-10T00:00:00Z")  # closed before the clock
        res = api.create_order({"project_id": ctx["proj"]["id"], "quantity": 10, "finish": "MATTE",
                                "ship_method": "STANDARD", "ship_address_id": ctx["addr"]["id"],
                                "payment_method": "CARD", "promo_codes": ["SEASON"]}, ctx["headers"])
        validate_error(res, "ERR_PROMO_NOT_ACTIVE", 409)
