"""Pure calculation rules (PRD §3.1-§3.9, SCAFFOLD §1.3).

All money is integer cents. PDPM intermediate arithmetic uses Decimal (never
float). Rounding is round-half-up, deferred to per-day then summed (PRD §2.8,
§3.9). Day counts are integer UTC-calendar-date deltas.
"""
from decimal import Decimal, ROUND_HALF_UP

from clock import parse_iso, to_utc_date

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
QUALIFYING_MIDNIGHTS = 3

PAID_BEDHOLD_CAP = {
    "MEDICAID": 10,
    "MEDICARE_A": 0,
    "MANAGED_CARE": 7,
    "PRIVATE": 30,
}

GROUP_CONCURRENT_CAP_PCT = Decimal("0.25")

# PDPM case-mix indices (PRD §3.4). NURSING uses a flat "NURS" rate row whose
# case_mix_index comes from the configured PdpmRate, so it is not listed here.
PT_OT_CMI = {"TA": "1.53", "TB": "1.69", "TC": "1.85", "TD": "1.00"}
SLP_CMI = {"SA": "1.00", "SB": "1.46", "SC": "2.13", "SF": "2.98"}
NTA_CMI = {"NA": "3.25", "NB": "2.53", "NC": "1.85", "ND": "1.34", "NE": "0.96"}

# Quality-measure scoring (PRD §3.1)
QM_BASELINE_MISSING = 50
MEASURE_CODES = ["FALLS_WITH_INJURY", "PRESSURE_ULCER", "ANTIPSYCHOTIC_USE", "REHOSPITALIZATION"]


# ---------------------------------------------------------------------------
# qualifying_stay_midnights (PRD §3.2)
# ---------------------------------------------------------------------------
def qualifying_stay_midnights(admit_iso, discharge_iso):
    admit_d = to_utc_date(parse_iso(admit_iso))
    disc_d = to_utc_date(parse_iso(discharge_iso))
    midnights = (disc_d - admit_d).days
    qualifies = midnights >= QUALIFYING_MIDNIGHTS
    return midnights, qualifies


# ---------------------------------------------------------------------------
# pdpm_component_classification (PRD §3.4)
# ---------------------------------------------------------------------------
def pt_ot_group(pt_function_score):
    if 0 <= pt_function_score <= 5:
        return "TA"
    if 6 <= pt_function_score <= 9:
        return "TB"
    if 10 <= pt_function_score <= 23:
        return "TC"
    return "TD"  # exactly 24


def slp_group(slp_components_count):
    return {0: "SA", 1: "SB", 2: "SC", 3: "SF"}[slp_components_count]


def nta_group(nta_comorbidity_points):
    if nta_comorbidity_points >= 12:
        return "NA"
    if 9 <= nta_comorbidity_points <= 11:
        return "NB"
    if 6 <= nta_comorbidity_points <= 8:
        return "NC"
    if 3 <= nta_comorbidity_points <= 5:
        return "ND"
    return "NE"  # 0..2


def classify(assessment):
    return (
        pt_ot_group(assessment["pt_function_score"]),
        slp_group(assessment["slp_components_count"]),
        nta_group(assessment["nta_comorbidity_points"]),
    )


# ---------------------------------------------------------------------------
# bed_hold_days (PRD §3.6)
# ---------------------------------------------------------------------------
def bed_hold_days(leave_start_iso, window_end_iso, payer_source):
    start_d = to_utc_date(parse_iso(leave_start_iso))
    end_d = to_utc_date(parse_iso(window_end_iso))
    leave_days = (end_d - start_d).days
    paid_cap = PAID_BEDHOLD_CAP[payer_source]
    paid = min(leave_days, paid_cap)
    return leave_days, paid


# ---------------------------------------------------------------------------
# therapy_minutes_aggregate per-row weighting (PRD §3.5)
# ---------------------------------------------------------------------------
def individual_equivalent_minutes(mode, minutes):
    if mode == "INDIVIDUAL":
        return minutes
    if mode == "CONCURRENT":
        return minutes // 2
    if mode == "GROUP":
        return minutes // 4
    raise ValueError("unknown mode %s" % mode)


# ---------------------------------------------------------------------------
# pdpm_per_diem_amount (PRD §3.9, SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def variable_adjustment(component, stay_day_index):
    """Day-index variable adjustment factor as Decimal (PRD §3.9)."""
    if component in ("PT", "OT"):
        if stay_day_index <= 20:
            return Decimal("1.00")
        # steps down 0.02 per 7-day block beginning at day 21
        block = (stay_day_index - 21) // 7  # 0 for 21..27, 1 for 28..34, ...
        factor = Decimal("0.98") - Decimal("0.02") * block
        if factor < 0:
            factor = Decimal("0")
        return factor
    if component == "NTA":
        return Decimal("3.00") if stay_day_index <= 3 else Decimal("1.00")
    # SLP, NURSING
    return Decimal("1.00")


def _rate_lookup(rates, component, group):
    """Return the active PdpmRate row for (component, group) or None.

    'rates' is an iterable of stored PdpmRate dicts.
    """
    for r in rates:
        if r.get("active") and r["component"] == component and r["case_mix_group"] == group:
            return r
    return None


def day_rate_cents_unrounded(groups, stay_day_index, rates):
    """Sum of component day amounts (unrounded Decimal cents) for one stay day.

    groups: dict mapping the resolved case-mix group per component, including
            the NURSING flat 'NURS' group and OT reusing the PT group code.
    Pinned order: resolve each component's adjusted base, sum components, the
    variable adjustment is applied per component before summation (PRD §3.9).
    """
    total = Decimal("0")
    for component in ("PT", "OT", "SLP", "NTA", "NURSING"):
        group = groups[component]
        rate_row = _rate_lookup(rates, component, group)
        if rate_row is None:
            # No active rate row priced as zero contribution.
            continue
        base = Decimal(rate_row["base_rate_cents"]) * Decimal(str(rate_row["case_mix_index"]))
        day_amount = base * variable_adjustment(component, stay_day_index)
        total += day_amount
    return total


def round_half_up_cents(amount):
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def resolve_pricing_groups(assessment):
    """Map the driving assessment's resolved groups onto the five components.

    SLP/PT/NTA use the assessment's resolved groups; OT reuses the PT group
    code; NURSING uses the flat 'NURS' group code (PRD §3.9).
    """
    return {
        "PT": assessment["pt_ot_case_mix_group"],
        "OT": assessment["pt_ot_case_mix_group"],
        "SLP": assessment["slp_case_mix_group"],
        "NTA": assessment["nta_case_mix_group"],
        "NURSING": "NURS",
    }


def claim_total(billed_days_indices, groups, rates):
    """Round per-day then sum (PRD §3.9).

    billed_days_indices: list of 1-based stay_day_index values for billed days.
    """
    total = 0
    for idx in billed_days_indices:
        day_unrounded = day_rate_cents_unrounded(groups, idx, rates)
        total += round_half_up_cents(day_unrounded)
    return total


# ---------------------------------------------------------------------------
# five_star_quality_score (PRD §3.1)
# ---------------------------------------------------------------------------
def measure_points(measure_code, numerator, denominator):
    rate = Decimal(numerator) / Decimal(denominator)
    if measure_code == "FALLS_WITH_INJURY":
        cuts = [(Decimal("0.01"), 100), (Decimal("0.03"), 75), (Decimal("0.05"), 50)]
    elif measure_code == "PRESSURE_ULCER":
        cuts = [(Decimal("0.02"), 100), (Decimal("0.05"), 75), (Decimal("0.08"), 50)]
    elif measure_code == "ANTIPSYCHOTIC_USE":
        cuts = [(Decimal("0.10"), 100), (Decimal("0.15"), 75), (Decimal("0.20"), 50)]
    elif measure_code == "REHOSPITALIZATION":
        cuts = [(Decimal("0.15"), 100), (Decimal("0.20"), 75), (Decimal("0.25"), 50)]
    else:
        raise ValueError("unknown measure_code %s" % measure_code)
    for threshold, pts in cuts:
        if rate < threshold:  # strict less-than (PRD §3.1)
            return pts
    return 25


def quality_measure_rating_from_total(qm_total):
    if qm_total >= 360:
        return 5
    if 280 <= qm_total <= 359:
        return 4
    if 200 <= qm_total <= 279:
        return 3
    if 120 <= qm_total <= 199:
        return 2
    return 1


def overall_star_rating(health_inspection_rating, staffing_rating, quality_measure_rating):
    score = health_inspection_rating
    score += 1 if staffing_rating >= 4 else 0
    score -= 1 if staffing_rating <= 2 else 0
    score += 1 if quality_measure_rating >= 4 else 0
    score -= 1 if quality_measure_rating <= 2 else 0
    return max(1, min(5, score))
