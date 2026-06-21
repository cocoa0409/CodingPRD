"""Settlement, refunds, and conservation invariants:
- transitive cascades on cancel (Order->Delivery->Earnings) and deliver
  (Delivery->Earnings->Dasher lifetime)
- missing-item refund boundary (missing_quantity == fulfilled_quantity)
- issue approval gated on order DELIVERED
- compensating invariants (cancel refund conserves customer charge; decline
  reversal conserves dasher lifetime earnings)
- wallet refund, line shorting, and issue rejection corners.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId,
    make_admin_headers, make_support_headers,
    make_customer_headers, make_dasher_headers, make_restaurant_headers,
    create_zone, create_restaurant, create_menu_item, create_customer, create_dasher,
    place_simple_order, get_first_line_item, dispatch,
    setup_market, setup_order_routed, setup_order_accepted,
    setup_order_delivered, setup_issue_ready,
)

ADMIN = make_admin_headers()
SUPPORT = make_support_headers()


# ===========================================================================
# transitive_cascade — depth-3 cancel (Order -> Delivery -> EarningsRecord)
# ===========================================================================
class TestCancelCascadeDepth3:
    def _setup_accepted_with_earnings(self):
        ctx = setup_order_accepted()
        dh = make_dasher_headers(ctx["dasher"]["id"])
        earnings, _ = _list(api_client.list_delivery_earnings(ctx["delivery"]["id"], dh))
        ctx["earnings_id"] = earnings[0]["id"]
        return ctx

    def test_cancel_cascades_to_delivery_cancelled(self, api):
        """PRD §3.11: "If a delivery exists in a non-terminal state — `OFFERED` or `ACCEPTED` — it is transitioned to `CANCELLED` and its earnings record is reversed from `ACCRUED` to `REVERSED`."

        Cancel -> Order CANCELLED -> ACCEPTED Delivery CANCELLED (hop 1->2).

        Design: Difficulty/transitive_cascade/cancel_cascade_order_delivery_earnings_depth3
        """
        ctx = self._setup_accepted_with_earnings()
        validate_success(api_client.cancel_order(
            ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"])))
        dh = make_dasher_headers(ctx["dasher"]["id"])
        order = validate_success(
            api_client.get_order(ctx["order"]["id"],
                                 make_customer_headers(ctx["customer"]["id"])))
        delivery = validate_success(api_client.get_delivery(ctx["delivery"]["id"], dh))
        assert order["fulfillment_status"] == "CANCELLED"
        assert delivery["fulfillment_status"] == "CANCELLED"

    def test_cancel_cascades_to_earnings_reversed(self, api):
        """PRD §3.11: "If a delivery exists in a non-terminal state — `OFFERED` or `ACCEPTED` — it is transitioned to `CANCELLED` and its earnings record is reversed from `ACCRUED` to `REVERSED`"

        The cancelled Delivery in turn reverses its EarningsRecord (hop 2->3,
        depth 3).

        Design: Difficulty/transitive_cascade/cancel_cascade_order_delivery_earnings_depth3
        """
        ctx = self._setup_accepted_with_earnings()
        validate_success(api_client.cancel_order(
            ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"])))
        dh = make_dasher_headers(ctx["dasher"]["id"])
        earnings = validate_success(
            api_client.get_earnings_record(ctx["earnings_id"], dh))
        assert earnings["status"] == "REVERSED", \
            "the cancelled delivery's earnings record must reverse to REVERSED"


# ===========================================================================
# transitive_cascade — depth-2 deliver settlement (Delivery -> Earnings -> Dasher)
# ===========================================================================
class TestDeliveredSettlementDepth2:
    def test_delivered_settles_pay_to_700(self, api):
        """PRD §3.8: "the delivery's `settled_pay_cents` is computed as the settled dasher pay, the earnings record moves from `ACCRUED` to `SETTLED`"

        Base 650 + tip 0 + guarantee top-up 50 = 700.

        Design: Difficulty/transitive_cascade/delivered_settlement_earnings_to_lifetime_depth2
        """
        ctx = setup_order_delivered(order_overrides={"tip_cents": 0})
        delivery = validate_success(
            api_client.get_delivery(ctx["delivery"]["id"],
                                    make_dasher_headers(ctx["dasher"]["id"])))
        assert delivery["settled_pay_cents"] == 700, \
            f"expected base 650 + top-up 50 = 700, got {delivery['settled_pay_cents']}"

    def test_settled_record_rederives_dasher_lifetime(self, api):
        """PRD §3.8: "the earnings record moves from `ACCRUED` to `SETTLED` (and the dasher's `lifetime_earnings_cents` is re-derived from its `SETTLED` records)"

        After one 700-pay settled delivery, lifetime_earnings_cents == 700 (hop
        Delivery -> Earnings -> Dasher).

        Design: Difficulty/transitive_cascade/delivered_settlement_earnings_to_lifetime_depth2
        """
        ctx = setup_order_delivered(order_overrides={"tip_cents": 0})
        dasher = validate_success(
            api_client.get_dasher(ctx["dasher"]["id"],
                                  make_dasher_headers(ctx["dasher"]["id"])))
        assert dasher["lifetime_earnings_cents"] == 700, \
            f"lifetime must re-derive to 700, got {dasher['lifetime_earnings_cents']}"


# ===========================================================================
# boundary_precision_check — missing_quantity == fulfilled_quantity (inclusive)
# ===========================================================================
class TestMissingQtyBoundary:
    def test_missing_qty_equals_fulfilled_is_approved(self, api):
        """PRD §3.12: "requires the `missing_quantity` not to exceed the line's current `fulfilled_quantity` (otherwise `ERR_MISSING_QTY_EXCEEDS_FULFILLED`)"
        PRD §3.12: "On approval the refund is computed as the line's snapshotted `unit_price_cents` multiplied by the `missing_quantity`"

        Line quantity 2 of a $5 item, missing 2 (== fulfilled 2, inclusive bound)
        -> APPROVED, refund 2*500=1000.

        Design: Difficulty/boundary_precision_check/missing_qty_equals_fulfilled_boundary_on_approve
        """
        ctx = setup_issue_ready(quantity=2, missing_quantity=2, item_price_cents=500)
        approved = validate_success(api_client.approve_issue(ctx["issue"]["id"], SUPPORT))
        assert approved["status"] == "APPROVED"
        assert approved["refund_amount_cents"] == 1000, \
            f"expected 500*2=1000, got {approved['refund_amount_cents']}"

    def test_missing_qty_above_fulfilled_is_rejected(self, api):
        """PRD §3.12: "requires the `missing_quantity` not to exceed the line's current `fulfilled_quantity` (otherwise `ERR_MISSING_QTY_EXCEEDS_FULFILLED`)."

        missing 3 on a fulfilled 2 line exceeds the bound -> rejected.

        Design: Difficulty/boundary_precision_check/missing_qty_equals_fulfilled_boundary_on_approve
        """
        ctx = setup_issue_ready(quantity=2, missing_quantity=3, item_price_cents=500)
        resp = api_client.approve_issue(ctx["issue"]["id"], SUPPORT)
        validate_error(resp, ApiErrorId.ERR_MISSING_QTY_EXCEEDS_FULFILLED.value,
                       expected_status=422)


# ===========================================================================
# compensating_invariant — cancel refund conserves customer charge
# ===========================================================================
class TestCancelRefundConservation:
    def _setup_routed_priced_order(self):
        """$5 item x3 (subtotal 1500), tip 100, dispatched (ROUTED)."""
        zone = create_zone(service_fee_bps=850)
        restaurant = create_restaurant(zone["id"])
        item = create_menu_item(restaurant["id"], name="Taco", price_cents=500)
        dasher = create_dasher(zone["id"])
        customer = create_customer()
        order = place_simple_order(customer["id"], restaurant["id"], item["id"],
                                   quantity=3, tip_cents=100)
        dispatch(order["id"], restaurant["id"], order["version"])
        return order, customer

    def test_refund_equals_full_customer_charge(self, api):
        """PRD §3.11: "`refunded_cents` is set to the sum of `order_subtotal_cents`, `service_fee_cents`, `delivery_fee_quote_cents`, and `tip_cents`"

        1500 + 128 + 780 + 100 = 2508.

        Design: Difficulty/compensating_invariant/cancel_refund_conserves_customer_charge
        """
        order, customer = self._setup_routed_priced_order()
        ch = make_customer_headers(customer["id"])
        cancelled = validate_success(api_client.cancel_order(order["id"], ch))
        assert cancelled["order_subtotal_cents"] == 1500
        assert cancelled["service_fee_cents"] == 128, \
            f"expected round_half_up(1500*850/10000)=128, got {cancelled['service_fee_cents']}"
        assert cancelled["delivery_fee_quote_cents"] == 780
        assert cancelled["refunded_cents"] == 2508, \
            f"expected 1500+128+780+100=2508, got {cancelled['refunded_cents']}"

    def test_cancel_sets_billing_refunded(self, api):
        """PRD §3.11: "Cancellation moves the order's `fulfillment_status` to `CANCELLED` and its `billing_status` to `REFUNDED`, and issues a full refund"

        Design: Difficulty/compensating_invariant/cancel_refund_conserves_customer_charge
        """
        order, customer = self._setup_routed_priced_order()
        cancelled = validate_success(
            api_client.cancel_order(order["id"], make_customer_headers(customer["id"])))
        assert cancelled["billing_status"] == "REFUNDED"


# ===========================================================================
# compensating_invariant — decline reversal conserves dasher lifetime earnings
# ===========================================================================
class TestDeclineReversalConservation:
    def test_decline_leaves_lifetime_earnings_zero(self, api):
        """PRD §3.3: "`lifetime_earnings_cents`, starting at 0 and re-derived as the sum of `settled_pay_cents` across the dasher's earnings records in state `SETTLED`"
        PRD §3.8: "reverses its earnings record from `ACCRUED` to `REVERSED`"

        A reversed accrual never settles, so lifetime stays 0.

        Design: Difficulty/compensating_invariant/decline_reversal_conserves_dasher_earnings
        """
        ctx = setup_order_routed(order_overrides={"tip_cents": 0})
        dh = make_dasher_headers(ctx["dasher"]["id"])
        validate_success(api_client.decline_delivery(ctx["delivery"]["id"], dh))
        dasher = validate_success(api_client.get_dasher(ctx["dasher"]["id"], dh))
        assert dasher["lifetime_earnings_cents"] == 0, \
            "a reversed accrual must never count toward lifetime earnings"

    def test_decline_moves_delivery_to_reassigned(self, api):
        """PRD §3.8: "A decline moves the delivery from `OFFERED` to `REASSIGNED`, reverses its earnings record from `ACCRUED` to `REVERSED`"

        Design: Difficulty/compensating_invariant/decline_reversal_conserves_dasher_earnings
        """
        ctx = setup_order_routed(order_overrides={"tip_cents": 0})
        dh = make_dasher_headers(ctx["dasher"]["id"])
        declined = validate_success(api_client.decline_delivery(ctx["delivery"]["id"], dh))
        assert declined["fulfillment_status"] == "REASSIGNED"


# ===========================================================================
# Corner: calculations / state_machines (refund settlement)
# ===========================================================================
def test_wallet_refund_credits_customer_wallet(api):
    """PRD §3.12: "If the refund destination is `WALLET`, the customer's `wallet_credit_cents` is increased by the refund amount."

    Missing 1 of a $5 item -> refund 500 credited to the wallet.

    Design: Corner/calculations/wallet_refund_credits_customer_wallet
    """
    ctx = setup_issue_ready(quantity=2, missing_quantity=1, refund_destination="WALLET",
                            item_price_cents=500)
    approved = validate_success(api_client.approve_issue(ctx["issue"]["id"], SUPPORT))
    assert approved["refund_amount_cents"] == 500
    customer = validate_success(
        api_client.get_customer(ctx["customer"]["id"],
                                make_customer_headers(ctx["customer"]["id"])))
    assert customer["wallet_credit_cents"] == 500, \
        f"wallet must be credited 500, got {customer['wallet_credit_cents']}"


def test_approve_missing_item_shorts_line_when_fully_missing(api):
    """PRD §3.12: "the line's `fulfilled_quantity` is decremented by `missing_quantity` (and the line's `status` moves to `SHORTED` if its `fulfilled_quantity` reaches 0)"

    A single-unit line fully missing -> fulfilled_quantity 0 and status SHORTED.

    Design: Corner/calculations/approve_missing_item_shorts_line_when_fully_missing
    """
    ctx = setup_issue_ready(quantity=1, missing_quantity=1, item_price_cents=500)
    validate_success(api_client.approve_issue(ctx["issue"]["id"], SUPPORT))
    li = get_first_line_item(ctx["order"]["id"], ctx["customer"]["id"])
    assert li["fulfilled_quantity"] == 0
    assert li["status"] == "SHORTED"


def test_reject_open_issue_no_money_moves(api):
    """PRD §3.12: "A rejection moves the issue to `REJECTED`, leaves `refund_amount_cents` at 0, and moves no money."

    Design: Corner/state_machines/reject_open_issue_no_money_moves
    """
    ctx = setup_issue_ready(quantity=2, missing_quantity=1, item_price_cents=500)
    rejected = validate_success(api_client.reject_issue(ctx["issue"]["id"], SUPPORT))
    assert rejected["status"] == "REJECTED"
    assert rejected["refund_amount_cents"] == 0
    order = validate_success(
        api_client.get_order(ctx["order"]["id"],
                             make_customer_headers(ctx["customer"]["id"])))
    assert order["refunded_cents"] == 0, "rejection must move no money"


# ---------------------------------------------------------------------------
def _list(resp):
    body = resp.json()
    return body["data"], body["meta"]
