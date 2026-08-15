"""Sales reports: empty-line rejection, per-line settlement rounding, and the
estimate-vs-settlement variant divergence."""
from test_helpers import (
    ApiErrorId,
    create_sales_report,
    make_exhibitor_headers,
    setup_placed_in_live,
    validate_error,
    validate_success,
)


class TestSalesReportCreation:
    def test_sales_report_empty_lines_rejected(self, api):
        """PRD §3.9: "An exhibitor drafts a sales report for a `PLACED`
        application (`ERR_APPLICATION_NOT_PLACED`) by supplying the
        `application_id` and a `lines` array — one entry per sales batch, each
        carrying a `sale_date` and a `gross_cents`; an empty `lines` array is
        rejected with `ERR_SALES_REPORT_EMPTY`, as is an attempt to submit
        one."

        Design: Corner/validations/sales_report_empty_lines_rejected
        """
        bundle = setup_placed_in_live()
        resp = api.create_sales_report(
            {"application_id": bundle["application"]["id"], "lines": []},
            make_exhibitor_headers(bundle["exhibitor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SALES_REPORT_EMPTY)


class TestEstimateVsSettlement:
    def test_tax_estimate_per_day_rounding_times_days(self, api):
        """PRD §3.3: "The show's selling days are counted inclusively from the
        calendar date of `starts_at` through the calendar date of `ends_at`.
        The per-day tax is the application's `estimated_daily_sales_cents`
        multiplied by `sales_tax_rate_bp` and divided by ten thousand, rounded
        half-up to the nearest cent; the `tax_estimate_cents` is that rounded
        per-day figure multiplied by the number of selling days."

        Design: Difficulty/dual_variant_calc/tax_estimate_vs_settlement_rounding_divergence
        """
        bundle = setup_placed_in_live()
        app = bundle["application"]
        # round_half_up(33333 * 875 / 10000) = 2917 per day x 4 selling days.
        assert app["estimated_daily_sales_cents"] == 33333
        assert app["tax_estimate_cents"] == 11668

    def test_settlement_per_line_rounding_diverges_from_estimate(self, api):
        """PRD §3.9: "Submitting — allowed once the convention is `LIVE`, in
        `LOAD_OUT`, or `CLOSED` (`ERR_PHASE_PRECONDITION`) — moves the report to
        the terminal `SUBMITTED` and settles the tax: each line's tax is its
        `gross_cents` multiplied by `sales_tax_rate_bp` and divided by ten
        thousand, rounded half-up to the nearest cent, and the
        `tax_settlement_cents` is the sum of those per-line amounts."
        PRD §3.9: "Because the settlement rounds per line before summing while
        the estimate (§3.3) rounds per day before multiplying, the two figures
        can legitimately disagree for the same underlying sales."

        Design: Difficulty/dual_variant_calc/tax_estimate_vs_settlement_rounding_divergence
        """
        bundle = setup_placed_in_live()
        report = create_sales_report(
            bundle["application"]["id"], bundle["exhibitor"]["id"]
        )  # 3 lines of 33333
        submitted = validate_success(
            api.submit_sales_report(
                report["id"], make_exhibitor_headers(bundle["exhibitor"]["id"])
            )
        )
        assert submitted["status"] == "SUBMITTED"
        # 3 x round_half_up(33333 * 0.0875) = 3 x 2917 = 8751.
        assert submitted["tax_settlement_cents"] == 8751
        # Sum-then-round of the same grosses (99999 * 0.0875 = 8749.9125 ->
        # 8750) is NOT the pinned order.
        assert submitted["tax_settlement_cents"] != 8750
        # The estimate variant (11668) operates on the Application domain and
        # legitimately disagrees.
        assert submitted["tax_settlement_cents"] != 11668


class TestSettlementRoundingOrder:
    def test_settlement_rounds_per_line_then_sums(self, api):
        """PRD §3.9: "each line's tax is its `gross_cents` multiplied by
        `sales_tax_rate_bp` and divided by ten thousand, rounded half-up to the
        nearest cent, and the `tax_settlement_cents` is the sum of those
        per-line amounts."

        Design: Difficulty/combinatorial_formula/sales_tax_settlement_per_line_rounding_order
        """
        bundle = setup_placed_in_live()
        report = create_sales_report(
            bundle["application"]["id"], bundle["exhibitor"]["id"]
        )
        submitted = validate_success(
            api.submit_sales_report(
                report["id"], make_exhibitor_headers(bundle["exhibitor"]["id"])
            )
        )
        # Per-line rounding pinned: 2917 + 2917 + 2917.
        assert submitted["tax_settlement_cents"] == 8751

    def test_settlement_is_not_sum_then_round(self, api):
        """PRD §3.9: "each line's tax is its `gross_cents` multiplied by
        `sales_tax_rate_bp` and divided by ten thousand, rounded half-up to the
        nearest cent, and the `tax_settlement_cents` is the sum of those
        per-line amounts."
        PRD §2.6: "Wherever a computation produces a fractional cent or a
        fractional score, the system rounds half up, and the exact points where
        rounding occurs are pinned per calculation in Section 3"

        Design: Difficulty/combinatorial_formula/sales_tax_settlement_per_line_rounding_order
        """
        bundle = setup_placed_in_live()
        app_id = bundle["application"]["id"]
        ex_headers = make_exhibitor_headers(bundle["exhibitor"]["id"])

        # The same total gross (99999) split three ways...
        three_line = create_sales_report(app_id, bundle["exhibitor"]["id"])
        submitted_three = validate_success(
            api.submit_sales_report(three_line["id"], ex_headers)
        )
        # ...versus a single line, proves the rounding point: per line, then
        # sum. One line rounds 8749.9125 -> 8750; three lines sum to 8751.
        one_line = create_sales_report(
            app_id,
            bundle["exhibitor"]["id"],
            lines=[{"sale_date": "2026-10-15", "gross_cents": 99999}],
        )
        submitted_one = validate_success(
            api.submit_sales_report(one_line["id"], ex_headers)
        )
        assert submitted_three["tax_settlement_cents"] == 8751
        assert submitted_one["tax_settlement_cents"] == 8750
