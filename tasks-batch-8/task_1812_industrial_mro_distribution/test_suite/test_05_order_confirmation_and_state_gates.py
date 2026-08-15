"""Order confirmation gates: customer status, hazmat, credit, and state errors."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_branch,
    create_central,
    create_customer,
    create_item,
    get_customer,
    get_location_balance,
    get_order,
    place_order,
    restock,
    setup_completed_order,
    setup_confirmed_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
BRANCH_MANAGER = TEST_USERS["branch_manager_headers"]


def _set_customer_status(api, customer, status):
    """PUT the account status with the current version (OCC-guarded, PRD §2.7)."""
    fresh = get_customer(customer["id"])
    res = api.update_customer(
        customer["id"],
        {"status": status, "expected_customer_version": fresh["version"]},
        ADMIN,
    )
    return validate_success(res, 200)


class TestConfirmStateErrorBeatsCreditFiscal:
    def _setup(self, api):
        customer = create_customer(
            account_number="HOLD-1", credit_limit_cents=1000,
            primary_ship_to_state="OH",
        )
        item = create_item(sku="CF-5K", list_price_cents=5000)
        branch = create_branch(location_code="BR-9")
        restock(branch["id"], item["id"], 1)
        order = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}]
        )
        _set_customer_status(api, customer, "CREDIT_HOLD")
        return customer, order

    def test_confirm_reports_customer_not_active_not_credit_limit(
        self, api, admin_headers
    ):
        """PRD §3.6: "Confirmation is the administrator's commitment point, and it
        is gated by four families of checks in the cascade order of §2.10. First,
        the account must be `ACTIVE` — confirming for an account on `CREDIT_HOLD`
        is rejected with `ERR_CUSTOMER_NOT_ACTIVE`"
        PRD §2.10: "When a request violates more than one rule, the system
        evaluates checks in a fixed global order so that an earlier failure always
        masks a later one."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_error_beats_credit_fiscal
        """
        _customer, order = self._setup(api)
        res = api.confirm_order(order["id"], admin_headers)
        # Auto-checks HTTP 409; ERR_CREDIT_LIMIT_EXCEEDED would map to 402.
        validate_error(res, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)

    def test_rejected_confirm_leaves_order_and_exposure_untouched(
        self, api, admin_headers
    ):
        """PRD §3.6: "Confirmation then stamps `confirmed_at` from the logical
        clock and debits the account's `open_credit_exposure_cents` by the order's
        `total_cents`."
        PRD §3.5: "New orders start with `status` `SUBMITTED` and
        `fulfillment_status` `UNALLOCATED`"

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_error_beats_credit_fiscal
        """
        customer, order = self._setup(api)
        res = api.confirm_order(order["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)

        order_after = get_order(order["id"])
        assert order_after["status"] == "SUBMITTED"
        assert order_after["fulfillment_status"] == "UNALLOCATED"
        account = get_customer(customer["id"])
        assert account["open_credit_exposure_cents"] == 0


class TestConfirmHazmatSafetyBeatsCreditFiscal:
    def _setup(self, api):
        customer = create_customer(
            account_number="HZ-C", credit_limit_cents=1000,
            primary_ship_to_state="NV",
        )
        item = create_item(
            sku="WC-ONLY", hazmat_restriction="WILL_CALL_ONLY", list_price_cents=5000
        )
        branch = create_branch(location_code="BR-10", region_state="NV")
        restock(branch["id"], item["id"], 1)
        order = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}],
            fulfillment_method="SAME_DAY",
        )
        return customer, order

    def test_same_day_hazmat_order_pricing_includes_freight_and_handling(
        self, api, admin_headers
    ):
        """PRD §3.5: "otherwise `SAME_DAY` carries 1,500 cents and `STANDARD` 795
        cents. Independently of any waiver, when any line's item has a
        `hazmat_restriction` other than `NONE` and the order is not will-call, a
        2,500-cent hazmat handling charge is added — even when the base freight
        was waived."

        Design: Difficulty/priority_pair_validation_conflict/confirm_hazmat_safety_beats_credit_fiscal
        """
        _customer, order = self._setup(api)
        assert order["subtotal_cents"] == 5000
        assert order["freight_cents"] == 4000  # 1,500 same-day + 2,500 hazmat
        assert order["total_cents"] == 9000

    def test_confirm_reports_hazmat_method_not_credit_limit(self, api, admin_headers):
        """PRD §3.6: "Second, hazmat method restrictions: an order whose
        `fulfillment_method` is anything other than `WILL_CALL` may not contain an
        item marked `WILL_CALL_ONLY`, and a `SAME_DAY` order may not contain a
        `GROUND_ONLY` item — either violation is rejected with
        `ERR_HAZMAT_METHOD_RESTRICTED`."
        PRD §2.10: "Seventh, hazmat and region shipping restrictions are evaluated.
        ... Finally, the credit gate at order confirmation is evaluated, after
        every other confirm-time rule has passed."

        Design: Difficulty/priority_pair_validation_conflict/confirm_hazmat_safety_beats_credit_fiscal
        """
        _customer, order = self._setup(api)
        res = api.confirm_order(order["id"], admin_headers)
        # Auto-checks HTTP 422; ERR_CREDIT_LIMIT_EXCEEDED would map to 402.
        validate_error(res, ApiErrorId.ERR_HAZMAT_METHOD_RESTRICTED)


class TestOrderConfirmRequiresCustomerActive:
    def _setup(self, api):
        customer = create_customer(
            account_number="XS-1", credit_limit_cents=10000000,
            primary_ship_to_state="OH",
        )
        item = create_item(sku="XS-1", list_price_cents=1000)
        branch = create_branch(location_code="BR-13")
        restock(branch["id"], item["id"], 1)
        order = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}]
        )
        return customer, order

    def test_credit_hold_blocks_confirm(self, api, admin_headers):
        """PRD §3.6: "the account must be `ACTIVE` — confirming for an account on
        `CREDIT_HOLD` is rejected with `ERR_CUSTOMER_NOT_ACTIVE`, while a
        `SUBMITTED` order awaiting confirmation is the only place customer status
        gates an in-flight order."

        Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_customer_active
        """
        customer, order = self._setup(api)
        _set_customer_status(api, customer, "CREDIT_HOLD")
        res = api.confirm_order(order["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)

    def test_reinstated_customer_unblocks_same_order(self, api, admin_headers):
        """PRD §3.1: "A credit hold touches nothing already in flight — open
        orders are unaffected — and bites only at order confirmation"
        PRD §3.6: "the account must be `ACTIVE` — confirming for an account on
        `CREDIT_HOLD` is rejected with `ERR_CUSTOMER_NOT_ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_customer_active
        """
        customer, order = self._setup(api)
        _set_customer_status(api, customer, "CREDIT_HOLD")
        res = api.confirm_order(order["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)

        _set_customer_status(api, customer, "ACTIVE")
        confirmed = validate_success(api.confirm_order(order["id"], admin_headers))
        assert confirmed["status"] == "CONFIRMED"


class TestHazmatRestrictions:
    def test_hazmat_region_restricted_delivery_but_will_call_exempt(
        self, api, admin_headers
    ):
        """PRD §3.6: "Third, hazmat region restrictions: on a delivery method, no
        line's item may list the customer's `primary_ship_to_state` among its
        `restricted_states`, on pain of `ERR_HAZMAT_REGION_RESTRICTED`; will-call
        pickup is exempt from both hazmat gates."

        Design: Corner/validations/hazmat_region_restricted_delivery_but_will_call_exempt
        """
        customer = create_customer(
            account_number="HR-1", credit_limit_cents=1000000,
            primary_ship_to_state="CA",
        )
        item = create_item(
            sku="HR-1", restricted_states=["CA"], list_price_cents=1000
        )
        branch = create_branch(location_code="BR-HR", region_state="CA")
        restock(branch["id"], item["id"], 2)
        order_std = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}],
            fulfillment_method="STANDARD",
        )
        order_wc = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}],
            fulfillment_method="WILL_CALL",
        )

        res = api.confirm_order(order_std["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_HAZMAT_REGION_RESTRICTED)

        confirmed = validate_success(api.confirm_order(order_wc["id"], admin_headers))
        assert confirmed["status"] == "CONFIRMED"

    def test_ground_only_method_matrix(self, api, admin_headers):
        """PRD §3.6: "an order whose `fulfillment_method` is anything other than
        `WILL_CALL` may not contain an item marked `WILL_CALL_ONLY`, and a
        `SAME_DAY` order may not contain a `GROUND_ONLY` item — either violation
        is rejected with `ERR_HAZMAT_METHOD_RESTRICTED`."

        Design: Corner/validations/ground_only_method_matrix
        """
        customer = create_customer(
            account_number="GO-1", credit_limit_cents=1000000,
            primary_ship_to_state="OH",
        )
        item = create_item(
            sku="GO-1", hazmat_restriction="GROUND_ONLY", list_price_cents=1000
        )
        branch = create_branch(location_code="BR-GO")
        restock(branch["id"], item["id"], 2)
        order_std = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}],
            fulfillment_method="STANDARD",
        )
        order_sd = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}],
            fulfillment_method="SAME_DAY",
        )

        confirmed = validate_success(api.confirm_order(order_std["id"], admin_headers))
        assert confirmed["status"] == "CONFIRMED"

        res = api.confirm_order(order_sd["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_HAZMAT_METHOD_RESTRICTED)


class TestOrderStateGates:
    def test_order_confirm_twice_returns_invalid_state(self, api, admin_headers):
        """PRD §3.7: "Once an order has been readied — `READY_FOR_WILL_CALL`,
        `SHIPPED`, or `FULFILLED` — cancellation is no longer a valid transition
        and is rejected with `ERR_INVALID_STATE_TRANSITION`, as is any confirm
        attempted twice or a complete attempted out of order."

        Design: Corner/state_machines/order_confirm_twice_returns_invalid_state
        """
        scenario = setup_confirmed_order(
            [{"qty": 2, "sku": "CF-2", "list_price_cents": 100}],
            customer_overrides={"account_number": "CF-2",
                                "credit_limit_cents": 100000},
            branch_overrides={"location_code": "BR-CF"},
            restock_qtys=[2],
        )
        order = scenario["order"]
        assert order["status"] == "CONFIRMED"

        res = api.confirm_order(order["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        balance = get_location_balance(
            scenario["branch"]["id"], scenario["items"][0]["id"]
        )
        assert balance["reserved_qty"] == 2, (
            f"allocation must not double-run, reserved_qty={balance['reserved_qty']}"
        )

    def test_mark_ready_before_confirm_returns_invalid_state(
        self, api, admin_headers, branch_manager_headers
    ):
        """PRD §3.7: "Both moves are allowed from `ALLOCATED` and from
        `PARTIALLY_ALLOCATED` alike — partial orders may be readied with their
        backordered units left open — and both require the order's commercial
        `status` to still be `CONFIRMED`, failing with
        `ERR_INVALID_STATE_TRANSITION` otherwise."

        Design: Corner/state_machines/mark_ready_before_confirm_returns_invalid_state
        """
        customer = create_customer(account_number="MR-1", credit_limit_cents=100000)
        item = create_item(sku="MR-1", list_price_cents=100)
        branch = create_branch(location_code="BR-MR")
        restock(branch["id"], item["id"], 1)
        order = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}]
        )
        res = api.mark_order_ready(order["id"], branch_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_central_branch_type_rejected_for_fulfillment(self, api, admin_headers):
        """PRD §3.5: "The request names the account via `customer_id`, chooses the
        fulfilling branch through `fulfillment_branch_id` — which must reference a
        `BRANCH` location, a `CENTRAL` reference being rejected with
        `ERR_BRANCH_TYPE_REQUIRED`"

        Design: Corner/errors/central_branch_type_rejected_for_fulfillment
        """
        customer = create_customer(account_number="BT-1", credit_limit_cents=100000)
        item = create_item(sku="BT-1", list_price_cents=100)
        central = create_central(location_code="CN-ONLY", region_state="OH")
        res = api.create_order(
            {
                "customer_id": customer["id"],
                "fulfillment_branch_id": central["id"],
                "fulfillment_method": "WILL_CALL",
                "lines": [{"item_id": item["id"], "qty": 1}],
            },
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_BRANCH_TYPE_REQUIRED)

    def test_order_cancel_after_completed_returns_invalid_state(
        self, api, admin_headers
    ):
        """PRD §3.7: "Once an order has been readied — `READY_FOR_WILL_CALL`,
        `SHIPPED`, or `FULFILLED` — cancellation is no longer a valid transition
        and is rejected with `ERR_INVALID_STATE_TRANSITION`, as is any confirm
        attempted twice or a complete attempted out of order."

        Design: Corner/state_machines/order_cancel_after_completed_returns_invalid_state
        """
        scenario = setup_completed_order(
            [{"qty": 1, "sku": "TL-1", "list_price_cents": 100}],
            customer_overrides={"account_number": "TL-1",
                                "credit_limit_cents": 100000},
            branch_overrides={"location_code": "BR-TL"},
            restock_qtys=[1],
        )
        assert scenario["order"]["status"] == "COMPLETED"
        res = api.cancel_order(scenario["order"]["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_complete_before_fulfilled_rejected(self, api, admin_headers):
        """PRD §3.7: "Completion is the administrator's final commercial act and
        requires `fulfillment_status` `FULFILLED`; anything earlier is rejected
        with `ERR_ORDER_NOT_FULFILLED`."

        Design: Corner/errors/complete_before_fulfilled_rejected
        """
        scenario = setup_confirmed_order(
            [{"qty": 1, "sku": "NF-1", "list_price_cents": 100}],
            customer_overrides={"account_number": "NF-1",
                                "credit_limit_cents": 100000},
            branch_overrides={"location_code": "BR-NF"},
            restock_qtys=[1],
        )
        assert scenario["order"]["status"] == "CONFIRMED"
        res = api.complete_order(scenario["order"]["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_FULFILLED)
