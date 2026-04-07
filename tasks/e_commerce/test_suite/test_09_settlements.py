"""
Test 09 -- Settlement lifecycle, reconciliation, period overlap, and balance.

Covers:
  - DRAFT -> PENDING_APPROVAL -> APPROVED -> PAID full lifecycle
  - PENDING_APPROVAL -> DISPUTED -> PENDING_APPROVAL (dispute + resolve)
  - Reconciliation arithmetic (gross, commission, refunds, net)
  - Period overlap detection
  - Settlement balance updates on mark-paid
"""

import pytest
from datetime import datetime, timedelta, timezone

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_cost_precision, assert_settlement, assert_shop_invariants,
    create_settlement_payload,
    create_and_approve_shop, create_and_list_product,
    setup_settlement_scenario, setup_submitted_settlement,
    setup_completed_order_for_refund, place_pay_and_deliver_order,
    get_shop_after,
    ERR_SETTLEMENT_NOT_DRAFT, ERR_SETTLEMENT_NOT_PENDING,
    ERR_SETTLEMENT_NOT_APPROVED, ERR_SETTLEMENT_NOT_DISPUTED_STATE,
    ERR_SETTLEMENT_PERIOD_OVERLAP, ERR_SETTLEMENT_ZERO_AMOUNT,
    ERR_SETTLEMENT_RECONCILIATION_MISMATCH,
    TEST_USERS,
)

_seller = TEST_USERS["seller_headers"]
_admin = TEST_USERS["admin_headers"]
_customer = TEST_USERS["customer_headers"]


# ============================================================================
# Settlement lifecycle
# ============================================================================


class TestSettlementLifecycle:
    """DRAFT -> PENDING_APPROVAL -> APPROVED -> PAID."""

    def test_create_settlement_is_draft(self):
        """A newly created settlement starts in DRAFT status."""
        shop, orders, settlement = setup_settlement_scenario(num_orders=2)
        assert settlement["status"] == "DRAFT"
        assert_settlement(settlement)

    def test_submit_settlement_transitions_to_pending(self):
        """Submitting a DRAFT settlement moves it to PENDING_APPROVAL."""
        shop, orders, settlement = setup_settlement_scenario(num_orders=2)
        submitted = get_success_data(
            api_client.submit_settlement(shop["id"], settlement["id"], _seller)
        )
        assert submitted["status"] == "PENDING_APPROVAL"
        assert_settlement(submitted)

    def test_approve_settlement_transitions_to_approved(self):
        """Approving a PENDING_APPROVAL settlement moves it to APPROVED."""
        shop, orders, settlement = setup_settlement_scenario(num_orders=2)
        get_success_data(
            api_client.submit_settlement(shop["id"], settlement["id"], _seller)
        )
        approved = get_success_data(
            api_client.approve_settlement(shop["id"], settlement["id"], _admin)
        )
        assert approved["status"] == "APPROVED"
        assert_settlement(approved)

    def test_mark_paid_transitions_to_paid(self):
        """Marking an APPROVED settlement as paid moves it to PAID."""
        shop, orders, settlement = setup_settlement_scenario(num_orders=2)
        get_success_data(
            api_client.submit_settlement(shop["id"], settlement["id"], _seller)
        )
        get_success_data(
            api_client.approve_settlement(shop["id"], settlement["id"], _admin)
        )
        paid = get_success_data(
            api_client.mark_settlement_paid(shop["id"], settlement["id"], _admin)
        )
        assert paid["status"] == "PAID"
        assert_settlement(paid)

    def test_submit_requires_positive_net_amount(self):
        """Submitting a settlement with zero net_amount fails."""
        shop = create_and_approve_shop()
        # No orders -> net_amount would be 0
        now = datetime.now(timezone.utc)
        payload = create_settlement_payload(
            period_start=(now - timedelta(days=30)).isoformat(),
            period_end=now.isoformat(),
        )
        settlement = get_success_data(
            api_client.create_settlement(shop["id"], payload, _seller)
        )
        resp = api_client.submit_settlement(shop["id"], settlement["id"], _seller)
        validate_error(resp, ERR_SETTLEMENT_ZERO_AMOUNT)

    def test_approve_non_pending_fails(self):
        """Approving a DRAFT settlement fails with ERR_SETTLEMENT_NOT_PENDING."""
        shop, orders, settlement = setup_settlement_scenario(num_orders=1)
        resp = api_client.approve_settlement(shop["id"], settlement["id"], _admin)
        validate_error(resp, ERR_SETTLEMENT_NOT_PENDING)

    def test_mark_paid_non_approved_fails(self):
        """Marking a PENDING_APPROVAL settlement as paid fails."""
        shop, orders, settlement = setup_settlement_scenario(num_orders=1)
        get_success_data(
            api_client.submit_settlement(shop["id"], settlement["id"], _seller)
        )
        resp = api_client.mark_settlement_paid(shop["id"], settlement["id"], _admin)
        validate_error(resp, ERR_SETTLEMENT_NOT_APPROVED)

    def test_submit_non_draft_fails(self):
        """Submitting an already-submitted settlement fails."""
        shop, orders, settlement = setup_settlement_scenario(num_orders=1)
        get_success_data(
            api_client.submit_settlement(shop["id"], settlement["id"], _seller)
        )
        resp = api_client.submit_settlement(shop["id"], settlement["id"], _seller)
        validate_error(resp, ERR_SETTLEMENT_NOT_DRAFT)


# ============================================================================
# Dispute flow
# ============================================================================


class TestSettlementDispute:
    """PENDING_APPROVAL -> DISPUTED -> PENDING_APPROVAL."""

    def test_dispute_transitions_to_disputed(self):
        """Disputing a PENDING_APPROVAL settlement moves it to DISPUTED."""
        shop, orders, settlement = setup_settlement_scenario(num_orders=2)
        get_success_data(
            api_client.submit_settlement(shop["id"], settlement["id"], _seller)
        )
        disputed = get_success_data(
            api_client.dispute_settlement(shop["id"], settlement["id"], _admin)
        )
        assert disputed["status"] == "DISPUTED"
        assert_settlement(disputed)

    def test_resolve_dispute_transitions_back_to_pending(self):
        """Resolving a DISPUTED settlement returns it to PENDING_APPROVAL."""
        shop, orders, settlement = setup_settlement_scenario(num_orders=2)
        get_success_data(
            api_client.submit_settlement(shop["id"], settlement["id"], _seller)
        )
        get_success_data(
            api_client.dispute_settlement(shop["id"], settlement["id"], _admin)
        )
        resolved = get_success_data(
            api_client.resolve_settlement_dispute(
                shop["id"], settlement["id"], _admin
            )
        )
        assert resolved["status"] == "PENDING_APPROVAL"
        assert_settlement(resolved)

    def test_dispute_non_pending_fails(self):
        """Disputing a DRAFT settlement fails."""
        shop, orders, settlement = setup_settlement_scenario(num_orders=1)
        resp = api_client.dispute_settlement(
            shop["id"], settlement["id"], _admin
        )
        validate_error(resp, ERR_SETTLEMENT_NOT_PENDING)

    def test_resolve_non_disputed_fails(self):
        """Resolving a non-DISPUTED settlement fails."""
        shop, orders, settlement = setup_settlement_scenario(num_orders=1)
        get_success_data(
            api_client.submit_settlement(shop["id"], settlement["id"], _seller)
        )
        resp = api_client.resolve_settlement_dispute(
            shop["id"], settlement["id"], _admin
        )
        validate_error(resp, ERR_SETTLEMENT_NOT_DISPUTED_STATE)


# ============================================================================
# Reconciliation arithmetic
# ============================================================================


class TestSettlementReconciliation:
    """Verify computed settlement amounts match expected values."""

    def test_reconciliation_amounts_correct(self):
        """gross - commission - refunds == net, all to 2 decimal places."""
        shop, orders, settlement = setup_settlement_scenario(
            num_orders=3, product_price=100.0
        )
        submitted = get_success_data(
            api_client.submit_settlement(shop["id"], settlement["id"], _seller)
        )
        gross = submitted["gross_amount"]
        commission = submitted["total_commission"]
        refunds = submitted["total_refunds"]
        net = submitted["net_amount"]

        assert_cost_precision(gross)
        assert_cost_precision(commission)
        assert_cost_precision(refunds)
        assert_cost_precision(net)

        expected_net = round(gross - commission - refunds, 2)
        assert net == pytest.approx(expected_net, abs=0.01), (
            f"net_amount ({net}) != gross ({gross}) - commission ({commission}) "
            f"- refunds ({refunds}) = {expected_net}"
        )

    def test_gross_equals_sum_of_order_totals(self):
        """gross_amount should equal sum of completed orders' total_amounts."""
        shop, orders, settlement = setup_settlement_scenario(
            num_orders=3, product_price=50.0
        )
        submitted = get_success_data(
            api_client.submit_settlement(shop["id"], settlement["id"], _seller)
        )
        expected_gross = sum(o["total_amount"] for o in orders)
        assert submitted["gross_amount"] == pytest.approx(expected_gross, abs=0.01)


# ============================================================================
# Period overlap
# ============================================================================


class TestSettlementPeriodOverlap:
    """Overlapping settlement periods should be rejected."""

    def test_overlapping_periods_rejected(self):
        """Settlement B overlapping Settlement A's period fails."""
        shop, orders, settlement_a = setup_settlement_scenario(num_orders=1)
        # settlement_a covers roughly now-1h to now+1h
        # Create a second settlement whose period overlaps
        now = datetime.now(timezone.utc)
        overlap_payload = create_settlement_payload(
            period_start=(now - timedelta(minutes=30)).isoformat(),
            period_end=(now + timedelta(hours=2)).isoformat(),
        )
        resp = api_client.create_settlement(
            shop["id"], overlap_payload, _seller
        )
        validate_error(resp, ERR_SETTLEMENT_PERIOD_OVERLAP)

    def test_non_overlapping_periods_succeed(self):
        """Two settlements with non-overlapping periods both succeed."""
        shop, orders, settlement_a = setup_settlement_scenario(num_orders=1)
        # Create a second settlement with a completely separate period
        future_start = datetime.now(timezone.utc) + timedelta(days=10)
        future_end = future_start + timedelta(days=10)
        payload = create_settlement_payload(
            period_start=future_start.isoformat(),
            period_end=future_end.isoformat(),
        )
        resp = api_client.create_settlement(shop["id"], payload, _seller)
        settlement_b = get_success_data(resp)
        assert settlement_b["status"] == "DRAFT"


# ============================================================================
# Balance update on mark-paid
# ============================================================================


class TestSettlementBalanceUpdate:
    """shop.settlement_balance is decremented by net_amount on mark-paid."""

    def test_balance_decremented_after_mark_paid(self):
        """After mark-paid, settlement_balance -= net_amount."""
        shop, orders, settlement = setup_settlement_scenario(
            num_orders=2, product_price=100.0
        )
        shop_before = get_shop_after(shop["id"])
        balance_before = shop_before["settlement_balance"]

        submitted = get_success_data(
            api_client.submit_settlement(shop["id"], settlement["id"], _seller)
        )
        net_amount = submitted["net_amount"]

        get_success_data(
            api_client.approve_settlement(shop["id"], settlement["id"], _admin)
        )
        get_success_data(
            api_client.mark_settlement_paid(shop["id"], settlement["id"], _admin)
        )

        shop_after = get_shop_after(shop["id"])
        expected_balance = round(balance_before - net_amount, 2)
        assert shop_after["settlement_balance"] == pytest.approx(
            expected_balance, abs=0.01
        ), (
            f"settlement_balance ({shop_after['settlement_balance']}) != "
            f"before ({balance_before}) - net ({net_amount})"
        )
        assert_shop_invariants(shop_after)
