"""Computed reads: performance benchmark variants, cash-flow projection,
storage breakeven and bin buffer, and list pagination."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_grower_headers,
    create_operation,
    setup_active_plan_with_buyer,
    setup_operation_with_active_plan,
    create_flat_contract,
    create_confirmed_delivery,
    create_contract_payload,
    create_storage_lot_payload,
    create_buyer_payload,
    record_settlement_tick,
    record_quote_tick,
)

ADVISOR = TEST_USERS["advisor_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _benchmark_ctx(api):
    """AGGRESSIVE operation with a full-priced pair of contracts and five
    market ticks (four SETTLEMENT, one QUOTE inside the harvest window)."""
    ctx = setup_active_plan_with_buyer(
        name="Bench Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
    )
    c1 = create_flat_contract(
        ctx, bushels=10000, fixed_price=4.55,
        delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
    )
    c2 = get_success_data(api.create_contract(
        create_contract_payload(
            ctx["operation"]["id"], ctx["plan"]["id"], ctx["buyer"]["id"],
            contract_type="HTA", bushels=9550, contract_month="2026-12", fixed_price=None,
            delivery_window_start="2026-11-01", delivery_window_end="2026-12-01",
        ),
        ADVISOR,
    ))
    get_success_data(api.fix_price(c2["id"], {"fixation_price": 4.70}, ADVISOR))
    record_settlement_tick(4.20, "2026-06-15")
    record_settlement_tick(4.30, "2026-07-15")
    record_settlement_tick(4.60, "2026-10-05")
    record_settlement_tick(4.80, "2026-10-20")
    record_quote_tick(9.99, "2026-10-10")
    return ctx


class TestPerformanceBenchmark:
    def test_benchmark_marketing_year_average(self, api):
        """PRD §3.11: "The `weighted_avg_sale_price` is the sum of `bushels`
        multiplied by `effective_price` over those contracts divided by the sum
        of `bushels`, rounded to four decimal places half-up, and null when the
        priced set is empty. The caller selects the benchmark variant through
        an optional `benchmark_method` parameter. Under `MARKETING_YEAR_AVG` —
        the default — the benchmark window runs from June 1 of the crop year
        through May 31 of the following year, inclusive, averaging every
        `SETTLEMENT` tick in the twelve-month marketing year." and "The
        `outperformance_bps` is the weighted average sale price minus the
        benchmark price, divided by the benchmark price, multiplied by ten
        thousand, rounded half-up to a whole basis point, and null when either
        input is null."

        Design: Difficulty/dual_variant_calc/benchmark_marketing_year_vs_harvest_window
        """
        ctx = _benchmark_ctx(api)
        grower = make_grower_headers(ctx["operation"]["id"])
        report = get_success_data(api.get_performance_report(ctx["operation"]["id"], grower))
        assert report["weighted_avg_sale_price"] == pytest.approx(4.6233, abs=5e-5), (
            f"(10000*4.55 + 9550*4.70) / 19550 == 4.6233, got {report['weighted_avg_sale_price']}"
        )
        assert report["benchmark_price"] == pytest.approx(4.4750, abs=5e-5), (
            f"mean of 4.20/4.30/4.60/4.80 == 4.4750, got {report['benchmark_price']}"
        )
        assert report["outperformance_bps"] == 331, (
            f"round((4.6233 - 4.4750) / 4.4750 * 10000) == 331, got {report['outperformance_bps']}"
        )
        assert report["benchmark_tick_count"] == 4, "only the four SETTLEMENT ticks in the year count"

    def test_benchmark_harvest_window_variant_reverses_sign(self, api):
        """PRD §3.11: "Under `HARVEST_WINDOW_AVG` the window runs from October
        1 through October 31 of the crop year, inclusive, averaging only ticks
        inside the October harvest window; identical trades therefore benchmark
        against a different number under the two variants." and "The
        `benchmark_price` is the mean of `SETTLEMENT` tick prices for the
        operation's `primary_commodity` whose `price_date` falls inside the
        selected window, rounded to four decimal places half-up, and null when
        no such tick exists."

        Design: Difficulty/dual_variant_calc/benchmark_marketing_year_vs_harvest_window
        """
        ctx = _benchmark_ctx(api)
        grower = make_grower_headers(ctx["operation"]["id"])
        report = get_success_data(api.get_performance_report(
            ctx["operation"]["id"], grower, params={"benchmark_method": "HARVEST_WINDOW_AVG"}
        ))
        assert report["weighted_avg_sale_price"] == pytest.approx(4.6233, abs=5e-5)
        assert report["benchmark_price"] == pytest.approx(4.7000, abs=5e-5), (
            "only 2026-10-05 (4.60) and 2026-10-20 (4.80) fall in the October window; "
            "the 9.99 QUOTE tick must be excluded"
        )
        assert report["outperformance_bps"] == -163, (
            f"round((4.6233 - 4.7000) / 4.7000 * 10000) == -163, got {report['outperformance_bps']}"
        )
        assert report["benchmark_tick_count"] == 2
        # Sign reversal purely from the variant's input-set window.
        year_report = get_success_data(api.get_performance_report(ctx["operation"]["id"], grower))
        assert year_report["outperformance_bps"] != report["outperformance_bps"]

    def test_performance_report_empty_priced_set_nulls(self, api):
        """PRD §3.11: "The `weighted_avg_sale_price` is the sum of `bushels`
        multiplied by `effective_price` over those contracts divided by the sum
        of `bushels`, rounded to four decimal places half-up, and null when the
        priced set is empty." and "The `benchmark_price` is the mean of
        `SETTLEMENT` tick prices for the operation's `primary_commodity` whose
        `price_date` falls inside the selected window, rounded to four decimal
        places half-up, and null when no such tick exists. The
        `outperformance_bps` is the weighted average sale price minus the
        benchmark price, divided by the benchmark price, multiplied by ten
        thousand, rounded half-up to a whole basis point, and null when either
        input is null. The report also returns `priced_contract_count` and
        `benchmark_tick_count`."

        Design: Difficulty/boundary_precision_check/performance_report_empty_priced_set_nulls
        """
        ctx = setup_operation_with_active_plan(
            name="Empty Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        report = get_success_data(api.get_performance_report(
            ctx["operation"]["id"], make_grower_headers(ctx["operation"]["id"])
        ))
        assert report["priced_contract_count"] == 0
        assert report["benchmark_tick_count"] == 0
        assert report["weighted_avg_sale_price"] is None, "empty priced set reports null, not zero"
        assert report["benchmark_price"] is None, "no ticks in window reports null, not zero"
        assert report["outperformance_bps"] is None, "null inputs propagate to a null outperformance"

    def test_performance_report_empty_set_returns_200_not_error(self, api):
        """PRD §3.11: "The report also returns `priced_contract_count` and
        `benchmark_tick_count`." and "The `outperformance_bps` is the weighted
        average sale price minus the benchmark price, divided by the benchmark
        price, multiplied by ten thousand, rounded half-up to a whole basis
        point, and null when either input is null."

        Design: Difficulty/boundary_precision_check/performance_report_empty_priced_set_nulls
        """
        ctx = setup_operation_with_active_plan(
            name="Empty Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        resp = api.get_performance_report(
            ctx["operation"]["id"], make_grower_headers(ctx["operation"]["id"])
        )
        report = validate_success(resp, expected_status=200)
        assert report["priced_contract_count"] == 0
        assert report["weighted_avg_sale_price"] is None
        assert report["outperformance_bps"] is None


class TestCashFlowProjection:
    def test_cash_flow_projection_month_buckets(self, api):
        """PRD §3.11: "The cash-flow projection buckets events by calendar
        month, ascending from the earliest contributing event through an
        optional `through_date`. Each bucket's inflow accumulates the
        `ticket_value_dollars` of confirmed, non-voided delivery tickets whose
        `delivery_date` falls in that month. Each bucket's outflow accumulates
        two components: for every storage lot occupying the month — a lot
        occupies month m when its `start_date` is on or before the last day of
        m and its end reference is on or after the first day of m — the lot's
        `bushels` multiplied by its `cost_per_bushel_month`; and for every
        `LONG_PUT` position of the operation, whether `OPEN`, `OFFSET`, or
        `LIQUIDATED`, the premium cost of `bushels` multiplied by
        `premium_per_bushel` in the position's execution month. Within a
        bucket, `net_cash_flow` is inflow minus outflow, and
        `cumulative_cash_flow` runs in month order — the projection is
        order-sensitive: buckets are reported ascending, and events sharing a
        month aggregate before netting. The projection returns the `buckets`
        array plus `total_inflow`, `total_outflow`, and `net_cash_flow` across
        the whole horizon."

        Design: Corner/calculations/cash_flow_projection_month_buckets
        """
        ctx = setup_active_plan_with_buyer(
            name="CF Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        contract = create_flat_contract(
            ctx, bushels=10000, fixed_price=4.50,
            delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
        )
        create_confirmed_delivery(ctx, contract, delivery_date="2026-10-12", gross_bushels=10000, moisture_pct=15.0)
        get_success_data(api.create_storage_lot(
            create_storage_lot_payload(
                ctx["operation"]["id"], bin_id="BIN-1", bushels=10000,
                start_date="2026-10-01", planned_end_date="2026-12-31",
                cost_per_bushel_month=0.03, annual_interest_rate=0.06,
            ),
            make_grower_headers(ctx["operation"]["id"]),
        ))
        report = get_success_data(api.get_cash_flow_projection(
            ctx["operation"]["id"], ADVISOR, params={"through_date": "2026-12-31"}
        ))
        assert report["total_inflow"] == pytest.approx(45000.00, abs=0.005)
        assert report["total_outflow"] == pytest.approx(900.00, abs=0.005)
        assert report["net_cash_flow"] == pytest.approx(44100.00, abs=0.005)
        months = [b["month"] for b in report["buckets"]]
        assert months == sorted(months), "buckets must be reported ascending"
        assert months == ["2026-10", "2026-11", "2026-12"], f"got {months}"
        by_month = {b["month"]: b for b in report["buckets"]}
        assert by_month["2026-10"]["net_cash_flow"] == pytest.approx(44700.00, abs=0.005)
        assert by_month["2026-11"]["net_cash_flow"] == pytest.approx(-300.00, abs=0.005)
        assert by_month["2026-12"]["net_cash_flow"] == pytest.approx(-300.00, abs=0.005)


class TestStorage:
    def test_storage_breakeven_part_month_ceil(self, api):
        """PRD §3.9: "The end reference is the lot's `actual_end_date` when it
        is `WITHDRAWN`, else its `planned_end_date`. The elapsed time is the
        calendar-day difference between the end reference and `start_date`,
        converted to months by dividing by 30 and rounding up — any part-month
        counts as a full month. The carry charge is `bushels` multiplied by
        `cost_per_bushel_month` multiplied by the month count, rounded to two
        decimals half-up. The interest charge is `bushels` multiplied by the
        harvest value per bushel, multiplied by `annual_interest_rate`,
        multiplied by the month count, divided by 12, rounded to two decimals
        half-up. The harvest value per bushel is the latest `SETTLEMENT` tick
        price for the operation's `primary_commodity`; when no settlement tick
        exists the computation is rejected with `ERR_NO_SETTLEMENT_PRICE`. The
        breakeven sale price is the sum of the harvest value of the lot —
        `bushels` multiplied by the harvest value per bushel — plus the carry
        plus the interest, divided by `bushels`, rounded to two decimals
        half-up. The computed read returns the `months` count,
        `carry_dollars`, `interest_dollars`, and `breakeven_sale_price`."

        Design: Corner/calculations/storage_breakeven_part_month_ceil
        """
        op = create_operation(
            name="Store Farm", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        record_settlement_tick(4.40, "2026-10-01")
        lot = get_success_data(api.create_storage_lot(
            create_storage_lot_payload(
                op["id"], bin_id="BIN-3", bushels=50000,
                start_date="2026-10-01", planned_end_date="2027-02-15",
                cost_per_bushel_month=0.03, annual_interest_rate=0.06,
            ),
            make_grower_headers(op["id"]),
        ))
        report = get_success_data(api.get_storage_breakeven(lot["id"], ADVISOR))
        assert report["months"] == 5, f"ceil(137 / 30) == 5, got {report['months']}"
        assert report["carry_dollars"] == pytest.approx(7500.00, abs=0.005)
        assert report["interest_dollars"] == pytest.approx(5500.00, abs=0.005)
        assert report["breakeven_sale_price"] == pytest.approx(4.66, abs=0.005), (
            "(50000*4.40 + 7500.00 + 5500.00) / 50000 == 4.66; got "
            f"{report['breakeven_sale_price']}"
        )

    def test_storage_bin_seven_day_buffer_gap(self, api):
        """PRD §2.8: "Second, storage lots sharing one bin observe a seven-day
        buffer. A new lot in the same bin as an existing `STORED` lot is
        rejected with `ERR_STORAGE_BIN_OVERLAP` unless the new lot's
        `start_date` is at least seven days after the existing lot's
        `planned_end_date`, or the new lot's `planned_end_date` is at least
        seven days before the existing lot's `start_date`. Adjacency falling
        inside the buffer is rejected."

        Design: Difficulty/resource_temporal_overlap/storage_bin_seven_day_buffer_gap
        """
        op = create_operation(
            name="Bin Farm", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        grower = make_grower_headers(op["id"])
        get_success_data(api.create_storage_lot(
            create_storage_lot_payload(
                op["id"], bin_id="BIN-7", bushels=30000,
                start_date="2026-10-01", planned_end_date="2026-10-31",
                cost_per_bushel_month=0.03, annual_interest_rate=0.06,
            ),
            grower,
        ))
        too_soon = api.create_storage_lot(
            create_storage_lot_payload(
                op["id"], bin_id="BIN-7", bushels=10000,
                start_date="2026-11-05", planned_end_date="2026-12-15",
                cost_per_bushel_month=0.03, annual_interest_rate=0.06,
            ),
            grower,
        )
        validate_error(too_soon, ApiErrorId.ERR_STORAGE_BIN_OVERLAP)

    def test_storage_bin_buffer_satisfied_after_seven_days(self, api):
        """PRD §2.8: "Second, storage lots sharing one bin observe a seven-day
        buffer. A new lot in the same bin as an existing `STORED` lot is
        rejected with `ERR_STORAGE_BIN_OVERLAP` unless the new lot's
        `start_date` is at least seven days after the existing lot's
        `planned_end_date`, or the new lot's `planned_end_date` is at least
        seven days before the existing lot's `start_date`. Adjacency falling
        inside the buffer is rejected."

        Design: Difficulty/resource_temporal_overlap/storage_bin_seven_day_buffer_gap
        """
        op = create_operation(
            name="Bin Farm", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        grower = make_grower_headers(op["id"])
        get_success_data(api.create_storage_lot(
            create_storage_lot_payload(
                op["id"], bin_id="BIN-7", bushels=30000,
                start_date="2026-10-01", planned_end_date="2026-10-31",
                cost_per_bushel_month=0.03, annual_interest_rate=0.06,
            ),
            grower,
        ))
        ok = api.create_storage_lot(
            create_storage_lot_payload(
                op["id"], bin_id="BIN-7", bushels=10000,
                start_date="2026-11-08", planned_end_date="2026-12-15",
                cost_per_bushel_month=0.03, annual_interest_rate=0.06,
            ),
            grower,
        )
        data = validate_success(ok, expected_status=201)
        assert data["status"] == "STORED", "a start eight days after the prior end clears the buffer"


class TestPagination:
    def test_list_pagination_envelope(self, api):
        """PRD §2.3: "List endpoints accept `limit` and `offset` as query
        parameters. When `limit` is omitted it defaults to 10; the minimum
        accepted value is 1 and the maximum is 100. The `offset` parameter
        defaults to 0. List responses are sorted by `created_at` ascending
        unless otherwise specified, and every list response carries `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        envelope."

        Design: Corner/endpoints/list_pagination_envelope
        """
        ids = []
        for i, (name, btype, rating) in enumerate(
            [("PB1", "ELEVATOR", "A"), ("PB2", "PROCESSOR", "B"), ("PB3", "EXPORTER", "C")]
        ):
            buyer = get_success_data(api.create_buyer(
                create_buyer_payload(name=name, buyer_type=btype, credit_rating=rating), ADVISOR
            ))
            ids.append(buyer["id"])
        page1, meta1 = validate_paginated(api.list_buyers(ADVISOR, params={"limit": 2}))
        assert len(page1) == 2, f"limit=2 must return 2 items, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_buyers(ADVISOR, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1, f"offset=2 with 3 total must return 1 item, got {len(page2)}"
        assert meta2["has_more"] is False
        page1_ids = {row["id"] for row in page1}
        assert page2[0]["id"] not in page1_ids, "page 2 must not repeat page-1 items"
