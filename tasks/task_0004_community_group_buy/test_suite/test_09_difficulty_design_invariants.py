"""Difficulty-design coverage: Rule 9 — Compensating-action invariants.

Two instances:
  - flash_inventory_conservation
  - commission_money_conservation
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_flash_scenario,
    setup_picked_up_order,
    file_after_sales, start_review, resolve_case,
    find_commission_entry, list_commission_entries,
    create_flash_purchase_payload,
    assert_flash_inventory_invariant,
    ADMIN, make_customer_headers,
)


class TestFlashInventoryConservation:
    """# difficulty: compensating_invariant/flash_inventory_conservation"""

    def _purchase_and_cancel(self, requested_units=3, total_stock=10):
        sc = setup_flash_scenario(total_stock=total_stock,
                                    tier_caps=[{"tier": 0, "max_units": 5}])
        order = get_success_data(api_client.flash_purchase(
            sc["flash_campaign"]["id"],
            create_flash_purchase_payload(requested_units=requested_units),
            make_customer_headers(sc["customer"]["id"]),
        ))
        order_after_cancel = get_success_data(api_client.cancel_order(
            order["id"], make_customer_headers(sc["customer"]["id"])
        ))
        fc_after = get_success_data(api_client.get_flash_campaign(
            sc["flash_campaign"]["id"], ADMIN
        ))
        return order_after_cancel, fc_after

    def test_inventory_returns_to_total_stock_after_cancel(self, api):
        """PRD §3.5: "The platform additionally rolls back the inventory:
        allocated_units is decreased by the order's flash_granted_units and
        remaining_units is increased by the same amount".

        Claim: after a 3-unit purchase from a 10-stock campaign followed by
        a cancel, allocated_units=0, remaining_units=10, locked_units=0.
        """
        order_after, fc_after = self._purchase_and_cancel(requested_units=3, total_stock=10)
        assert order_after["payment_status"] == "REFUNDED"
        assert order_after["fulfillment_status"] == "CANCELLED"
        assert fc_after["allocated_units"] == 0
        assert fc_after["remaining_units"] == 10
        assert fc_after["locked_units"] == 0
        assert_flash_inventory_invariant(fc_after)

    def test_invariant_holds_under_forward_plus_compensating_action(self, api):
        """PRD §3.5: "remaining_units equals total_stock minus locked_units
        minus allocated_units."

        Claim: after a cancel that follows a purchase, the conserved
        invariant locked + allocated + remaining == total_stock holds.
        """
        _, fc_after = self._purchase_and_cancel(requested_units=2, total_stock=10)
        assert (fc_after["locked_units"] + fc_after["allocated_units"]
                + fc_after["remaining_units"]) == fc_after["total_stock"]


class TestCommissionMoneyConservation:
    """# difficulty: compensating_invariant/commission_money_conservation"""

    def _setup_picked_up_with_settled_total_100(self):
        return setup_picked_up_order(unit_price_cents=100, quantity=1)

    def test_net_rebate_cents_preserved_across_refund_clawback_flag(self, api):
        """PRD §3.9 Clawback Lifecycle: "When an order's payment_status
        advances to REFUND_PENDING (whether through campaign failure, a
        flash-order cancel, or an after-sales REFUND_ONLY / RETURN_REFUND
        resolution), every PENDING CommissionEntry derived from that order
        advances from PENDING to PENDING_CLAWBACK."

        Claim: the entry's net_rebate_cents value is preserved across the
        compensating action — only its status changes from PENDING to
        PENDING_CLAWBACK.
        """
        sc = self._setup_picked_up_with_settled_total_100()
        order = sc["order"]
        entry_before = find_commission_entry(sc["leader"]["id"], order["id"])
        assert entry_before is not None
        net_before = entry_before["net_rebate_cents"]
        assert net_before == 7  # gross=8, tax=1, net=7

        case = file_after_sales(order["id"], sc["customer"]["id"], "REFUND_ONLY", 100)
        start_review(case["id"])
        resolve_case(case["id"], "REFUND_ONLY")

        entry_after = find_commission_entry(sc["leader"]["id"], order["id"])
        assert entry_after["status"] == "PENDING_CLAWBACK"
        assert entry_after["net_rebate_cents"] == net_before

    def test_sum_of_net_rebate_cents_invariant_across_refund(self, api):
        """PRD §3.9 Clawback Lifecycle: "every PENDING CommissionEntry
        derived from that order advances from PENDING to PENDING_CLAWBACK."

        Claim: summing net_rebate_cents over CommissionEntry rows for the
        order yields the same value before and immediately after the
        compensating action — only entry status changes, the underlying
        money figure is preserved.
        """
        sc = self._setup_picked_up_with_settled_total_100()
        order = sc["order"]
        entries_before = [e for e in list_commission_entries(sc["leader"]["id"])
                          if e["order_id"] == order["id"]]
        sum_before = sum(e["net_rebate_cents"] for e in entries_before)

        case = file_after_sales(order["id"], sc["customer"]["id"], "REFUND_ONLY", 100)
        start_review(case["id"])
        resolve_case(case["id"], "REFUND_ONLY")

        entries_after = [e for e in list_commission_entries(sc["leader"]["id"])
                         if e["order_id"] == order["id"]]
        sum_after = sum(e["net_rebate_cents"] for e in entries_after)
        assert sum_before == sum_after
