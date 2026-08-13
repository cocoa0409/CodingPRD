"""Stockroom ledger, stock status bands, and valuation policies
(PRD §3.9)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_inventory_transaction_payload,
    create_supply_item,
    get_item,
    get_valuation,
    make_trainer,
    post_ledger_entry,
    set_clock,
    trainer_headers,
    validate_error,
    validate_success,
)


class TestSupplyItemCreation:

    def test_threshold_constraint_and_computed_stock_defaults(self):
        """PRD §3.9: "a `reorder_threshold` (zero or more but strictly below
        `par_level`)".
        PRD §3.9: "A new item has `current_stock` zero and `stock_status`
        `OUT_OF_STOCK`."

        Design: Corner/entities/supply_item_constraint_and_computed_stock
        """
        resp = api_client.create_supply_item(
            {
                "item_name": "Bad Item",
                "category": "TAPE",
                "unit": "ROLL",
                "par_level": 10,
                "reorder_threshold": 10,
                "unit_cost_cents": 100,
            },
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        item = create_supply_item(item_name="Good Item", par_level=10,
                                  reorder_threshold=3)
        assert item["current_stock"] == 0
        assert item["stock_status"] == "OUT_OF_STOCK"
        assert item["version"] == 1


class TestStockBandsAndViolations:

    def test_low_stock_upper_edge_is_inclusive(self):
        """PRD §3.9: "The item's `current_stock` is always the signed sum
        over its whole ledger, and `stock_status` follows: zero is
        `OUT_OF_STOCK`, from one up to `reorder_threshold` is `LOW_STOCK`,
        and anything above the threshold is `IN_STOCK`."

        Design: Corner/cross_cutting_layers/low_stock_boundary_at_threshold
        """
        tr1 = make_trainer()
        item = create_supply_item(par_level=50, reorder_threshold=15)
        set_clock("2026-08-01T12:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=15,
                          unit_cost_cents=100,
                          occurred_at="2026-08-01T09:00:00Z")
        at_threshold = get_item(item["id"])
        assert at_threshold["current_stock"] == 15
        assert at_threshold["stock_status"] == "LOW_STOCK", \
            "stock exactly at the threshold is still LOW_STOCK"

        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=1,
                          unit_cost_cents=100,
                          occurred_at="2026-08-01T10:00:00Z")
        above = get_item(item["id"])
        assert above["current_stock"] == 16
        assert above["stock_status"] == "IN_STOCK"

    def test_quantity_and_stock_floor_violations(self):
        """PRD §3.9: "a `quantity` that is always strictly positive (zero or
        negative draws `ERR_QUANTITY_NONPOSITIVE`)".
        PRD §3.9: "A `USAGE` or `WASTE` entry that would drive the item's
        stock below zero is rejected with `ERR_INSUFFICIENT_STOCK`."

        Design: Corner/validations/inventory_quantity_and_stock_violations
        """
        tr1 = make_trainer()
        item = create_supply_item(par_level=30, reorder_threshold=10)
        set_clock("2026-08-01T12:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=2,
                          unit_cost_cents=100,
                          occurred_at="2026-08-01T09:00:00Z")

        resp = api_client.create_inventory_transaction(
            create_inventory_transaction_payload(
                supply_item_id=item["id"], txn_type="USAGE", quantity=0,
                occurred_at="2026-08-01T10:00:00Z"),
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_QUANTITY_NONPOSITIVE)

        resp = api_client.create_inventory_transaction(
            create_inventory_transaction_payload(
                supply_item_id=item["id"], txn_type="USAGE", quantity=3,
                occurred_at="2026-08-01T10:05:00Z"),
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)

        assert get_item(item["id"])["current_stock"] == 2, \
            "a rejected usage leaves the ledger untouched"

    def test_threshold_edit_reconciles_stock_status(self):
        """PRD §3.9: "A `SystemAdmin` may later adjust `par_level`,
        `reorder_threshold`, `unit_cost_cents`, or `is_discontinued`; when
        the threshold changes, `stock_status` is recomputed against the
        unchanged stock figure."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_on_threshold_edit
        """
        tr1 = make_trainer()
        item = create_supply_item(par_level=50, reorder_threshold=15)
        set_clock("2026-08-01T12:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=10,
                          unit_cost_cents=100,
                          occurred_at="2026-08-01T09:00:00Z")
        # The ledger append is itself a reconciling mutation of the item
        # (current_stock / stock_status), so per PRD §2.6 it has already
        # incremented the item's version; re-read the pre-PATCH baseline.
        pre_patch = get_item(item["id"])
        assert pre_patch["stock_status"] == "LOW_STOCK"

        lowered = validate_success(api_client.patch_supply_item(
            item["id"], {"reorder_threshold": 3}, ADMIN))
        assert lowered["stock_status"] == "IN_STOCK", \
            "10 units above the lowered threshold of 3"
        assert lowered["version"] == pre_patch["version"] + 1, \
            "the PATCH mutates the item and increments its version"

        raised = validate_success(api_client.patch_supply_item(
            item["id"], {"reorder_threshold": 20}, ADMIN))
        assert raised["stock_status"] == "LOW_STOCK", \
            "10 units within 1..20 is LOW_STOCK again"


class TestValuationPolicies:
    """Difficulty instances inventory_fifo_vs_wac_running_same_ledger and
    wac_running_vs_exact_rounding_order, plus the FIFO corner."""

    def _ledger_a(self):
        """RESTOCK 3@100, USAGE 1, RESTOCK 1@103, USAGE 2 (PRD §3.9
        chronological replay)."""
        tr1 = make_trainer()
        item = create_supply_item(item_name="Athletic Tape")
        set_clock("2026-08-01T13:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=3,
                          unit_cost_cents=100,
                          occurred_at="2026-08-01T09:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="USAGE", quantity=1,
                          occurred_at="2026-08-01T10:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=1,
                          unit_cost_cents=103,
                          occurred_at="2026-08-01T11:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="USAGE", quantity=2,
                          occurred_at="2026-08-01T12:00:00Z")
        return tr1, item

    def test_fifo_values_ledger_a_at_surviving_layer(self):
        """PRD §3.9: "Under `FIFO`, the replay maintains cost layers: each
        `RESTOCK` pushes a layer of quantity and unit cost; each `USAGE` or
        `WASTE` consumes layers oldest-first".

        Design: Difficulty/dual_variant_calc/inventory_fifo_vs_wac_running_same_ledger
        """
        tr1, item = self._ledger_a()
        fifo = get_valuation(item["id"], "FIFO", tr1)
        # 3@100 - 1 used - 2 used leaves the 1@103 layer.
        assert fifo["quantity_on_hand"] == 1
        assert fifo["valuation_cents"] == 103

    def test_wac_running_diverges_from_fifo_on_same_ledger(self):
        """PRD §3.9: "Under `WAC_RUNNING`, a running unit cost is maintained:
        after every transaction the unit cost is recomputed as the running
        value divided by the running quantity, rounded half-up to a whole
        cent".

        Design: Difficulty/dual_variant_calc/inventory_fifo_vs_wac_running_same_ledger
        """
        tr1, item = self._ledger_a()
        wac = get_valuation(item["id"], "WAC_RUNNING", tr1)
        # wac 100 -> 100; restock -> 303/3 = 101; usage 2 -> 303 - 202.
        assert wac["quantity_on_hand"] == 1
        assert wac["valuation_cents"] == 101
        fifo = get_valuation(item["id"], "FIFO", tr1)
        assert fifo["valuation_cents"] != wac["valuation_cents"], \
            "the two policies diverge on identical ledger data"

    def _ledger_b(self):
        """RESTOCK 3@100, RESTOCK 1@103, USAGE 2."""
        tr1 = make_trainer()
        item = create_supply_item(item_name="Bandages", category="FIRST_AID",
                                  unit="BOX", par_level=40,
                                  reorder_threshold=10)
        set_clock("2026-08-01T12:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=3,
                          unit_cost_cents=100,
                          occurred_at="2026-08-01T09:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=1,
                          unit_cost_cents=103,
                          occurred_at="2026-08-01T10:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="USAGE", quantity=2,
                          occurred_at="2026-08-01T11:00:00Z")
        return tr1, item

    def test_wac_running_per_transaction_rounding(self):
        """PRD §3.9: "a `RESTOCK` adds its quantity times its unit cost to
        the running value, and a `USAGE` or `WASTE` subtracts its quantity
        times the freshly recomputed unit cost; the valuation is the running
        value itself."

        Design: Difficulty/combinatorial_formula/wac_running_vs_exact_rounding_order
        """
        tr1, item = self._ledger_b()
        running = get_valuation(item["id"], "WAC_RUNNING", tr1)
        # 403/4 rounds half-up to 101 per transaction; 403 - 2*101 = 201.
        assert running["valuation_cents"] == 201

    def test_wac_exact_rounds_once_at_the_end(self):
        """PRD §3.9: "Under `WAC_EXACT`, the same flow is computed with exact
        rational arithmetic and a single round-half-up applied once at the
        very end."

        Design: Difficulty/combinatorial_formula/wac_running_vs_exact_rounding_order
        """
        tr1, item = self._ledger_b()
        exact = get_valuation(item["id"], "WAC_EXACT", tr1)
        # Exact: 403 - 2*(403/4) = 201.5 -> round_half_up = 202.
        assert exact["valuation_cents"] == 202
        running = get_valuation(item["id"], "WAC_RUNNING", tr1)
        assert running["valuation_cents"] != exact["valuation_cents"], \
            "rounding order is load-bearing"

    def test_fifo_multi_layer_consumption_oldest_first(self):
        """PRD §3.9: "replays the ledger in chronological order —
        `occurred_at` ascending, ties broken by creation order".
        PRD §3.9: "each `USAGE` or `WASTE` consumes layers oldest-first;
        each `ADJUSTMENT` pushes a layer priced at the most recent `RESTOCK`
        unit cost".

        Design: Corner/calculations/inventory_fifo_multi_layer_consumption
        """
        tr1 = make_trainer()
        item = create_supply_item(item_name="Gauze", category="FIRST_AID",
                                  unit="BOX", par_level=40,
                                  reorder_threshold=10)
        set_clock("2026-08-01T12:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=2,
                          unit_cost_cents=100,
                          occurred_at="2026-08-01T09:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=2,
                          unit_cost_cents=150,
                          occurred_at="2026-08-01T10:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="USAGE", quantity=3,
                          occurred_at="2026-08-01T11:00:00Z")
        fifo = get_valuation(item["id"], "FIFO", tr1)
        # USAGE 3 consumes 2@100 and 1@150; the 1@150 layer remains.
        assert fifo["quantity_on_hand"] == 1
        assert fifo["valuation_cents"] == 150
        wac = get_valuation(item["id"], "WAC_RUNNING", tr1)
        # wac after the second restock: 500/4 = 125; 500 - 3*125 = 125.
        assert wac["valuation_cents"] == 125

    def test_valuation_policy_is_a_closed_enum(self):
        """PRD §3.9: "under one of three policies selected by the `policy`
        parameter."
        PRD §2.9: "Field-shape validation — required fields present, enum
        values valid, date ranges sane".

        Design: Corner/endpoints/valuation_invalid_policy_rejected
        """
        tr1 = make_trainer()
        item = create_supply_item(par_level=30, reorder_threshold=10)
        resp = api_client.get_supply_item_valuation(item["id"], "LIFO",
                                                    trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestUsageAdjustmentConservation:
    """Difficulty instance inventory_usage_adjustment_conserves_stock_value."""

    def _setup_stocked_item(self):
        tr1 = make_trainer()
        item = create_supply_item(unit_cost_cents=200)
        set_clock("2026-08-01T12:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=5,
                          unit_cost_cents=200,
                          occurred_at="2026-08-01T09:00:00Z")
        return tr1, item

    def test_usage_then_adjustment_conserves_units(self):
        """PRD §3.9: "the ledger is append-only — there is no update and no
        delete ... the sign comes from the type, with `RESTOCK` and
        `ADJUSTMENT` adding and `USAGE` and `WASTE` subtracting".

        Design: Difficulty/compensating_invariant/inventory_usage_adjustment_conserves_stock_value
        """
        tr1, item = self._setup_stocked_item()
        assert get_item(item["id"])["current_stock"] == 5
        post_ledger_entry(item["id"], tr1, txn_type="USAGE", quantity=2,
                          occurred_at="2026-08-01T10:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="ADJUSTMENT", quantity=2,
                          occurred_at="2026-08-01T11:00:00Z",
                          reason="recount found misplaced rolls")
        after = get_item(item["id"])
        assert after["current_stock"] == 5, \
            "units conserved across the usage+adjustment pair"
        assert after["stock_status"] == "LOW_STOCK", \
            "5 units within 1..15 reads LOW_STOCK"

    def test_adjustment_layer_priced_at_last_restock_conserves_value(self):
        """PRD §3.9: "each `ADJUSTMENT` pushes a layer priced at the most
        recent `RESTOCK` unit cost — or zero cents if the item was never
        restocked; the valuation is the sum over remaining layers of quantity
        times unit cost, an exact integer number of cents."

        Design: Difficulty/compensating_invariant/inventory_usage_adjustment_conserves_stock_value
        """
        tr1, item = self._setup_stocked_item()
        before = get_valuation(item["id"], "FIFO", tr1)
        assert before["quantity_on_hand"] == 5
        assert before["valuation_cents"] == 1000
        post_ledger_entry(item["id"], tr1, txn_type="USAGE", quantity=2,
                          occurred_at="2026-08-01T10:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="ADJUSTMENT", quantity=2,
                          occurred_at="2026-08-01T11:00:00Z",
                          reason="recount found misplaced rolls")
        after = get_valuation(item["id"], "FIFO", tr1)
        assert after["valuation_cents"] == 1000, \
            "value conserved: the adjustment layers at the 200 restock cost"
