"""Section 16(b) short-swing profit analysis: dual matching variants, pinned
rounding order, and the six-month matchability window (PRD §2.7, §3.9)."""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, ApiErrorId,
    make_compliance_officer_headers,
    assert_short_swing_analysis,
    create_issuer, create_active_person, set_clock,
    ingest_transaction, confirm_transaction,
)


def _confirm_all(transactions):
    for txn in transactions:
        confirm_transaction(txn["id"])


def _buy(person_id, date, shares, price):
    return ingest_transaction(person_id, transaction_date=date,
                              transaction_code="P", shares=shares,
                              price_per_share=price)


def _sell(person_id, date, shares, price):
    return ingest_transaction(person_id, transaction_date=date,
                              transaction_code="S", shares=shares,
                              price_per_share=price)


class TestMaxRecoveryVsFifo:
    def _setup_four_trade_book(self, api):
        """Buy 100 @ 20.00 (2026-02-02), buy 100 @ 8.00 (2026-03-02),
        sell 100 @ 15.00 (2026-04-01), sell 100 @ 18.00 (2026-05-01)."""
        issuer = create_issuer()
        person = create_active_person(issuer["id"], is_officer=True)
        txns = [
            _buy(person["id"], "2026-02-02", 100, 20.00),
            _buy(person["id"], "2026-03-02", 100, 8.00),
            _sell(person["id"], "2026-04-01", 100, 15.00),
            _sell(person["id"], "2026-05-01", 100, 18.00),
        ]
        _confirm_all(txns)
        return person

    def test_max_recovery_matches_highest_sale_to_lowest_purchase(self, api):
        """PRD §3.9: "`short_swing_profit` is the authoritative recovery figure
        under the maximum-recovery rule: sales are processed in descending
        `price_per_share` order with ties broken by `created_at` ascending, and
        each sale is matched against the remaining purchase with the lowest
        `price_per_share` that is both matchable with the sale and yields a
        positive spread, ties again broken by `created_at` ascending."
        PRD §3.9: "Only pairs in which the sale's `price_per_share` exceeds the
        purchase's `price_per_share` participate in the profit total."

        Design: Difficulty/dual_variant_calc/short_swing_max_recovery_vs_fifo
        """
        person = self._setup_four_trade_book(api)
        resp = api.get_short_swing_analysis(
            person["id"], make_compliance_officer_headers())
        data = validate_success(resp, 200)
        assert_short_swing_analysis(data, person["id"])
        # MAX_RECOVERY: sale 100 @ 18.00 matches purchase 100 @ 8.00 ->
        # (18.00 - 8.00) * 100 = 1000.00; sale @ 15.00 finds no remaining
        # positive-spread purchase (only the 20.00 lot is left).
        assert data["short_swing_profit"] == pytest.approx(1000.00, abs=1e-9), (
            f"Expected MAX_RECOVERY profit 1000.00, "
            f"got {data['short_swing_profit']}")

    def test_fifo_variant_matches_in_time_order(self, api):
        """PRD §3.9: "`short_swing_profit_fifo` is the chronological comparison
        figure: sales are processed in ascending `transaction_date` order with
        ties broken by `created_at` ascending, and each sale is matched against
        the earliest remaining purchase that is matchable and yields a positive
        spread — earliest by `transaction_date`, ties by `created_at`. The two
        variants can produce different totals for identical inputs, which is
        exactly why both are reported."

        Design: Difficulty/dual_variant_calc/short_swing_max_recovery_vs_fifo
        """
        person = self._setup_four_trade_book(api)
        data = validate_success(api.get_short_swing_analysis(
            person["id"], make_compliance_officer_headers()), 200)
        # FIFO: sale @ 15.00 (04-01) matches the earliest positive-spread
        # purchase 100 @ 8.00 -> (15.00 - 8.00) * 100 = 700.00; sale @ 18.00
        # then finds no positive spread (only the 20.00 lot remains).
        assert data["short_swing_profit_fifo"] == pytest.approx(700.00, abs=1e-9), (
            f"Expected FIFO profit 700.00, got {data['short_swing_profit_fifo']}")
        assert data["short_swing_profit"] != pytest.approx(
            data["short_swing_profit_fifo"], abs=1e-9), (
            "The two variants must diverge for this input data")


class TestPerPairRoundingOrder:
    def test_round_per_pair_then_sum(self, api):
        """PRD §2.7: "One rounding order is pinned and may not be varied: in
        the short-swing analysis, each matched pair's profit is rounded half-up
        to two decimal places first, and the rounded per-pair values are then
        summed."
        PRD §3.9: "the pair's profit is the difference between the sale's and
        the purchase's `price_per_share` multiplied by the matched shares —
        rounded half-up to two decimal places per pair first, with the rounded
        per-pair values then summed, in that pinned order."

        Design: Difficulty/combinatorial_formula/short_swing_per_pair_rounding_order
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"], is_officer=True)
        txns = [
            _buy(person["id"], "2026-03-02", 1, 10.000),
            _buy(person["id"], "2026-03-03", 1, 10.000),
            _sell(person["id"], "2026-04-01", 1, 10.005),
            _sell(person["id"], "2026-04-02", 1, 10.005),
        ]
        _confirm_all(txns)
        data = validate_success(api.get_short_swing_analysis(
            person["id"], make_compliance_officer_headers()), 200)
        # Each pair earns 0.005 -> rounds HALF_UP to 0.01 per pair; the pinned
        # order then sums 0.01 + 0.01 = 0.02. Sum-then-round of 0.010 would
        # produce 0.01 and is the forbidden order.
        assert data["short_swing_profit"] == pytest.approx(0.02, abs=1e-9), (
            f"Round-per-pair-then-sum must yield 0.02, "
            f"got {data['short_swing_profit']}")

    def test_fifo_variant_uses_same_pinned_rounding_order(self, api):
        """PRD §2.7: "One rounding order is pinned and may not be varied: in
        the short-swing analysis, each matched pair's profit is rounded half-up
        to two decimal places first, and the rounded per-pair values are then
        summed."

        Design: Difficulty/combinatorial_formula/short_swing_per_pair_rounding_order
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"], is_officer=True)
        txns = [
            _buy(person["id"], "2026-03-02", 1, 10.000),
            _buy(person["id"], "2026-03-03", 1, 10.000),
            _sell(person["id"], "2026-04-01", 1, 10.005),
            _sell(person["id"], "2026-04-02", 1, 10.005),
        ]
        _confirm_all(txns)
        data = validate_success(api.get_short_swing_analysis(
            person["id"], make_compliance_officer_headers()), 200)
        assert data["short_swing_profit_fifo"] == pytest.approx(0.02, abs=1e-9), (
            f"FIFO variant follows the same pinned rounding order, "
            f"got {data['short_swing_profit_fifo']}")
        assert data["short_swing_profit"] == pytest.approx(
            data["short_swing_profit_fifo"], abs=1e-9), (
            "Identical per-pair spreads give identical variant totals here")


class TestSixMonthWindowBoundary:
    def test_six_month_window_exactly_excluded(self, api):
        """PRD §3.9: "A purchase and a sale are matchable when their
        transaction dates lie strictly less than six calendar months apart, in
        either order: the sale's date falls before the purchase's date plus six
        calendar months, or the purchase's date falls before the sale's date
        plus six calendar months. Adding calendar months clamps the day to the
        end of the resulting month when that month is shorter. A purchase and a
        sale exactly six calendar months apart are not matchable."
        PRD §3.9: "Only pairs in which the sale's `price_per_share` exceeds the
        purchase's `price_per_share` participate in the profit total."

        Design: Corner/calculations/six_month_window_exactly_excluded
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"])
        # PRD §3.3: confirmation rejects a transaction_date later than the
        # logical clock date; the clock boots at 2026-08-01 (PRD §2.5), so
        # advance it past the latest sale date before confirming.
        set_clock("2026-08-06T00:00:00Z")
        txns = [
            _buy(person["id"], "2026-02-05", 100, 10.00),
            _buy(person["id"], "2026-02-05", 100, 10.00),
            # 2026-08-04 is one day inside the six-month window: matchable.
            _sell(person["id"], "2026-08-04", 100, 14.00),
            # 2026-08-05 is exactly six calendar months after 2026-02-05:
            # not matchable.
            _sell(person["id"], "2026-08-05", 100, 14.00),
        ]
        _confirm_all(txns)
        data = validate_success(api.get_short_swing_analysis(
            person["id"], make_compliance_officer_headers()), 200)
        # Only the 08-04 sale matches a purchase: (14.00 - 10.00) * 100 =
        # 400.00. If the exactly-six-months sale participated, the total would
        # be 800.00 under either variant.
        assert data["short_swing_profit"] == pytest.approx(400.00, abs=1e-9), (
            f"Exactly-six-months sale must be excluded (profit 400.00), "
            f"got {data['short_swing_profit']}")
        assert data["short_swing_profit_fifo"] == pytest.approx(400.00, abs=1e-9), (
            f"FIFO must agree here at 400.00, "
            f"got {data['short_swing_profit_fifo']}")
