"""Feed purchasing, supply projection, and the daily close (PRD §3.7)."""
import pytest

from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    assert_same_instant,
    purchase_order_payload, receipt_payload,
    intake_horse, create_ordered_purchase_order, receive_order,
    create_received_order, list_feed_lots, list_day_closes, feed_summary_entry,
)

BARN = TEST_USERS["barn_manager_headers"]


def _two_resident_horses():
    """A (1000 lbs, BCS 3 -> ration 25.0) and B (900 lbs, BCS 5 -> ration 18.0);
    grass demand 25.0*0.7*0.5 + 18.0*0.7 = 8.75 + 12.6 = 21.35 lbs/day."""
    intake_horse(name="A", sex="MARE", estimated_weight_lbs=1000, age_years=6,
                 body_condition_score=3)
    intake_horse(name="B", sex="GELDING", estimated_weight_lbs=900, age_years=7,
                 body_condition_score=5)


class TestSupplyVariants:
    def test_tight_supply_uses_on_hand_only(self):
        """PRD §3.7: "The tight figure, `days_of_supply_tight`, divides usable
        stock alone by the seasonally scaled daily demand and rounds half up to
        two decimals; the committed figure, `days_of_supply_committed`, adds
        inbound stock to the numerator, so identical inputs yield a larger
        committed figure whenever any order is open."
        PRD §3.7: "A seasonal multiplier then scales demand according to the
        calendar month of the computation: 1.25 from December through February,
        1.00 from March through May, 0.90 from June through August, and 1.10 from
        September through November."

        Design: Difficulty/dual_variant_calc/feed_supply_tight_vs_committed_divergence
        """
        _two_resident_horses()
        create_received_order("GRASS_HAY", 600, 10)  # 600 lbs usable on hand
        create_ordered_purchase_order("GRASS_HAY", 300, 10)  # 300 lbs inbound open
        entry = feed_summary_entry("GRASS_HAY")
        assert entry["daily_demand_lbs"] == pytest.approx(21.35, abs=1e-9)
        assert entry["days_of_supply_tight"] == pytest.approx(31.23, abs=1e-9), (
            "600 / (21.35 * 0.9)")
        assert entry["reorder_required"] is False

    def test_committed_supply_includes_inbound_orders(self):
        """PRD §3.7: "The tight figure, `days_of_supply_tight`, divides usable
        stock alone by the seasonally scaled daily demand and rounds half up to
        two decimals; the committed figure, `days_of_supply_committed`, adds
        inbound stock to the numerator, so identical inputs yield a larger
        committed figure whenever any order is open."
        PRD §3.7: "inbound stock adds the undelivered remainder — `quantity_lbs`
        minus `received_lbs` — of every purchase order in `ORDERED` or
        `PARTIALLY_RECEIVED`."

        Design: Difficulty/dual_variant_calc/feed_supply_tight_vs_committed_divergence
        """
        _two_resident_horses()
        create_received_order("GRASS_HAY", 600, 10)
        create_ordered_purchase_order("GRASS_HAY", 300, 10)
        entry = feed_summary_entry("GRASS_HAY")
        assert entry["days_of_supply_committed"] == pytest.approx(46.84, abs=1e-9), (
            "(600 + 300) / (21.35 * 0.9)")
        assert entry["days_of_supply_committed"] != entry["days_of_supply_tight"], (
            "variants diverge whenever an order is open")


class TestPurchaseOrderRounding:
    def test_per_lot_rounding_diverges_from_estimate(self):
        """PRD §3.7: "The pinned order — per-lot rounding, then summation, then
        surcharge on the sum — matters: three lots of 333 lbs each at 7.5 cents
        per pound yield 2498 cents per lot and 7494 cents in total, whereas
        summing the raw product first would yield 7493; the two evaluation orders
        differ by a cent, and this system takes the per-lot order."
        PRD §3.7: "an `estimated_total_cents` computed once at creation as the
        ordered quantity times the unit price, rounded half up to integer cents —
        a single-rounding estimate"

        Design: Difficulty/combinatorial_formula/purchase_order_per_lot_rounding_order
        """
        po = get_success_data(api_client.create_purchase_order(
            purchase_order_payload(feed_type="GRASS_HAY", quantity_lbs=999,
                                   unit_cents_per_lb=7.5), BARN))
        assert po["estimated_total_cents"] == 7493, (
            "single-rounding estimate: round_half_up(999 * 7.5)")
        get_success_data(api_client.mark_purchase_order_ordered(po["id"], BARN))
        for day in ("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z",
                    "2026-09-03T00:00:00Z"):
            receive_order(po["id"], 333, day)
        final = get_success_data(api_client.get_purchase_order(po["id"], BARN))
        assert final["actual_total_cents"] == 7494, "sum of per-lot rounded 2498 x 3"
        assert final["actual_total_cents"] != final["estimated_total_cents"], (
            "rounding order is observable")

    def test_surcharge_and_grand_total_on_full_receipt(self):
        """PRD §3.7: "the receipt that reaches the ordered quantity exactly moves
        it to `RECEIVED` and closes the books: `delivery_surcharge_cents` is eight
        percent of `actual_total_cents` rounded half up, and `grand_total_cents`
        is `actual_total_cents` plus that surcharge."

        Design: Difficulty/combinatorial_formula/purchase_order_per_lot_rounding_order
        """
        po = create_ordered_purchase_order("GRASS_HAY", 999, 7.5)
        for day in ("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z",
                    "2026-09-03T00:00:00Z"):
            receive_order(po["id"], 333, day)
        final = get_success_data(api_client.get_purchase_order(po["id"], BARN))
        assert final["status"] == "RECEIVED"
        assert final["received_lbs"] == pytest.approx(999, abs=1e-9)
        assert final["delivery_surcharge_cents"] == 600, (
            "round_half_up(7494 * 0.08) = round_half_up(599.52)")
        assert final["grand_total_cents"] == 8094


class TestCloseDayConservation:
    def _setup_three_lots(self):
        _two_resident_horses()
        create_received_order(
            "GRASS_HAY", 999, 7.5,
            receipts=[(333, "2026-08-20T00:00:00Z"),
                      (333, "2026-08-25T00:00:00Z"),
                      (333, "2026-09-01T00:00:00Z")])

    def test_close_days_drawdown_and_expiry_waste(self):
        """PRD §3.7: "Expiry waste comes first: every lot of that type whose
        `expiry_date` falls before the `close_date` is wasted down to zero
        on-hand, and the record's `wasted_lbs` is the sum of those remaining
        quantities. Demand is then computed as that feed type's
        `daily_demand_lbs` times the seasonal multiplier for the close date's
        month, rounded half up to two decimal places. Drawdown follows
        first-expiring-first-out: usable lots are drained in `expiry_date`
        ascending order, ties broken by `created_at` ascending."

        Design: Difficulty/compensating_invariant/feed_lot_conservation_across_close_days
        """
        self._setup_three_lots()
        for close_date in ("2026-08-19T00:00:00Z", "2026-08-20T00:00:00Z",
                           "2026-08-21T00:00:00Z"):
            get_success_data(api_client.close_feed_day(
                {"close_date": close_date}, BARN))

        lots = list_feed_lots()
        assert len(lots) == 3
        quantities = [lot["quantity_lbs"] for lot in lots]
        assert quantities[0] == pytest.approx(0.0, abs=1e-9), (
            "lot 1 drained twice then wasted at the 08-21 close")
        assert quantities[1] == pytest.approx(313.78, abs=1e-9), "333 - 19.22"
        assert quantities[2] == pytest.approx(333.0, abs=1e-9)

        closes = list_day_closes("GRASS_HAY")
        assert len(closes) == 3
        for record in closes:
            assert record["consumed_lbs"] == pytest.approx(19.22, abs=1e-9), (
                "round_half_up(21.35 * 0.9, 2)")

    def test_feed_conservation_invariant_holds(self):
        """PRD §3.7: "the received quantity becomes both the lot's `initial_lbs` —
        an immutable anchor for the feed conservation invariant — and its starting
        `quantity_lbs`"
        PRD §3.7: "The record's `consumed_lbs` is the lesser of the rounded demand
        and the usable stock, and `shortfall_lbs` captures whatever demand the
        stock could not meet."

        Design: Difficulty/compensating_invariant/feed_lot_conservation_across_close_days
        """
        self._setup_three_lots()
        for close_date in ("2026-08-19T00:00:00Z", "2026-08-20T00:00:00Z",
                           "2026-08-21T00:00:00Z"):
            get_success_data(api_client.close_feed_day(
                {"close_date": close_date}, BARN))

        on_hand = sum(lot["quantity_lbs"] for lot in list_feed_lots())
        closes = list_day_closes("GRASS_HAY")
        consumed = sum(r["consumed_lbs"] for r in closes)
        wasted = sum(r["wasted_lbs"] for r in closes)
        initial = sum(lot["initial_lbs"] for lot in list_feed_lots())

        assert on_hand == pytest.approx(646.78, abs=1e-9)
        assert consumed == pytest.approx(57.66, abs=1e-9), "3 * 19.22"
        assert wasted == pytest.approx(294.56, abs=1e-9), "333 - 2*19.22"
        assert initial == pytest.approx(999.0, abs=1e-9)
        assert on_hand + consumed + wasted == pytest.approx(999.0, abs=1e-9), (
            "conservation: initial == on-hand + consumed + wasted")


class TestReorderAndEmptySummary:
    def test_feed_reorder_strictly_below_30(self):
        """PRD §3.7: "Otherwise `reorder_required` is true exactly when the tight
        figure is strictly below 30 days — a reading of exactly 30.00 does not
        trigger a reorder."

        Design: Corner/calculations/feed_reorder_strictly_below_30
        """
        _two_resident_horses()
        create_received_order("GRASS_HAY", 576, 10)
        entry = feed_summary_entry("GRASS_HAY")
        assert entry["days_of_supply_tight"] == pytest.approx(29.98, abs=1e-9), (
            "576 / (21.35 * 0.9)")
        assert entry["reorder_required"] is True

    def test_feed_summary_structure_empty_db(self):
        """PRD §3.7: "The supply summary is computed on read and returns a
        `summaries` array with one entry per feed type."
        PRD §3.7: "When a feed type's daily demand is zero, both figures are null
        and `reorder_required` is false."

        Design: Corner/endpoints/feed_summary_structure_empty_db
        """
        data = get_success_data(api_client.get_feed_inventory_summary(BARN))
        summaries = data["summaries"]
        assert isinstance(summaries, list)
        assert len(summaries) == 4
        assert {e["feed_type"] for e in summaries} == {
            "GRASS_HAY", "ALFALFA", "GRAIN", "SUPPLEMENT"}
        for entry in summaries:
            assert entry["daily_demand_lbs"] == pytest.approx(0.0, abs=1e-9)
            assert entry["days_of_supply_tight"] is None
            assert entry["days_of_supply_committed"] is None
            assert entry["reorder_required"] is False


class TestReceiptAndCloseDayGates:
    def test_over_receipt_rejected(self):
        """PRD §3.7: "the cumulative `received_lbs` plus the new quantity must not
        exceed the ordered `quantity_lbs` (`ERR_OVER_RECEIPT`)"
        PRD §3.7: "the receipt that reaches the ordered quantity exactly moves it
        to `RECEIVED` and closes the books"

        Design: Corner/validations/over_receipt_rejected
        """
        po = create_ordered_purchase_order("GRAIN", 100, 10)
        after60 = receive_order(po["id"], 60, "2026-10-01T00:00:00Z")
        assert after60["status"] == "PARTIALLY_RECEIVED"

        resp = api_client.receive_purchase_order(
            po["id"], receipt_payload(quantity_received_lbs=50,
                                      expiry_date="2026-10-02T00:00:00Z"), BARN)
        validate_error(resp, ApiErrorId.ERR_OVER_RECEIPT, 422)

        after40 = receive_order(po["id"], 40, "2026-10-02T00:00:00Z")
        assert after40["status"] == "RECEIVED"
        assert after40["received_lbs"] == pytest.approx(100, abs=1e-9)

    def test_close_day_already_closed_rejected(self):
        """PRD §3.7: "Each calendar date may be closed at most once across the
        whole system — a second close of the same date fails with
        `ERR_DAY_ALREADY_CLOSED`."

        Design: Corner/validations/close_day_already_closed_rejected
        """
        first = get_success_data(api_client.close_feed_day(
            {"close_date": "2026-08-19T00:00:00Z"}, BARN))
        assert_same_instant(first["closed_date"], "2026-08-19T00:00:00Z")
        resp = api_client.close_feed_day(
            {"close_date": "2026-08-19T00:00:00Z"}, BARN)
        validate_error(resp, ApiErrorId.ERR_DAY_ALREADY_CLOSED, 409)
        second = get_success_data(api_client.close_feed_day(
            {"close_date": "2026-08-20T00:00:00Z"}, BARN))
        assert_same_instant(second["closed_date"], "2026-08-20T00:00:00Z")

    def test_close_day_shortfall_records_unmet_demand(self):
        """PRD §3.7: "The record's `consumed_lbs` is the lesser of the rounded
        demand and the usable stock, and `shortfall_lbs` captures whatever demand
        the stock could not meet."

        Design: Corner/cross_cutting_layers/close_day_shortfall_records_unmet_demand
        """
        intake_horse(name="A", sex="MARE", estimated_weight_lbs=1000, age_years=6,
                     body_condition_score=3)  # grass demand 8.75 lbs/day
        create_received_order("GRASS_HAY", 5, 10,
                              receipts=[(5, "2026-09-01T00:00:00Z")])
        get_success_data(api_client.close_feed_day(
            {"close_date": "2026-08-19T00:00:00Z"}, BARN))
        records = list_day_closes("GRASS_HAY")
        assert len(records) == 1
        record = records[0]
        assert record["consumed_lbs"] == pytest.approx(5.0, abs=1e-9), (
            "min(7.88 demand, 5 usable)")
        assert record["shortfall_lbs"] == pytest.approx(2.88, abs=1e-9), (
            "7.88 - 5.00")
        lots = list_feed_lots()
        assert lots[0]["quantity_lbs"] == pytest.approx(0.0, abs=1e-9)
