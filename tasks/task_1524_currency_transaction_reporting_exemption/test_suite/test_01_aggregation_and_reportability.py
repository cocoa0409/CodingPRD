"""Daily aggregation + CTR reportability cascade (PRD §3.4) and boundaries."""
from test_helpers import (
    ApiErrorId,
    create_ctr_in_draft,
    get_aggregation_for,
    get_single_ctr_for_customer,
    get_success_data,
    list_ctrs_for_customer,
    make_analyst_headers,
    make_officer_headers,
    make_teller_headers,
    post_cash_txn,
    post_instrument_sale,
    set_clock,
    setup_branch_and_customer,
    api_client,
    validate_success,
)


class TestCtrThresholdBoundary:
    def test_ctr_threshold_exactly_at_boundary_not_reportable(self, api):
        """PRD §3.4: "`raw_reportable_in` is true exactly when `total_cash_in_cents`
        is strictly greater than 1000000 cents".

        Design: Difficulty/boundary_precision_check/ctr_threshold_exactly_10000_vs_one_cent_over
        """
        branch, customer = setup_branch_and_customer(clock="2026-08-01T12:00:00Z")
        post_cash_txn(customer["id"], branch["id"], amount_cents=600_000,
                      occurred_at="2026-08-01T10:00:00Z")
        post_cash_txn(customer["id"], branch["id"], amount_cents=400_000,
                      occurred_at="2026-08-01T10:30:00Z")
        agg = get_aggregation_for(customer["id"], "2026-08-01")
        assert agg["total_cash_in_cents"] == 1_000_000
        assert agg["raw_reportable_in"] is False
        _, meta = list_ctrs_for_customer(customer["id"])
        assert meta["total_count"] == 0

    def test_ctr_threshold_one_cent_over_creates_draft(self, api):
        """PRD §3.4: "When `ctr_required` flips from false to true and no live CTR
        exists for the pair—live meaning status in `DRAFT`, `VALIDATED`, `FILED`,
        `ACKNOWLEDGED`, or `AMENDMENT_REQUIRED`—the system auto-creates a CTR in
        `DRAFT` with its snapshot set to the current totals."

        Design: Difficulty/boundary_precision_check/ctr_threshold_exactly_10000_vs_one_cent_over
        """
        branch, customer = setup_branch_and_customer(clock="2026-08-01T12:00:00Z")
        post_cash_txn(customer["id"], branch["id"], amount_cents=600_000,
                      occurred_at="2026-08-01T10:00:00Z")
        post_cash_txn(customer["id"], branch["id"], amount_cents=400_000,
                      occurred_at="2026-08-01T10:30:00Z")
        post_cash_txn(customer["id"], branch["id"], amount_cents=1,
                      occurred_at="2026-08-01T11:00:00Z")
        data, meta = list_ctrs_for_customer(customer["id"])
        assert meta["total_count"] == 1
        assert data[0]["status"] == "DRAFT"
        assert data[0]["snapshot_cash_in_cents"] == 1_000_001


class TestAggregationComposition:
    def test_cash_out_direction_also_reportable(self, api):
        """PRD §3.4: "`raw_reportable_out` is true exactly when `total_cash_out_cents`
        is strictly greater than 1000000 cents."
        PRD §3.7: "The structuring detector runs automatically on every posted cash
        transaction with direction `CASH_IN` and on every recorded monetary
        instrument sale."

        Design: Corner/calculations/cash_out_direction_also_reportable
        """
        branch, customer = setup_branch_and_customer()
        post_cash_txn(customer["id"], branch["id"], direction="CASH_OUT",
                      amount_cents=1_200_000, occurred_at="2026-08-01T08:00:00Z")
        data, meta = list_ctrs_for_customer(customer["id"])
        assert meta["total_count"] == 1
        assert data[0]["snapshot_cash_out_cents"] == 1_200_000
        assert data[0]["snapshot_cash_in_cents"] == 0
        # structuring detector ignores CASH_OUT
        resp = api_client.list_structuring_alerts(
            headers=make_officer_headers(), params={"customer_id": customer["id"]},
        )
        assert resp.json()["meta"]["total_count"] == 0

    def test_multi_branch_same_day_aggregation_single_row(self, api):
        """PRD §3.4: "The DailyCashAggregation row for a (`customer_id`,
        `business_date`) pair is the single source from which reporting
        obligations derive."
        PRD §2.8: "the pair (`customer_id`, `business_date`) is unique across
        all aggregation rows."

        Design: Corner/calculations/multi_branch_same_day_aggregation_single_row
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        br2 = create_branch(name="West", branch_code="BR2")
        customer = create_customer(legal_name="Multibranch Mike", tin="16-1616161")
        post_cash_txn(customer["id"], br1["id"], amount_cents=600_000,
                      occurred_at="2026-08-01T08:00:00Z")
        post_cash_txn(customer["id"], br2["id"], amount_cents=500_000,
                      occurred_at="2026-08-01T08:30:00Z")
        resp = api_client.list_daily_aggregations(
            headers=make_officer_headers(), params={"customer_id": customer["id"]},
        )
        body = resp.json()
        assert body["meta"]["total_count"] == 1
        assert body["data"][0]["total_cash_in_cents"] == 1_100_000
        assert body["data"][0]["transaction_count"] == 2
        _, meta = list_ctrs_for_customer(customer["id"])
        assert meta["total_count"] == 1

    def test_instrument_sale_counts_toward_cash_in_aggregation(self, api):
        """PRD §3.3: "A sale is born `RECORDED`, derives its `business_date` from
        `occurred_at`, and counts toward the customer's cash-in aggregation even
        though no deposit account is involved."

        Design: Corner/calculations/instrument_sale_counts_toward_cash_in_aggregation
        """
        branch, customer = setup_branch_and_customer()
        post_instrument_sale(
            customer["id"], branch["id"], amount_cents=600_000,
            occurred_at="2026-08-01T08:00:00Z",
            purchaser_name="Mia", purchaser_tin="17-1717171",
            purchaser_address="4 Pine", purchaser_id_number="ID-7",
        )
        post_cash_txn(customer["id"], branch["id"], amount_cents=500_000,
                      occurred_at="2026-08-01T08:30:00Z")
        agg = get_aggregation_for(customer["id"], "2026-08-01")
        assert agg["total_cash_in_cents"] == 1_100_000
        assert agg["transaction_count"] == 1
        assert agg["instrument_sale_count"] == 1
        _, meta = list_ctrs_for_customer(customer["id"])
        assert meta["total_count"] == 1

    def test_instrument_sale_void_recomputes_totals_and_fees(self, api):
        """PRD §3.2: "A successful void moves the transaction `POSTED → VOIDED`,
        stamps `voided_at` with the current logical time, recomputes the daily
        aggregation (voided records contribute nothing), re-evaluates CTR
        reportability with the full cascade of §3.4, and appends an audit event."
        PRD §3.3: "The void moves the sale `RECORDED → VOIDED`, stamps `voided_at`,
        recomputes the aggregation including instrument counts and the fee total,
        re-evaluates CTR reportability, and appends an audit event."

        Design: Corner/calculations/instrument_sale_void_recomputes_totals_and_fees
        """
        branch, customer = setup_branch_and_customer()
        post_instrument_sale(
            customer["id"], branch["id"], amount_cents=500_000,
            occurred_at="2026-08-01T08:00:00Z",
            purchaser_name="Rex", purchaser_tin="11-1111110",
            purchaser_address="3 Elm", purchaser_id_number="ID-1",
        )
        s2 = post_instrument_sale(
            customer["id"], branch["id"], amount_cents=200_000,
            occurred_at="2026-08-01T08:05:00Z",
        )
        resp = api_client.void_instrument_sale(
            s2["id"], {"void_reason": "misprint"}, headers=make_teller_headers("teller-1"),
        )
        validate_success(resp)
        agg = get_aggregation_for(customer["id"], "2026-08-01")
        assert agg["total_cash_in_cents"] == 500_000
        assert agg["instrument_sale_count"] == 1
        assert agg["instrument_fee_total_cents"] == 2500

    def test_immediate_read_after_write_consistency(self, api):
        """PRD §2.8: "Every create or void of a cash transaction or monetary
        instrument sale recomputes the affected row immediately within the same
        request; the system is strictly consistent—every mutation and the full
        cascade it triggers commit atomically".

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        branch, customer = setup_branch_and_customer()
        post_cash_txn(customer["id"], branch["id"], amount_cents=1_100_000,
                      occurred_at="2026-08-01T08:00:00Z")
        agg = get_aggregation_for(customer["id"], "2026-08-01")
        assert agg["total_cash_in_cents"] == 1_100_000
        assert agg["ctr_required"] is True
        _, meta = list_ctrs_for_customer(customer["id"])
        assert meta["total_count"] == 1


class TestInstrumentFeeCalc:
    def test_instrument_fee_minimum_floor_and_half_cent_round(self, api):
        """PRD §3.3: "Each sale carries a per-instrument `fee_cents`, computed as
        the greater of 150 cents and the sale's `amount_cents` multiplied by 50
        basis points (that is, multiplied by 50 and divided by 10000), rounded
        half-up to whole cents."

        Design: Corner/calculations/instrument_fee_minimum_floor_and_half_cent_round
        """
        branch, customer = setup_branch_and_customer()
        f1 = post_instrument_sale(customer["id"], branch["id"], amount_cents=10_000,
                                  occurred_at="2026-08-01T08:00:00Z")
        f2 = post_instrument_sale(customer["id"], branch["id"], amount_cents=30_000,
                                  occurred_at="2026-08-01T08:05:00Z")
        f3 = post_instrument_sale(customer["id"], branch["id"], amount_cents=30_100,
                                  occurred_at="2026-08-01T08:10:00Z")
        assert f1["fee_cents"] == 150
        assert f2["fee_cents"] == 150
        assert f3["fee_cents"] == 151

    def test_instrument_fee_round_per_item_then_sum(self, api):
        """PRD §3.3: "The rounding is applied per instrument first; the daily
        aggregation's `instrument_fee_total_cents` then sums the already-rounded
        per-instrument fees. The pinned order matters: rounding each fee and then
        summing is the implemented rule, and summing amounts first and rounding
        once is a different result—for two sales of 100100 cents and 99900 cents,
        per-instrument rounding yields a daily fee total of 1001 cents while
        sum-then-round yields 1000 cents."

        Design: Difficulty/combinatorial_formula/instrument_fee_round_per_item_then_sum
        """
        branch, customer = setup_branch_and_customer()
        s1 = post_instrument_sale(customer["id"], branch["id"], amount_cents=100_100,
                                  occurred_at="2026-08-01T08:30:00Z")
        s2 = post_instrument_sale(customer["id"], branch["id"], amount_cents=99_900,
                                  occurred_at="2026-08-01T08:45:00Z")
        agg = get_aggregation_for(customer["id"], "2026-08-01")
        assert s1["fee_cents"] == 501
        assert s2["fee_cents"] == 500
        assert agg["instrument_fee_total_cents"] == 1001

    def test_instrument_fee_round_per_item_then_sum_second_pair(self, api):
        """PRD §3.3: "Each sale carries a per-instrument `fee_cents`, computed as
        the greater of 150 cents and the sale's `amount_cents` multiplied by 50
        basis points (that is, multiplied by 50 and divided by 10000), rounded
        half-up to whole cents. The rounding is applied per instrument first; the
        daily aggregation's `instrument_fee_total_cents` then sums the
        already-rounded per-instrument fees."

        Second instance confirming per-item rounding on a distinct pair of amounts
        (40100 -> 201, 40500 -> 203, total 404).

        Design: Difficulty/combinatorial_formula/instrument_fee_round_per_item_then_sum
        """
        branch, customer = setup_branch_and_customer()
        s1 = post_instrument_sale(customer["id"], branch["id"], amount_cents=40_100,
                                  occurred_at="2026-08-01T08:30:00Z")
        s2 = post_instrument_sale(customer["id"], branch["id"], amount_cents=40_500,
                                  occurred_at="2026-08-01T08:45:00Z")
        agg = get_aggregation_for(customer["id"], "2026-08-01")
        assert s1["fee_cents"] == 201   # round_half_up(200.5)
        assert s2["fee_cents"] == 203   # round_half_up(202.5)
        assert agg["instrument_fee_total_cents"] == 404


class TestCompensatingInvariant:
    def test_cash_void_restores_aggregation_totals(self, api):
        """PRD §3.2: "A successful void moves the transaction `POSTED → VOIDED`,
        stamps `voided_at` with the current logical time, recomputes the daily
        aggregation (voided records contribute nothing), re-evaluates CTR
        reportability with the full cascade of §3.4, and appends an audit event."
        PRD §3.4: "When `ctr_required` flips from true to false and a live CTR
        exists in `DRAFT` or `VALIDATED`, that CTR is transitioned to `VOIDED`."

        Design: Difficulty/compensating_invariant/cash_void_restores_aggregation_totals
        """
        branch, customer = setup_branch_and_customer()
        post_cash_txn(customer["id"], branch["id"], amount_cents=700_000,
                      occurred_at="2026-08-01T08:00:00Z")
        txn2 = post_cash_txn(customer["id"], branch["id"], amount_cents=300_001,
                             occurred_at="2026-08-01T08:30:00Z")
        ctr = get_single_ctr_for_customer(customer["id"])
        assert ctr["status"] == "DRAFT"
        resp = api_client.void_cash_transaction(
            txn2["id"], {"void_reason": "duplicate entry"},
            headers=make_teller_headers("teller-1"),
        )
        validate_success(resp)
        agg = get_aggregation_for(customer["id"], "2026-08-01")
        assert agg["total_cash_in_cents"] == 700_000
        assert agg["transaction_count"] == 1
        assert agg["ctr_required"] is False
        ctr_after = get_success_data(
            api_client.get_ctr(ctr["id"], headers=make_officer_headers()),
        )
        assert ctr_after["status"] == "VOIDED"

    def test_cash_void_restores_aggregation_totals_no_drift_on_counts(self, api):
        """PRD §3.2: "A successful void moves the transaction `POSTED → VOIDED`,
        stamps `voided_at` with the current logical time, recomputes the daily
        aggregation (voided records contribute nothing)".
        PRD §3.4: "`transaction_count` — the count of contributing posted cash
        transactions across both directions."

        Independent re-derivation with different amounts / directions confirming
        both totals and counts are conserved after the compensating void.

        Design: Difficulty/compensating_invariant/cash_void_restores_aggregation_totals
        """
        branch, customer = setup_branch_and_customer()
        post_cash_txn(customer["id"], branch["id"], direction="CASH_IN",
                      amount_cents=400_000, occurred_at="2026-08-01T08:00:00Z")
        post_cash_txn(customer["id"], branch["id"], direction="CASH_OUT",
                      amount_cents=250_000, occurred_at="2026-08-01T08:15:00Z")
        txn3 = post_cash_txn(customer["id"], branch["id"], direction="CASH_IN",
                             amount_cents=150_000, occurred_at="2026-08-01T08:30:00Z")
        resp = api_client.void_cash_transaction(
            txn3["id"], {"void_reason": "rescinded"},
            headers=make_teller_headers("teller-1"),
        )
        validate_success(resp)
        agg = get_aggregation_for(customer["id"], "2026-08-01")
        assert agg["total_cash_in_cents"] == 400_000
        assert agg["total_cash_out_cents"] == 250_000
        assert agg["transaction_count"] == 2
