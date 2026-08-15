"""Register operations: sale totals, ownership/state gates, and void cascades."""
from test_helpers import (
    ApiErrorId,
    MGR,
    PRICER,
    begin_sort,
    close_cycle_and_get_next,
    close_till_session,
    count_session,
    create_batch,
    create_batch_with_items,
    create_donor,
    create_cycle,
    create_floored_item,
    create_guideline,
    create_sold_item,
    create_worker,
    get_success_data,
    make_cashier_headers,
    open_till_session,
    price_item,
    ring_sale,
    run_markdown,
    to_floor_item,
    triage_item,
    validate_error,
    validate_paginated,
    validate_success,
)


def _floor_value_cents(api):
    """Sum of current_price_cents over everything currently ON_FLOOR."""
    data, _meta = validate_paginated(api.list_items(MGR, params={"status": "ON_FLOOR"}))
    return sum(item["current_price_cents"] for item in data)


class TestSaleTotals:
    def test_sale_total_mixed_tenders(self, api):
        """PRD 3.6: "The sale's `total_cents` is the sum of the lines'
        `current_price_cents`, with no further rounding since those prices are
        already markdown-rounded, and `line_count` records the number of lines."
        PRD 3.6: "adds the total to the session's `cash_sales_cents` for a CASH sale
        or `card_sales_cents` for a CARD sale; and recomputes `expected_cash_cents`
        as the opening float plus the cash-sales total."
        PRD 3.3: "publishing a guideline for a category retires the category's prior
        `ACTIVE` guideline — the old row's `status` becomes `RETIRED`, the new row's
        `supersedes_id` points back at the old one, and `version_no` continues the
        per-category sequence (the first guideline ever published for a category is
        1)"

        Design: Corner/calculations/sale_total_mixed_tenders
        """
        g1 = create_guideline("HOUSEWARES", 200)
        donor, batch, items = create_batch_with_items(
            [
                {"category": "HOUSEWARES", "condition": "POOR"},
                {"category": "HOUSEWARES", "condition": "FAIR"},
                {"category": "CLOTHING", "condition": "GOOD"},
            ]
        )
        begin_sort(batch["id"])
        for item in items:
            triage_item(item["id"], "SALABLE")
        create_guideline("CLOTHING", 2000)

        priced_a = price_item(items[0]["id"])   # under v1: 200 x 0.35 = 70 -> 100
        assert priced_a["base_price_cents"] == 100, "clamped to the 100-cent floor"
        g2 = create_guideline("HOUSEWARES", 500)
        priced_b = price_item(items[1]["id"])   # under v2: 500 x 0.6 = 300
        priced_c = price_item(items[2]["id"])   # 2000 x 0.8 = 1600
        assert priced_b["base_price_cents"] == 300
        assert priced_c["base_price_cents"] == 1600

        cycle = create_cycle()
        for item in items:
            to_floor_item(item["id"])
        cashier = create_worker("W Cash", "STAFF")
        session = open_till_session(cashier["id"], 5000)

        sale = ring_sale(session["id"], cashier["id"],
                         [items[0]["id"], items[1]["id"], items[2]["id"]], "CARD")
        assert sale["total_cents"] == 2000, "100 + 300 + 1600"
        assert sale["line_count"] == 3
        assert sale["status"] == "COMPLETED"

        session_after = validate_success(api.get_till_session(session["id"], MGR))
        assert session_after["card_sales_cents"] == 2000
        assert session_after["cash_sales_cents"] == 0
        assert session_after["expected_cash_cents"] == 5000, (
            "CARD sales never move the expected cash figure"
        )

        g1_after = validate_success(api.get_guideline(g1["id"], MGR))
        g2_after = validate_success(api.get_guideline(g2["id"], MGR))
        assert g1_after["status"] == "RETIRED"
        assert g2_after["status"] == "ACTIVE"
        assert g2_after.get("supersedes_id") == g1["id"]
        assert g2_after["version_no"] == 2


class TestSalePreconditions:
    def test_sale_empty_lines_rejected(self, api):
        """PRD 2.9: "Request schema — ... required arrays non-empty (`item_ids` on a
        sale, `allocations` on a transfer, `adjustments` on a revalue) ... —
        violations yield `ERR_INVALID_REQUEST`."

        Design: Corner/validations/sale_empty_lines_rejected
        """
        cashier = create_worker("W Cash", "STAFF")
        session = open_till_session(cashier["id"], 1000)
        resp = api.create_sale(
            {"till_session_id": session["id"], "item_ids": [], "payment_method": "CASH"},
            make_cashier_headers(cashier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_sale_line_not_on_floor(self, api):
        """PRD 3.6: "Every listed item must be `ON_FLOOR`; anything else — including
        an item `ON_HOLD` — fails with `ERR_ITEM_INVALID_STATE`."

        Design: Corner/validations/sale_line_not_on_floor
        """
        create_guideline("CLOTHING", 2000)
        donor, batch, items = create_batch_with_items(
            [
                {"category": "CLOTHING", "condition": "GOOD"},
                {"category": "CLOTHING", "condition": "GOOD"},
            ]
        )
        begin_sort(batch["id"])
        for item in items:
            triage_item(item["id"], "SALABLE")
        for item in items:
            price_item(item["id"])
        cycle = create_cycle()
        to_floor_item(items[1]["id"])
        get_success_data(api.hold_item(items[1]["id"], PRICER))

        cashier = create_worker("W Cash", "STAFF")
        session = open_till_session(cashier["id"], 5000)
        headers = make_cashier_headers(cashier["id"])

        # Item A is PRICED (never floored); item B is ON_HOLD. Neither is sellable.
        resp_a = api.create_sale(
            {"till_session_id": session["id"], "item_ids": [items[0]["id"]],
             "payment_method": "CASH"},
            headers,
        )
        validate_error(resp_a, ApiErrorId.ERR_ITEM_INVALID_STATE)
        resp_b = api.create_sale(
            {"till_session_id": session["id"], "item_ids": [items[1]["id"]],
             "payment_method": "CASH"},
            headers,
        )
        validate_error(resp_b, ApiErrorId.ERR_ITEM_INVALID_STATE)

        session_after = validate_success(api.get_till_session(session["id"], MGR))
        assert session_after["cash_sales_cents"] == 0
        assert session_after["expected_cash_cents"] == 5000


class TestSaleSessionGate:
    def test_sale_requires_owned_open_session(self, api):
        """PRD 3.6: "The named session must be OPEN and owned by the acting cashier:
        a sale attempted on a session in any other state fails with
        `ERR_TILL_INVALID_STATE`, and a cashier ringing on another worker's session
        fails with `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Difficulty/cross_entity_state_dependency/sale_requires_owned_open_session
        """
        create_guideline("CLOTHING", 2000, 1.0)
        donor, batch, items = create_batch_with_items(
            [
                {"category": "CLOTHING", "condition": "GOOD"},
                {"category": "CLOTHING", "condition": "GOOD"},
            ]
        )
        begin_sort(batch["id"])
        for item in items:
            triage_item(item["id"], "SALABLE")
        for item in items:
            price_item(item["id"])
        cycle = create_cycle()
        for item in items:
            to_floor_item(item["id"])

        w1 = create_worker("W One", "STAFF")
        w2 = create_worker("W Two", "STAFF")
        session = open_till_session(w1["id"], 3000)

        # Another cashier's OPEN session rejects the sale.
        resp = api.create_sale(
            {"till_session_id": session["id"], "item_ids": [items[0]["id"]],
             "payment_method": "CASH"},
            make_cashier_headers(w2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

        # The owning cashier rings it.
        sale = ring_sale(session["id"], w1["id"], [items[0]["id"]], "CASH")
        assert sale["total_cents"] == 1600
        assert sale["status"] == "COMPLETED"

        # After the count the session is RECONCILED, so even the owner cannot ring.
        count_session(session["id"], 4600)
        resp2 = api.create_sale(
            {"till_session_id": session["id"], "item_ids": [items[1]["id"]],
             "payment_method": "CASH"},
            make_cashier_headers(w1["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_TILL_INVALID_STATE)
        item2 = validate_success(api.get_item(items[1]["id"], MGR))
        assert item2["status"] == "ON_FLOOR", "rejected sale leaves the item untouched"

    def test_void_after_count_cashier_blocked_manager_allowed(self, api):
        """PRD 3.6: "A `Cashier` may void only while the sale's session is still OPEN
        and their own — violations surface as `ERR_TILL_INVALID_STATE` or
        `ERR_FORBIDDEN_OWNERSHIP` — while a `StoreManager` may void so long as the
        session is anything short of CLOSED."

        Design: Difficulty/cross_entity_state_dependency/sale_requires_owned_open_session
        """
        ctx = create_sold_item(base_cents=2000, opening_float_cents=5000)
        session = ctx["session"]
        sale = ctx["sale"]
        cashier = ctx["cashier"]
        item_id = ctx["item"]["id"]

        count_session(session["id"], 6600)  # 5000 float + 1600 sale -> even count
        # Cashier void requires the session still OPEN.
        resp = api.void_sale(sale["id"], {}, make_cashier_headers(cashier["id"]))
        validate_error(resp, ApiErrorId.ERR_TILL_INVALID_STATE)

        # A manager may void while the session is short of CLOSED (same UTC day).
        voided = validate_success(api.void_sale(sale["id"], {}, MGR))
        assert voided["status"] == "VOIDED"
        item = validate_success(api.get_item(item_id, MGR))
        assert item["status"] == "ON_FLOOR"
        session_after = validate_success(api.get_till_session(session["id"], MGR))
        assert session_after["cash_sales_cents"] == 0
        assert session_after["expected_cash_cents"] == 5000


class TestVoidRestoreCascade:
    def test_void_restore_cascade(self, api):
        """PRD 3.6: "Its compensation cascade then runs: every line item returns
        `SOLD` → `ON_FLOOR` with `current_price_cents` and `markdown_round` restored
        exactly as they stood at sale time (both are immutable while an item is
        SOLD) and its `sale_id` cleared; each restored item's batch `sold_item_count`
        drops by one and that batch's `version` bumps; the session's cash or card
        total falls by the sale's `total_cents` according to its payment method; and
        `expected_cash_cents` is recomputed."

        Design: Difficulty/transitive_cascade/void_restore_cascade
        """
        ctx = create_sold_item(base_cents=2000, opening_float_cents=5000)
        batch_id = ctx["batch"]["id"]
        item_id = ctx["item"]["id"]
        session_id = ctx["session"]["id"]

        mid_batch = validate_success(api.get_batch(batch_id, MGR))
        assert mid_batch["sold_item_count"] == 1

        voided = validate_success(
            api.void_sale(ctx["sale"]["id"], {"reason": "customer return"},
                          make_cashier_headers(ctx["cashier"]["id"]))
        )
        assert voided["status"] == "VOIDED"

        item = validate_success(api.get_item(item_id, MGR))
        assert item["status"] == "ON_FLOOR"
        assert item["current_price_cents"] == 1600
        assert item["markdown_round"] == 0, "restored, not reset"
        assert item.get("sale_id") is None

        batch_after = validate_success(api.get_batch(batch_id, MGR))
        assert batch_after["sold_item_count"] == 0

        session_after = validate_success(api.get_till_session(session_id, MGR))
        assert session_after["cash_sales_cents"] == 0
        assert session_after["expected_cash_cents"] == 5000

    def test_void_restore_multi_batch_sale(self, api):
        """PRD 3.6: "The void records `voided_by_user_id`, `voided_at`, and an
        optional `reason` stored as the sale's `void_reason`."
        PRD 3.6: "every line item returns `SOLD` → `ON_FLOOR` with
        `current_price_cents` and `markdown_round` restored exactly as they stood at
        sale time (both are immutable while an item is SOLD) and its `sale_id`
        cleared; each restored item's batch `sold_item_count` drops by one and that
        batch's `version` bumps"

        Design: Difficulty/transitive_cascade/void_restore_cascade
        """
        create_guideline("CLOTHING", 2000, 1.0)
        donor, batch1, items1 = create_batch_with_items(
            [{"category": "CLOTHING", "condition": "GOOD"}]
        )
        _d2, batch2, items2 = create_batch_with_items(
            [{"category": "CLOTHING", "condition": "GOOD"}], donor=donor
        )
        for batch, items in ((batch1, items1), (batch2, items2)):
            begin_sort(batch["id"])
            triage_item(items[0]["id"], "SALABLE")
            price_item(items[0]["id"])
        cycle = create_cycle()
        to_floor_item(items1[0]["id"])
        to_floor_item(items2[0]["id"])

        cashier = create_worker("W Cash", "STAFF")
        session = open_till_session(cashier["id"], 5000)
        sale = ring_sale(session["id"], cashier["id"],
                         [items1[0]["id"], items2[0]["id"]], "CASH")
        assert sale["total_cents"] == 3200

        voided = validate_success(
            api.void_sale(sale["id"], {"reason": "customer return"},
                          make_cashier_headers(cashier["id"]))
        )
        assert voided["status"] == "VOIDED"
        assert voided.get("voided_by_user_id") == cashier["id"]
        assert voided.get("voided_at"), "void stamps the clock"
        assert voided.get("void_reason") == "customer return"

        for item_id in (items1[0]["id"], items2[0]["id"]):
            item = validate_success(api.get_item(item_id, MGR))
            assert item["status"] == "ON_FLOOR"
            assert item["current_price_cents"] == 1600
            assert item.get("sale_id") is None
        for batch_id in (batch1["id"], batch2["id"]):
            batch_after = validate_success(api.get_batch(batch_id, MGR))
            assert batch_after["sold_item_count"] == 0


class TestVoidConservesExpectedCash:
    def test_sale_void_conserves_expected_cash(self, api):
        """PRD 3.6: "adds the total to the session's `cash_sales_cents` for a CASH
        sale or `card_sales_cents` for a CARD sale; and recomputes
        `expected_cash_cents` as the opening float plus the cash-sales total. Only
        COMPLETED sales feed these session totals — a voided sale's total is fully
        removed."

        Design: Difficulty/compensating_invariant/sale_void_conserves_expected_cash
        """
        ctx = create_floored_item("CLOTHING", "GOOD", 2000)
        cashier = create_worker("W Cash", "STAFF")
        session = open_till_session(cashier["id"], 5000)
        before = validate_success(api.get_till_session(session["id"], MGR))
        assert before["expected_cash_cents"] == 5000, "float only"

        sale = ring_sale(session["id"], cashier["id"], [ctx["item"]["id"]], "CASH")
        during = validate_success(api.get_till_session(session["id"], MGR))
        assert during["cash_sales_cents"] == 1600
        assert during["expected_cash_cents"] == 6600

        validate_success(
            api.void_sale(sale["id"], {}, make_cashier_headers(cashier["id"]))
        )
        after = validate_success(api.get_till_session(session["id"], MGR))
        assert after["cash_sales_cents"] == 0
        assert after["expected_cash_cents"] == 5000, (
            "the void must return expected cash exactly to its pre-sale value"
        )
        assert after["status"] == "OPEN", "the session itself is untouched"

    def test_card_sale_void_leaves_expected_cash_untouched(self, api):
        """PRD 3.6: "adds the total to the session's `cash_sales_cents` for a CASH
        sale or `card_sales_cents` for a CARD sale; and recomputes
        `expected_cash_cents` as the opening float plus the cash-sales total. Only
        COMPLETED sales feed these session totals — a voided sale's total is fully
        removed."

        Design: Difficulty/compensating_invariant/sale_void_conserves_expected_cash
        """
        ctx = create_floored_item("CLOTHING", "GOOD", 2000)
        cashier = create_worker("W Cash", "STAFF")
        session = open_till_session(cashier["id"], 5000)

        sale = ring_sale(session["id"], cashier["id"], [ctx["item"]["id"]], "CARD")
        during = validate_success(api.get_till_session(session["id"], MGR))
        assert during["card_sales_cents"] == 1600
        assert during["cash_sales_cents"] == 0
        assert during["expected_cash_cents"] == 5000, "CARD never moves expected cash"

        validate_success(
            api.void_sale(sale["id"], {}, make_cashier_headers(cashier["id"]))
        )
        after = validate_success(api.get_till_session(session["id"], MGR))
        assert after["card_sales_cents"] == 0, "the voided CARD total is fully removed"
        assert after["cash_sales_cents"] == 0
        assert after["expected_cash_cents"] == 5000


class TestVoidConservesFloorInventory:
    def test_sale_void_conserves_floor_inventory(self, api):
        """PRD 3.6: "every line item returns `SOLD` → `ON_FLOOR` with
        `current_price_cents` and `markdown_round` restored exactly as they stood at
        sale time (both are immutable while an item is SOLD) and its `sale_id`
        cleared"

        Design: Difficulty/compensating_invariant/sale_void_conserves_floor_inventory
        """
        create_guideline("CLOTHING", 2000, 1.0)
        donor, batch, items = create_batch_with_items(
            [
                {"category": "CLOTHING", "condition": "GOOD"},
                {"category": "CLOTHING", "condition": "GOOD"},
            ]
        )
        begin_sort(batch["id"])
        for item in items:
            triage_item(item["id"], "SALABLE")
        for item in items:
            price_item(item["id"])
        cycle1 = create_cycle()
        for item in items:
            to_floor_item(item["id"])

        # Age both items one markdown round: 1600 -> 1200.
        _closed, cycle2 = close_cycle_and_get_next(cycle1["id"])
        run_markdown(cycle2["id"])
        assert _floor_value_cents(api) == 2400, "two items at 1200 each"

        cashier = create_worker("W Cash", "STAFF")
        session = open_till_session(cashier["id"], 5000)
        sale = ring_sale(session["id"], cashier["id"], [items[0]["id"]], "CASH")
        assert sale["total_cents"] == 1200, "sold at the marked-down price"
        assert _floor_value_cents(api) == 1200, "only item B remains on the floor"

        validate_success(
            api.void_sale(sale["id"], {}, make_cashier_headers(cashier["id"]))
        )
        assert _floor_value_cents(api) == 2400, "floor valuation restored exactly"

        item = validate_success(api.get_item(items[0]["id"], MGR))
        assert item["status"] == "ON_FLOOR"
        assert item["current_price_cents"] == 1200, "NOT reset to the 1600 base"
        assert item["markdown_round"] == 1, "markdown round is restored, not reset"
        assert item.get("sale_id") is None

    def test_multi_line_void_restores_markdown_prices(self, api):
        """PRD 3.6: "every line item returns `SOLD` → `ON_FLOOR` with
        `current_price_cents` and `markdown_round` restored exactly as they stood at
        sale time (both are immutable while an item is SOLD) and its `sale_id`
        cleared"

        Design: Difficulty/compensating_invariant/sale_void_conserves_floor_inventory
        """
        create_guideline("CLOTHING", 2000, 1.0)
        donor, batch, items = create_batch_with_items(
            [
                {"category": "CLOTHING", "condition": "GOOD"},
                {"category": "CLOTHING", "condition": "GOOD"},
            ]
        )
        begin_sort(batch["id"])
        for item in items:
            triage_item(item["id"], "SALABLE")
        for item in items:
            price_item(item["id"])
        cycle1 = create_cycle()
        for item in items:
            to_floor_item(item["id"])
        _closed, cycle2 = close_cycle_and_get_next(cycle1["id"])
        run_markdown(cycle2["id"])

        cashier = create_worker("W Cash", "STAFF")
        session = open_till_session(cashier["id"], 5000)
        sale = ring_sale(session["id"], cashier["id"],
                         [items[0]["id"], items[1]["id"]], "CASH")
        assert sale["total_cents"] == 2400
        assert _floor_value_cents(api) == 0

        validate_success(
            api.void_sale(sale["id"], {}, make_cashier_headers(cashier["id"]))
        )
        assert _floor_value_cents(api) == 2400
        for item_id in (items[0]["id"], items[1]["id"]):
            item = validate_success(api.get_item(item_id, MGR))
            assert item["status"] == "ON_FLOOR"
            assert item["current_price_cents"] == 1200
            assert item["markdown_round"] == 1
            assert item.get("sale_id") is None


class TestVoidErrorPrecedence:
    def test_second_void_after_session_close_reports_state(self, api):
        """PRD 2.9: "A void attempted on a sale that is already VOIDED reports
        `ERR_SALE_INVALID_STATE` even when the void window has also closed, because
        the state tier outranks the temporal tier."

        Design: Difficulty/priority_pair_validation_conflict/void_state_beats_temporal
        """
        ctx = create_sold_item(base_cents=2000, opening_float_cents=5000)
        sale_id = ctx["sale"]["id"]
        session_id = ctx["session"]["id"]
        cashier_id = ctx["cashier"]["id"]

        validate_success(api.void_sale(sale_id, {}, make_cashier_headers(cashier_id)))
        count_session(session_id, 5000)   # float only after the void
        close_till_session(session_id)

        # The sale is VOIDED *and* the session is CLOSED; the state error must win.
        resp = api.void_sale(sale_id, {}, MGR)
        validate_error(resp, ApiErrorId.ERR_SALE_INVALID_STATE)
        sale = validate_success(api.get_sale(sale_id, MGR))
        assert sale["status"] == "VOIDED", "no side effects fired on the rejection"

    def test_double_void_same_day_rejected(self, api):
        """PRD 3.6: "A void compensates a COMPLETED sale, moving it to `VOIDED`;
        attempting one on a sale that is not COMPLETED fails with
        `ERR_SALE_INVALID_STATE`, and this state check outranks the window check
        below (§2.9)."

        Design: Difficulty/priority_pair_validation_conflict/void_state_beats_temporal
        """
        ctx = create_sold_item(base_cents=2000, opening_float_cents=5000)
        sale_id = ctx["sale"]["id"]
        cashier_id = ctx["cashier"]["id"]

        validate_success(api.void_sale(sale_id, {}, make_cashier_headers(cashier_id)))
        # Session still OPEN and same UTC day: only the state precondition can fail.
        resp = api.void_sale(sale_id, {}, make_cashier_headers(cashier_id))
        validate_error(resp, ApiErrorId.ERR_SALE_INVALID_STATE)
        sale = validate_success(api.get_sale(sale_id, MGR))
        assert sale["status"] == "VOIDED"

    def test_void_window_closed_after_session_close(self, api):
        """PRD 3.6: "Independently, the void window requires the clock's UTC date to
        equal the sale's `created_at` UTC date and the session to be not CLOSED; a
        void attempted on a later UTC date, or after the session has closed, fails
        with `ERR_SALE_VOID_WINDOW_CLOSED`."

        Design: Corner/validations/void_window_closed_after_session_close
        """
        ctx = create_sold_item(base_cents=2000, opening_float_cents=5000)
        sale_id = ctx["sale"]["id"]
        session_id = ctx["session"]["id"]
        item_id = ctx["item"]["id"]

        count_session(session_id, 6600)  # even count: 5000 float + 1600 sale
        close_till_session(session_id)

        # The sale is still COMPLETED, so the temporal window is the failing rule.
        resp = api.void_sale(sale_id, {}, MGR)
        validate_error(resp, ApiErrorId.ERR_SALE_VOID_WINDOW_CLOSED)
        sale = validate_success(api.get_sale(sale_id, MGR))
        assert sale["status"] == "COMPLETED"
        item = validate_success(api.get_item(item_id, MGR))
        assert item["status"] == "SOLD"
