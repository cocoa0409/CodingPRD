"""Sales-order lifecycle: pricing gating, confirmation, shipment, invoicing (PRD §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_settlement_margin_consistency,
    create_active_contract,
    create_order,
    create_priced_order,
    create_vehicle,
    get_settlement,
    setup_released_tallow_lot,
    validate_error,
    validate_success,
)

SM = TEST_USERS["sales_manager_headers"]
RD = TEST_USERS["route_dispatcher_headers"]
FA = TEST_USERS["finance_analyst_headers"]
ANY = TEST_USERS["any_headers"]


class TestOrderStateMachine:
    def test_order_invoice_from_priced_rejected(self, api):
        """PRD §3.8: "A `FinanceAnalyst` invoices a `SHIPPED` order (`ERR_ORDER_INVALID_STATE`
        otherwise) while the current period settlement is `OPEN` or `REOPENED`
        (`ERR_PERIOD_CLOSED`); the settlement's `product_revenue_cents` increases by the
        order's `net_amount_cents`, and the order becomes `INVOICED`, its terminal state."

        Design: Corner/state_machines/order_invoice_from_priced_rejected
        """
        from test_helpers import create_plant

        plant = create_plant()
        contract = create_active_contract(plant["id"])
        order = create_priced_order(contract, quantity_lbs=100, expected_grade="STANDARD")
        assert order["status"] == "PRICED"

        res = api.invoice_order(order["id"], FA)
        validate_error(res, ApiErrorId.ERR_ORDER_INVALID_STATE, expected_status=409)

        order_after = validate_success(api.get_sales_order(order["id"], ANY), 200)
        assert order_after["status"] == "PRICED"
        settlement = get_settlement(plant["id"], period_index=1)
        assert settlement["product_revenue_cents"] == 0

    def test_cancelled_order_terminal_lockdown(self, api):
        """PRD §3.8: "Cancellation is available from `DRAFT`, `PRICED`, or `CONFIRMED` (else
        `ERR_ORDER_INVALID_STATE`); cancelling a `CONFIRMED` order releases its allocations
        the same way."
        PRD §3.8: "The sales manager confirms a `PRICED` order (`ERR_ORDER_INVALID_STATE`
        otherwise, `ERR_CONTRACT_NOT_ACTIVE` if the contract has left `ACTIVE`) with an
        `allocations` list whose entries each pair a `lot_id` with a `quantity_lbs`."

        Design: Corner/state_machines/cancelled_order_terminal_lockdown
        """
        from test_helpers import create_plant

        plant = create_plant()
        contract = create_active_contract(plant["id"])
        order = create_order(contract["id"], plant["id"], quantity_lbs=100)
        cancelled = validate_success(api.cancel_order(order["id"], SM), 200)
        assert cancelled["status"] == "CANCELLED"

        # CANCELLED is terminal: no transition exists out of it.
        res = api.confirm_order(order["id"], {"allocations": []}, SM)
        validate_error(res, ApiErrorId.ERR_ORDER_INVALID_STATE, expected_status=409)

        fetched = validate_success(api.get_sales_order(order["id"], ANY), 200)
        assert fetched["status"] == "CANCELLED"


class TestConfirmContractDependency:
    def _setup_priced_order(self, api):
        from test_helpers import create_plant

        plant = create_plant()
        contract = create_active_contract(plant["id"], margin_floor_pct=15.0)
        # STANDARD multiplier: unit 50, margin 24.0 — comfortably above the floor.
        order = create_priced_order(contract, quantity_lbs=100, expected_grade="STANDARD")
        assert order["status"] == "PRICED"
        return plant, contract, order

    def test_confirm_rejected_while_contract_suspended(self, api):
        """PRD §3.8: "The sales manager confirms a `PRICED` order (`ERR_ORDER_INVALID_STATE`
        otherwise, `ERR_CONTRACT_NOT_ACTIVE` if the contract has left `ACTIVE`) with an
        `allocations` list whose entries each pair a `lot_id` with a `quantity_lbs`."
        PRD §2.9 item 11: "**Cross-entity state.** ... order creation, pricing, and
        confirmation require the contract `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`, 409); ..."

        Design: Difficulty/cross_entity_state_dependency/order_confirm_blocked_by_suspended_contract
        """
        plant, contract, order = self._setup_priced_order(api)
        suspended = validate_success(api.suspend_contract(contract["id"], SM), 200)
        assert suspended["status"] == "SUSPENDED"

        # Empty allocations would also fail the sum check, but the cross-entity contract
        # gate (priority 11) evaluates before allocation sums (priority 13).
        res = api.confirm_order(order["id"], {"allocations": []}, SM)
        validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, expected_status=409)

        order_after = validate_success(api.get_sales_order(order["id"], ANY), 200)
        assert order_after["status"] == "PRICED"

    def test_confirm_proceeds_after_contract_reinstated(self, api):
        """PRD §3.8: "A `SalesManager` may suspend an `ACTIVE` contract and later reinstate
        a `SUSPENDED` one; out-of-state transitions return `ERR_CONTRACT_INVALID_STATE`."
        PRD §3.8: "Then, in this order: the allocations must sum exactly to the order's
        `quantity_lbs` (`ERR_ALLOCATION_MISMATCH`), and only afterward is each lot's
        `available_lbs` checked for sufficiency (`ERR_INSUFFICIENT_LOT_QUANTITY`)."

        Design: Difficulty/cross_entity_state_dependency/order_confirm_blocked_by_suspended_contract
        """
        plant, contract, order = self._setup_priced_order(api)
        validate_success(api.suspend_contract(contract["id"], SM), 200)
        res = api.confirm_order(order["id"], {"allocations": []}, SM)
        validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, expected_status=409)

        reinstated = validate_success(api.reinstate_contract(contract["id"], SM), 200)
        assert reinstated["status"] == "ACTIVE"

        # With the contract ACTIVE again, the confirm gate passes the cross-entity check
        # and evaluation now reaches the allocation-sum rule (empty list != 100 lbs).
        res2 = api.confirm_order(order["id"], {"allocations": []}, SM)
        validate_error(res2, ApiErrorId.ERR_ALLOCATION_MISMATCH, expected_status=422)
        order_after = validate_success(api.get_sales_order(order["id"], ANY), 200)
        assert order_after["status"] == "PRICED"


class TestOrderFulfilmentPipeline:
    def test_invoice_accrues_revenue_to_open_settlement(self, api):
        """PRD §3.8: "A `FinanceAnalyst` invoices a `SHIPPED` order (`ERR_ORDER_INVALID_STATE`
        otherwise) while the current period settlement is `OPEN` or `REOPENED`
        (`ERR_PERIOD_CLOSED`); the settlement's `product_revenue_cents` increases by the
        order's `net_amount_cents`, and the order becomes `INVOICED`, its terminal state."
        PRD §3.8: "Shipping records `shipped_vehicle_id` (null until this moment), turns the
        vehicle `DIRTY` with one more completed trip, decrements each allocated lot's
        `allocated_lbs` by its shipped quantity (a lot left with `available_lbs` and
        `allocated_lbs` both zero becomes `DEPLETED`), adds the order's `quantity_lbs` to
        the contract's `delivered_volume_lbs`, and moves the order to `SHIPPED`."
        PRD §3.1: "Its `gross_margin_cents` is always derivable as `product_revenue_cents`
        plus `pickup_fees_accrued_cents` minus `energy_costs_cents` minus
        `transport_costs_cents`. Its `margin_pct` expresses that gross margin as a
        percentage of the sum of product revenue and pickup fees, rounded half-up to two
        decimal places, and is null whenever that revenue sum is zero."

        Design: Corner/endpoints/invoice_accrues_revenue_to_open_settlement
        """
        # PREMIUM TALLOW lot 800 lbs RELEASED; the 3h cook run accrued 12600 energy cost.
        ctx = setup_released_tallow_lot()
        plant = ctx["plant"]
        contract = create_active_contract(plant["id"], margin_floor_pct=15.0)
        order = create_priced_order(contract, quantity_lbs=100, expected_grade="STANDARD")
        # unit 50; gross 5000; discount 0; freight 12500; net 17500.
        assert order["net_amount_cents"] == 17500

        confirmed = validate_success(
            api.confirm_order(
                order["id"],
                {"allocations": [{"lot_id": ctx["lot"]["id"], "quantity_lbs": 100}]},
                SM,
            ),
            200,
        )
        assert confirmed["status"] == "CONFIRMED"

        vehicle = create_vehicle(plant["id"], vehicle_tag="V-F", capacity_lbs=40000,
                                 duty_class="FINISHED_PRODUCT")
        shipped = validate_success(
            api.ship_order(order["id"], {"vehicle_id": vehicle["id"]}, RD), 200
        )
        assert shipped["status"] == "SHIPPED"
        assert shipped["shipped_vehicle_id"] == vehicle["id"]

        invoiced = validate_success(api.invoice_order(order["id"], FA), 200)
        assert invoiced["status"] == "INVOICED"

        settlement = get_settlement(plant["id"], period_index=1)
        assert settlement["product_revenue_cents"] == 17500
        assert settlement["energy_costs_cents"] == 12600  # 3h * 4200 from the cook run
        assert settlement["gross_margin_cents"] == 4900  # 17500 + 0 - 12600 - 0
        assert settlement["margin_pct"] == pytest.approx(28.0, abs=1e-9)
        assert_settlement_margin_consistency(settlement)

        contract_after = validate_success(
            api.get_customer_contract(contract["id"], ANY), 200
        )
        assert contract_after["delivered_volume_lbs"] == 100

        vehicle_after = validate_success(api.get_vehicle(vehicle["id"], ANY), 200)
        assert vehicle_after["sanitation_status"] == "DIRTY"
        assert vehicle_after["completed_trip_count"] == 1

        # 700 lbs remain available with nothing allocated: not depleted.
        lot = validate_success(api.get_product_lot(ctx["lot"]["id"], ANY), 200)
        assert lot["allocated_lbs"] == 0
        assert lot["available_lbs"] == 700
        assert lot["status"] == "RELEASED"
