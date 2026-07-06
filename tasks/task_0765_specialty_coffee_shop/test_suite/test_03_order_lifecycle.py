"""Order lifecycle: parallel payment/fulfillment dimensions, void compensation."""
import test_helpers as th
from test_helpers import validate_success, validate_error, ApiErrorId


class TestParallelStateDimensions:
    def _paid_and_fulfilled(self, api, headers):
        shop = th.setup_latte_shop(api, headers=headers)
        order = th.latte_only_order(api, shop, quantity=1, with_shot=False, headers=headers)
        validate_success(api.pay_order(order["id"], headers))
        fulfilled = validate_success(api.fulfill_order(order["id"], headers))
        return fulfilled

    def test_payment_dimension_reaches_paid(self, api, manager_headers):
        """PRD 3.6: "A `Customer`, `Barista`, or `Manager` may pay an order, moving
        `payment_status` `UNPAID -> PAID` and recording payment of `total_cents`;
        paying is permitted only while the order's `fulfillment_status` is not
        `VOIDED`, and a payment attempt against a voided order is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
        """
        order = self._paid_and_fulfilled(api, manager_headers)
        assert order["payment_status"] == "PAID", f"got {order['payment_status']}"

    def test_fulfillment_dimension_reaches_fulfilled(self, api, manager_headers):
        """PRD 3.6: "Fulfillment is performed by a `Barista` or `Manager` and drives
        `fulfillment_status` `PLACED -> FULFILLED`."
        PRD 3.6: "Payment and fulfillment are two independent dimensions of an order
        that evolve separately."

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
        """
        order = self._paid_and_fulfilled(api, manager_headers)
        assert order["fulfillment_status"] == "FULFILLED", f"got {order['fulfillment_status']}"


class TestPointsConservationRedeemThenVoid:
    def _order_redeeming(self, api, headers):
        member = th.new_member(api, headers=headers, email="redeem@example.com", full_name="R")
        th.set_member_points(api, member["id"], lifetime_delta=0, balance_delta=100, headers=headers)
        shop = th.setup_latte_shop(api, headers=headers)
        order = th.latte_only_order(api, shop, member_id=member["id"], quantity=2,
                                    with_shot=True, points_redeemed=20, headers=headers)
        return member, order

    def test_placement_debits_redeemed_points(self, api, manager_headers):
        """PRD 3.5: "When `points_redeemed` is greater than zero, the member's
        `points_balance` is reduced by that amount at placement."

        Design: Difficulty/compensating_invariant/points_conservation_redeem_then_void
        """
        member, _ = self._order_redeeming(api, manager_headers)
        fetched = validate_success(api.get_member(member["id"], manager_headers))
        # balance 100 - redeemed 20 = 80
        assert fetched["points_balance"] == 80, f"got {fetched['points_balance']}"

    def test_void_restores_redeemed_points_to_balance(self, api, manager_headers):
        """PRD 3.6: "Voiding an order that is still `PLACED` (`PLACED -> VOIDED`)
        restores any redeemed points, adding `points_redeemed` back to the member's
        `points_balance`; and if the order was `PAID`, its `payment_status` moves
        `PAID -> REFUNDED` with a refund of `total_cents` recorded."

        Design: Difficulty/compensating_invariant/points_conservation_redeem_then_void
        """
        member, order = self._order_redeeming(api, manager_headers)
        validate_success(api.void_order(order["id"], manager_headers))
        fetched = validate_success(api.get_member(member["id"], manager_headers))
        # 80 + 20 restored = 100 (conserved)
        assert fetched["points_balance"] == 100, f"got {fetched['points_balance']}"


class TestBeanGramsConservationFulfillThenVoid:
    def _fulfilled_order(self, api, headers):
        shop = th.setup_latte_shop(api, headers=headers)
        order = th.latte_only_order(api, shop, quantity=2, with_shot=True, headers=headers)
        validate_success(api.fulfill_order(order["id"], headers))
        return shop, order

    def test_fulfill_draws_line_bean_grams(self, api, manager_headers):
        """PRD 3.6: "For each line, `line_bean_grams` is drawn from the origin's
        `ACTIVE` lot (its `consumed_grams` increases by that amount, and
        `on_hand_grams` falls)."

        Design: Difficulty/compensating_invariant/bean_grams_conservation_fulfill_then_void
        """
        shop, _ = self._fulfilled_order(api, manager_headers)
        lot = validate_success(api.get_bean_lot(shop["lot_id"], manager_headers))
        # (18 + 9) * 2 = 54 drawn from 1000 -> 946
        assert lot["on_hand_grams"] == 946, f"got {lot['on_hand_grams']}"

    def test_void_restores_beans_to_pre_fulfill_value(self, api, manager_headers):
        """PRD 3.6: "Voiding an order that was already `FULFILLED`
        (`FULFILLED -> VOIDED`) additionally unwinds the fulfillment: for each line
        the drawn `line_bean_grams` is restored to the lot it came from (that lot's
        `consumed_grams` decreases by the same amount, so its `on_hand_grams`
        returns to its pre-fulfill value)"

        Design: Difficulty/compensating_invariant/bean_grams_conservation_fulfill_then_void
        """
        shop, order = self._fulfilled_order(api, manager_headers)
        voided = validate_success(api.void_order(order["id"], manager_headers))
        lot = validate_success(api.get_bean_lot(shop["lot_id"], manager_headers))
        assert lot["on_hand_grams"] == 1000, f"got {lot['on_hand_grams']}"
        assert voided["fulfillment_status"] == "VOIDED", f"got {voided['fulfillment_status']}"


def test_pay_voided_order_rejected(api, manager_headers):
    """PRD 3.6: "paying is permitted only while the order's `fulfillment_status` is
    not `VOIDED`, and a payment attempt against a voided order is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pay_voided_order_invalid_state
    """
    item = th.new_menu_item(api, name="Batch", category="BEVERAGE", base_price_cents=400,
                            required_equipment_type="BATCH_BREW", size="MEDIUM",
                            origin_required=False, headers=manager_headers)
    order = th.new_order(api, headers=manager_headers,
                         lines=[{"menu_item_id": item["id"], "quantity": 1, "modifier_ids": []}])
    validate_success(api.void_order(order["id"], manager_headers))
    resp = api.pay_order(order["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
