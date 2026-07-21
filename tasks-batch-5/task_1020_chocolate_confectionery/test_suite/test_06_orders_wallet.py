"""Order confirmation, wallet, validation precedence, and preorder fulfilment
(PRD §2.5, §3.2, §3.5, §3.6).

Covers wallet conservation, state-over-fiscal and safety-over-constraint error
precedence, the preorder fulfilment window, account-type compatibility, duplicate
lines, and non-positive quantities.
"""
from test_helpers import (
    validate_success, validate_error, make_customer_headers,
    PROD, SALES, ADMIN,
    create_customer, create_product, create_released_batch,
    create_order, add_line, confirm_order, allocate_order, set_clock,
    setup_confirmed_retail_order,
)


class TestWalletCreditConserved:
    """compensating_invariant / wallet_credit_conserved_confirm_then_cancel —
    confirming with wallet_apply 500 debits to 9500, cancel refunds exactly 500,
    so wallet_credit_cents returns to 10000 with zero drift."""

    def test_wallet_restored_after_confirm_then_cancel(self, api):
        """PRD §3.6: "A `CONFIRMED` order becomes `CANCELLED` and refunds any
        `wallet_applied_cents` back to the customer's `wallet_credit_cents`,
        resetting `wallet_applied_cents` to 0."

        Design: Difficulty/compensating_invariant/wallet_credit_conserved_confirm_then_cancel
        """
        setup = setup_confirmed_retail_order(
            line_qty=1, base_price=1000, wallet_grant=10000, wallet_apply_cents=500)
        cust_id = setup["customer"]["id"]
        order = validate_success(api.cancel_order(setup["order"]["id"], make_customer_headers(cust_id)))
        assert order["status"] == "CANCELLED", order
        customer = validate_success(api.get_customer(cust_id, ADMIN))
        assert customer["wallet_credit_cents"] == 10000, customer

    def test_confirm_debits_wallet_by_applied_amount(self, api):
        """PRD §3.5: "the amount actually applied, `wallet_applied_cents`, is the
        smallest of the requested amount, the customer's available
        `wallet_credit_cents`, and the sum of subtotal, tax, and gift fee; the
        customer's `wallet_credit_cents` is debited by exactly that applied
        amount."

        Design: Difficulty/compensating_invariant/wallet_credit_conserved_confirm_then_cancel
        """
        setup = setup_confirmed_retail_order(
            line_qty=1, base_price=1000, wallet_grant=10000, wallet_apply_cents=500)
        customer = validate_success(api.get_customer(setup["customer"]["id"], ADMIN))
        assert customer["wallet_credit_cents"] == 9500, customer


class TestStateBeatsFiscalOnReconfirm:
    """priority_pair_validation_conflict / state_beats_fiscal_on_reconfirm — a
    re-confirm of an already-CONFIRMED wholesale order whose credit_limit was
    lowered below total fails both checks; the state check wins."""

    def _confirmed_then_credit_lowered(self, api):
        customer = create_customer(account_type="WHOLESALE", credit_limit_cents=20000000)
        product = create_product(base_price_cents=1000, shelf_life_days=90, unit_weight_g=100)
        order = create_order(customer["id"], "WHOLESALE")
        add_line(order["id"], customer["id"], product["id"], 120)
        confirm_order(order["id"], customer["id"])
        validate_success(api.update_customer(customer["id"], {"credit_limit_cents": 50000}, ADMIN))
        return customer, order

    def test_reconfirm_returns_invalid_state_not_credit_limit(self, api):
        """PRD §2.5: "the checks are evaluated in a fixed priority order so that
        the returned `error_id` is deterministic. The ordering, highest priority
        first, is: ... (7) state legality of the requested transition
        (`ERR_INVALID_STATE`); and then the domain-specific business rules
        described throughout Section 3, which include ... credit limit
        (`ERR_CREDIT_LIMIT_EXCEEDED`)".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reconfirm
        """
        customer, order = self._confirmed_then_credit_lowered(api)
        resp = api.confirm_order(order["id"], make_customer_headers(customer["id"]))
        validate_error(resp, "ERR_INVALID_STATE", 409)

    def test_order_unchanged_after_rejected_reconfirm(self, api):
        """PRD §3.5: "Confirming an order advances it `DRAFT -> CONFIRMED`". A
        re-confirm of a CONFIRMED order is not a defined transition and leaves the
        order CONFIRMED.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reconfirm
        """
        customer, order = self._confirmed_then_credit_lowered(api)
        api.confirm_order(order["id"], make_customer_headers(customer["id"]))
        fetched = validate_success(api.get_order(order["id"], SALES))
        assert fetched["status"] == "CONFIRMED", fetched


class TestSafetyBeatsConstraintOnAllocate:
    """priority_pair_validation_conflict / safety_beats_constraint_on_allocate —
    allocating an order whose product became allergen-restricted AND has zero
    inventory fails both; safety wins."""

    def _confirmed_then_allergen_restricted(self, api):
        customer = create_customer(account_type="RETAIL")
        product = create_product(base_price_cents=1000, shelf_life_days=30, unit_weight_g=40, allergens=["MILK"])
        order = create_order(customer["id"], "RETAIL")
        add_line(order["id"], customer["id"], product["id"], 1)
        confirm_order(order["id"], customer["id"])
        validate_success(api.update_customer(customer["id"], {"allergen_restrictions": ["MILK"]}, ADMIN))
        return customer, order

    def test_allocate_returns_allergen_not_insufficient_inventory(self, api):
        """PRD §3.6: "Allocation re-checks that no line's product carries a
        restricted allergen and requires that, for every line, the `RELEASED`
        non-expired batches of that line's product hold at least the line's
        `quantity` in aggregate `available_units`." PRD §2.5 ordering places
        allergen safety (`ERR_ALLERGEN_RESTRICTED`) before inventory sufficiency
        (`ERR_INSUFFICIENT_INVENTORY`).

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_allocate
        """
        customer, order = self._confirmed_then_allergen_restricted(api)
        resp = api.allocate_order(order["id"], SALES)
        validate_error(resp, "ERR_ALLERGEN_RESTRICTED", 422)

    def test_order_stays_confirmed_after_allergen_rejection(self, api):
        """PRD §3.6: "Once confirmed, an order is allocated against inventory by a
        `SalesManager`, advancing it `CONFIRMED -> ALLOCATED`." A rejected
        allocate leaves the order CONFIRMED.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_allocate
        """
        customer, order = self._confirmed_then_allergen_restricted(api)
        api.allocate_order(order["id"], SALES)
        fetched = validate_success(api.get_order(order["id"], SALES))
        assert fetched["status"] == "CONFIRMED", fetched


def test_preorder_fulfill_outside_window_closed(api):
    """PRD §3.6: "for a pre-order it additionally requires that the current
    logical clock falls within the inclusive window from `fulfillment_window_start`
    to `fulfillment_window_end`, a window violation being rejected with
    `ERR_FULFILLMENT_WINDOW_CLOSED`."

    Design: Corner/state_machines/preorder_fulfill_outside_window_closed
    """
    customer = create_customer(account_type="RETAIL")
    product = create_product(base_price_cents=1000, shelf_life_days=90, unit_weight_g=40)
    create_released_batch(product["id"], 10)
    order = create_order(
        customer["id"], "PREORDER",
        fulfillment_window_start="2026-07-01T00:00:00Z",
        fulfillment_window_end="2026-07-02T00:00:00Z",
    )
    add_line(order["id"], customer["id"], product["id"], 1)
    confirm_order(order["id"], customer["id"])
    allocate_order(order["id"])
    set_clock("2026-07-10T00:00:00Z")
    resp = api.fulfill_order(order["id"], PROD)
    validate_error(resp, "ERR_FULFILLMENT_WINDOW_CLOSED", 422)
    fetched = validate_success(api.get_order(order["id"], SALES))
    assert fetched["status"] == "ALLOCATED", fetched


def test_wholesale_order_type_account_mismatch(api):
    """PRD §3.5: "a `WHOLESALE` order requires a `WHOLESALE` account, while a
    `RETAIL` or `PREORDER` order requires a `RETAIL` or `CORPORATE` account. An
    incompatible pairing is rejected with `ERR_ACCOUNT_TYPE_MISMATCH`."

    Design: Corner/validations/wholesale_order_type_account_mismatch
    """
    customer = create_customer(account_type="RETAIL")
    product = create_product(base_price_cents=1000, shelf_life_days=30, unit_weight_g=40)
    order = create_order(customer["id"], "WHOLESALE")
    add_line(order["id"], customer["id"], product["id"], 60)
    resp = api.confirm_order(order["id"], make_customer_headers(customer["id"]))
    validate_error(resp, "ERR_ACCOUNT_TYPE_MISMATCH", 422)


def test_duplicate_product_line_rejected(api):
    """PRD §3.5: "An order may not carry two lines for the same `product_id`; a
    second line for a product already on the order is rejected with
    `ERR_DUPLICATE_LINE`."

    Design: Corner/validations/duplicate_product_line_rejected
    """
    customer = create_customer(account_type="RETAIL")
    product = create_product(base_price_cents=500, shelf_life_days=30, unit_weight_g=10)
    order = create_order(customer["id"], "RETAIL")
    add_line(order["id"], customer["id"], product["id"], 1)
    resp = api.add_order_line(
        order["id"], {"product_id": product["id"], "quantity": 2},
        make_customer_headers(customer["id"]))
    validate_error(resp, "ERR_DUPLICATE_LINE", 409)


def test_order_line_zero_quantity_rejected(api):
    """PRD §3.5: "A non-positive `quantity` is rejected with
    `ERR_INVALID_QUANTITY`."

    Design: Corner/validations/order_line_zero_quantity_rejected
    """
    customer = create_customer(account_type="RETAIL")
    product = create_product(base_price_cents=500, shelf_life_days=30, unit_weight_g=10)
    order = create_order(customer["id"], "RETAIL")
    resp = api.add_order_line(
        order["id"], {"product_id": product["id"], "quantity": 0},
        make_customer_headers(customer["id"]))
    validate_error(resp, "ERR_INVALID_QUANTITY", 422)
