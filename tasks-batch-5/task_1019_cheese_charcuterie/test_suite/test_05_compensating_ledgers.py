"""Compensating ledgers: weight conservation across fulfill+return and store-credit
conservation across pay+cancel; plus insufficient store-credit rejection."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_lot_weight_ledger, setup_fulfilled_retail_order, setup_paid_retail_order,
    setup_submitted_retail_order, TEST_USERS,
)

CS = TEST_USERS["counter_staff_headers"]
SM = TEST_USERS["shop_manager_headers"]


# ─── compensating_invariant / lot_weight_conserved_fulfill_then_return ─────
class TestLotWeightConserved:
    def _fulfill_then_return(self, api):
        sc = setup_fulfilled_retail_order(actual_cut_weight_g=500, requested_weight_g=500,
                                          received_weight_g=1000)
        api.return_order(sc["order"]["id"], CS)
        return sc

    def test_weight_returns_to_lot_after_return(self, api):
        """PRD §3.6: "A return reverses the physical consumption of every product line: each
        line's actual cut weight is subtracted from its lot's `consumed_weight_g` and added
        back to the lot's `current_weight_g`, returning the stock."

        Design: Difficulty/compensating_invariant/lot_weight_conserved_fulfill_then_return
        """
        sc = self._fulfill_then_return(api)
        lot = get_success_data(api.get_lot(sc["lot"]["id"], SM))
        assert lot["current_weight_g"] == 1000
        assert lot["consumed_weight_g"] == 0
        assert_lot_weight_ledger(lot)

    def test_order_returned_and_refunded(self, api):
        """PRD §3.6: "**Returning** an order applies only to a `FULFILLED` order (a return
        attempted on any other fulfillment state is rejected with `ERR_ORDER_NOT_FULFILLED`)
        that is also `PAID`, and moves it `FULFILLED → RETURNED`."

        Design: Difficulty/compensating_invariant/lot_weight_conserved_fulfill_then_return
        """
        sc = self._fulfill_then_return(api)
        order = get_success_data(api.get_order(sc["order"]["id"], CS))
        assert order["fulfillment_status"] == "RETURNED"
        assert order["payment_status"] == "REFUNDED"


# ─── compensating_invariant / store_credit_conserved_pay_then_cancel ───────
class TestStoreCreditConserved:
    def _pay_store_credit_then_cancel(self, api):
        sc = setup_paid_retail_order(payment_method="STORE_CREDIT", price_per_kg_cents=4200,
                                     requested_weight_g=500, received_weight_g=1000,
                                     store_credit_cents=10000)
        api.cancel_order(sc["order"]["id"], CS)
        return sc

    def test_store_credit_restored_to_prepayment_value(self, api):
        """PRD §3.6: "The **store-credit ledger** holds that paying by store credit reduces the
        balance by the order total and the matching refund restores it by the amount applied,
        so a store-credit payment followed by its compensating refund — whether via cancellation
        or return — leaves the customer's `store_credit_cents` at its pre-payment value."

        Design: Difficulty/compensating_invariant/store_credit_conserved_pay_then_cancel
        """
        sc = self._pay_store_credit_then_cancel(api)
        customer = get_success_data(api.get_customer(sc["customer"]["id"], SM))
        assert customer["store_credit_cents"] == 10000

    def test_applied_amount_recorded_and_order_refunded(self, api):
        """PRD §3.5: "On a successful store-credit payment, the customer's `store_credit_cents`
        is reduced by the order total and the order's `store_credit_applied_cents` records
        exactly that amount debited."

        Design: Difficulty/compensating_invariant/store_credit_conserved_pay_then_cancel
        """
        sc = self._pay_store_credit_then_cancel(api)
        order = get_success_data(api.get_order(sc["order"]["id"], CS))
        assert order["store_credit_applied_cents"] == 2100
        assert order["payment_status"] == "REFUNDED"


# ─── Corner: validations / corner_pay_store_credit_insufficient ────────────
def test_pay_store_credit_insufficient(api):
    """PRD §3.5: "A store-credit payment requires the customer's `store_credit_cents` to be at
    least the order's `total_cents`; otherwise it is rejected with
    `ERR_INSUFFICIENT_STORE_CREDIT` (HTTP 402)."

    Design: Corner/validations/corner_pay_store_credit_insufficient
    """
    sc = setup_submitted_retail_order(price_per_kg_cents=4200, requested_weight_g=500,
                                      received_weight_g=1000, store_credit_cents=1000)
    res = api.pay_order(sc["order"]["id"], {"payment_method": "STORE_CREDIT"}, CS)
    validate_error(res, "ERR_INSUFFICIENT_STORE_CREDIT")
