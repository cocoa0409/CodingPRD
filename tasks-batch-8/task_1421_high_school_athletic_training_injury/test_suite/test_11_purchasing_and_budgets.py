"""Restock ordering, budget commitment/realization, and reorder suggestions
(PRD §3.9)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_inventory_transaction,
    create_budget,
    create_order,
    create_supply_item,
    director_headers,
    get_budget_by_year,
    get_item,
    make_director,
    make_trainer,
    post_ledger_entry,
    set_clock,
    setup_approved_order,
    setup_submitted_order,
    submit_order,
    trainer_headers,
    validate_error,
    validate_success,
)


class TestOrderStateMachine:

    def test_out_of_order_and_terminal_transitions_rejected(self):
        """PRD §3.9: "Approval is the director's, and the checks run in the
        global order of §2.9: the order must be `SUBMITTED` (else
        `ERR_INVALID_STATE`)".
        PRD §3.9: "A trainer receives an `APPROVED` order (any other state:
        `ERR_INVALID_STATE`)".
        PRD §3.9: "Finally, a trainer may cancel an order from `DRAFT`,
        `SUBMITTED`, or `APPROVED` into `CANCELLED`; cancelling an `APPROVED`
        order releases its committed amount back to the budget —
        `committed_spend_cents` shrinks by the extended cost and
        `available_cents` is recomputed — as compensation for the earlier
        commit. `RECEIVED`, `REJECTED`, and `CANCELLED` are terminal."

        Design: Corner/state_machines/restock_invalid_transitions_rejected
        """
        tr1 = make_trainer()
        ad = make_director()
        create_budget(2026, 100000)
        item = create_supply_item(category="FIRST_AID", unit="EACH",
                                  par_level=20, reorder_threshold=5,
                                  unit_cost_cents=500)
        order = create_order(item["id"], tr1, quantity=4,
                             unit_cost_cents=500)
        assert order["status"] == "DRAFT"

        # Approve requires SUBMITTED; DRAFT rejects it.
        resp = api_client.approve_restock_order(order["id"],
                                                director_headers(ad))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        submit_order(order["id"], tr1)
        # Receive requires APPROVED; SUBMITTED rejects it.
        resp = api_client.receive_restock_order(order["id"],
                                                trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        approved = validate_success(api_client.approve_restock_order(
            order["id"], director_headers(ad)))
        assert approved["status"] == "APPROVED"
        cancelled = validate_success(api_client.cancel_restock_order(
            order["id"], trainer_headers(tr1)))
        assert cancelled["status"] == "CANCELLED"

        # CANCELLED is terminal for the receive edge.
        resp = api_client.receive_restock_order(order["id"],
                                                trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestBudgetFiscalGate:

    def test_approval_rejected_when_budget_cannot_cover(self):
        """PRD §3.9: "that budget's `available_cents` must cover the order's
        `extended_cost_cents` (else `ERR_BUDGET_EXCEEDED`, HTTP 402)".
        PRD §3.9: "The server computes `extended_cost_cents` as the quantity
        times the unit cost".

        Design: Corner/validations/budget_fiscal_gate_on_approval
        """
        tr1 = make_trainer()
        ad = make_director()
        create_budget(2026, 1000)
        item = create_supply_item(category="FIRST_AID", unit="EACH",
                                  par_level=20, reorder_threshold=5,
                                  unit_cost_cents=500)
        o1 = setup_submitted_order(item["id"], tr1, quantity=4,
                                   unit_cost_cents=500)
        assert o1["extended_cost_cents"] == 2000
        o2 = setup_submitted_order(item["id"], tr1, quantity=1,
                                   unit_cost_cents=500)

        resp = api_client.approve_restock_order(o1["id"],
                                                director_headers(ad))
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
        after = validate_success(api_client.get_restock_order(o1["id"],
                                                              ADMIN))
        assert after["status"] == "SUBMITTED", \
            "the rejected approval leaves the order SUBMITTED"

        approved = validate_success(api_client.approve_restock_order(
            o2["id"], director_headers(ad)))
        assert approved["status"] == "APPROVED", "500 fits within 1000"
        assert get_budget_by_year(2026)["available_cents"] == 500

    def test_duplicate_fiscal_year_rejected(self):
        """PRD §3.9: "the `fiscal_year` must be unique across budgets (a
        duplicate is rejected with `ERR_DUPLICATE_BUDGET_YEAR`)".
        PRD §3.9: "and `available_cents`, the total minus realized minus
        committed."

        Design: Corner/validations/duplicate_budget_year_rejected
        """
        b1 = create_budget(2026, 50000)
        assert b1["fiscal_year"] == 2026
        resp = api_client.create_supply_budget(
            {"fiscal_year": 2026, "total_budget_cents": 60000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BUDGET_YEAR)

        b2 = create_budget(2027, 60000)
        # No orders exist for 2027: realized and committed are both zero.
        assert b2["available_cents"] == 60000


class TestDiscontinuedItem:

    def test_restock_order_for_discontinued_item_rejected(self):
        """PRD §3.9: "ordering a discontinued item is rejected with
        `ERR_ITEM_DISCONTINUED`."

        Design: Corner/validations/restock_discontinued_item_rejected
        """
        tr1 = make_trainer()
        create_budget(2026, 50000)
        item = create_supply_item(item_name="Old Brace", category="EQUIPMENT",
                                  unit="EACH", par_level=10,
                                  reorder_threshold=2, unit_cost_cents=1500)
        patched = validate_success(api_client.patch_supply_item(
            item["id"], {"is_discontinued": True}, ADMIN))
        assert patched["is_discontinued"] is True

        resp = api_client.create_restock_order(
            {"supply_item_id": item["id"], "quantity": 5,
             "unit_cost_cents": 1500, "fiscal_year": 2026},
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_ITEM_DISCONTINUED)


class TestReceiptCascade:
    """Difficulty instance restock_receive_ledger_budget_cascade (2 tests)."""

    def _setup_approved_order(self):
        tr1 = make_trainer()
        ad = make_director()
        create_budget(2026, 100000)
        item = create_supply_item(item_name="Water Cooler",
                                  category="HYDRATION", unit="EACH",
                                  unit_cost_cents=500)
        order = setup_approved_order(item["id"], tr1, ad, quantity=20,
                                     unit_cost_cents=500)
        assert order["extended_cost_cents"] == 10000
        return tr1, ad, item, order

    def test_receipt_appends_restock_ledger_entry(self):
        """PRD §3.9: "A trainer receives an `APPROVED` order (any other
        state: `ERR_INVALID_STATE`), moving it to `RECEIVED` and appending a
        `RESTOCK` ledger entry that carries the order's quantity and unit
        cost, a `restock_order_id` back-reference, the current clock as
        `occurred_at`, and the receiver as `recorded_by_staff_id`."

        Design: Difficulty/transitive_cascade/restock_receive_ledger_budget_cascade
        """
        tr1, ad, item, order = self._setup_approved_order()
        received = validate_success(api_client.receive_restock_order(
            order["id"], trainer_headers(tr1)))
        assert received["status"] == "RECEIVED"

        rows = validate_success(api_client.list_inventory_transactions(
            trainer_headers(tr1), params={"restock_order_id": order["id"]}))
        assert len(rows) == 1
        txn = rows[0]
        assert_inventory_transaction(txn)
        assert txn["txn_type"] == "RESTOCK"
        assert txn["quantity"] == 20
        assert txn["unit_cost_cents"] == 500

        # Hop 2: the ledger append recomputes the item's stock fields.
        item_after = get_item(item["id"])
        assert item_after["current_stock"] == 20
        assert item_after["stock_status"] == "IN_STOCK", \
            "20 units sit above the threshold of 15"

    def test_receipt_moves_commitment_to_realized(self):
        """PRD §3.9: "That ledger append recomputes the item's
        `current_stock` and `stock_status`, while on the budget the extended
        cost leaves `committed_spend_cents` and lands in
        `realized_spend_cents`, with `available_cents` recomputed."

        Design: Difficulty/transitive_cascade/restock_receive_ledger_budget_cascade
        """
        tr1, ad, item, order = self._setup_approved_order()
        validate_success(api_client.receive_restock_order(
            order["id"], trainer_headers(tr1)))
        budget = get_budget_by_year(2026)
        assert budget["committed_spend_cents"] == 0
        assert budget["realized_spend_cents"] == 10000
        assert budget["available_cents"] == 90000


class TestApproveCancelConservation:
    """Difficulty instance order_approve_cancel_conserves_budget (2 tests)."""

    def _setup(self):
        tr1 = make_trainer()
        ad = make_director()
        budget = create_budget(2026, 10000)
        item = create_supply_item(item_name="Splints", category="FIRST_AID",
                                  unit="EACH", par_level=20,
                                  reorder_threshold=5, unit_cost_cents=500)
        order = setup_submitted_order(item["id"], tr1, quantity=4,
                                      unit_cost_cents=500)
        return tr1, ad, budget, order

    def test_approval_commits_spend(self):
        """PRD §3.9: "Approval stamps `approved_by_staff_id`, moves the order
        to `APPROVED`, and commits the spend: the budget's
        `committed_spend_cents` grows by the extended cost and
        `available_cents` is recomputed."

        Design: Difficulty/compensating_invariant/order_approve_cancel_conserves_budget
        """
        tr1, ad, budget, order = self._setup()
        assert budget["available_cents"] == 10000
        validate_success(api_client.approve_restock_order(
            order["id"], director_headers(ad)))
        after = get_budget_by_year(2026)
        assert after["committed_spend_cents"] == 2000
        assert after["available_cents"] == 8000

    def test_cancel_of_approved_order_releases_commitment(self):
        """PRD §3.9: "cancelling an `APPROVED` order releases its committed
        amount back to the budget — `committed_spend_cents` shrinks by the
        extended cost and `available_cents` is recomputed — as compensation
        for the earlier commit."

        Design: Difficulty/compensating_invariant/order_approve_cancel_conserves_budget
        """
        tr1, ad, budget, order = self._setup()
        validate_success(api_client.approve_restock_order(
            order["id"], director_headers(ad)))
        cancelled = validate_success(api_client.cancel_restock_order(
            order["id"], trainer_headers(tr1)))
        assert cancelled["status"] == "CANCELLED"
        after = get_budget_by_year(2026)
        assert after["committed_spend_cents"] == 0
        assert after["available_cents"] == 10000, \
            "approve+cancel conserves budget cents exactly"
        assert after["realized_spend_cents"] == 0


class TestReorderSuggestion:
    """Difficulty instance reorder_suggestion_pinned_evaluation_order and
    corner reorder_suggestion_without_budget_returns_zero."""

    def test_pinned_evaluation_order_with_committed_order(self):
        """PRD §3.9: "Second, take the inbound quantity as the sum of
        `quantity` over this item's `APPROVED` restock orders. Third, the
        deficit is `par_level` minus stock minus inbound, floored at zero...
        Sixth, the most the budget can afford is that available amount
        divided by the item's `unit_cost_cents`, rounded down to a whole
        unit. Seventh, the suggestion is the smaller of the deficit and the
        affordable quantity, again floored at zero."

        Design: Difficulty/combinatorial_formula/reorder_suggestion_pinned_evaluation_order
        """
        tr1 = make_trainer()
        ad = make_director()
        create_budget(2026, 14000)
        item = create_supply_item(item_name="Ice Packs", category="FIRST_AID",
                                  unit="EACH", unit_cost_cents=500)
        set_clock("2026-08-01T12:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=10,
                          unit_cost_cents=500,
                          occurred_at="2026-08-01T09:00:00Z")
        setup_approved_order(item["id"], tr1, ad, quantity=20,
                             unit_cost_cents=500)

        data = validate_success(api_client.get_reorder_suggestion(
            item["id"], trainer_headers(tr1)))
        assert data["current_stock"] == 10
        assert data["inbound_qty"] == 20, \
            "the APPROVED order counts as inbound before the deficit"
        assert data["deficit_qty"] == 20, "max(0, 50 - 10 - 20)"
        # committed (10000) already includes the order counted as inbound.
        assert data["available_budget_cents"] == 4000
        assert data["max_affordable_qty"] == 8, "floor(4000 / 500)"
        assert data["suggested_qty"] == 8, "min(deficit 20, affordable 8)"

    def test_pinned_order_available_includes_committed_and_clamps(self):
        """PRD §3.9: "Fifth, available budget is the budget's
        `total_budget_cents` minus its realized spend minus its committed
        spend — where committed spend already includes the `APPROVED` orders
        counted in step two."

        Design: Difficulty/combinatorial_formula/reorder_suggestion_pinned_evaluation_order
        """
        tr1 = make_trainer()
        ad = make_director()
        create_budget(2026, 14000)
        item = create_supply_item(item_name="Ice Packs", category="FIRST_AID",
                                  unit="EACH", unit_cost_cents=500)
        set_clock("2026-08-01T12:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=10,
                          unit_cost_cents=500,
                          occurred_at="2026-08-01T09:00:00Z")
        setup_approved_order(item["id"], tr1, ad, quantity=20,
                             unit_cost_cents=500)
        budget_after = get_budget_by_year(2026)
        assert budget_after["committed_spend_cents"] == 10000

        data = validate_success(api_client.get_reorder_suggestion(
            item["id"], trainer_headers(tr1)))
        # The same APPROVED order is inbound stock AND committed budget;
        # suggestion = min(deficit 20, floor(4000/500)) = 8.
        assert data["suggested_qty"] == 8
        assert data["available_budget_cents"] == 4000

    def test_missing_budget_yields_zero_suggestion(self):
        """PRD §3.9: "Fourth, find the `SupplyBudget` whose `fiscal_year`
        matches the logical clock's current year; if none exists, treat
        available budget as zero."

        Design: Corner/calculations/reorder_suggestion_without_budget_returns_zero
        """
        tr1 = make_trainer()
        item = create_supply_item(item_name="Tape", par_level=30,
                                  reorder_threshold=10, unit_cost_cents=200)
        set_clock("2026-08-01T12:00:00Z")
        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=5,
                          unit_cost_cents=200,
                          occurred_at="2026-08-01T09:00:00Z")
        data = validate_success(api_client.get_reorder_suggestion(
            item["id"], trainer_headers(tr1)))
        assert data["deficit_qty"] == 25, "30 - 5 - 0 inbound"
        assert data["available_budget_cents"] == 0, \
            "no budget record for the clock year"
        assert data["max_affordable_qty"] == 0
        assert data["suggested_qty"] == 0
