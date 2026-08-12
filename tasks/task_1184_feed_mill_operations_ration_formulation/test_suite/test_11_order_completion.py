"""Order completion: quantity tolerance boundary, mismatch rejection, and the
IN_PRODUCTION from-state requirement (PRD §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_confirmed_order, setup_released_batch,
    setup_active_grow_formula, make_customer, make_order,
)

MM = TEST_USERS["mill_manager_headers"]


class TestCompletionQuantityTolerance:
    def test_completion_quantity_exactly_two_pct_passes(self, api):
        """PRD §3.5: "The tolerance check divides the absolute gap between the sum of `actual_tons` over the order's `RELEASED` batches and the order's `tons` by the order's `tons`; a deviation strictly above two percent is rejected with `ERR_ORDER_TONS_MISMATCH`, while exactly 0.02 passes."

        Design: Corner/calculations/completion_quantity_exactly_two_pct_passes
        """
        # Both lines at their exact 2.00 mix limits: corn 7.140, SBM 3.060.
        ctx = setup_released_batch(corn_actual=7.140, sbm_actual=3.060)
        order = validate_success(api.complete_order(ctx["order"]["id"], MM), 200)
        # Released total 10.200 vs order 10 -> deviation exactly 0.02 (inclusive).
        assert order["status"] == "COMPLETED"
        # Final price: corn 214200 + SBM 159120 = 373320; margin 44798;
        # delivery 16500 -> 434618.
        assert order["final_total_cents"] == 434618

    def test_complete_with_released_tons_off_rejected(self, api):
        """PRD §3.5: "a deviation strictly above two percent is rejected with `ERR_ORDER_TONS_MISMATCH`, while exactly 0.02 passes."

        Design: Corner/errors/complete_with_released_tons_off_rejected
        """
        # The only batch targeted (and released) 12t against a 10t order.
        ctx = setup_released_batch(target_tons=12, corn_actual=8.400,
                                   sbm_actual=3.600)
        resp = api.complete_order(ctx["order"]["id"], MM)
        validate_error(resp, ApiErrorId.ERR_ORDER_TONS_MISMATCH)

        order = validate_success(api.get_order(ctx["order"]["id"], MM), 200)
        assert order["status"] == "IN_PRODUCTION", (
            "|12 - 10| / 10 = 0.20 > 0.02: rejected completion leaves the order untouched")


class TestCompletionFromState:
    def test_complete_quoted_order_rejected_invalid_state(self, api):
        """PRD §3.5: "Production flips the order on its own: the first batch of the order to start moves it `CONFIRMED` → `IN_PRODUCTION`. Completion is a `MillManager` act with three gates: the order must not be `blocked` — no batch in `HOLD` — (`ERR_ORDER_BLOCKED`); no batch may remain in `PLANNED`, `BATCHING`, `MIXED`, or `HOLD` (`ERR_INVALID_STATE`); and the released tonnage must land within tolerance."
        PRD §2.11: "State preconditions — transition from-states and cross-entity state requirements, including blocked bins and blocked orders (`ERR_INVALID_STATE`, `ERR_BIN_BLOCKED`, `ERR_ORDER_BLOCKED`)."

        Design: Corner/state_machines/complete_quoted_order_rejected_invalid_state
        """
        env = setup_active_grow_formula()
        customer = make_customer("Acme Farms", 1000000)
        order = make_order(customer, env["formula"]["id"], 10)  # stays QUOTED

        resp = api.complete_order(order["id"], MM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_order(order["id"], MM), 200)
        assert after["status"] == "QUOTED"
