"""Multi-hop cascades and the cyclic reorder-receipt loop.

Queue A: transitive_cascade (ship -> part decrement -> reorder auto-suggest;
core accept -> line decrement -> account credit), non_linear_state_machine
(reorder PARTIALLY_RECEIVED self-loop).
"""
from test_helpers import (
    validate_success, get_success_data, api_client,
    setup_allocated_wholesale_order, setup_pending_core_return, setup_ordered_reorder,
    ship, current_version,
    receive_reorder_payload,
    TEST_USERS,
)

REP = TEST_USERS["wholesale_rep_headers"]
INV = TEST_USERS["inventory_manager_headers"]
ADMIN = TEST_USERS["warranty_admin_headers"]


def _reorders_for_part(part_id):
    resp = api_client.list_reorder_requests(REP, params={"part_id": part_id})
    data, _ = _paginated(resp)
    return data


def _paginated(resp):
    from test_helpers import validate_paginated
    return validate_paginated(resp)


# ─── transitive_cascade: tc_ship_decrements_part_autosuggests_reorder ─────────

class TestShipReorderCascade:
    """ship -> on_hand decrement -> available recompute crosses reorder_point ->
    SUGGESTED reorder auto-created."""

    def test_ship_decrements_inventory(self, api):
        """PRD §3.4: "for each allocated line the part's on_hand_qty is decreased by
        the line's qty and its reserved_qty is decreased by the line's qty, then
        available_qty is recomputed".

        Rotor on_hand 5, reorder_point 2; allocate+ship qty 3 -> on_hand 2,
        reserved 0, available 2 (hop 1 of the cascade).

        Design: Difficulty/transitive_cascade/tc_ship_decrements_part_autosuggests_reorder
        """
        part, account, order, line = setup_allocated_wholesale_order(
            qty=3, stock_qty=5,
            part_overrides=dict(description="Rotor", list_price_cents=9000, cost_cents=4000,
                                core_charge_cents=0, is_rebuildable=False, warranty_days=30,
                                stockable=True, reorder_point=2, reorder_qty=4))
        ship(order["id"])
        final = get_success_data(api_client.get_part(part["id"], REP))
        assert final["on_hand_qty"] == 2
        assert final["reserved_qty"] == 0
        assert final["available_qty"] == 2

    def test_ship_auto_suggests_reorder_at_threshold(self, api):
        """PRD §3.4: "if the part is now at or below its reorder point and is
        stockable with no open reorder request, a new SUGGESTED reorder request is
        auto-created as the second hop (per §2.6)."
        PRD §2.6: "The suggested request's replenishment quantity is snapshotted from
        the part's reorder_qty."

        Shipping to available 2 (== reorder_point 2) creates exactly one SUGGESTED
        reorder with qty_ordered == 4 (hop 3 of the cascade).

        Design: Difficulty/transitive_cascade/tc_ship_decrements_part_autosuggests_reorder
        """
        part, account, order, line = setup_allocated_wholesale_order(
            qty=3, stock_qty=5,
            part_overrides=dict(description="Rotor", list_price_cents=9000, cost_cents=4000,
                                core_charge_cents=0, is_rebuildable=False, warranty_days=30,
                                stockable=True, reorder_point=2, reorder_qty=4))
        ship(order["id"])
        reorders = _reorders_for_part(part["id"])
        suggested = [r for r in reorders if r["status"] == "SUGGESTED"]
        assert len(suggested) == 1, f"expected exactly one SUGGESTED reorder, got {len(suggested)}"
        assert suggested[0]["qty_ordered"] == 4, "qty_ordered snapshotted from reorder_qty"


# ─── transitive_cascade: tc_core_accept_decrements_line_credits_account ───────

class TestCoreAcceptCascade:
    """core accept -> cores_outstanding decrement -> account A/R credit."""

    def test_accept_decrements_cores_outstanding(self, api):
        """PRD §3.6: "Acceptance cascades in two hops: first the line's
        cores_outstanding is decreased by the return qty, and then the refund is
        credited against the order's account".

        Caliper line cores_outstanding 1; accepting the qty-1 core return drops it
        to 0 (hop 2).

        Design: Difficulty/transitive_cascade/tc_core_accept_decrements_line_credits_account
        """
        part, account, order, line, cr = setup_pending_core_return(qty=1, line_qty=1)
        accepted = get_success_data(api_client.accept_core_return(cr["id"], ADMIN))
        assert accepted["status"] == "ACCEPTED"
        final_line = get_success_data(api_client.get_order_line(line["id"], REP))
        assert final_line["cores_outstanding"] == 0, "cores_outstanding must drop to 0"

    def test_accept_credits_account_ar(self, api):
        """PRD §3.6: "and then the refund is credited against the order's account -
        the account's ar_balance_cents is decreased by refund_cents, clamped at a
        floor of zero - before the return moves to ACCEPTED."

        Invoiced caliper order charges A/R 19400; accepting the core refund (5400)
        relieves A/R to 14000 (hop 3).

        Design: Difficulty/transitive_cascade/tc_core_accept_decrements_line_credits_account
        """
        part, account, order, line, cr = setup_pending_core_return(qty=1, line_qty=1)
        before = get_success_data(api_client.get_account(account["id"], REP))
        assert before["ar_balance_cents"] == 19400, "A/R charged with invoiced order total"
        get_success_data(api_client.accept_core_return(cr["id"], ADMIN))
        after = get_success_data(api_client.get_account(account["id"], REP))
        assert after["ar_balance_cents"] == 14000, (
            f"A/R should drop by the 5400 core refund to 14000, got {after['ar_balance_cents']}"
        )


# ─── non_linear_state_machine: nlsm_reorder_cyclic_partial_receipt_loop ───────

class TestReorderPartialReceiptLoop:
    """PARTIALLY_RECEIVED -> receive -> PARTIALLY_RECEIVED repeats, accumulating."""

    def test_partial_receipts_accumulate_in_loop(self, api):
        """PRD §3.8: "When the new running total of qty_received plus receive_qty
        still falls short of qty_ordered, the request lands in (or remains in)
        PARTIALLY_RECEIVED and can absorb further partial receipts in a loop."

        ORDERED reorder qty_ordered 10: receive 3 -> PARTIALLY_RECEIVED qty 3;
        receive 4 -> PARTIALLY_RECEIVED qty 7.

        Design: Difficulty/non_linear_state_machine/nlsm_reorder_cyclic_partial_receipt_loop
        """
        part, ro = setup_ordered_reorder(reorder_qty=10, reorder_point=2)
        r1 = get_success_data(api_client.receive_reorder_request(
            ro["id"], receive_reorder_payload(3), INV))
        assert r1["status"] == "PARTIALLY_RECEIVED"
        assert r1["qty_received"] == 3
        r2 = get_success_data(api_client.receive_reorder_request(
            ro["id"], receive_reorder_payload(4), INV))
        assert r2["status"] == "PARTIALLY_RECEIVED"
        assert r2["qty_received"] == 7

    def test_final_receipt_completes_and_stocks_part(self, api):
        """PRD §3.8: "When the running total of qty_received plus receive_qty exactly
        equals qty_ordered, the receipt completes the request: qty_received becomes
        equal to qty_ordered and the request moves to RECEIVED."
        PRD §3.8: "Each receipt increases the part's on_hand_qty by receive_qty,
        recomputes the part's available_qty, and adds receive_qty to qty_received."

        After 3 + 4 + 3 = 10 receipts the reorder is RECEIVED (qty_received 10) and
        the part's on_hand reaches 10.

        Design: Difficulty/non_linear_state_machine/nlsm_reorder_cyclic_partial_receipt_loop
        """
        part, ro = setup_ordered_reorder(reorder_qty=10, reorder_point=2)
        api_client.receive_reorder_request(ro["id"], receive_reorder_payload(3), INV)
        api_client.receive_reorder_request(ro["id"], receive_reorder_payload(4), INV)
        r3 = get_success_data(api_client.receive_reorder_request(
            ro["id"], receive_reorder_payload(3), INV))
        assert r3["status"] == "RECEIVED"
        assert r3["qty_received"] == 10
        final_part = get_success_data(api_client.get_part(part["id"], INV))
        assert final_part["on_hand_qty"] == 10, "on_hand accumulates to 10 across receipts"
