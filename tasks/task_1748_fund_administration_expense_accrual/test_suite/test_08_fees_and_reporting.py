"""Fee invoices (tiered + contiguous tiling), performance vs benchmark, and
the audit-support trial balance."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_fee_invoice,
    assert_money,
    assert_rate,
    base_kit_with_final_nav,
    create_fee_invoice_payload,
    create_nav,
    declared_distribution_kit,
    finalize_nav,
    set_logical_clock,
    submit_price,
    approve_price,
    make_fund_accountant_headers,
    validate_error,
    validate_success,
)

CTRL = TEST_USERS["fund_controller_headers"]
ACCT = TEST_USERS["fund_accountant_headers"]


def _create_invoice(fund_id, start, end):
    return api_client.create_fee_invoice(
        create_fee_invoice_payload(fund_id, period_start=start, period_end=end),
        make_fund_accountant_headers("acct_1"),
    )


def _straddle_kit():
    """FINAL record with TNA 119999671.23 (position 1.2M @ 100.00)."""
    return base_kit_with_final_nav(
        quantity=1200000,
        fund_overrides={
            "adviser_fee_tiers": [
                {"up_to_net_assets": 100000000, "rate_bps": 50},
                {"up_to_net_assets": None, "rate_bps": 40},
            ]
        },
    )


def test_adviser_fee_tiered_straddle_gross(api):
    """PRD §3.9: "For an `ADVISER` invoice, the gross fee walks the fund's
    `adviser_fee_tiers` marginally in ascending order: each tier contributes
    the portion of the average falling between the previous tier's ceiling
    (zero for the first tier) and its own `up_to_net_assets` — the last tier,
    whose ceiling is null, being unbounded — floored at zero, multiplied by
    that tier's `rate_bps`."
    PRD §3.9: "Either way, the `gross_fee` is the aggregated rate-units divided
    by ten thousand, multiplied by the day count, divided by 365, rounded to
    two decimal places half-up."

    Design: Difficulty/combinatorial_formula/adviser_fee_tiered_marginal_straddle
    """
    kit = _straddle_kit()
    resp = api.create_fee_invoice(
        create_fee_invoice_payload(
            kit["fund"]["id"], period_start="2026-08-01",
            period_end="2026-10-29",
        ),
        make_fund_accountant_headers("acct_1"),
    )
    invoice = validate_success(resp, 201)
    assert_fee_invoice(invoice)
    # Single contributing FINAL date: ADNA is that day's TNA.
    assert_money(invoice["average_daily_net_assets"], 119999671.23,
                 "average_daily_net_assets")
    # 100M x 50bps + 19,999,671.23 x 40bps, scaled by 90/365 days.
    assert_money(invoice["gross_fee"], 143013.37, "gross_fee")


def test_adviser_fee_net_of_zero_waiver_offset(api):
    """PRD §3.9: "The `waiver_offset` is the sum of `amount` over `WAIVER`
    ledger entries whose `entry_date` falls inside the period across all
    agreements of the fund's classes, and the `net_fee` is the gross fee minus
    the waiver offset, floored at zero and rounded to two decimal places
    half-up."
    PRD §3.9: "The invoice is born `DRAFT` with the preparer's identifier in
    `created_by_user_id`"

    Design: Difficulty/combinatorial_formula/adviser_fee_tiered_marginal_straddle
    """
    kit = _straddle_kit()
    resp = api.create_fee_invoice(
        create_fee_invoice_payload(
            kit["fund"]["id"], period_start="2026-08-01",
            period_end="2026-10-29",
        ),
        make_fund_accountant_headers("acct_1"),
    )
    invoice = validate_success(resp, 201)
    assert_money(invoice["waiver_offset"], 0.00, "waiver_offset")
    assert_money(invoice["net_fee"], 143013.37, "net_fee")
    assert invoice["status"] == "DRAFT"
    assert invoice["created_by_user_id"] == "acct_1"


def _tiling_kit():
    """Two FINAL records (2026-08-04 and 2026-09-01) and the first ADVISER
    invoice covering 2026-08-01..2026-08-31."""
    kit = base_kit_with_final_nav(
        fund_overrides={
            "adviser_fee_tiers": [
                {"up_to_net_assets": 100000000, "rate_bps": 50},
                {"up_to_net_assets": None, "rate_bps": 40},
            ]
        },
    )
    set_logical_clock("2026-09-01T00:00:00Z")
    px2 = submit_price(kit["security"]["id"], price_date="2026-09-01")
    approve_price(px2["id"])
    nav2 = create_nav(kit["share_class"]["id"], accounting_date="2026-09-01")
    finalize_nav(nav2["id"], expected_version=nav2["version"])
    inv1 = validate_success(
        _create_invoice(kit["fund"]["id"], "2026-08-01", "2026-08-31"),
        201,
    )
    return kit, inv1


def test_fee_invoice_gap_period_rejected(api):
    """PRD §3.9: "Invoice periods for the same fund and fee type must tile
    contiguously: when a prior invoice in `DRAFT`, `APPROVED`, or `PAID`
    exists, the new `period_start` must be exactly one day after that invoice's
    `period_end`, otherwise the create is rejected with
    `ERR_FEE_PERIOD_NOT_CONTIGUOUS` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/fee_invoice_contiguous_tiling_required
    """
    kit, inv1 = _tiling_kit()
    # 99999.73 x 50bps x 31/365 days.
    assert_money(inv1["gross_fee"], 42.47, "first invoice gross_fee")
    gap = _create_invoice(kit["fund"]["id"], "2026-09-02", "2026-09-30")
    validate_error(gap, ApiErrorId.ERR_FEE_PERIOD_NOT_CONTIGUOUS, 409)


def test_fee_invoice_exact_next_day_accepted(api):
    """PRD §3.9: "Invoice periods for the same fund and fee type must tile
    contiguously: when a prior invoice in `DRAFT`, `APPROVED`, or `PAID`
    exists, the new `period_start` must be exactly one day after that invoice's
    `period_end`, otherwise the create is rejected with
    `ERR_FEE_PERIOD_NOT_CONTIGUOUS` (HTTP 409)."
    PRD §3.9: "Either way, the `gross_fee` is the aggregated rate-units divided
    by ten thousand, multiplied by the day count, divided by 365, rounded to
    two decimal places half-up."

    Design: Difficulty/resource_temporal_overlap/fee_invoice_contiguous_tiling_required
    """
    kit, inv1 = _tiling_kit()
    ok = _create_invoice(kit["fund"]["id"], "2026-09-01", "2026-09-30")
    invoice = validate_success(ok, 201)
    # 99999.73 x 50bps x 30/365 days.
    assert_money(invoice["gross_fee"], 41.10, "second invoice gross_fee")


def test_fee_invoice_pay_before_approve_rejected(api):
    """PRD §3.9: "Approval, by a `FundController`, enforces segregation of
    duties against `created_by_user_id` (`ERR_SOD_VIOLATION`), records the
    approver in `approved_by_user_id`, and moves the invoice from `DRAFT` to
    `APPROVED`; payment then moves it from `APPROVED` to `PAID`."
    PRD §2.9: "State eligibility of the target resource for the requested
    transition — `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/fee_invoice_pay_before_approve_rejected
    """
    kit = base_kit_with_final_nav()
    invoice = validate_success(
        _create_invoice(kit["fund"]["id"], "2026-08-01", "2026-08-31"),
        201,
    )
    resp = api.pay_fee_invoice(invoice["id"], CTRL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_performance_vs_benchmark_excess(api):
    """PRD §3.9: "The `period_return_pct` is the sum of the end record's
    `nav_per_share` and the distributions-per-share total, divided by the begin
    record's `nav_per_share`, minus one, multiplied by one hundred, rounded to
    four decimal places half-up; the `excess_return_pct` is the
    `period_return_pct` minus the `benchmark_return_pct`, likewise rounded to
    four decimal places half-up."
    PRD §3.9: "The `distributions_per_share_total` is the sum of
    `income_per_share` over the class's `PAID` distributions whose
    `payable_date` falls after the begin record's `accounting_date` and on or
    before the end record's `accounting_date`."

    Design: Corner/calculations/performance_vs_benchmark_excess
    """
    kit = declared_distribution_kit(income=51.00)  # FINAL 2026-08-04 nav 10.0000
    set_logical_clock("2026-08-10T00:00:00Z")
    paid = validate_success(
        api.pay_distribution(kit["distribution"]["id"], {"reinvest": False}, CTRL),
        200,
    )
    assert paid["status"] == "PAID"

    set_logical_clock("2026-08-11T00:00:00Z")
    px2 = submit_price(kit["security"]["id"], price_date="2026-08-11",
                       price=101.00)
    approve_price(px2["id"])
    nav2 = create_nav(kit["share_class"]["id"], accounting_date="2026-08-11")
    finalize_nav(nav2["id"], expected_version=nav2["version"])

    resp = api.get_performance(
        kit["share_class"]["id"], CTRL,
        params={"from_date": "2026-08-04", "to_date": "2026-08-11",
                "benchmark_return_pct": 1.0},
    )
    perf = validate_success(resp, 200)
    assert_rate(perf["begin_nav_per_share"], 10.0000, "begin_nav_per_share")
    assert_rate(perf["end_nav_per_share"], 10.1000, "end_nav_per_share")
    assert_rate(perf["distributions_per_share_total"], 0.0051,
                "distributions_per_share_total")
    # (10.1000 + 0.0051) / 10.0000 - 1 = 0.01051 -> x100 = 1.0510 (PRD §3.9).
    assert_rate(perf["period_return_pct"], 1.0510, "period_return_pct")
    assert_rate(perf["excess_return_pct"], 0.0510, "excess_return_pct")


def test_trial_balance_aggregates_final_records(api):
    """PRD §3.9: "Given an `as_of_date`, each share class of the fund
    contributes its `FINAL` accounting record with the greatest
    `accounting_date` on or before that date — a class with no such record
    contributes zero — and the response sums across classes"
    PRD §3.9: "If no class of the fund has any `FINAL` record on or before the
    `as_of_date`, the read fails with `ERR_NO_FINAL_NAV_IN_PERIOD`."

    Design: Corner/calculations/trial_balance_aggregates_final_records
    """
    kit = base_kit_with_final_nav()
    resp = api.get_trial_balance(
        kit["fund"]["id"], CTRL, params={"as_of_date": "2026-08-04"}
    )
    tb = validate_success(resp, 200)
    assert tb["as_of_date"] == "2026-08-04"
    assert_money(tb["total_market_value"], 100000.00, "total_market_value")
    assert_money(tb["total_accrued_expenses"], 0.27, "total_accrued_expenses")
    assert_money(tb["total_net_assets"], 99999.73, "total_net_assets")

    early = api.get_trial_balance(
        kit["fund"]["id"], CTRL, params={"as_of_date": "2026-08-03"}
    )
    validate_error(early, ApiErrorId.ERR_NO_FINAL_NAV_IN_PERIOD, 422)
