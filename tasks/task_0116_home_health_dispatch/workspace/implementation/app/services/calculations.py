"""PDGM payment, mileage tier, HHA-hours, and supporting calculations.

All monetary arithmetic uses Decimal with ROUND_HALF_UP. The provisional and
final PDGM payment formulas, the round-then-sum mileage aggregation, and the
LUPA branch all live here (SCAFFOLD §1.3 / PRD §3.6 / §3.7).
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, List, Tuple

from .lookups import (
    ADMISSION_LETTER,
    BASE_30DAY_RATE,
    CLINICAL_GROUPING_LETTER,
    CMW_TABLE,
    FUNCTIONAL_LETTER,
    LUPA_PER_VISIT_RATE,
    LUPA_THRESHOLD,
    TIER1_LIMIT_MILES,
    TIER1_RATE,
    TIER2_LIMIT_MILES,
    TIER2_RATE,
    TIER3_RATE,
)


# ---------- precision helpers ---------------------------------------------

CENT = Decimal("0.01")
FOUR_DP = Decimal("0.0001")


def to_decimal(x) -> Decimal:
    """Convert numeric input to Decimal without going through float."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        # Use str() to avoid float-precision artifacts where possible. Caller
        # is responsible for not introducing float drift earlier in the pipeline.
        return Decimal(str(x))
    if isinstance(x, str):
        return Decimal(x)
    raise TypeError(f"cannot convert {type(x).__name__} to Decimal")


def round_half_up(value: Decimal, places: int) -> Decimal:
    """ROUND_HALF_UP to `places` decimal places."""
    q = Decimal(10) ** (-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def to_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def to_four_dp(value: Decimal) -> Decimal:
    return value.quantize(FOUR_DP, rounding=ROUND_HALF_UP)


# ---------- HIPPS / case-mix ---------------------------------------------

def hipps_code(timing_category: str, clinical_grouping: str,
               functional_level: str, admission_source: str) -> str:
    """Build the 5-character HIPPS code per PRD §3.7."""
    pos1 = "1" if timing_category == "EARLY" else "2"
    pos2 = CLINICAL_GROUPING_LETTER[clinical_grouping]
    pos3 = FUNCTIONAL_LETTER[functional_level]
    pos4 = ADMISSION_LETTER[admission_source]
    pos5 = "1"
    return f"{pos1}{pos2}{pos3}{pos4}{pos5}"


def lookup_case_mix_weight(timing_category: str, clinical_grouping: str,
                           functional_level: str, admission_source: str) -> Decimal:
    """Fetch case-mix weight (4-decimal Decimal) from the CMW_TABLE."""
    key = (timing_category, clinical_grouping, functional_level, admission_source)
    if key not in CMW_TABLE:
        # Per the PRD/SCAFFOLD, only tabulated tuples are valid. Fall back to a
        # 4-dp 0.0000 weight so the surface is well-formed even for off-table
        # combinations that callers manage to construct; the schema validation
        # at OASIS creation should prevent this.
        return Decimal("0.0000")
    return CMW_TABLE[key]


# ---------- PDGM payment paths -------------------------------------------

def wage_adjusted_base(wage_index: Decimal) -> Decimal:
    """Step 2 of provisional/case-mix final: BASE * wage_index, 4dp HALF_UP."""
    return to_four_dp(BASE_30DAY_RATE * wage_index)


def case_mix_payment(wage_index: Decimal, case_mix_weight: Decimal) -> Decimal:
    """Provisional/case-mix final payment: round_wab * cmw, 2dp HALF_UP."""
    wab = wage_adjusted_base(wage_index)
    return to_money(wab * case_mix_weight)


def lupa_payment(wage_index: Decimal,
                 chronological_visits: Iterable[dict]) -> Decimal:
    """Sum of per-visit LUPA payments, rounded-then-summed.

    `chronological_visits` is an iterable of visit dicts already sorted by
    (visit_date, start_minute, id) ascending. Each visit's per-visit payment
    is rate[discipline] * wage_index, rounded HALF_UP to 2 decimals, then
    accumulated.
    """
    total = Decimal("0.00")
    for v in chronological_visits:
        rate = LUPA_PER_VISIT_RATE.get(v["visit_type"])
        if rate is None:
            continue
        per_visit = to_money(rate * wage_index)
        total += per_visit
    return total


def is_lupa(completed_visit_count: int) -> bool:
    """LUPA triggers when completed-visit count is strictly less than threshold."""
    return completed_visit_count < LUPA_THRESHOLD


# ---------- Mileage tier formula -----------------------------------------

def mileage_reimbursement(miles_driven: Decimal) -> Decimal:
    """Three-tier mileage reimbursement, rounded HALF_UP to 2 decimals.

    Tier 1 covers miles 0..30 inclusive of 30 (rate 0.70).
    Tier 2 covers miles (30..100] (rate 0.55).
    Tier 3 covers miles > 100 (rate 0.40).
    """
    m = to_decimal(miles_driven)
    zero = Decimal("0")
    tier1_miles = min(m, TIER1_LIMIT_MILES)
    tier2_miles = min(max(m - TIER1_LIMIT_MILES, zero), TIER2_LIMIT_MILES)
    tier3_miles = max(m - (TIER1_LIMIT_MILES + TIER2_LIMIT_MILES), zero)
    raw = (tier1_miles * TIER1_RATE
           + tier2_miles * TIER2_RATE
           + tier3_miles * TIER3_RATE)
    return to_money(raw)


def aggregate_mileage(amounts: Iterable[Decimal]) -> Decimal:
    """Round-then-sum aggregation. Inputs must already be 2dp Decimals."""
    total = Decimal("0.00")
    for a in amounts:
        total += a
    # Aggregation does no further rounding — but normalise scale to 2dp so the
    # JSON surface is consistent when the input list is empty.
    return total.quantize(CENT, rounding=ROUND_HALF_UP)


# ---------- HHA hours ----------------------------------------------------

def hha_hours_from_minutes(start_minute: int, end_minute: int) -> Decimal:
    """Per-visit HHA hours, rounded HALF_UP to 2 decimals."""
    minutes = Decimal(end_minute - start_minute)
    return round_half_up(minutes / Decimal(60), 2)


def consumed_hha_hours(visits: Iterable[dict]) -> Decimal:
    """Sum of hha_hours across visits with visit_type=HHA and status in {SCHEDULED, COMPLETED}.

    Inputs are visit dicts already filtered to a single episode; each visit's
    hha_hours has already been rounded at create time.
    """
    total = Decimal("0.00")
    for v in visits:
        if v.get("visit_type") != "HHA":
            continue
        if v.get("status") not in ("SCHEDULED", "COMPLETED"):
            continue
        total += to_decimal(v.get("hha_hours", 0))
    return total
