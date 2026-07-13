"""Cost-outcome reporting: forward-looking (projected) vs chronological (actual) savings,
and the pinned round-per-visit-then-sum rounding order."""
from test_helpers import setup_cost_outcome


def test_cost_outcome_projected_uses_expected_baseline_visits(api):
    """PRD 3.9: "the forward-looking figure projected_savings_cents is expected_ed_visits
    multiplied by the same rounded per-visit saving."
    With baseline 8 over 365 enrollment_days, expected_ed_visits = 8 and
    projected_savings_cents = 8 * round_half_up(124700 * 0.855) = 8 * 106619 = 852952.

    Design: Difficulty/dual_variant_calc/outcome_projected_vs_actual_savings
    """
    report = setup_cost_outcome(api, baseline_ed_visits_12mo=8)["cost_outcome"]
    assert report["expected_ed_visits"] == 8, (
        f"expected 8 expected_ed_visits, got {report['expected_ed_visits']}")
    assert report["projected_savings_cents"] == 852952, (
        f"expected projected 852952, got {report['projected_savings_cents']}")


def test_cost_outcome_actual_uses_realized_averted_visits(api):
    """PRD 3.9: "The chronological figure actual_savings_cents is averted_ed_visits
    multiplied by that rounded per-visit saving; the forward-looking figure
    projected_savings_cents is expected_ed_visits multiplied by the same rounded per-visit
    saving."
    Two realized ED visits give actual_ed_visits = 2, averted_ed_visits = max(0, 8-2) = 6,
    and actual_savings_cents = 6 * 106619 = 639714, distinct from the projected 852952.

    Design: Difficulty/dual_variant_calc/outcome_projected_vs_actual_savings
    """
    report = setup_cost_outcome(api, baseline_ed_visits_12mo=8)["cost_outcome"]
    assert report["actual_ed_visits"] == 2, (
        f"expected 2 actual_ed_visits, got {report['actual_ed_visits']}")
    assert report["averted_ed_visits"] == 6, (
        f"expected 6 averted_ed_visits, got {report['averted_ed_visits']}")
    assert report["actual_savings_cents"] == 639714, (
        f"expected actual 639714, got {report['actual_savings_cents']}")
    assert report["projected_savings_cents"] != report["actual_savings_cents"], (
        "projected and actual savings must differ (852952 != 639714)")


def test_cost_outcome_per_visit_saving_rounded_before_multiply(api):
    """PRD 3.9: "The per-visit saving, per_averted_saving_cents, is the program's
    avg_ed_cost_cents multiplied by its diversion_credit_pct, rounded half up to whole cents
    - and this rounding happens first, before any multiplication by a visit count."
    round_half_up(124700 * 0.855) = round_half_up(106618.5) = 106619.

    Design: Difficulty/combinatorial_formula/outcome_savings_round_per_visit_then_sum
    """
    report = setup_cost_outcome(api, baseline_ed_visits_12mo=8)["cost_outcome"]
    assert report["per_averted_saving_cents"] == 106619, (
        f"expected per-visit saving 106619, got {report['per_averted_saving_cents']}")


def test_cost_outcome_actual_savings_round_per_visit_then_sum(api):
    """PRD 2.8: "the precise rounding point is pinned in Section 3.9 so that per-visit
    savings are rounded before they are multiplied by a visit count, never after."
    Six averted visits at 106619 each sum to 639714, not round_half_up(6 * 106618.5).

    Design: Difficulty/combinatorial_formula/outcome_savings_round_per_visit_then_sum
    """
    report = setup_cost_outcome(api, baseline_ed_visits_12mo=8)["cost_outcome"]
    assert report["averted_ed_visits"] == 6
    assert report["actual_savings_cents"] == 639714, (
        f"expected 639714 (6*106619), got {report['actual_savings_cents']}")
