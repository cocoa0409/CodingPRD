"""Submission pricing: pacing-tier branch selection, per-line round-then-sum
rounding, and the budget-cap exact-fit boundary."""
from test_helpers import (
    ApiErrorId,
    add_line_item,
    add_measure,
    assert_program_ledger_invariants,
    build_submitted_application,
    create_active_ally,
    create_draft_application,
    create_program_year,
    get_line_item,
    get_program_year,
    list_line_items_for_application,
    make_trade_ally_headers,
    open_program_year,
    set_clock,
    submit_application,
    validate_error,
)


def _program_with_preload(preload_rate, target_specs, budget=20_000_000,
                          savings_goal=500_000):
    """Open a program whose committed total is preloaded by one submitted
    application. Returns (py, ally, preload_measure, target_measures)."""
    set_clock()
    py = create_program_year(budget_cap_cents=budget, savings_goal_kwh=savings_goal)
    preload_measure = add_measure(
        py["id"], measure_code="M-PRELOAD", base_rate_cents=preload_rate,
        deemed_kwh_per_unit=100,
    )
    target_measures = [
        add_measure(py["id"], **spec) for spec in target_specs
    ]
    py = open_program_year(py["id"])
    ally = create_active_ally()
    build_submitted_application(py, ally, preload_measure, quantity=1,
                                invoice_date="2026-08-01",
                                service_address="1 Preload Ave")
    return py, ally, preload_measure, target_measures


class TestPacingTierBranchSelection:
    def test_standard_tier_when_committed_below_fifty(self, api, admin_headers):
        """PRD §3.4: "Each line is then pinned to a `pacing_tier_at_submit`:
        below fifty percent, `STANDARD_TIER`, priced at the full base rate; at
        least fifty but below eighty percent, `MID_TIER`, priced at eighty
        percent of the base rate (a tier factor of 0.80); at eighty percent or
        above, `HIGH_TIER`, priced at half the base rate (a tier factor of
        0.50)."

        Design: Difficulty/combinatorial_formula/pacing_tier_conditional_branch_selection
        """
        set_clock()
        py = create_program_year(budget_cap_cents=20_000_000)
        measure = add_measure(
            py["id"], measure_code="M-BIG", base_rate_cents=11_000_000,
            deemed_kwh_per_unit=100,
        )
        py = open_program_year(py["id"])
        ally = create_active_ally()
        # First submission happens at committed_pct == 0 -> STANDARD_TIER.
        app, line = build_submitted_application(py, ally, measure, quantity=1)

        line = get_line_item(line["id"])
        assert line["pacing_tier_at_submit"] == "STANDARD_TIER"
        assert line["incentive_cents"] == 11_000_000
        assert app["incentive_total_cents"] == 11_000_000

    def test_mid_tier_at_committed_pct_55(self, api, admin_headers):
        """PRD §3.4: "at least fifty but below eighty percent, `MID_TIER`,
        priced at eighty percent of the base rate (a tier factor of 0.80)"
        PRD §3.4: "The boundaries are inclusive on the lower edge — a committed
        percentage of exactly fifty selects `MID_TIER`, and exactly eighty
        selects `HIGH_TIER`."

        Design: Difficulty/combinatorial_formula/pacing_tier_conditional_branch_selection
        """
        # Preload commits 11,000,000 of 20,000,000 -> committed_pct == 55.
        py, ally, _preload, targets = _program_with_preload(
            11_000_000,
            [{"measure_code": "M-TARGET", "base_rate_cents": 100_000,
              "deemed_kwh_per_unit": 100}],
        )
        app = create_draft_application(py, ally, invoice_date="2026-08-02")
        line = add_line_item(app, targets[0], quantity=5, ally=ally)
        app = submit_application(app, ally)

        line = get_line_item(line["id"])
        assert line["pacing_tier_at_submit"] == "MID_TIER"
        # 100000 * 5 * 0.80 = 400000 (not 500000 standard, not 250000 high).
        assert line["incentive_cents"] == 400_000
        assert app["incentive_total_cents"] == 400_000

    def test_high_tier_at_committed_pct_80(self, api, admin_headers):
        """PRD §3.4: "at eighty percent or above, `HIGH_TIER`, priced at half
        the base rate (a tier factor of 0.50). The boundaries are inclusive on
        the lower edge — a committed percentage of exactly fifty selects
        `MID_TIER`, and exactly eighty selects `HIGH_TIER`."

        Design: Difficulty/combinatorial_formula/pacing_tier_conditional_branch_selection
        """
        # Preload commits 16,000,000 of 20,000,000 -> committed_pct == 80.
        py, ally, _preload, targets = _program_with_preload(
            16_000_000,
            [{"measure_code": "M-TARGET", "base_rate_cents": 100_000,
              "deemed_kwh_per_unit": 100}],
        )
        app = create_draft_application(py, ally, invoice_date="2026-08-02")
        line = add_line_item(app, targets[0], quantity=5, ally=ally)
        app = submit_application(app, ally)

        line = get_line_item(line["id"])
        assert line["pacing_tier_at_submit"] == "HIGH_TIER"
        # 100000 * 5 * 0.50 = 250000.
        assert line["incentive_cents"] == 250_000
        assert app["incentive_total_cents"] == 250_000


class TestPerLineRoundThenSum:
    def test_round_each_line_then_sum(self, api, admin_headers):
        """PRD §2.7: "Where a multiplication would produce a fractional cent —
        the per-line incentive pricing of §3.4 — each line is rounded half-up to
        a whole cent first, and only then are the integer line amounts summed.
        Summing unrounded values and rounding once at the end is explicitly
        forbidden, because the two orders can disagree by a cent on fractional
        inputs."

        Design: Difficulty/combinatorial_formula/application_incentive_per_line_round_then_sum
        """
        # committed_pct == 80 -> HIGH_TIER factor 0.50; each 333-cent unit
        # prices at round_half_up(166.5) == 167 per line.
        py, ally, _preload, targets = _program_with_preload(
            16_000_000,
            [{"measure_code": "M-ODD", "base_rate_cents": 333,
              "deemed_kwh_per_unit": 100}],
        )
        app = create_draft_application(py, ally, invoice_date="2026-08-02")
        add_line_item(app, targets[0], quantity=1, ally=ally)
        add_line_item(app, targets[0], quantity=1, ally=ally)
        app = submit_application(app, ally)

        # Per-line-then-sum: 167 + 167 == 334; sum-then-round would give 333.
        assert app["incentive_total_cents"] == 334
        assert app["incentive_total_cents"] != 333

    def test_each_line_rounded_half_up_individually(self, api, admin_headers):
        """PRD §3.4: "Each line's `incentive_cents` is then the measure's
        `base_rate_cents` multiplied by the line's `quantity` and by the pinned
        tier factor, rounded half-up to a whole cent; per §2.7 the rounding
        happens per line before any summation."

        Design: Difficulty/combinatorial_formula/application_incentive_per_line_round_then_sum
        """
        py, ally, _preload, targets = _program_with_preload(
            16_000_000,
            [{"measure_code": "M-ODD", "base_rate_cents": 333,
              "deemed_kwh_per_unit": 100}],
        )
        app = create_draft_application(py, ally, invoice_date="2026-08-02")
        add_line_item(app, targets[0], quantity=1, ally=ally)
        add_line_item(app, targets[0], quantity=1, ally=ally)
        app = submit_application(app, ally)

        lines = list_line_items_for_application(app["id"])
        assert len(lines) == 2
        for line in lines:
            assert line["pacing_tier_at_submit"] == "HIGH_TIER"
            assert line["incentive_cents"] == 167, (
                "round_half_up(333 * 1 * 0.50) == 167 per line"
            )
        assert sum(l["incentive_cents"] for l in lines) == 334


class TestProgramCapExactFit:
    def test_exact_fit_allowed(self, api, admin_headers):
        """PRD §3.4: "The budget-cap check compares the freshly priced total
        against headroom: the sum of this application's per-line
        `incentive_cents` — each priced at the pacing tier in force at this
        moment — must not exceed the year's remaining uncommitted budget, that
        is, `budget_cap_cents` minus the current `committed_cents`."

        Design: Difficulty/boundary_precision_check/program_cap_exact_fit_allowed
        """
        # Preload 19,999,500 of 20,000,000 -> committed_pct == 99 -> HIGH_TIER
        # (factor 0.50). A base-1000 unit prices at exactly 500 == the 500
        # cents of remaining headroom: "must not exceed" permits equality.
        py, ally, _preload, targets = _program_with_preload(
            19_999_500,
            [{"measure_code": "M-SMALL", "base_rate_cents": 1_000,
              "deemed_kwh_per_unit": 10}],
        )
        app = create_draft_application(py, ally, invoice_date="2026-08-02")
        line = add_line_item(app, targets[0], quantity=1, ally=ally)
        app = submit_application(app, ally)

        assert app["status"] == "SUBMITTED"
        assert get_line_item(line["id"])["incentive_cents"] == 500
        py_after = get_program_year(py["id"])
        assert py_after["committed_cents"] == 20_000_000
        assert_program_ledger_invariants(py_after)

    def test_one_cent_over_fit_rejected(self, api, admin_headers):
        """PRD §3.4: "A submission that would push committed spending past the
        cap fails with `ERR_PROGRAM_CAP_EXCEEDED` (HTTP 402)."

        Design: Difficulty/boundary_precision_check/program_cap_exact_fit_allowed
        """
        # Same headroom (500 cents at HIGH_TIER), but a base-1001 unit prices
        # at round_half_up(500.5) == 501 > 500.
        py, ally, _preload, targets = _program_with_preload(
            19_999_500,
            [{"measure_code": "M-SMALL", "base_rate_cents": 1_001,
              "deemed_kwh_per_unit": 10}],
        )
        app = create_draft_application(py, ally, invoice_date="2026-08-02")
        add_line_item(app, targets[0], quantity=1, ally=ally)

        res = api.submit_application(app["id"], make_trade_ally_headers(ally["id"]))
        validate_error(res, ApiErrorId.ERR_PROGRAM_CAP_EXCEEDED, expected_status=402)
        assert get_program_year(py["id"])["committed_cents"] == 19_999_500
