"""Calculation rules (PRD §3.4, §3.8, §3.9, §3.10; scaffold §1.3).

All money is integer cents. Insurance is ceiled. Grades are floored to a 0.5 lattice.
"""
import math
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING

REGRADE_SURCHARGE_CENTS = 1500
AUTHENTIC_ONLY_GRADE_SENTINEL = -1


def floor_to_half(raw):
    """Floor a numeric value down to the nearest 0.5 (PRD §3.4).

    Multiply by two, take the floor to the nearest whole number, divide by two.
    Uses Decimal to avoid binary-float artifacts at half-point boundaries.
    """
    d = Decimal(str(raw)) * 2
    floored = d.to_integral_value(rounding=ROUND_FLOOR)
    return float(floored / 2)


def weighted_floored(centering, corners, edges, surface, std):
    """Weighted average of the four subgrades using bps weights, floored to 0.5.

    raw = (c*cW + co*coW + e*eW + s*sW) / 10000 ; then floor to half-point.
    """
    cW = std["centering_weight_bps"]
    coW = std["corners_weight_bps"]
    eW = std["edges_weight_bps"]
    sW = std["surface_weight_bps"]
    num = (
        Decimal(str(centering)) * cW
        + Decimal(str(corners)) * coW
        + Decimal(str(edges)) * eW
        + Decimal(str(surface)) * sW
    )
    raw = num / Decimal(10000)
    return floor_to_half(raw)


def provisional_overall_grade(centering, corners, edges, surface, std):
    """Optimistic: weighted-then-floored; ignores the lowest-subgrade cap (PRD §3.4)."""
    return weighted_floored(centering, corners, edges, surface, std)


def final_overall_grade(centering, corners, edges, surface, std):
    """Pessimistic: weighted-floored value capped at (min_subgrade + 1.5), refloored (PRD §3.4)."""
    weighted = weighted_floored(centering, corners, edges, surface, std)
    min_sub = min(centering, corners, edges, surface)
    capped = min(weighted, min_sub + 1.5)
    return floor_to_half(capped)


def ceil_div_bps(value_cents, rate_bps):
    """ceil(value_cents * rate_bps / 10000) in exact integer arithmetic."""
    return math.ceil(Decimal(value_cents) * Decimal(rate_bps) / Decimal(10000))


def estimate_item_fee(declared_value_cents, service_level):
    """Per-item estimate at submit: base + ceil(insurance on UNCAPPED declared value) (PRD §3.8)."""
    base = service_level["base_fee_cents"]
    rate = service_level["insurance_rate_bps"]
    est_insurance = ceil_div_bps(declared_value_cents, rate)
    return base + est_insurance


def finalize_item_fee(declared_value_cents, regrade_count, service_level):
    """Per-item final fee: base + ceil(insurance on CAPPED value) + regrade surcharge (PRD §3.8)."""
    base = service_level["base_fee_cents"]
    rate = service_level["insurance_rate_bps"]
    cap = service_level["max_declared_value_cents"]
    capped_value = min(declared_value_cents, cap)
    final_insurance = ceil_div_bps(capped_value, rate)
    regrade_surcharge = regrade_count * REGRADE_SURCHARGE_CENTS
    return base + final_insurance + regrade_surcharge


def covered_value(items, service_level):
    """Sum of per-item declared value CAPPED at tier max, EXCLUDING rejected items (PRD §3.9).

    Returns (covered_value_cents, premium_cents). premium = ceil(SUM-then-rate) — sum-then-ceil.
    """
    cap = service_level["max_declared_value_cents"]
    rate = service_level["insurance_rate_bps"]
    covered = 0
    for item in items:
        if item["status"] == "REJECTED_RETURNED":
            continue
        covered += min(item["declared_value_cents"], cap)
    premium = ceil_div_bps(covered, rate)
    return covered, premium


def label_grade_text(final_overall, verdict, authentic_min_grade):
    """Grade text on the label (PRD §3.5).

    - verdict GENUINE and final_overall >= authentic_min_grade -> numeric (e.g. "9.5")
    - verdict GENUINE and final_overall < authentic_min_grade -> "AUTHENTIC"
    - verdict ALTERED or COUNTERFEIT -> "NOT GENUINE"
    """
    if verdict in ("ALTERED", "COUNTERFEIT"):
        return "NOT GENUINE"
    # GENUINE
    if final_overall >= authentic_min_grade:
        return _format_grade(final_overall)
    return "AUTHENTIC"


def grade_value_for_bucket(final_overall, verdict, authentic_min_grade):
    """Discrete grade_value for the population bucket (PRD §3.10).

    final_overall when gradeable-authentic, else the AUTHENTIC-only sentinel -1.
    A NOT GENUINE item is not authentic-gradeable -> sentinel bucket.
    """
    if verdict in ("ALTERED", "COUNTERFEIT"):
        return AUTHENTIC_ONLY_GRADE_SENTINEL
    if final_overall >= authentic_min_grade:
        return final_overall
    return AUTHENTIC_ONLY_GRADE_SENTINEL


def _format_grade(value):
    """Render a numeric grade like 9.5 or 10 -> '9.5' / '10'."""
    if float(value) == int(value):
        return str(int(value))
    return str(value)


def normalize_title_key(title):
    """Normalize a title into the bucket title key (e.g. '1986 Fleer Jordan #57' ->
    '1986-FLEER-JORDAN-57'). Uppercase, alnum tokens joined by hyphen."""
    import re
    tokens = re.findall(r"[A-Za-z0-9]+", title.upper())
    return "-".join(tokens)
