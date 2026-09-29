"""Building suitability scoring (PRD 3.3).

The scored population is pinned to the report's own VERIFIED components.
Weights and contributions are held as exact fractions and the half-up rounding
is applied exactly once, to the final scaled result.
"""

from fractions import Fraction

import store
from rounding import pct2, pct2_frac

USEFUL_LIFE_HORIZON_YEARS = 30
PASSING_SCORE = pct2("62.50")
CRITICAL_CAP = Fraction(40, 100)
POST_REMEDIATION_PENALTY_FLOOR = Fraction(5, 100)
LIFE_SAFETY_MIN_YEARS = 5

CONDITION_PENALTY = {
    "EXCELLENT": Fraction(0),
    "GOOD": Fraction(5, 100),
    "FAIR": Fraction(15, 100),
    "POOR": Fraction(35, 100),
}


def remaining_life(component, variant):
    years = component["remaining_useful_life_years"]
    if variant == "POST_REMEDIATION":
        years += component["planned_remediation_gain_years"]
    return years


def condition_penalty(component, variant):
    penalty = CONDITION_PENALTY[component["condition_rating"]]
    if variant == "POST_REMEDIATION":
        return min(penalty, POST_REMEDIATION_PENALTY_FLOOR)
    return penalty


def score_report(report, variant):
    """Return the assessment's `score`, `basis`, `critical_cap_applied` and
    `verdict` for one variant."""
    verified = [c for c in store.report_components(report["id"])
                if c["verification_status"] == "VERIFIED"]
    if not verified:
        return {
            "score": pct2(0),
            "basis": "NO_VERIFIED_COMPONENTS",
            "critical_cap_applied": False,
            "verdict": "FAILED",
        }

    cost_total = sum(c["replacement_cost_cents"] for c in verified)
    raw = Fraction(0)
    for component in verified:
        if cost_total == 0:
            weight = Fraction(1, len(verified))
        else:
            weight = Fraction(component["replacement_cost_cents"], cost_total)
        years = remaining_life(component, variant)
        factor = Fraction(years, USEFUL_LIFE_HORIZON_YEARS)
        if factor > 1:
            factor = Fraction(1)
        if factor < 0:
            factor = Fraction(0)
        difference = factor - condition_penalty(component, variant)
        if difference < 0:
            difference = Fraction(0)
        raw += weight * difference

    capped = False
    for component in verified:
        if (component["is_life_safety"]
                and remaining_life(component, variant) < LIFE_SAFETY_MIN_YEARS):
            capped = True
            break
    if capped and raw > CRITICAL_CAP:
        raw = CRITICAL_CAP

    score = pct2_frac(raw * 100)
    return {
        "score": score,
        "basis": "VERIFIED_COMPONENTS",
        "critical_cap_applied": capped,
        "verdict": "PASSED" if score >= PASSING_SCORE else "FAILED",
    }
