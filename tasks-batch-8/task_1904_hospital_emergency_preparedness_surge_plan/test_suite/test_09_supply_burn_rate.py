"""Supply cache ledger: burn-rate rounding order, window filtering, reorder
threshold, ledger reconciliation, and the append-only ledger exception."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_stock_transaction,
    assert_supply_item,
    create_stock_transaction_payload,
    create_supply_item,
    post_stock,
    setup_item_under_yellow_tier,
    validate_error,
    validate_success,
)

LC = TEST_USERS["logistics_chief_headers"]


class TestPinnedRoundingOrder:
    def test_observed_then_projected_round_half_up_order(self, api):
        """PRD §3.6: "The backward-looking `observed_daily_burn_rate` uses a
        trailing window of 168 hours, that is, seven days, ending at the current
        logical clock: sum the `quantity` of every `ISSUE` entry for the item whose
        `occurred_at` falls at or after the instant 168 hours before now and
        strictly before now, subtract the summed `quantity` of every `RETURN` entry
        in the same window — receipts and adjustments never enter the window —
        divide the net by seven, and round half-up to four decimal places."
        PRD §3.6: "The rounding order is pinned — the observed rate is rounded
        first, then multiplied by the multiplier, then the product is rounded
        half-up to four decimal places — so an identical ledger under a `YELLOW`
        or worse posture always yields a strictly higher projected rate than
        observed."

        Design: Difficulty/combinatorial_formula/burn_rate_round_then_multiply_order
        """
        item, _incident = setup_item_under_yellow_tier()
        data = validate_success(api.get_supply_item(item["id"], LC))
        assert_supply_item(data)
        assert data["observed_daily_burn_rate"] == pytest.approx(0.4286, abs=1e-9), (
            "round_half_up(3/7, 4)"
        )
        assert data["projected_daily_burn_rate"] == pytest.approx(0.5358, abs=1e-9), (
            "round_half_up(0.4286 * 1.25, 4) — the unpinned multiply-first order "
            "would give 0.5357"
        )

    def test_days_of_supply_and_reorder_flag_under_projection(self, api):
        """PRD §3.6: "`days_of_supply` is `quantity_on_hand` divided by
        `projected_daily_burn_rate`, floored to a whole number of days, and is null
        whenever the projected rate is zero. `below_reorder_level` is true exactly
        when `days_of_supply` is not null and is strictly less than
        `reorder_min_days` — an item sitting precisely at its floor is not below
        reorder — and is false whenever `days_of_supply` is null."

        Design: Difficulty/combinatorial_formula/burn_rate_round_then_multiply_order
        """
        item, _incident = setup_item_under_yellow_tier()
        data = validate_success(api.get_supply_item(item["id"], LC))
        assert data["quantity_on_hand"] == 7, "10 received − 3 issued"
        assert data["days_of_supply"] == 13, "floor(7 / 0.5358) = floor(13.0653...)"
        assert data["below_reorder_level"] is False, "13 < 13 is false (strict)"


class TestStockConservation:
    def _item_with_receipt(self):
        item = create_supply_item(item_name="IV kits", category="OTHER_SUPPLY",
                                  unit="each", reorder_min_days=3)
        post_stock(item["id"], "RECEIVE", 10, "2026-07-30T09:00:00Z")
        return item

    def test_issue_then_return_conserves_quantity_on_hand(self, api):
        """PRD §3.6: "The item's `quantity_on_hand` is recomputed synchronously on
        every entry: a receipt adds the quantity, an issue subtracts it, a return
        adds it back, and an adjustment resets the on-hand figure to the stated
        absolute value."

        Design: Difficulty/compensating_invariant/stock_issue_then_return_conserves_quantity_on_hand
        """
        item = self._item_with_receipt()
        q0 = validate_success(api.get_supply_item(item["id"], LC))["quantity_on_hand"]
        assert q0 == 10

        post_stock(item["id"], "ISSUE", 4, "2026-07-30T10:00:00Z")
        q1 = validate_success(api.get_supply_item(item["id"], LC))["quantity_on_hand"]
        assert q1 == 6, "after ISSUE 4"

        post_stock(item["id"], "RETURN", 4, "2026-07-30T11:00:00Z")
        q2 = validate_success(api.get_supply_item(item["id"], LC))["quantity_on_hand"]
        assert q2 == q0, "RETURN 4 restores the pre-issue value: no drift"

    def test_issue_return_pair_nets_to_zero_burn_and_null_days(self, api):
        """PRD §3.6: "sum the `quantity` of every `ISSUE` entry for the item whose
        `occurred_at` falls at or after the instant 168 hours before now and
        strictly before now, subtract the summed `quantity` of every `RETURN` entry
        in the same window — receipts and adjustments never enter the window —
        divide the net by seven, and round half-up to four decimal places."
        PRD §3.6: "`days_of_supply` is `quantity_on_hand` divided by
        `projected_daily_burn_rate`, floored to a whole number of days, and is null
        whenever the projected rate is zero."

        Design: Difficulty/compensating_invariant/stock_issue_then_return_conserves_quantity_on_hand
        """
        item = self._item_with_receipt()
        post_stock(item["id"], "ISSUE", 4, "2026-07-30T10:00:00Z")
        post_stock(item["id"], "RETURN", 4, "2026-07-30T11:00:00Z")

        data = validate_success(api.get_supply_item(item["id"], LC))
        assert data["observed_daily_burn_rate"] == pytest.approx(0.0, abs=1e-9), (
            "4 issued − 4 returned nets to zero inside the window"
        )
        assert data["days_of_supply"] is None, (
            "zero projected burn ⇒ days_of_supply is null, not infinity or 0"
        )


class TestLedgerShape:
    def test_stock_transaction_immutable_common_fields_false(self, api):
        """PRD §2.4: "The single exception is the `StockTransaction` ledger. Ledger
        entries are immutable and append-only: a stock transaction carries `id` and
        `created_at` only, and both `updated_at` and `version` are absent from it."

        Design: Corner/entities/stock_transaction_immutable_common_fields_false
        """
        item = create_supply_item(item_name="Gauze", category="OTHER_SUPPLY",
                                  unit="each", reorder_min_days=2)
        tx = post_stock(item["id"], "RECEIVE", 5, "2026-07-30T09:00:00Z")
        assert_stock_transaction(tx)
        assert "version" not in tx and "updated_at" not in tx

        reread = validate_success(api.get_stock_transaction(tx["id"], LC))
        assert_stock_transaction(reread)


class TestBurnWindowFiltering:
    def test_burn_rate_window_excludes_receives_adjusts_and_out_of_window_issues(self, api):
        """PRD §3.6: "The backward-looking `observed_daily_burn_rate` uses a
        trailing window of 168 hours, that is, seven days, ending at the current
        logical clock: sum the `quantity` of every `ISSUE` entry for the item whose
        `occurred_at` falls at or after the instant 168 hours before now and
        strictly before now, subtract the summed `quantity` of every `RETURN` entry
        in the same window — receipts and adjustments never enter the window —
        divide the net by seven, and round half-up to four decimal places."
        PRD §3.6: "The item's `quantity_on_hand` is recomputed synchronously on
        every entry: a receipt adds the quantity, an issue subtracts it, a return
        adds it back, and an adjustment resets the on-hand figure to the stated
        absolute value."

        Design: Corner/calculations/burn_rate_window_excludes_receives_adjusts_and_out_of_window_issues
        """
        item = create_supply_item(item_name="Saline bags", category="MEDICATION",
                                  unit="each", reorder_min_days=100)
        post_stock(item["id"], "RECEIVE", 200, "2026-07-26T09:00:00Z")
        post_stock(item["id"], "ISSUE", 100, "2026-07-20T10:00:00Z")  # outside window
        post_stock(item["id"], "ISSUE", 7, "2026-07-30T10:00:00Z")    # inside window

        data = validate_success(api.get_supply_item(item["id"], LC))
        assert data["quantity_on_hand"] == 93, "200 − 100 − 7: all ledger types move stock"
        assert data["observed_daily_burn_rate"] == pytest.approx(1.0, abs=1e-9), (
            "only the in-window ISSUE of 7 counts; 7/7"
        )
        assert data["projected_daily_burn_rate"] == pytest.approx(1.0, abs=1e-9), (
            "no ACTIVATED incident ⇒ multiplier 1.0"
        )
        assert data["days_of_supply"] == 93
        assert data["below_reorder_level"] is True, "93 < 100"

    def test_days_of_supply_null_when_burn_zero(self, api):
        """PRD §3.6: "`days_of_supply` is `quantity_on_hand` divided by
        `projected_daily_burn_rate`, floored to a whole number of days, and is null
        whenever the projected rate is zero. `below_reorder_level` is true exactly
        when `days_of_supply` is not null and is strictly less than
        `reorder_min_days` — an item sitting precisely at its floor is not below
        reorder — and is false whenever `days_of_supply` is null."

        Design: Corner/calculations/days_of_supply_null_when_burn_zero
        """
        item = create_supply_item(item_name="Burn gowns", category="PPE", unit="each",
                                  reorder_min_days=1)
        post_stock(item["id"], "RECEIVE", 5, "2026-07-30T09:00:00Z")

        data = validate_success(api.get_supply_item(item["id"], LC))
        assert data["observed_daily_burn_rate"] == pytest.approx(0.0, abs=1e-9)
        assert data["days_of_supply"] is None
        assert data["below_reorder_level"] is False


class TestLedgerGuards:
    def test_issue_exceeding_stock_rejected(self, api):
        """PRD §3.6: "An issue whose `quantity` exceeds the item's current
        `quantity_on_hand` is rejected with `ERR_INSUFFICIENT_STOCK`."

        Design: Corner/validations/issue_exceeding_stock_rejected
        """
        item = create_supply_item(item_name="Splints", category="OTHER_SUPPLY",
                                  unit="each", reorder_min_days=1)
        post_stock(item["id"], "RECEIVE", 3, "2026-07-30T09:00:00Z")

        resp = api.create_stock_transaction(
            create_stock_transaction_payload(item["id"], "ISSUE", 5,
                                             "2026-07-30T10:00:00Z"),
            LC,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)
        data = validate_success(api.get_supply_item(item["id"], LC))
        assert data["quantity_on_hand"] == 3, "no partial issue"

    def test_stock_transaction_future_occurred_at_rejected(self, api):
        """PRD §2.5: "Because business timestamps are validated against this clock,
        a stock transaction's `occurred_at` may be backdated but must never be
        later than the current logical clock time; a future-dated `occurred_at` is
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/stock_transaction_future_occurred_at_rejected
        """
        item = create_supply_item(item_name="Masks", category="PPE", unit="box",
                                  reorder_min_days=1)
        resp = api.create_stock_transaction(
            create_stock_transaction_payload(item["id"], "RECEIVE", 5,
                                             "2026-08-02T00:00:00Z"),
            LC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestComputedReadAndThresholds:
    def test_supply_item_computed_read_includes_burn_fields(self, api):
        """PRD §3.6: "New items start with `quantity_on_hand` at zero."
        PRD §3.6: "The item's `quantity_on_hand` is recomputed synchronously on
        every entry: a receipt adds the quantity, an issue subtracts it, a return
        adds it back, and an adjustment resets the on-hand figure to the stated
        absolute value."
        PRD §3.6: "`days_of_supply` is `quantity_on_hand` divided by
        `projected_daily_burn_rate`, floored to a whole number of days, and is null
        whenever the projected rate is zero."

        Design: Corner/endpoints/supply_item_computed_read_includes_burn_fields
        """
        item = create_supply_item(item_name="Gloves", category="PPE", unit="box",
                                  reorder_min_days=4)
        post_stock(item["id"], "RECEIVE", 5, "2026-07-30T09:00:00Z")

        data = validate_success(api.get_supply_item(item["id"], LC))
        assert_supply_item(data)
        assert data["quantity_on_hand"] == 5
        assert data["observed_daily_burn_rate"] == pytest.approx(0.0, abs=1e-9)
        assert data["projected_daily_burn_rate"] == pytest.approx(0.0, abs=1e-9), (
            "RECEIVE never enters the burn window"
        )
        assert data["days_of_supply"] is None
        assert data["below_reorder_level"] is False

    def test_reorder_threshold_strict_less_than(self, api):
        """PRD §3.6: "`below_reorder_level` is true exactly when `days_of_supply`
        is not null and is strictly less than `reorder_min_days` — an item sitting
        precisely at its floor is not below reorder — and is false whenever
        `days_of_supply` is null."
        PRD §3.6: "The item's `quantity_on_hand` is recomputed synchronously on
        every entry: a receipt adds the quantity, an issue subtracts it, a return
        adds it back, and an adjustment resets the on-hand figure to the stated
        absolute value."

        Design: Corner/cross_cutting_layers/reorder_threshold_strict_less_than
        """
        item = create_supply_item(item_name="Oxygen tanks", category="OXYGEN",
                                  unit="tank", reorder_min_days=13)
        post_stock(item["id"], "RECEIVE", 20, "2026-07-30T09:00:00Z")
        post_stock(item["id"], "ISSUE", 7, "2026-07-30T10:00:00Z")

        data0 = validate_success(api.get_supply_item(item["id"], LC))
        assert data0["days_of_supply"] == 13, "floor(13 / 1.0)"
        assert data0["below_reorder_level"] is False, "13 < 13 is false"

        post_stock(item["id"], "ADJUST", 12, "2026-07-30T12:00:00Z")
        data1 = validate_success(api.get_supply_item(item["id"], LC))
        assert data1["quantity_on_hand"] == 12, "ADJUST resets on-hand absolutely"
        assert data1["days_of_supply"] == 12
        assert data1["below_reorder_level"] is True, "12 < 13"
        assert data1["observed_daily_burn_rate"] == pytest.approx(1.0, abs=1e-9), (
            "ADJUST never enters the burn window"
        )

    def test_quantity_on_hand_reconciles_across_transaction_types(self, api):
        """PRD §3.6: "The item's `quantity_on_hand` is recomputed synchronously on
        every entry: a receipt adds the quantity, an issue subtracts it, a return
        adds it back, and an adjustment resets the on-hand figure to the stated
        absolute value."
        PRD §3.6: "sum the `quantity` of every `ISSUE` entry for the item whose
        `occurred_at` falls at or after the instant 168 hours before now and
        strictly before now, subtract the summed `quantity` of every `RETURN` entry
        in the same window — receipts and adjustments never enter the window —
        divide the net by seven, and round half-up to four decimal places."

        Design: Corner/cross_cutting_layers/quantity_on_hand_reconciles_across_transaction_types
        """
        item = create_supply_item(item_name="Trauma kits", category="OTHER_SUPPLY",
                                  unit="each", reorder_min_days=1)
        post_stock(item["id"], "RECEIVE", 10, "2026-07-30T09:00:00Z")
        post_stock(item["id"], "ISSUE", 3, "2026-07-30T09:10:00Z")
        post_stock(item["id"], "RETURN", 1, "2026-07-30T09:20:00Z")
        post_stock(item["id"], "ADJUST", 25, "2026-07-30T09:30:00Z")
        post_stock(item["id"], "ISSUE", 5, "2026-07-30T09:40:00Z")

        data = validate_success(api.get_supply_item(item["id"], LC))
        assert data["quantity_on_hand"] == 20, "10 − 3 + 1, reset to 25, then − 5"
        assert data["observed_daily_burn_rate"] == pytest.approx(1.0, abs=1e-9), (
            "(3 + 5 − 1)/7 — ADJUST never enters the burn window"
        )
