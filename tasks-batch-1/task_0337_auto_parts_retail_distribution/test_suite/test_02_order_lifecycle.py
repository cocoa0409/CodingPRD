"""Sales-order lifecycle: the parallel fulfillment x settlement dimensions, and the
two compensation pairs (allocate/cancel conserves inventory; invoice/pay conserves
A/R).

Queue A: non_linear_state_machine (parallel order dimensions), compensating_invariant.
"""
from test_helpers import (
    validate_success, get_success_data, api_client,
    setup_open_wholesale_order_with_line, setup_shipped_caliper_order,
    allocate, ship, invoice, pay, current_version,
    TEST_USERS,
)

REP = TEST_USERS["wholesale_rep_headers"]


# ─── non_linear_state_machine: nlsm_salesorder_parallel_fulfillment_x_settlement ─

class TestParallelOrderDimensions:
    """fulfillment_status and settlement_status advance independently."""

    def test_settlement_stays_unbilled_through_fulfillment(self, api):
        """PRD §3.3: "These two status dimensions evolve independently of one
        another: the physical fulfillment dimension (OPEN, ALLOCATED, SHIPPED,
        CANCELLED) and the financial settlement dimension (UNBILLED, INVOICED, PAID)
        are tracked separately."

        While fulfillment advances OPEN -> ALLOCATED -> SHIPPED, settlement remains
        UNBILLED.

        Design: Difficulty/non_linear_state_machine/nlsm_salesorder_parallel_fulfillment_x_settlement
        """
        part, account, order, line = setup_open_wholesale_order_with_line(qty=2, stock_qty=5)
        allocated = allocate(order["id"])
        assert allocated["fulfillment_status"] == "ALLOCATED"
        assert allocated["settlement_status"] == "UNBILLED", "settlement must stay UNBILLED after allocate"
        shipped = ship(order["id"])
        assert shipped["fulfillment_status"] == "SHIPPED"
        assert shipped["settlement_status"] == "UNBILLED", "settlement must stay UNBILLED after ship"

    def test_fulfillment_frozen_at_shipped_through_settlement(self, api):
        """PRD §3.3: "These two status dimensions evolve independently of one
        another: the physical fulfillment dimension (OPEN, ALLOCATED, SHIPPED,
        CANCELLED) and the financial settlement dimension (UNBILLED, INVOICED, PAID)
        are tracked separately."

        Once SHIPPED, settlement advances UNBILLED -> INVOICED -> PAID while
        fulfillment stays SHIPPED.

        Design: Difficulty/non_linear_state_machine/nlsm_salesorder_parallel_fulfillment_x_settlement
        """
        part, account, order, line = setup_open_wholesale_order_with_line(qty=2, stock_qty=5)
        allocate(order["id"])
        ship(order["id"])
        invoiced = invoice(order["id"])
        assert invoiced["fulfillment_status"] == "SHIPPED"
        assert invoiced["settlement_status"] == "INVOICED"
        paid = pay(order["id"])
        assert paid["fulfillment_status"] == "SHIPPED", "fulfillment must stay SHIPPED after pay"
        assert paid["settlement_status"] == "PAID"


# ─── compensating_invariant: ci_inventory_units_conserved_allocate_then_cancel ─

class TestInventoryConservation:
    """allocate reserves, cancel releases; on_hand + reserved is conserved."""

    def test_cancel_after_allocate_restores_reservation(self, api):
        """PRD §3.4: "Cancelling an ALLOCATED order additionally compensates the
        reservation: for each allocated line the part's reserved_qty is decreased by
        the line's qty and the part's available_qty is recomputed, which conserves
        the total of on-hand plus reserved across the allocate/cancel pair".

        Part on_hand 5 reserved 0; allocate qty 3 then cancel -> back to on_hand 5,
        reserved 0, available 5.

        Design: Difficulty/compensating_invariant/ci_inventory_units_conserved_allocate_then_cancel
        """
        part, account, order, line = setup_open_wholesale_order_with_line(qty=3, stock_qty=5)
        allocate(order["id"])
        cancelled = get_success_data(api_client.cancel_order(order["id"], REP))
        assert cancelled["fulfillment_status"] == "CANCELLED"
        final_part = get_success_data(api_client.get_part(part["id"], REP))
        assert final_part["on_hand_qty"] == 5, "on_hand must be conserved at 5"
        assert final_part["reserved_qty"] == 0, "reservation must be released to 0"
        assert final_part["available_qty"] == 5, "available must return to 5"

    def test_reservation_raised_at_allocate(self, api):
        """PRD §3.4: "for each non-special-order line the part's reserved_qty is
        increased by the line's qty and the part's available_qty is recomputed".

        Before the compensating cancel, allocate must raise reserved_qty to 3 while
        on_hand stays 5 (available drops to 2), establishing the quantity the cancel
        later conserves.

        Design: Difficulty/compensating_invariant/ci_inventory_units_conserved_allocate_then_cancel
        """
        part, account, order, line = setup_open_wholesale_order_with_line(qty=3, stock_qty=5)
        allocate(order["id"])
        allocated_part = get_success_data(api_client.get_part(part["id"], REP))
        assert allocated_part["on_hand_qty"] == 5, "on_hand unchanged at allocation"
        assert allocated_part["reserved_qty"] == 3, "reserved raised to line qty"
        assert allocated_part["available_qty"] == 2, "available = 5 - 3"


# ─── compensating_invariant: ci_ar_balance_conserved_invoice_then_pay ─────────

class TestArBalanceConservation:
    """invoice charges A/R, pay relieves it; A/R returns to zero."""

    def test_invoice_then_pay_returns_ar_to_zero(self, api):
        """PRD §3.5: "the account's ar_balance_cents is increased by the order's
        order_total_cents".
        PRD §3.5: "the account's ar_balance_cents is decreased by the order's
        order_total_cents, clamped at a floor of zero, and the order moves to PAID.
        Invoice and payment form a compensation pair that conserves the account's A/R."

        Caliper order total 19400 (merch 14000 + core 5400). After invoice A/R ==
        19400; after pay A/R == 0.

        Design: Difficulty/compensating_invariant/ci_ar_balance_conserved_invoice_then_pay
        """
        part, account, order, line = setup_shipped_caliper_order(qty=1, stock_qty=3)
        invoiced = invoice(order["id"])
        assert invoiced["order_total_cents"] == 19400, (
            f"order_total expected 19400 (merch 14000 + core 5400), got {invoiced['order_total_cents']}"
        )
        acct_after_invoice = get_success_data(api_client.get_account(account["id"], REP))
        assert acct_after_invoice["ar_balance_cents"] == 19400, "A/R charged with order_total"
        pay(order["id"])
        acct_after_pay = get_success_data(api_client.get_account(account["id"], REP))
        assert acct_after_pay["ar_balance_cents"] == 0, "A/R relieved to 0 after pay (no drift)"

    def test_order_reaches_paid_after_compensation(self, api):
        """PRD §3.5: "the order moves to PAID. Invoice and payment form a
        compensation pair that conserves the account's A/R."

        The settlement dimension lands on PAID at the end of the invoice/pay pair.

        Design: Difficulty/compensating_invariant/ci_ar_balance_conserved_invoice_then_pay
        """
        part, account, order, line = setup_shipped_caliper_order(qty=1, stock_qty=3)
        invoice(order["id"])
        paid = pay(order["id"])
        assert paid["settlement_status"] == "PAID"
