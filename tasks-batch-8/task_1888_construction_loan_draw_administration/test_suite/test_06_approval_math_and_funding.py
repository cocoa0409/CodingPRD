"""Approval mathematics, dual progress variants, funding cascade, mark-installed."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_inspection,
    add_draw,
    add_draw_documents,
    add_stored_line_item,
    add_work_line_item,
    approve_draw,
    complete_inspection,
    fund_draw,
    get_budget_line,
    get_draw,
    get_draw_line_item,
    get_loan,
    make_borrower_headers,
    order_inspection,
    progress_draw,
    setup_funded_scenario,
    setup_loan_with_lines,
    start_review_draw,
    submit_draw,
    validate_error,
    validate_success,
)

PROCESSOR = TEST_USERS["draw_processor_headers"]
OFFICER = TEST_USERS["credit_officer_headers"]
SERVICER = TEST_USERS["loan_servicer_headers"]


class TestDualProgressVariants:
    def _funded_three_line_loan(self):
        """Canonical funded draw on a loan with three budget lines (80M total)."""
        return setup_funded_scenario(
            reserve_cents=200_000,
            extra_line_specs=(("FRAM", "Framing", 30_000_000, False),
                              ("CONT", "Contingency", 10_000_000, True)),
        )

    def test_dual_progress_percents_diverge(self, api):
        """PRD §3.4: "`ACCEPTED` is consequential: the loan's
        `inspection_percent_complete` is recomputed as the
        `percent_complete_reported` of the loan's latest `ACCEPTED` inspection".
        PRD §3.4: "The cost-based `cost_percent_complete` is a reporting field: the
        sum, across all of the loan's budget lines in any status, of each line's
        `disbursed_cents` plus its `retained_cents`, divided by the sum of all
        lines' `revised_amount_cents`, multiplied by 100, and rounded half-up to
        two decimal places".
        PRD §3.4: "Identical inputs produce different percents under the two
        variants, by design."

        Design: Difficulty/dual_variant_calc/progress_percent_dual_basis
        """
        sc = self._funded_three_line_loan()
        loan = get_loan(sc["loan"]["id"])
        assert loan["inspection_percent_complete"] == 50.00, (
            "inspection variant reads the latest ACCEPTED inspection"
        )
        # cost variant: (9500000 + 500000) / 80000000 * 100 = 12.50
        assert loan["cost_percent_complete"] == 12.50, (
            "cost variant uses funded dollars over revised budget"
        )

    def test_dual_progress_loan_aggregates(self, api):
        """PRD §3.4: "Whenever that recomputed value reaches or exceeds the loan's
        `retainage_milestone_pct` — an inclusive boundary — the loan's
        `milestone_reached` latches true and never flips back".
        PRD §3.5: "On the loan, `principal_disbursed_cents`, `retained_cents`, and
        `cost_percent_complete` are recomputed".

        Design: Difficulty/dual_variant_calc/progress_percent_dual_basis
        """
        sc = self._funded_three_line_loan()
        loan = get_loan(sc["loan"]["id"])
        assert loan["milestone_reached"] is True, (
            "50.00 reaches the default 50.00 milestone (inclusive boundary)"
        )
        assert loan["principal_disbursed_cents"] == 9_500_000
        assert loan["retained_cents"] == 500_000


class TestRetainageRounding:
    def _approve_two_line_draw(self):
        """Two lines approved 105 each at 10% standard retainage."""
        sc = setup_loan_with_lines(
            line_specs=(("X1", "Line X", 10_000, False),
                        ("Y1", "Line Y", 10_000, False)),
            commitment_amount_cents=1_000_000,
        )
        draw = add_draw(sc)
        item_x = add_work_line_item(draw["id"], sc["lines"]["X1"]["id"], 105,
                                    sc["borrower"]["id"])
        item_y = add_work_line_item(draw["id"], sc["lines"]["Y1"]["id"], 105,
                                    sc["borrower"]["id"])
        add_draw_documents(sc, draw["id"], (
            ("INVOICE", 210, True),
            ("LIEN_WAIVER_CONDITIONAL", 210, True),
        ))
        progress_draw(sc, draw["id"], inspection_pct=40.00, approve=True)
        return sc, draw, item_x, item_y

    def test_retainage_rounding_per_line(self, api):
        """PRD §3.5: "Each line's `retainage_cents` is its `approved_cents`
        multiplied by that effective percent and divided by 100, rounded half up to
        a whole cent".
        PRD §2.5: "Retainage has its own pinned rounding order: every draw line
        item is rounded to whole cents first, and only then are the per-line
        amounts summed into the draw total; summing first and rounding once is not
        equivalent and is not permitted."

        Design: Difficulty/combinatorial_formula/retainage_rounding_per_line_then_sum
        """
        _sc, _draw, item_x, item_y = self._approve_two_line_draw()
        x = get_draw_line_item(item_x["id"])
        y = get_draw_line_item(item_y["id"])
        assert x["approved_cents"] == 105
        # round_half_up(105 * 10.00 / 100) = round_half_up(10.5) = 11 per line
        assert x["retainage_cents"] == 11, "105 at 10% rounds half up to 11"
        assert y["retainage_cents"] == 11
        assert x["net_fundable_cents"] == 105 - 11

    def test_retainage_rounding_draw_totals(self, api):
        """PRD §2.5: "Retainage has its own pinned rounding order: every draw line
        item is rounded to whole cents first, and only then are the per-line
        amounts summed into the draw total; summing first and rounding once is not
        equivalent and is not permitted."
        PRD §3.5: "The effective percent is the loan's `reduced_retainage_pct` when
        `milestone_reached` is true at that moment and its `retainage_pct`
        otherwise."

        Design: Difficulty/combinatorial_formula/retainage_rounding_per_line_then_sum
        """
        _sc, draw, _x, _y = self._approve_two_line_draw()
        approved = get_draw(draw["id"])
        # per-line-then-sum: 11 + 11 = 22 (sum-then-round would give 21)
        assert approved["retainage_total_cents"] == 22, (
            "Per-line rounding is pinned: 11 + 11, not round(210 * 0.10) = 21"
        )
        assert approved["effective_retainage_pct"] == 10.00, (
            "Milestone not reached at 40.00, so the standard 10.00 pct applies"
        )
        assert approved["milestone_applied"] is False


class TestStoredMaterialsCaps:
    def _approve_stored_draw(self):
        """One STORED_MATERIALS line: requested 200000, invoice value 200000."""
        sc = setup_loan_with_lines(
            line_specs=(("MATS", "Materials", 1_000_000, False),))
        draw = add_draw(sc)
        item = add_stored_line_item(
            draw["id"], sc["lines"]["MATS"]["id"], 200_000, 200_000,
            sc["borrower"]["id"], insurance_ref="CERT-77")
        add_draw_documents(sc, draw["id"], (
            ("LIEN_WAIVER_CONDITIONAL", 200_000, True),
        ))
        submit_draw(draw["id"], sc["borrower"]["id"])
        start_review_draw(draw["id"])
        insp = order_inspection(sc["loan"]["id"], "2026-03-20", draw_id=draw["id"])
        complete_inspection(insp["id"], 40.00, "2026-03-21",
                            stored_materials_observed_cents=200_000)
        accept_inspection(insp["id"])
        approve_draw(draw["id"])
        return sc, draw, item

    def test_stored_materials_invoice_cap_binds(self, api):
        """PRD §3.5: "A `STORED_MATERIALS` line adds a fourth ceiling, the
        stored-materials advance cap: if the line's `is_installed` is true the cap
        equals its full `stored_material_invoice_cents`, and otherwise the cap is
        that invoice value multiplied by the loan's `stored_materials_max_pct` and
        divided by 100, rounded down to a whole cent — so an uninstalled line may
        be advanced at most 75% of invoice value under default policy."

        Design: Difficulty/combinatorial_formula/stored_materials_min_of_caps
        """
        _sc, _draw, item = self._approve_stored_draw()
        settled = get_draw_line_item(item["id"])
        # min(requested 200000, headroom 1000000, inspection cap 400000,
        #     floor(200000 * 75%) = 150000) -> the advance cap binds
        assert settled["approved_cents"] == 150_000, (
            "The 75%-of-invoice advance cap is the smallest ceiling"
        )

    def test_stored_materials_retainage_and_net(self, api):
        """PRD §3.5: "Each line's `retainage_cents` is its `approved_cents`
        multiplied by that effective percent and divided by 100, rounded half up to
        a whole cent — and the rounding order is pinned".
        PRD §3.5: "A line's `net_fundable_cents` is then its `approved_cents` minus
        its `retainage_cents`."

        Design: Difficulty/combinatorial_formula/stored_materials_min_of_caps
        """
        _sc, draw, item = self._approve_stored_draw()
        settled = get_draw_line_item(item["id"])
        assert settled["retainage_cents"] == 15_000, (
            "10% standard retainage on 150000 (milestone 40.00 not reached)"
        )
        assert settled["net_fundable_cents"] == 135_000
        assert get_draw(draw["id"])["status"] == "APPROVED"


class TestMilestoneBoundary:
    def _two_draw_boundary_loan(self):
        """Draw 1 at inspection 49.99 APPROVED; draw 2 ready at 50.00."""
        sc = setup_loan_with_lines(
            line_specs=(("SITE", "Site work", 1_000_000, False),))
        d1 = add_draw(sc, period_start="2026-03-01", period_end="2026-03-31")
        add_work_line_item(d1["id"], sc["lines"]["SITE"]["id"], 100_000,
                           sc["borrower"]["id"])
        add_draw_documents(sc, d1["id"], (
            ("INVOICE", 100_000, True),
            ("LIEN_WAIVER_CONDITIONAL", 100_000, True),
        ))
        progress_draw(sc, d1["id"], inspection_pct=49.99,
                      inspection_scheduled="2026-03-19",
                      inspection_completed="2026-03-20", approve=True)
        d2 = add_draw(sc, period_start="2026-04-01", period_end="2026-04-30")
        add_work_line_item(d2["id"], sc["lines"]["SITE"]["id"], 100_000,
                           sc["borrower"]["id"])
        add_draw_documents(sc, d2["id"], (
            ("INVOICE", 100_000, True),
            ("LIEN_WAIVER_CONDITIONAL", 100_000, True),
        ), doc_date="2026-04-25")
        progress_draw(sc, d2["id"], inspection_pct=50.00,
                      inspection_scheduled="2026-04-19",
                      inspection_completed="2026-04-20", approve=True)
        return sc, d1, d2

    def test_milestone_below_boundary_standard_retainage(self, api):
        """PRD §3.4: "Whenever that recomputed value reaches or exceeds the loan's
        `retainage_milestone_pct` — an inclusive boundary — the loan's
        `milestone_reached` latches true and never flips back".
        PRD §3.5: "The effective percent is the loan's `reduced_retainage_pct` when
        `milestone_reached` is true at that moment and its `retainage_pct`
        otherwise."

        Design: Difficulty/boundary_precision_check/milestone_exactly_50_reduced_retainage
        """
        _sc, d1, _d2 = self._two_draw_boundary_loan()
        draw1 = get_draw(d1["id"])
        assert draw1["retainage_total_cents"] == 10_000, (
            "49.99 does not reach 50.00: standard 10.00 pct withholds 10000"
        )
        assert draw1["milestone_applied"] is False

    def test_milestone_at_boundary_reduced_retainage(self, api):
        """PRD §3.4: "Whenever that recomputed value reaches or exceeds the loan's
        `retainage_milestone_pct` — an inclusive boundary — the loan's
        `milestone_reached` latches true and never flips back".
        PRD §3.5: "The effective percent is the loan's `reduced_retainage_pct` when
        `milestone_reached` is true at that moment and its `retainage_pct`
        otherwise."

        Design: Difficulty/boundary_precision_check/milestone_exactly_50_reduced_retainage
        """
        sc, _d1, d2 = self._two_draw_boundary_loan()
        draw2 = get_draw(d2["id"])
        assert draw2["retainage_total_cents"] == 5_000, (
            "Exactly 50.00 reaches the milestone: reduced 5.00 pct withholds 5000"
        )
        assert draw2["milestone_applied"] is True
        assert get_loan(sc["loan"]["id"])["milestone_reached"] is True


class TestApprovedUnfundedHeadroom:
    def test_approved_unfunded_reserved_headroom(self, api):
        """PRD §3.5: "Each budget line touched by the draw has its
        `approved_unfunded_cents` recomputed — that field is the sum of
        `approved_cents` over the line's items sitting in `APPROVED`, not yet
        `FUNDED`, draws, reserving headroom against later approvals".
        PRD §3.5: "Its cost headroom is the budget line's `revised_amount_cents`
        minus its `disbursed_cents`, minus its `retained_cents`, minus its
        `approved_unfunded_cents` — the budget not yet consumed or reserved."

        Design: Corner/calculations/approved_unfunded_reserved_headroom
        """
        sc = setup_loan_with_lines(
            line_specs=(("SITE", "Site work", 1_000_000, False),))
        d1 = add_draw(sc, period_start="2026-03-01", period_end="2026-03-31")
        add_work_line_item(d1["id"], sc["lines"]["SITE"]["id"], 100_000,
                           sc["borrower"]["id"])
        add_draw_documents(sc, d1["id"], (
            ("INVOICE", 100_000, True),
            ("LIEN_WAIVER_CONDITIONAL", 100_000, True),
        ))
        progress_draw(sc, d1["id"], inspection_pct=50.00,
                      inspection_scheduled="2026-03-19",
                      inspection_completed="2026-03-20", approve=True)

        d2 = add_draw(sc, period_start="2026-04-01", period_end="2026-04-30")
        add_work_line_item(d2["id"], sc["lines"]["SITE"]["id"], 950_000,
                           sc["borrower"]["id"])
        add_draw_documents(sc, d2["id"], (
            ("INVOICE", 950_000, True),
            ("LIEN_WAIVER_CONDITIONAL", 950_000, True),
        ), doc_date="2026-04-25")
        progress_draw(sc, d2["id"], inspection_pct=100.00,
                      inspection_scheduled="2026-04-19",
                      inspection_completed="2026-04-20", approve=True)

        draw2 = get_draw(d2["id"])
        # headroom = 1000000 - 0 - 0 - 100000 = 900000; inspection cap
        # floor(1000000 * 100%) - 100000 = 900000; requested 950000 is capped.
        assert draw2["approved_total_cents"] == 900_000, (
            "The APPROVED-not-FUNDED draw 1 reserves 100000 of headroom"
        )
        line = get_budget_line(sc["lines"]["SITE"]["id"])
        assert line["approved_unfunded_cents"] == 1_000_000, (
            "100000 + 900000 reserved across two APPROVED draws"
        )


class TestFundingCascade:
    def _approved_draw(self):
        sc = setup_loan_with_lines()
        draw = add_draw(sc)
        item = add_work_line_item(draw["id"], sc["lines"]["SITE"]["id"],
                                  10_000_000, sc["borrower"]["id"])
        add_draw_documents(sc, draw["id"], (
            ("INVOICE", 10_000_000, True),
            ("LIEN_WAIVER_CONDITIONAL", 10_000_000, True),
        ))
        progress_draw(sc, draw["id"], inspection_pct=50.00, approve=True)
        return sc, draw, item

    def test_fund_cascade_draw_and_items(self, api):
        """PRD §3.5: "Funding cascades through three levels. On each line item,
        `funded_cents` is set to its `net_fundable_cents`."
        PRD §3.5: "The draw's `funded_total_cents` becomes the sum of its items'
        `funded_cents`, and the draw settles into the terminal `FUNDED` state."

        Design: Difficulty/transitive_cascade/fund_cascade_three_levels
        """
        sc, draw, item = self._approved_draw()
        funded = validate_success(api.fund_draw(draw["id"], SERVICER), 200)
        assert funded["status"] == "FUNDED"
        # approved 10000000, milestone reached -> 5% retainage 500000, net 9500000
        assert funded["funded_total_cents"] == 9_500_000
        settled_item = get_draw_line_item(item["id"])
        assert settled_item["funded_cents"] == 9_500_000, (
            "funded_cents is set to net_fundable_cents at funding"
        )

    def test_fund_cascade_budget_line_and_loan(self, api):
        """PRD §3.5: "On each touched budget line, `disbursed_cents` grows by the
        line's `net_fundable_cents`, `retained_cents` grows by the line's
        `retainage_cents`, and `approved_unfunded_cents` shrinks by the line's
        `approved_cents`, with the budget line's `version` incrementing. On the
        loan, `principal_disbursed_cents`, `retained_cents`, and
        `cost_percent_complete` are recomputed and the loan's `version` increments
        by one."

        Design: Difficulty/transitive_cascade/fund_cascade_three_levels
        """
        sc, draw, _item = self._approved_draw()
        fund_draw(draw["id"])

        line = get_budget_line(sc["lines"]["SITE"]["id"])
        assert line["disbursed_cents"] == 9_500_000
        assert line["retained_cents"] == 500_000
        assert line["approved_unfunded_cents"] == 0, (
            "The approved reservation is consumed by funding"
        )
        loan = get_loan(sc["loan"]["id"])
        assert loan["principal_disbursed_cents"] == 9_500_000
        assert loan["retained_cents"] == 500_000
        # (9500000 + 500000) / 40000000 * 100 = 25.00
        assert loan["cost_percent_complete"] == 25.00


class TestMarkInstalled:
    def test_mark_installed_transitions(self, api):
        """PRD §3.5: "Once a draw is `APPROVED` or `FUNDED`, a `DrawProcessor` may
        mark a stored-materials line installed, supplying the `installed_date`; the
        line's `is_installed` becomes true and the date is recorded. The capability
        exists only for `STORED_MATERIALS` lines — invoking it on a
        `WORK_COMPLETED` line is rejected with `ERR_LINE_NOT_STORED_MATERIALS`
        (HTTP 422) — and only while the owning draw is `APPROVED` or `FUNDED`; a
        draw in any other state, or a repeat marking of an already-installed line,
        is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/mark_installed_transitions
        """
        sc = setup_loan_with_lines(line_specs=(
            ("WRK", "Work", 1_000_000, False),
            ("MATS", "Materials", 1_000_000, False),
        ))
        draw = add_draw(sc)
        item_w = add_work_line_item(draw["id"], sc["lines"]["WRK"]["id"], 100_000,
                                    sc["borrower"]["id"])
        item_s = add_stored_line_item(draw["id"], sc["lines"]["MATS"]["id"],
                                      200_000, 200_000, sc["borrower"]["id"],
                                      insurance_ref="CERT-9",
                                      stored_location="Lot 9")
        add_draw_documents(sc, draw["id"], (
            ("INVOICE", 100_000, True),
            ("LIEN_WAIVER_CONDITIONAL", 300_000, True),
        ))
        progress_draw(sc, draw["id"], inspection_pct=40.00, approve=True)

        wrong_type = api.mark_installed(
            item_w["id"], {"installed_date": "2026-04-10"}, PROCESSOR)
        validate_error(wrong_type, ApiErrorId.ERR_LINE_NOT_STORED_MATERIALS)

        marked = validate_success(api.mark_installed(
            item_s["id"], {"installed_date": "2026-04-10"}, PROCESSOR), 200)
        assert marked["is_installed"] is True
        assert marked["installed_date"] == "2026-04-10"

        repeat = api.mark_installed(
            item_s["id"], {"installed_date": "2026-04-11"}, PROCESSOR)
        validate_error(repeat, ApiErrorId.ERR_INVALID_STATE)
        after = get_draw_line_item(item_s["id"])
        assert after["installed_date"] == "2026-04-10", (
            "The repeat marking does not overwrite the recorded date"
        )
