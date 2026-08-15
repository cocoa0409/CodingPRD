"""State machines: initial states, invalid transitions, terminal lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_hedge,
    book_shipment,
    create_batch,
    create_counterparty,
    create_fixed_contract,
    create_hedge,
    create_ptbf_contract,
    create_roast_batch_payload,
    cup_batch_pass,
    finish_batch,
    pack_batch,
    receive_shipment,
    record_price_fix,
    set_clock,
    setup_packed_batch,
    setup_roasted_batch,
    start_batch,
    validate_error,
    validate_success,
    walk_shipment_to_arrived,
)

TRADER = TEST_USERS["trader_headers"]
RISK = TEST_USERS["risk_manager_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]
ROAST_OP = TEST_USERS["roast_operator_headers"]
HEAD_ROASTER = TEST_USERS["head_roaster_headers"]


class TestContractInitialState:
    def test_contract_initial_state(self, api):
        """PRD §3.1: "A new contract's two parallel state dials start at
        `fulfillment_status` `OPEN` on the receipt side. On the pricing side,
        a differential contract starts at `pricing_status` `UNFIXED` with
        `fixed_lbs_accum` zero."

        Design: Corner/state_machines/contract_initial_state
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-INIT")
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-INIT",
                                         total_lbs=1000, differential=0.25)
        assert contract["pricing_status"] == "UNFIXED"
        assert contract["fulfillment_status"] == "OPEN"
        assert contract["fixed_lbs_accum"] == 0


class TestShipmentInvalidTransitions:
    def test_shipment_cancel_from_received_returns_invalid_state(self, api):
        """PRD §3.4: "A booking can be cancelled only before it ships —
        `BOOKED` to `CANCELLED` — because once the coffee is moving it must
        be received or disputed, not erased. Any of these attempted from the
        wrong state is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/shipment_cancel_from_received_returns_invalid_state
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-INV2")
        contract = create_fixed_contract(
            supplier["id"], contract_ref="C-INV2", total_lbs=1000,
            fixed_price=2.00,
        )
        shipment = book_shipment(contract["id"], shipment_ref="SH-INV2",
                                  planned_lbs=1000)
        walk_shipment_to_arrived(shipment["id"])
        receive_shipment(shipment["id"], 1000, lot_code="L-INV2")
        resp = api.cancel_shipment(shipment["id"], LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTerminalLockdown:
    def test_terminal_state_lockdown_shipment(self, api):
        """PRD §3.4: "A booking can be cancelled only before it ships —
        `BOOKED` to `CANCELLED` — because once the coffee is moving it must
        be received or disputed, not erased. Any of these attempted from the
        wrong state is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_state_lockdown_shipment
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-TERM")
        contract = create_fixed_contract(
            supplier["id"], contract_ref="C-TERM", total_lbs=1000,
            fixed_price=2.00,
        )
        shipment = book_shipment(contract["id"], shipment_ref="SH-TERM",
                                  planned_lbs=1000)
        validate_success(api.cancel_shipment(shipment["id"], LOGISTICS))
        # Shipment is now in terminal CANCELLED. Any further transition is rejected.
        resp = api.depart_shipment(shipment["id"], LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_terminal_state_lockdown_futures_hedge(self, api):
        """PRD §3.3: "Lifting belongs back to the `Trader`, who supplies an
        `exit_price_usd_per_lb` that must be provided and strictly positive."
        PRD §2.8: "After existence comes state legality — the target entity
        must be in a state that permits the requested transition, otherwise
        `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.3: "Approval belongs to the `RiskManager`."
        Once LIFTED the hedge is terminal; a further approve must be rejected.

        Design: Corner/state_machines/terminal_state_lockdown_futures_hedge
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-HTL", credit_limit_usd=10000000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-HTL",
                                         total_lbs=5000, differential=0.25)
        hedge = create_hedge(contract["id"], hedge_side="BUY_FUTURES",
                              hedge_lbs=1000, entry_price=1.80,
                              trader_headers=TEST_USERS["trader_headers"])
        approve_hedge(hedge["id"])
        # Manually lift with a positive exit price
        validate_success(api.lift_futures_hedge(
            hedge["id"], {"exit_price_usd_per_lb": 1.90}, TRADER))
        # LIFTED is terminal: another approve attempt must fail
        resp = api.approve_futures_hedge(hedge["id"], RISK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRoastBatchInvalidTransitions:
    def test_roast_batch_void_from_packed_returns_invalid_state(self, api):
        """PRD §3.8: "Finally, a batch still in `SCHEDULED` can be voided:
        voiding moves it to `VOIDED`, releases every allocation from `ACTIVE`
        back to `RELEASED`, returns the mass to each lot's `available_lbs`,
        and recomputes the position. Actions attempted from the wrong
        production state are `ERR_INVALID_STATE`."

        Design: Corner/state_machines/roast_batch_void_from_packed_returns_invalid_state
        """
        set_clock()
        ctx = setup_packed_batch(
            supplier_ref="SUP-VO", product_sku="P-VO",
            scheduled_green_lbs=100, actual_roasted_lbs=84, packed_lbs=84,
        )
        batch = ctx["batch"]
        # batch is PACKED now
        resp = api.void_roast_batch(batch["id"], ROAST_OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
