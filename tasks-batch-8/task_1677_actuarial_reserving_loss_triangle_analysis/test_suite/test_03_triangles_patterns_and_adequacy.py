"""Triangle-driven computation: development-factor selection boundaries,
tail-factor estimation, the pinned per-factor rounding order, large-loss
threshold segregation, and the two case-reserve adequacy variants
(PRD §2.6, §3.2, §3.3, §3.4, §3.5, §3.6).
"""
import pytest

from test_helpers import (
    aggregate_triangle,
    assert_cell_multiset,
    assert_development_pattern,
    assert_reserve_run,
    create_claim,
    create_pattern,
    create_reserve_run,
    create_segment,
    post_case_reserve,
    post_payment,
    select_pattern,
    validate_success,
)


def _tail_book_with_triangle():
    """One claim with a single dev-0 payment; triangle valued at 2025-Q1."""
    segment = create_segment(name="Tail Book", line_of_business="WORKERS_COMP")
    claim = create_claim(
        segment["id"],
        claim_number="E-1",
        accident_date="2025-01-15",
        report_date="2025-01-18",
    )
    post_payment(claim["id"], "2025-02-01T00:00:00Z", 100000)
    triangle = aggregate_triangle(segment["id"], "PAID", "2025-Q1")
    return {"segment": segment, "claim": claim, "triangle": triangle}


def _gl_rounding_book():
    """R-1 (accident 2025-Q1) pays 100000 at dev 0 then 23445 at dev 1;
    R-2 (accident 2025-Q2) pays 80000 at dev 0. Triangle at 2025-Q2."""
    segment = create_segment(
        name="GL Book",
        line_of_business="GENERAL_LIABILITY",
        large_loss_threshold_cents=10000000,
        max_range_width_pct=1.0,
    )
    claim_r1 = create_claim(
        segment["id"],
        claim_number="R-1",
        accident_date="2025-01-15",
        report_date="2025-01-16",
    )
    post_payment(claim_r1["id"], "2025-02-01T00:00:00Z", 100000)
    post_payment(claim_r1["id"], "2025-05-10T00:00:00Z", 23445)
    claim_r2 = create_claim(
        segment["id"],
        claim_number="R-2",
        accident_date="2025-04-10",
        report_date="2025-04-11",
    )
    post_payment(claim_r2["id"], "2025-05-20T00:00:00Z", 80000)
    triangle = aggregate_triangle(segment["id"], "PAID", "2025-Q2")
    return {"segment": segment, "claims": {"R-1": claim_r1, "R-2": claim_r2},
            "triangle": triangle}


class TestTailFactorDefaults:
    def test_tail_factor_defaults_when_no_developed_periods(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.4: "For each adjacent column pair, the eligible accident
        quarters are those having cells at both columns; when no accident
        quarter qualifies at a given age, the pattern carries no factor for
        that age, and when no accident-quarter pair is fully developed
        anywhere, `selected_factors` is an empty array."
        PRD §3.4: "The `tail_factor` extends the curve beyond the data: with at
        least three selected factors it is the cube root of the product of the
        final three selected factors, taken from their already-rounded values
        and itself rounded half-up to four decimal places; with fewer than
        three it is exactly 1.0000, and no extrapolation is attempted."

        Design: Difficulty/boundary_precision_check/tail_factor_defaults_when_zero_developed_periods
        """
        ctx = _tail_book_with_triangle()
        pattern = create_pattern(
            ctx["segment"]["id"], "PAID", "2025-Q1", "2025-Q1", "2025-Q3"
        )
        assert_development_pattern(pattern)
        assert pattern["selected_factors"] == [], (
            "with a single accident quarter at dev 0 only, no link ratio is computable"
        )
        assert pattern["tail_factor"] == pytest.approx(1.0), (
            "fewer than three selected factors fixes the tail at exactly 1.0000"
        )

    def test_empty_pattern_chain_ladder_yields_zero_ibnr(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.4: "At the age exactly equal to n, the cumulative factor is
        the tail factor itself."
        PRD §3.5: "The run's `ultimate_cents` is the total across both layers
        and all accident quarters, and its `ibnr_cents` is that total minus the
        sum of the latest-diagonal cells across both layers."

        Design: Difficulty/boundary_precision_check/tail_factor_defaults_when_zero_developed_periods
        """
        ctx = _tail_book_with_triangle()
        pattern = create_pattern(
            ctx["segment"]["id"], "PAID", "2025-Q1", "2025-Q1", "2025-Q3"
        )
        select_pattern(pattern["id"])
        run = create_reserve_run(
            ctx["segment"]["id"], "2025-Q1", "CHAIN_LADDER", "PAID"
        )
        assert_reserve_run(run)
        assert run["ultimate_cents"] == 100000, (
            "CDF at age 0 is the tail factor 1.0000, so the ultimate equals the diagonal"
        )
        assert run["ibnr_cents"] == 0


class TestTailFactorGeometricMean:
    def test_tail_factor_geometric_mean_of_last_three_factors(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.4: "The `tail_factor` extends the curve beyond the data: with
        at least three selected factors it is the cube root of the product of
        the final three selected factors, taken from their already-rounded
        values and itself rounded half-up to four decimal places; with fewer
        than three it is exactly 1.0000, and no extrapolation is attempted."
        PRD §3.4: "the raw link ratio at an age is the sum of the eligible
        accident quarters' later-column cells divided by the sum of their
        earlier-column cells — a volume-weighted average link ratio — and each
        selected factor is that ratio rounded half-up to four decimal places
        before any downstream use"

        Design: Corner/calculations/tail_factor_geometric_mean_of_last_three_factors
        """
        segment = create_segment(
            name="Tail3 Book",
            line_of_business="WORKERS_COMP",
            large_loss_threshold_cents=4000000,
            max_range_width_pct=1.0,
        )
        claim = create_claim(
            segment["id"],
            claim_number="T-1",
            accident_date="2025-01-15",
            report_date="2025-01-18",
        )
        post_payment(claim["id"], "2025-02-01T00:00:00Z", 100000)
        post_payment(claim["id"], "2025-10-05T00:00:00Z", 33100)
        aggregate_triangle(segment["id"], "PAID", "2025-Q4")

        pattern = create_pattern(
            segment["id"], "PAID", "2025-Q4", "2025-Q4", "2026-Q2"
        )
        assert pattern["selected_factors"] == pytest.approx([1.0, 1.0, 1.331]), (
            "cumulative cells 100000/100000/100000/133100 give link ratios "
            "1.0, 1.0 and 1.331"
        )
        assert pattern["tail_factor"] == pytest.approx(1.1), (
            "cube root of 1.0 x 1.0 x 1.331 is exactly 1.1"
        )


class TestFactorRoundingOrder:
    def test_factor_rounding_order_pins_selected_factor(
        self, api, actuarial_analyst_headers
    ):
        """PRD §2.6: "each selected development factor is rounded to four
        decimal places at selection time, before it participates in any
        cumulative-factor product, and the cumulative development factor
        computed from those already-rounded factors is itself rounded to four
        decimal places."
        PRD §3.4: "each selected factor is that ratio rounded half-up to four
        decimal places before any downstream use"

        Design: Difficulty/combinatorial_formula/factor_rounding_order_changes_ultimate_cents
        """
        ctx = _gl_rounding_book()
        pattern = create_pattern(
            ctx["segment"]["id"], "PAID", "2025-Q2", "2025-Q2", "2026-Q1"
        )
        assert pattern["selected_factors"] == pytest.approx([1.2345]), (
            "raw ratio 123445/100000 = 1.23445 rounds half-up to 1.2345 at selection time"
        )
        assert pattern["tail_factor"] == pytest.approx(1.0)

    def test_factor_rounding_order_changes_ultimate_cents(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.5: "the quarter's latest-diagonal cell — the cell at the age
        equal to the number of quarters elapsed from the accident quarter to
        the valuation quarter — is multiplied by the cumulative development
        factor at that age, and the product is rounded half-up to whole cents."
        PRD §2.6: "Carrying unrounded link ratios into downstream
        multiplication is a different rule and produces different cent values;
        implementations must not do it."

        Design: Difficulty/combinatorial_formula/factor_rounding_order_changes_ultimate_cents
        """
        ctx = _gl_rounding_book()
        pattern = create_pattern(
            ctx["segment"]["id"], "PAID", "2025-Q2", "2025-Q2", "2026-Q1"
        )
        select_pattern(pattern["id"])
        run = create_reserve_run(
            ctx["segment"]["id"], "2025-Q2", "CHAIN_LADDER", "PAID"
        )
        assert_reserve_run(run)
        # CDF(0) = 1.2345 x tail 1.0; CDF(1) = tail = 1.0 (age equals n=1).
        # ultimate = 123445 x 1.0000 + round_half_up(80000 x 1.2345) = 222205.
        assert run["ultimate_cents"] == 222205
        assert run["ibnr_cents"] == 18760


class TestLargeLossThresholdBoundary:
    def _threshold_book(self):
        """Segment with a 400000-cent threshold; claim C-B paid 300000 then a
        case reserve of 100000, landing reported incurred exactly on 400000."""
        segment = create_segment(name="Main Book", line_of_business="COMMERCIAL_AUTO")
        claim = create_claim(
            segment["id"],
            claim_number="C-B",
            accident_date="2025-04-10",
            report_date="2025-04-12",
        )
        post_payment(claim["id"], "2025-05-15T00:00:00Z", 200000)
        post_payment(claim["id"], "2025-08-10T00:00:00Z", 100000)
        return {"segment": segment, "claim": claim}

    def test_large_loss_threshold_exact_equality_segregates_claim(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.2: "`is_large_loss` is true exactly when
        `reported_incurred_cents` reaches or exceeds the segment's
        `large_loss_threshold_cents` — the at-least boundary is pinned, so a
        claim sitting exactly on the threshold is a large loss."
        PRD §3.2: "`is_segregated` is true when the claim is a large loss or
        carries a catastrophe event assignment."

        Design: Difficulty/boundary_precision_check/large_loss_threshold_exact_equality_segregates
        """
        ctx = self._threshold_book()
        post_case_reserve(ctx["claim"]["id"], "2025-08-20T00:00:00Z", 100000)
        data = validate_success(
            api.get_claim(ctx["claim"]["id"], actuarial_analyst_headers)
        )
        assert data["reported_incurred_cents"] == 400000, (
            "300000 paid plus 100000 case outstanding lands exactly on the threshold"
        )
        assert data["is_large_loss"] is True, "the at-least boundary is pinned"
        assert data["is_segregated"] is True

    def test_large_loss_boundary_moves_claim_into_large_layer(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.3: "The `cells` array covers the bulk layer — claims that are
        not segregated at aggregation time — and the `large_loss_cells` array
        covers the segregated layer, in the same cell shape."
        PRD §3.3: "On a `PAID` basis, a cell is the sum of payment amounts
        minus reversal amounts across the layer's claims for that accident
        quarter, taken over all transactions with development index no later
        than the column."

        Design: Difficulty/boundary_precision_check/large_loss_threshold_exact_equality_segregates
        """
        ctx = self._threshold_book()
        post_case_reserve(ctx["claim"]["id"], "2025-08-20T00:00:00Z", 100000)
        triangle = aggregate_triangle(ctx["segment"]["id"], "PAID", "2025-Q3")
        assert triangle["cells"] == [], (
            "the only claim is segregated, so the bulk layer is empty"
        )
        assert_cell_multiset(
            triangle["large_loss_cells"],
            [("2025-Q2", 0, 200000), ("2025-Q2", 1, 300000)],
            label="large_loss_cells",
        )


class TestCaseReserveAdequacyVariants:
    def _adequacy_book(self):
        """Claims C-A (accident 2025-Q1, paid 100000/100000/50000 at dev
        0/1/2) and C-D (accident 2025-Q2, paid 100000 at dev 0 plus an
        80000-cent case reserve), PAID triangle at 2025-Q3 and a SELECTED
        pattern covering 2025-Q3."""
        segment = create_segment(name="Main Book", line_of_business="COMMERCIAL_AUTO")
        claim_a = create_claim(
            segment["id"],
            claim_number="C-A",
            accident_date="2025-01-15",
            report_date="2025-01-20",
        )
        post_payment(claim_a["id"], "2025-02-01T00:00:00Z", 100000)
        post_payment(claim_a["id"], "2025-05-01T00:00:00Z", 100000)
        post_payment(claim_a["id"], "2025-09-01T00:00:00Z", 50000)
        claim_d = create_claim(
            segment["id"],
            claim_number="C-D",
            accident_date="2025-04-10",
            report_date="2025-04-15",
        )
        post_payment(claim_d["id"], "2025-05-01T00:00:00Z", 100000)
        post_case_reserve(claim_d["id"], "2025-05-15T00:00:00Z", 80000)
        aggregate_triangle(segment["id"], "PAID", "2025-Q3")
        pattern = create_pattern(segment["id"], "PAID", "2025-Q3", "2025-Q3", "2026-Q2")
        select_pattern(pattern["id"])
        return {"segment": segment, "claim_d": claim_d}

    def test_case_adequacy_development_vs_benchmark_divergence(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.6: "The indicated outstanding is the claim's
        `paid_to_date_cents` multiplied by the amount by which the cumulative
        development factor at the claim's age exceeds one.
        `adequacy_ratio_development` is then the `case_outstanding_cents`
        divided by that indicated outstanding, rounded half-up to four decimal
        places; when the indicated outstanding is zero, the ratio is null."

        Design: Difficulty/dual_variant_calc/case_adequacy_development_vs_benchmark_divergence
        """
        ctx = self._adequacy_book()
        data = validate_success(
            api.get_claim(ctx["claim_d"]["id"], actuarial_analyst_headers)
        )
        # Claim age 1; the selected pattern's CDF(1) is 1.25, so indicated
        # outstanding is 100000 x 0.25 = 25000 and the ratio is 80000/25000.
        assert data["adequacy_ratio_development"] == pytest.approx(3.2)

    def test_case_adequacy_benchmark_variant_value(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.6: "`adequacy_ratio_benchmark` is the `case_outstanding_cents`
        divided by the segment's `benchmark_open_severity_cents`, rounded
        half-up to four decimal places, and it is null when the benchmark is
        zero."
        PRD §3.6: "The schedule-benchmark variant ignores the claim's own
        payment history and compares the case reserve against the segment's
        flat schedule severity"

        Design: Difficulty/dual_variant_calc/case_adequacy_development_vs_benchmark_divergence
        """
        ctx = self._adequacy_book()
        data = validate_success(
            api.get_claim(ctx["claim_d"]["id"], actuarial_analyst_headers)
        )
        assert data["adequacy_ratio_benchmark"] == pytest.approx(1.6), (
            "80000 case outstanding over the 50000 schedule severity"
        )
        assert data["adequacy_ratio_development"] != data["adequacy_ratio_benchmark"], (
            "the two variants answer different questions about the same reserve"
        )
