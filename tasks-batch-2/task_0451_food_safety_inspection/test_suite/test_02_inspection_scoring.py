"""Inspection scoring: the two parallel scores, the pinned rounding order, the grade /
placard derivation with critical cap, and the A-cut boundary.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula, boundary_precision_check.
Queue B (Corner): calculations (zero-violation perfect score, repeat-offense surcharge).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    create_code, create_inspector, create_permitted_establishment,
    setup_completed_inspection, setup_inspection_in_progress,
    add_violation, complete_inspection,
    TEST_USERS, make_inspector_headers,
)

CLERK = TEST_USERS["permit_clerk_headers"]
DIRECTOR = TEST_USERS["health_director_headers"]


# ─── dual_variant_calc / dv_inspection_as_observed_vs_final_score_diverge ────
def test_as_observed_and_final_scores_diverge_under_corrections(api):
    """PRD §3.5: "The `as_observed_score` is a provisional figure that ignores on-site
    corrections entirely: it is 100 minus the sum of every violation's observed points,
    clamped so it is never below 0."
    PRD §3.5: "The `final_score` credits corrections: it is 100 minus the sum of every
    violation's final points, again clamped so it is never below 0."
    PRD §3.5: "Its `demerit_points_final` is the same observed figure unless the violation
    was corrected on site, in which case the observed figure is halved and rounded up to
    the nearest whole point."

    Two corrected violations: CRITICAL base 12 and NON_CRITICAL base 9.
    observed = 12 + 9 = 21 -> as_observed_score 79.
    final = ceil(12/2) + ceil(9/2) = 6 + 5 = 11 -> final_score 89.

    Design: Difficulty/dual_variant_calc/dv_inspection_as_observed_vs_final_score_diverge
    """
    code_crit = create_code("CRITICAL", 12, code="3-501.16", title="Cold holding")
    code_nc = create_code("NON_CRITICAL", 9, code="6-301.11", title="Handwash signage")
    _, _, completed = setup_completed_inspection(
        scheduled_index=10,
        violations=[(code_crit["id"], True), (code_nc["id"], True)])
    assert completed["as_observed_score"] == 79, f"expected 79, got {completed['as_observed_score']}"
    assert completed["final_score"] == 89, f"expected 89, got {completed['final_score']}"
    assert completed["as_observed_score"] != completed["final_score"], (
        "the two variants must diverge under on-site corrections")


def test_as_observed_ignores_correction_credit(api):
    """PRD §3.5: "The `as_observed_score` is a provisional figure that ignores on-site
    corrections entirely: it is 100 minus the sum of every violation's observed points,
    clamped so it is never below 0."

    A single corrected NON_CRITICAL base 9 violation: observed points 9 regardless of the
    correction, so as_observed_score = 100 - 9 = 91 while final_score = 100 - ceil(9/2) = 95.

    Design: Difficulty/dual_variant_calc/dv_inspection_as_observed_vs_final_score_diverge
    """
    code_nc = create_code("NON_CRITICAL", 9, code="6-301.11", title="Handwash signage")
    _, _, completed = setup_completed_inspection(
        scheduled_index=10, violations=[(code_nc["id"], True)])
    assert completed["as_observed_score"] == 91, f"expected 91, got {completed['as_observed_score']}"
    assert completed["final_score"] == 95, f"expected 95, got {completed['final_score']}"


# ─── combinatorial_formula / combo_grade_worst_of_band_and_critical_cap ──────
def test_single_critical_caps_grade_at_b_despite_band_a(api):
    """PRD §3.6: "Independently, a critical-count cap is derived because each critical
    violation lowers the best achievable letter: zero critical violations cap at `A`,
    exactly one caps at `B`, and two or more cap at `C`."
    PRD §3.6: "The grade is the worse of the score band and the critical cap, where
    severity orders `A` before `B` before `C` before `CLOSED` and "worse" means the more
    severe of the two."

    One uncorrected CRITICAL base 5: final_score 95 (band A) but critical_count 1 caps
    the letter at B, so grade resolves to B.

    Design: Difficulty/combinatorial_formula/combo_grade_worst_of_band_and_critical_cap
    """
    code_crit = create_code("CRITICAL", 5, code="3-501.16", title="Cold holding")
    _, _, completed = setup_completed_inspection(
        scheduled_index=10, violations=[(code_crit["id"], False)])
    assert completed["final_score"] == 95, f"expected 95, got {completed['final_score']}"
    assert completed["critical_count"] == 1, f"expected 1 critical, got {completed['critical_count']}"
    assert completed["grade"] == "B", f"band A capped at B by 1 critical, got {completed['grade']}"
    assert completed["placard_color"] == "YELLOW", f"B pairs with YELLOW, got {completed['placard_color']}"


def test_two_criticals_cap_grade_at_c_despite_band_a(api):
    """PRD §3.6: "Independently, a critical-count cap is derived because each critical
    violation lowers the best achievable letter: zero critical violations cap at `A`,
    exactly one caps at `B`, and two or more cap at `C`."
    PRD §3.6: "The grade is the worse of the score band and the critical cap, where
    severity orders `A` before `B` before `C` before `CLOSED` and "worse" means the more
    severe of the two."

    Two uncorrected CRITICAL base 5 (total 10): final_score 90 (band A) but critical_count
    2 caps the letter at C, so grade resolves to C (not CLOSED: criticals < 3, score >= 60).

    Design: Difficulty/combinatorial_formula/combo_grade_worst_of_band_and_critical_cap
    """
    c1 = create_code("CRITICAL", 5, code="3-501.16", title="Cold holding")
    c2 = create_code("CRITICAL", 5, code="3-501.17", title="Date marking")
    _, _, completed = setup_completed_inspection(
        scheduled_index=10, violations=[(c1["id"], False), (c2["id"], False)])
    assert completed["final_score"] == 90, f"expected 90, got {completed['final_score']}"
    assert completed["critical_count"] == 2, f"expected 2 criticals, got {completed['critical_count']}"
    assert completed["grade"] == "C", f"band A capped at C by 2 criticals, got {completed['grade']}"


# ─── combinatorial_formula / combo_scoring_per_line_ceil_then_sum_rounding_order
def test_rounding_is_per_violation_ceil_then_sum(api):
    """PRD §2.9: "where a correction credit halves a violation's points, that halving is
    applied per violation and rounded up to the nearest whole point before any summation.
    Only after every violation's points are individually computed are they summed."
    PRD §3.5: "Its `demerit_points_final` is the same observed figure unless the violation
    was corrected on site, in which case the observed figure is halved and rounded up to
    the nearest whole point. These per-violation figures are computed and rounded
    individually before any summation."

    Two corrected NON_CRITICAL base 9: ceil(9/2)=5 each, summing to 10 -> final_score 90.
    (Sum-then-halve would give ceil(18/2)=9 -> final_score 91; the per-line order pins 90.)

    Design: Difficulty/combinatorial_formula/combo_scoring_per_line_ceil_then_sum_rounding_order
    """
    code_a = create_code("NON_CRITICAL", 9, code="6-301.11", title="Handwash signage")
    code_b = create_code("NON_CRITICAL", 9, code="6-501.12", title="Cleaning")
    est, insp, inspection = setup_inspection_in_progress(scheduled_index=10)
    v_a = add_violation(inspection["id"], code_a["id"], insp["id"], corrected_on_site=True)
    add_violation(inspection["id"], code_b["id"], insp["id"], corrected_on_site=True)
    assert v_a["demerit_points_final"] == 5, (
        f"ceil(9/2) per violation is 5, got {v_a['demerit_points_final']}")
    completed = complete_inspection(inspection["id"], insp["id"])
    assert completed["final_score"] == 90, f"expected 90 (per-line ceil then sum), got {completed['final_score']}"
    assert completed["grade"] == "A", f"final_score 90 with no criticals is grade A, got {completed['grade']}"


def test_per_violation_ceil_on_odd_base_points(api):
    """PRD §3.5: "Its `demerit_points_final` is the same observed figure unless the
    violation was corrected on site, in which case the observed figure is halved and
    rounded up to the nearest whole point."

    A single corrected NON_CRITICAL base 7: ceil(7/2)=4 -> demerit_points_final 4,
    final_score = 100 - 4 = 96.

    Design: Difficulty/combinatorial_formula/combo_scoring_per_line_ceil_then_sum_rounding_order
    """
    code = create_code("NON_CRITICAL", 7, code="6-301.11", title="Handwash signage")
    est, insp, inspection = setup_inspection_in_progress(scheduled_index=10)
    v = add_violation(inspection["id"], code["id"], insp["id"], corrected_on_site=True)
    assert v["demerit_points_final"] == 4, f"ceil(7/2) is 4, got {v['demerit_points_final']}"
    completed = complete_inspection(inspection["id"], insp["id"])
    assert completed["final_score"] == 96, f"expected 96, got {completed['final_score']}"


# ─── boundary_precision_check / bpc_grade_a_at_final_score_exactly_90 ────────
def test_grade_a_at_final_score_exactly_90(api):
    """PRD §3.6: "a final score of at least 90 is band `A`".

    One uncorrected NON_CRITICAL base 10: final_score = 100 - 10 = 90, grade A (>=90 inclusive).

    Design: Difficulty/boundary_precision_check/bpc_grade_a_at_final_score_exactly_90
    """
    code = create_code("NON_CRITICAL", 10, code="6-301.11", title="Handwash signage")
    _, _, completed = setup_completed_inspection(
        scheduled_index=10, violations=[(code["id"], False)])
    assert completed["final_score"] == 90, f"expected 90, got {completed['final_score']}"
    assert completed["grade"] == "A", f"final_score 90 is the inclusive A boundary, got {completed['grade']}"


def test_grade_b_just_below_a_cut_at_final_score_89(api):
    """PRD §3.6: "a final score of at least 80 but below 90 is band `B`".

    One uncorrected NON_CRITICAL base 11: final_score = 100 - 11 = 89, one below the A cut,
    so grade B.

    Design: Difficulty/boundary_precision_check/bpc_grade_a_at_final_score_exactly_90
    """
    code = create_code("NON_CRITICAL", 11, code="6-301.11", title="Handwash signage")
    _, _, completed = setup_completed_inspection(
        scheduled_index=10, violations=[(code["id"], False)])
    assert completed["final_score"] == 89, f"expected 89, got {completed['final_score']}"
    assert completed["grade"] == "B", f"final_score 89 is below the A cut, got {completed['grade']}"


# ─── Corner / calc_scoring_zero_violations_perfect_score ─────────────────────
def test_zero_violations_yield_perfect_score_grade_a(api):
    """PRD §3.5: "The `as_observed_score` is a provisional figure that ignores on-site
    corrections entirely: it is 100 minus the sum of every violation's observed points,
    clamped so it is never below 0."
    PRD §3.6: "a final score of at least 90 is band `A`" and "The placard color is paired
    to the grade: `A` is `GREEN`".

    An empty violation set: both scores are 100, grade A, placard GREEN.

    Design: Corner/calculations/calc_scoring_zero_violations_perfect_score
    """
    _, _, completed = setup_completed_inspection(scheduled_index=0, violations=[])
    assert completed["as_observed_score"] == 100, f"expected 100, got {completed['as_observed_score']}"
    assert completed["final_score"] == 100, f"expected 100, got {completed['final_score']}"
    assert completed["grade"] == "A", f"expected A, got {completed['grade']}"
    assert completed["placard_color"] == "GREEN", f"expected GREEN, got {completed['placard_color']}"


# ─── Corner / calc_scoring_repeat_offense_surcharge_applied ──────────────────
def test_repeat_offense_adds_surcharge_points(api):
    """PRD §3.5: "the system compute its `repeat_offense` flag: the flag is true when the
    same FDA code was cited on a prior finalized inspection of this establishment and that
    prior citation was left unresolved."
    PRD §3.5: "Its `demerit_points_observed` is the cited code's `base_demerit_points`,
    plus the code's `repeat_surcharge_points` when this violation is a repeat offense and
    zero otherwise."

    A code base 10 / surcharge 8 cited uncorrected on a finalized ROUTINE inspection
    (left OPEN), then re-cited uncorrected on a second inspection: repeat_offense true,
    demerit_points_observed 18, as_observed_score 82.

    Design: Corner/calculations/calc_scoring_repeat_offense_surcharge_applied
    """
    from test_helpers import set_clock, setup_finalized_inspection
    set_clock(120)
    code_r = create_code("NON_CRITICAL", 10, code="4-601.11", title="Equipment clean",
                         repeat_surcharge_points=8)
    inspector = create_inspector()
    est, _, _ = create_permitted_establishment()
    # First inspection: cite the code uncorrected and finalize (grade A, leaves it OPEN).
    setup_finalized_inspection(
        scheduled_index=120, violations=[(code_r["id"], False)],
        inspector=inspector, establishment=est)
    # Second inspection: re-cite the same code uncorrected.
    second = api_client.create_inspection(
        {"establishment_id": est["id"], "inspector_id": inspector["id"],
         "inspection_type": "ROUTINE", "scheduled_index": 121}, CLERK).json()["data"]
    api_client.start_inspection(second["id"], make_inspector_headers(inspector["id"]))
    v2 = add_violation(second["id"], code_r["id"], inspector["id"], corrected_on_site=False)
    assert v2["repeat_offense"] is True, "second citation of an unresolved prior code is a repeat offense"
    assert v2["demerit_points_observed"] == 18, (
        f"base 10 + surcharge 8 = 18, got {v2['demerit_points_observed']}")
    completed = complete_inspection(second["id"], inspector["id"])
    assert completed["as_observed_score"] == 82, f"expected 82, got {completed['as_observed_score']}"
