"""Parallel payment/fulfilment tracks, the credit ledger, and the fiscal ceiling."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, setup_committed_line_with_account, make_delivery_order,
    get_order, get_account, get_line, TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]


class TestParallelPaymentAndFulfilment:
    def _order_paid_and_packed(self, api):
        ctx = setup_committed_line_with_account(api, base_price_cents=400, par_qty=10,
                                                contract_tier="STANDARD",
                                                production_date="2026-06-06T00:00:00Z")
        order = make_delivery_order(api, ctx["account"]["id"], ctx["product"]["id"],
                                    ctx["line"]["id"], qty=1,
                                    delivery_date="2026-06-06T10:00:00Z")
        validate_success(api.pay_delivery_order(order["id"], {"amount_cents": 100}, MANAGER))
        validate_success(api.pack_delivery_order(order["id"], MANAGER))
        return order["id"]

    def test_partial_payment_advances_payment_status_independently(self, api):
        """PRD 3.7: "A payment strictly between zero and the outstanding amount moves an
        UNPAID order to PARTIALLY_PAID". PRD 3.7: "Each payment adds to amount_paid_cents".

        Design: Difficulty/non_linear_state_machine/delivery_order_parallel_payment_fulfillment
        """
        order_id = self._order_paid_and_packed(api)
        order = get_order(api, order_id)
        assert order["payment_status"] == "PARTIALLY_PAID", order
        assert order["amount_paid_cents"] == 100, order

    def test_pack_advances_fulfilment_status_independently(self, api):
        """PRD 3.7: "Fulfilment and payment advance on two independent tracks. On the
        fulfilment track: a Manager packs a PENDING order to PACKED".

        Design: Difficulty/non_linear_state_machine/delivery_order_parallel_payment_fulfillment
        """
        order_id = self._order_paid_and_packed(api)
        order = get_order(api, order_id)
        assert order["fulfillment_status"] == "PACKED", order


class TestCreditConservationOnVoid:
    def _delivered(self, api):
        ctx = setup_committed_line_with_account(api, base_price_cents=400, par_qty=10,
                                                contract_tier="STANDARD",
                                                production_date="2026-06-16T00:00:00Z")
        order = make_delivery_order(api, ctx["account"]["id"], ctx["product"]["id"],
                                    ctx["line"]["id"], qty=1,
                                    delivery_date="2026-06-16T10:00:00Z")
        validate_success(api.pack_delivery_order(order["id"], MANAGER))
        validate_success(api.deliver_delivery_order(order["id"], MANAGER))
        return ctx, order["id"]

    def test_deliver_books_outstanding_into_credit_balance(self, api):
        """PRD 2.7: "Delivering an order books its outstanding amount into the balance".
        PRD 3.7: "delivery books the order's outstanding amount — line_total_cents minus
        amount_paid_cents — into the account's credit_balance_cents".

        Design: Difficulty/compensating_invariant/credit_balance_conservation_on_void
        """
        ctx, _ = self._delivered(api)
        account = get_account(api, ctx["account"]["id"])
        assert account["credit_balance_cents"] == 360, account   # round(400*0.9)

    def test_void_reverses_booking_restoring_pre_delivery_balance(self, api):
        """PRD 2.7: "the guaranteed consequence is that delivering an order and then voiding
        it restores credit_balance_cents to precisely its pre-delivery value." PRD 3.7:
        "Cancelling an order that is already DELIVERED is a void: it likewise moves to
        CANCELLED and releases its par, but it additionally reverses the credit that
        delivery booked".

        Design: Difficulty/compensating_invariant/credit_balance_conservation_on_void
        """
        ctx, order_id = self._delivered(api)
        validate_success(api.cancel_delivery_order(order_id, MANAGER))
        account = get_account(api, ctx["account"]["id"])
        order = get_order(api, order_id)
        line = get_line(api, ctx["line"]["id"])
        assert account["credit_balance_cents"] == 0, account
        assert order["fulfillment_status"] == "CANCELLED", order
        assert line["reserved_qty"] == 0, line


class TestConstraintVsFiscalPrecedence:
    def test_par_shortfall_pre_empts_credit_ceiling(self, api):
        """PRD 2.8: precedence "7. Quantity and capacity constraints (ERR_INSUFFICIENT_PAR
        ...). ... 9. The fiscal credit ceiling (ERR_CREDIT_LIMIT_EXCEEDED)." PRD 3.7: "The
        reservation must not drive the line's available_qty negative ... else
        ERR_INSUFFICIENT_PAR."

        Design: Difficulty/priority_pair_validation_conflict/constraint_vs_fiscal_on_create_order
        """
        # Fully reserve the par-5 line with a big-credit account, then order from a tiny-credit one.
        big = setup_committed_line_with_account(api, base_price_cents=400, par_qty=5,
                                                credit_limit_cents=1_000_000,
                                                production_date="2026-07-10T00:00:00Z")
        make_delivery_order(api, big["account"]["id"], big["product"]["id"], big["line"]["id"],
                            qty=5, delivery_date="2026-07-10T10:00:00Z")
        small = get_success_data(api.create_wholesale_account(
            {"name": "SmallCo", "credit_limit_cents": 100, "contract_tier": "STANDARD"}, MANAGER))
        validate_error(api.create_delivery_order({
            "wholesale_account_id": small["id"], "product_id": big["product"]["id"],
            "bake_plan_line_id": big["line"]["id"], "delivery_date": "2026-07-10T10:00:00Z",
            "qty": 3}, MANAGER), ApiErrorId.ERR_INSUFFICIENT_PAR.value)

    def test_credit_ceiling_fires_in_isolation_when_par_is_available(self, api):
        """PRD 3.7: "the projected balance (the account's current credit_balance_cents plus
        the order's outstanding amount) must not exceed the account's credit_limit_cents; a
        breach is refused with ERR_CREDIT_LIMIT_EXCEEDED. This same fiscal ceiling also
        guards delivery-order booking at creation."

        Design: Difficulty/priority_pair_validation_conflict/constraint_vs_fiscal_on_create_order
        """
        ctx = setup_committed_line_with_account(api, base_price_cents=400, par_qty=10,
                                                credit_limit_cents=100,
                                                production_date="2026-07-12T00:00:00Z")
        validate_error(api.create_delivery_order({
            "wholesale_account_id": ctx["account"]["id"], "product_id": ctx["product"]["id"],
            "bake_plan_line_id": ctx["line"]["id"], "delivery_date": "2026-07-12T10:00:00Z",
            "qty": 2}, MANAGER), ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)


class TestCreditLimitAtCreation:
    def test_create_order_exceeding_credit_limit_is_rejected(self, api):
        """PRD 3.7: "This same fiscal ceiling also guards delivery-order booking at
        creation."

        Design: Corner/errors/credit_limit_exceeded_on_create_order
        """
        ctx = setup_committed_line_with_account(api, base_price_cents=400, par_qty=10,
                                                credit_limit_cents=100,
                                                production_date="2026-06-28T00:00:00Z")
        validate_error(api.create_delivery_order({
            "wholesale_account_id": ctx["account"]["id"], "product_id": ctx["product"]["id"],
            "bake_plan_line_id": ctx["line"]["id"], "delivery_date": "2026-06-28T10:00:00Z",
            "qty": 2}, MANAGER), ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)
