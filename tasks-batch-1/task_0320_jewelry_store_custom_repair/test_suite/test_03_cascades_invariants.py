"""Transitive-cascade and compensating-invariant depth tests.

Translates queue-A difficulty instances under rule_ids transitive_cascade and
compensating_invariant.
"""
import pytest
from test_helpers import (
    validate_success,
    create_deposit_paid_custom_order,
    create_accepted_trade_in,
    create_approved_warranty_claim,
    drive_spawned_warranty_ticket_to_ready,
    create_active_layaway_plan,
    post_ledger_entry,
    TEST_USERS,
)

SA = TEST_USERS["sales_associate_headers"]
GS = TEST_USERS["goldsmith_headers"]
SM = TEST_USERS["store_manager_headers"]


class TestTransitiveCascade:
    def test_cancel_order_refunds_deposit_through_ledger_to_balance(self, api):
        """PRD §3.3: "On cancellation, if any deposit has been collected
        (`deposit_paid_cents` greater than 0), the system refunds it to the customer's store
        credit by posting a `CreditLedgerEntry` with direction `CREDIT`, an `amount_cents`
        equal to `deposit_paid_cents`, and reason `LAYAWAY_REFUND`, then recomputes the
        customer's `store_credit_balance_cents`."

        Design: Difficulty/transitive_cascade/custom_cancel_to_ledger_to_customer_balance_depth3
        """
        order, customer_id = create_deposit_paid_custom_order(
            deposit_cents=90000, estimated_materials_cents=200000, design_fee_cents=50000
        )
        cancelled = validate_success(
            api.cancel_custom_order(order["id"], {"expected_version": order["version"]}, SM), 200
        )
        assert cancelled["status"] == "CANCELLED"
        customer = validate_success(api.get_customer(customer_id, SM), 200)
        assert customer["store_credit_balance_cents"] == 90000

    def test_cancelled_order_reaches_terminal_cancelled_state(self, api):
        """PRD §3.3: "A manager may cancel an order while it is still in any of `DRAFT`,
        `QUOTED`, `DEPOSIT_PAID`, `IN_DESIGN`, `DESIGN_REVIEW`, or `APPROVED`."

        Design: Difficulty/transitive_cascade/custom_cancel_to_ledger_to_customer_balance_depth3
        """
        order, customer_id = create_deposit_paid_custom_order(
            deposit_cents=90000, estimated_materials_cents=200000, design_fee_cents=50000
        )
        cancelled = validate_success(
            api.cancel_custom_order(order["id"], {"expected_version": order["version"]}, SM), 200
        )
        assert cancelled["status"] == "CANCELLED"

    def test_warranty_repair_pickup_bubbles_claim_to_resolved(self, api):
        """PRD §3.4: "If the ticket was spawned from a warranty claim — that is,
        `warranty_claim_id` is set — pickup bubbles up to resolve the originating claim,
        moving that `WarrantyClaim` to `RESOLVED`."

        Design: Difficulty/transitive_cascade/warranty_pickup_bubbles_claim_resolved_depth2
        """
        claim, spawned_rt_id, _, _ = create_approved_warranty_claim()
        ticket = drive_spawned_warranty_ticket_to_ready(spawned_rt_id)
        picked_up = validate_success(
            api.pickup_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, SA), 200
        )
        assert picked_up["status"] == "PICKED_UP"
        claim_after = validate_success(api.get_warranty_claim(claim["id"], SM), 200)
        assert claim_after["status"] == "RESOLVED"

    def test_warranty_ticket_pickup_is_terminal_picked_up(self, api):
        """PRD §3.4: "A sales associate completes the ticket on customer pickup, moving
        `READY → PICKED_UP`."

        Design: Difficulty/transitive_cascade/warranty_pickup_bubbles_claim_resolved_depth2
        """
        claim, spawned_rt_id, _, _ = create_approved_warranty_claim()
        ticket = drive_spawned_warranty_ticket_to_ready(spawned_rt_id)
        picked_up = validate_success(
            api.pickup_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, SA), 200
        )
        assert picked_up["status"] == "PICKED_UP"


class TestCompensatingInvariant:
    def test_credit_then_equal_debit_returns_balance_to_zero(self, api):
        """PRD §2.9: "Each `Customer` exposes a computed `store_credit_balance_cents`, which
        is defined as the exact sum of `amount_cents` over every `CreditLedgerEntry` for that
        customer whose `direction` is `CREDIT`, minus the exact sum of `amount_cents` over
        every entry whose `direction` is `DEBIT`."

        Design: Difficulty/compensating_invariant/store_credit_conserved_under_credit_then_debit
        """
        offer, customer_id = create_accepted_trade_in(
            metal_karat="K18",
            metal_weight_grams=12.0,
            metal_spot_price_cents_per_gram=6000,
            gemstone_value_cents=150000,
            condition="GOOD",
        )
        customer = validate_success(api.get_customer(customer_id, SM), 200)
        assert customer["store_credit_balance_cents"] == 153000
        post_ledger_entry(customer_id, "DEBIT", 153000, reason="PURCHASE")
        customer = validate_success(api.get_customer(customer_id, SM), 200)
        assert customer["store_credit_balance_cents"] == 0

    def test_trade_in_accept_posts_credit_to_balance(self, api):
        """PRD §3.6: "On acceptance the system posts a `CreditLedgerEntry` with direction
        `CREDIT`, `amount_cents` equal to the `buyback_credit_cents`, and reason `TRADE_IN`,
        sets the offer's `credit_ledger_entry_id` to the new entry, recomputes the customer's
        `store_credit_balance_cents`, and increments the offer's `version`."

        Design: Difficulty/compensating_invariant/store_credit_conserved_under_credit_then_debit
        """
        offer, customer_id = create_accepted_trade_in(
            metal_karat="K18",
            metal_weight_grams=12.0,
            metal_spot_price_cents_per_gram=6000,
            gemstone_value_cents=150000,
            condition="GOOD",
        )
        customer = validate_success(api.get_customer(customer_id, SM), 200)
        assert customer["store_credit_balance_cents"] == 153000

    def test_reserve_then_cancel_returns_item_to_in_stock(self, api):
        """PRD §3.5: "Activation sets `paid_to_date_cents` equal to the `down_payment_cents`,
        moves the inventory item to `RESERVED`, increments the item's `version`, and
        increments the plan's `version`."
        PRD §3.5: "If the plan was `ACTIVE`, cancellation releases the reserved item back to
        `IN_STOCK`."

        Design: Difficulty/compensating_invariant/inventory_availability_conserved_under_reserve_then_cancel
        """
        plan, customer_id, item = create_active_layaway_plan(
            item_price_cents=500000, installment_count=5
        )
        reserved_item = validate_success(api.get_inventory_item(item["id"], SM), 200)
        assert reserved_item["status"] == "RESERVED"
        cancelled = validate_success(
            api.cancel_layaway_plan(plan["id"], {"expected_version": plan["version"]}, SM), 200
        )
        assert cancelled["status"] == "CANCELLED"
        item_after = validate_success(api.get_inventory_item(item["id"], SM), 200)
        assert item_after["status"] == "IN_STOCK"

    def test_cancel_active_layaway_reaches_terminal_cancelled(self, api):
        """PRD §3.5: "A manager may cancel a plan from either `PENDING` or `ACTIVE`
        (otherwise `ERR_INVALID_STATE`)."

        Design: Difficulty/compensating_invariant/inventory_availability_conserved_under_reserve_then_cancel
        """
        plan, customer_id, item = create_active_layaway_plan(
            item_price_cents=500000, installment_count=5
        )
        cancelled = validate_success(
            api.cancel_layaway_plan(plan["id"], {"expected_version": plan["version"]}, SM), 200
        )
        assert cancelled["status"] == "CANCELLED"
