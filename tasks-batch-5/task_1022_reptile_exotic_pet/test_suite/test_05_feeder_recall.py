"""Feeder shipments, recalls, reversals: cascades, conservation, error precedence."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    make_store_manager_headers,
    create_feeder_batch, create_customer, create_subscription, create_shipment,
    setup_subscription_with_shipment, open_recall,
)

_SALES = TEST_USERS["sales_associate_headers"]
_SM = TEST_USERS["store_manager_headers"]


class TestRecallCascadeDepth3:
    def test_recall_reverses_shipment_holds_subscription_and_credits_customer(self, api):
        """PRD §3.7: "Every `SHIPPED` shipment that allocated any recalled batch is reversed — moved to `REVERSED` with `reversed_reason` set to `RECALL" "Each subscription behind such a reversed shipment moves from `ACTIVE` to `HELD`, and the subscription's customer is compensated: their `wallet_credit_cents` increases by the reversed shipment's `shipment_cost_cents"

        Design: Difficulty/transitive_cascade/recall_cascade_batch_to_shipment_to_subscription_depth3
        """
        ctx = setup_subscription_with_shipment(
            api,
            batch_overrides={"quantity_on_hand": 30, "unit_price_cents": 50},
            sub_overrides={"quantity_per_shipment": 10},
            customer_overrides={"email": "recall-d3@x.com"},
        )
        open_recall(api, [ctx["batch"]["id"]], opener_id="mgr-recall", target_feeder_type="CRICKET")
        batch = get_success_data(api.get_feeder_batch(ctx["batch"]["id"], headers=_SM))
        shipment = get_success_data(api.get_shipment(ctx["shipment"]["id"], headers=_SM))
        sub = get_success_data(api.get_subscription(ctx["subscription"]["id"], headers=_SM))
        cust = get_success_data(api.get_customer(ctx["customer"]["id"], headers=_SM))
        assert batch["status"] == "RECALLED"
        assert shipment["status"] == "REVERSED"
        assert shipment["reversed_reason"] == "RECALL"
        assert sub["status"] == "HELD"
        # shipment cost = 10 * round(50*1.25=62.5 -> 63) = 630
        assert cust["wallet_credit_cents"] == 630

    def test_recall_forces_batch_quantity_to_zero_without_restoring(self, api):
        """PRD §3.7: "Each affected feeder batch moves from `AVAILABLE` to `RECALLED` and has its `quantity_on_hand` forced to 0. Every `SHIPPED` shipment that allocated any recalled batch is reversed" "but, unlike a manual reversal, a recall does **not** restore the recalled batch quantities"

        Design: Difficulty/transitive_cascade/recall_cascade_batch_to_shipment_to_subscription_depth3
        """
        ctx = setup_subscription_with_shipment(
            api,
            batch_overrides={"quantity_on_hand": 30, "unit_price_cents": 50},
            sub_overrides={"quantity_per_shipment": 10},
            customer_overrides={"email": "recall-noreturn@x.com"},
        )
        open_recall(api, [ctx["batch"]["id"]], opener_id="mgr-recall", target_feeder_type="CRICKET")
        batch = get_success_data(api.get_feeder_batch(ctx["batch"]["id"], headers=_SM))
        assert batch["quantity_on_hand"] == 0


class TestFeederUnitConservation:
    def test_manual_reverse_restores_batch_quantity(self, api):
        """PRD §3.6: "A `SalesAssociate` may manually reverse a `SHIPPED` shipment, moving it to `REVERSED` with `reversed_reason` set to `MANUAL`; a manual reversal restores each allocation line's `quantity` to its batch's `quantity_on_hand`, and any batch that was `DEPLETED` returns to `AVAILABLE`."

        Design: Difficulty/compensating_invariant/feeder_unit_conservation_ship_then_reverse
        """
        ctx = setup_subscription_with_shipment(
            api,
            batch_overrides={"quantity_on_hand": 30, "unit_price_cents": 50},
            sub_overrides={"quantity_per_shipment": 10},
            customer_overrides={"email": "conserve1@x.com"},
        )
        reversed_ship = validate_success(api.reverse_shipment(ctx["shipment"]["id"], headers=_SALES))
        assert reversed_ship["status"] == "REVERSED"
        assert reversed_ship["reversed_reason"] == "MANUAL"
        batch = get_success_data(api.get_feeder_batch(ctx["batch"]["id"], headers=_SM))
        assert batch["quantity_on_hand"] == 30
        assert batch["status"] == "AVAILABLE"

    def test_ship_decrements_then_reverse_conserves_total(self, api):
        """PRD §3.6: "As stock is drawn down, each batch's `quantity_on_hand` is decremented and any batch reaching 0 flips from `AVAILABLE` to `DEPLETED`."
        PRD §3.6: "a manual reversal restores each allocation line's `quantity` to its batch's `quantity_on_hand"

        Design: Difficulty/compensating_invariant/feeder_unit_conservation_ship_then_reverse
        """
        ctx = setup_subscription_with_shipment(
            api,
            batch_overrides={"quantity_on_hand": 30, "unit_price_cents": 50},
            sub_overrides={"quantity_per_shipment": 10},
            customer_overrides={"email": "conserve2@x.com"},
        )
        after_ship = get_success_data(api.get_feeder_batch(ctx["batch"]["id"], headers=_SM))
        assert after_ship["quantity_on_hand"] == 20  # 30 - 10
        get_success_data(api.reverse_shipment(ctx["shipment"]["id"], headers=_SALES))
        after_reverse = get_success_data(api.get_feeder_batch(ctx["batch"]["id"], headers=_SM))
        assert after_reverse["quantity_on_hand"] == 30  # restored


class TestShipmentSafetyBeatsFiscal:
    def _recalled_batch_subscription(self, api, email):
        batch = create_feeder_batch(api, feeder_type="CRICKET", size="MEDIUM",
                                    quantity_on_hand=10, unit_price_cents=50)
        open_recall(api, [batch["id"]], opener_id="mgr-recall", target_feeder_type="CRICKET")
        customer = create_customer(api, email=email)
        sub = create_subscription(api, customer["id"], feeder_type="CRICKET",
                                  size="MEDIUM", quantity_per_shipment=10)
        return sub

    def test_ship_with_only_recalled_batch_returns_feeder_recalled(self, api):
        """PRD §3.6: "If every candidate batch is recalled or expired so that no eligible stock exists at all, the shipment is refused with `ERR_FEEDER_RECALLED`; if eligible stock exists but the total available matching quantity is less than `quantity_per_shipment`, it is refused with `ERR_INSUFFICIENT_FEEDER_STOCK` — the recalled/expired-exhaustion check takes precedence over the insufficient-quantity check."

        Design: Difficulty/priority_pair_validation_conflict/shipment_safety_beats_fiscal
        """
        sub = self._recalled_batch_subscription(api, "safety1@x.com")
        resp = api.create_shipment(sub["id"], headers=_SALES)
        validate_error(resp, ApiErrorId.ERR_FEEDER_RECALLED.value)

    def test_recall_exhaustion_takes_precedence_and_leaves_subscription_active(self, api):
        """PRD §3.6: "the recalled/expired-exhaustion check takes precedence over the insufficient-quantity check."

        Design: Difficulty/priority_pair_validation_conflict/shipment_safety_beats_fiscal
        """
        sub = self._recalled_batch_subscription(api, "safety2@x.com")
        resp = api.create_shipment(sub["id"], headers=_SALES)
        validate_error(resp, ApiErrorId.ERR_FEEDER_RECALLED.value)
        after = get_success_data(api.get_subscription(sub["id"], headers=_SM))
        assert after["status"] == "ACTIVE"


class TestShipmentInsufficientStockBoundary:
    def test_second_ship_against_drained_stock_returns_insufficient(self, api):
        """PRD §3.6: "if eligible stock exists but the total available matching quantity is less than `quantity_per_shipment`, it is refused with `ERR_INSUFFICIENT_FEEDER_STOCK"

        Design: Difficulty/boundary_precision_check/shipment_insufficient_at_zero_stock
        """
        ctx = setup_subscription_with_shipment(
            api,
            batch_overrides={"size": "SMALL", "quantity_on_hand": 10, "unit_price_cents": 40},
            sub_overrides={"size": "SMALL", "quantity_per_shipment": 10, "cadence_days": 7},
            customer_overrides={"email": "insuff@x.com"},
        )
        # first shipment (in the fixture) drained the qty-10 batch to 0
        resp = api.create_shipment(ctx["subscription"]["id"], headers=_SALES)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FEEDER_STOCK.value)
        batch = get_success_data(api.get_feeder_batch(ctx["batch"]["id"], headers=_SM))
        assert batch["quantity_on_hand"] == 0

    def test_first_ship_exactly_drains_batch_to_depleted(self, api):
        """PRD §3.6: "As stock is drawn down, each batch's `quantity_on_hand` is decremented and any batch reaching 0 flips from `AVAILABLE` to `DEPLETED`."

        Design: Difficulty/boundary_precision_check/shipment_insufficient_at_zero_stock
        """
        ctx = setup_subscription_with_shipment(
            api,
            batch_overrides={"size": "SMALL", "quantity_on_hand": 10, "unit_price_cents": 40},
            sub_overrides={"size": "SMALL", "quantity_per_shipment": 10, "cadence_days": 7},
            customer_overrides={"email": "exact-drain@x.com"},
        )
        batch = get_success_data(api.get_feeder_batch(ctx["batch"]["id"], headers=_SM))
        assert batch["quantity_on_hand"] == 0
        assert batch["status"] == "DEPLETED"


class TestRecallFourEyes:
    def test_close_recall_by_opener_returns_segregation_of_duties(self, api):
        """PRD §3.7: "A recall is closed by a `StoreManager` whose `X-User-ID` differs from the recall's `opened_by_user_id` (a four-eyes control; a match is rejected with `ERR_SEGREGATION_OF_DUTIES`)"

        Design: Corner/validations/recall_close_by_opener_returns_segregation_of_duties
        """
        batch = create_feeder_batch(api, feeder_type="CRICKET", size="MEDIUM",
                                    quantity_on_hand=20, unit_price_cents=50)
        recall = open_recall(api, [batch["id"]], opener_id="mgr-a", target_feeder_type="CRICKET")
        resp = api.close_recall(recall["id"], headers=make_store_manager_headers("mgr-a"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        after = get_success_data(api.get_recall(recall["id"], headers=_SM))
        assert after["status"] == "OPEN"
