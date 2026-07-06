"""Transitive cancellation cascades and the standing-order lifecycle cycle."""
from test_helpers import (
    validate_success, get_success_data,
    setup_committed_line_with_account, make_standing_order, make_delivery_order,
    make_route, add_stop, set_clock, get_standing_order, get_order, get_route,
    get_stop, get_line, get_account, TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]


class TestStandingOrderCancelCascade:
    def _scenario(self, api):
        ctx = setup_committed_line_with_account(api, base_price_cents=400, par_qty=20,
                                                production_date="2026-06-10T00:00:00Z")
        set_clock(api, "2026-06-08T00:00:00Z")
        so = make_standing_order(api, ctx["account"]["id"], ctx["product"]["id"],
                                 qty_per_delivery=5, weekday_mask=["WED"], cutoff_hours=24)
        order = make_delivery_order(api, ctx["account"]["id"], ctx["product"]["id"],
                                    ctx["line"]["id"], qty=5,
                                    delivery_date="2026-06-10T10:00:00Z",
                                    standing_order_id=so["id"])
        route = make_route(api, route_date="2026-06-10T00:00:00Z", driver_name="Dan",
                           window_start="2026-06-10T06:00:00Z", window_end="2026-06-10T14:00:00Z")
        stop = add_stop(api, route["id"], order["id"], sequence=1,
                        arrival_window_start="2026-06-10T08:00:00Z",
                        arrival_window_end="2026-06-10T09:00:00Z")
        validate_success(api.cancel_standing_order(so["id"], MANAGER))
        return {"so": so, "order": order, "route": route, "stop": stop, "line": ctx["line"]}

    def test_cancel_cascades_to_standing_order_and_delivery_order(self, api):
        """PRD 3.6: "Cancelling a standing order ... sets it to CANCELLED and triggers a
        three-link cascade. First, every delivery order citing this standing order whose
        fulfillment_status is PENDING, PACKED, or OUT_FOR_DELIVERY is transitioned to
        CANCELLED."

        Design: Difficulty/transitive_cascade/standing_order_cancel_cascades_to_route_load
        """
        s = self._scenario(api)
        assert get_standing_order(api, s["so"]["id"])["status"] == "CANCELLED"
        assert get_order(api, s["order"]["id"])["fulfillment_status"] == "CANCELLED"

    def test_cancel_cascades_through_stop_to_route_load_and_par(self, api):
        """PRD 3.6: "each such order cancellation releases its par ... and cancels that
        order's non-cancelled route stop, if any. Third, each stop cancellation makes the
        stop's route recompute its stop_count and total_load_qty."

        Design: Difficulty/transitive_cascade/standing_order_cancel_cascades_to_route_load
        """
        s = self._scenario(api)
        assert get_stop(api, s["stop"]["id"])["status"] == "CANCELLED"
        route = get_route(api, s["route"]["id"])
        assert route["total_load_qty"] == 0, route
        assert route["stop_count"] == 0, route
        assert get_line(api, s["line"]["id"])["reserved_qty"] == 0


class TestAccountCloseCascade:
    def _scenario(self, api):
        ctx = setup_committed_line_with_account(api, base_price_cents=400, par_qty=20,
                                                production_date="2026-06-10T00:00:00Z")
        set_clock(api, "2026-06-08T00:00:00Z")
        so = make_standing_order(api, ctx["account"]["id"], ctx["product"]["id"],
                                 qty_per_delivery=5, weekday_mask=["WED"], cutoff_hours=24)
        order = make_delivery_order(api, ctx["account"]["id"], ctx["product"]["id"],
                                    ctx["line"]["id"], qty=5,
                                    delivery_date="2026-06-10T10:00:00Z",
                                    standing_order_id=so["id"])
        validate_success(api.close_account(ctx["account"]["id"], MANAGER))
        return {"account": ctx["account"], "so": so, "order": order, "line": ctx["line"]}

    def test_close_cancels_account_and_standing_order(self, api):
        """PRD 3.9: "Closing an account is permitted from either ACTIVE or SUSPENDED, but
        only when its credit_balance_cents is exactly zero; the account then moves to
        CLOSED and a cascade runs. Every standing order of the account that is ACTIVE or
        PAUSED is cancelled".

        Design: Difficulty/transitive_cascade/account_close_cascades_to_delivery_orders
        """
        s = self._scenario(api)
        assert get_account(api, s["account"]["id"])["status"] == "CLOSED"
        assert get_standing_order(api, s["so"]["id"])["status"] == "CANCELLED"

    def test_close_cancels_open_delivery_orders_releasing_par(self, api):
        """PRD 3.9: "each such standing order's non-cancelled, non-delivered delivery orders
        (those in PENDING, PACKED, or OUT_FOR_DELIVERY) are cancelled as well — which
        releases their par exactly as an individual order cancellation would".

        Design: Difficulty/transitive_cascade/account_close_cascades_to_delivery_orders
        """
        s = self._scenario(api)
        assert get_order(api, s["order"]["id"])["fulfillment_status"] == "CANCELLED"
        assert get_line(api, s["line"]["id"])["reserved_qty"] == 0


class TestStandingOrderPauseResumeCycle:
    def _cycle(self, api):
        account = get_success_data(api.create_wholesale_account(
            {"name": "Deli", "credit_limit_cents": 1_000_000, "contract_tier": "STANDARD"}, MANAGER))
        product = get_success_data(api.create_product(
            {"sku": "CYC-1", "name": "Bagel", "category": "BREAD",
             "base_price_cents": 250, "shelf_life_hours": 24}, MANAGER))
        so = make_standing_order(api, account["id"], product["id"], qty_per_delivery=10,
                                 weekday_mask=["MON"], cutoff_hours=24)
        v0 = so["version"]
        validate_success(api.pause_standing_order(so["id"], MANAGER))
        validate_success(api.resume_standing_order(so["id"], MANAGER))
        return so["id"], v0

    def test_pause_then_resume_returns_to_active(self, api):
        """PRD 3.6: "A manager may pause an ACTIVE standing order to PAUSED and resume a
        PAUSED one back to ACTIVE".

        Design: Difficulty/non_linear_state_machine/standing_order_active_paused_active_cycle
        """
        so_id, _ = self._cycle(api)
        assert get_standing_order(api, so_id)["status"] == "ACTIVE"

    def test_each_transition_increments_version(self, api):
        """PRD 2.4: "a version integer that begins at 1 (or the server's chosen initial
        value) and increments by one on every mutation."

        Design: Difficulty/non_linear_state_machine/standing_order_active_paused_active_cycle
        """
        so_id, v0 = self._cycle(api)
        # Two mutations (pause, resume) from the observed creation version, absolute base agnostic.
        assert get_standing_order(api, so_id)["version"] == v0 + 2
