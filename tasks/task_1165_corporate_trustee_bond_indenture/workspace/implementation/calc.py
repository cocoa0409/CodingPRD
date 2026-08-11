"""Calculation rules (scaffold Table 3 / PRD section 3): interest accrual,
pro-rata allocation, extraordinary fee tiers, collateral coverage, consent
tabulation, quorum tally, covenant ratio check. All money math is exact
integer arithmetic; round-half-up where specified; the single coverage
division floors."""
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP

from validate import parse_date_strict, parse_datetime, round_half_up_ratio

HAIRCUT_BPS = {
    "REAL_ESTATE": 2000,
    "EQUIPMENT": 3000,
    "SECURITIES": 500,
    "GUARANTEE": 4000,
}
SUBSTITUTE_HAIRCUT_HIGH_TIER_BPS = 1000
SUBSTITUTE_HAIRCUT_STANDARD_BPS = 2500
MIN_COVERAGE_BPS = 12500

TIER1_HOURS = 10
TIER2_MULTIPLIER = Decimal("1.5")
FEE_CAP_MULTIPLE = 4


def interest_days(convention, start_iso, end_iso):
    """Day count in the half-open window [start, end)."""
    d1 = parse_date_strict(start_iso)
    d2 = parse_date_strict(end_iso)
    if d1 is None or d2 is None:
        return 0
    if convention == "THIRTY_360":
        return (360 * (d2.year - d1.year) + 30 * (d2.month - d1.month)
                + (min(d2.day, 30) - min(d1.day, 30)))
    return (d2 - d1).days


def interest_year_denominator(convention):
    return 360 if convention in ("ACT_360", "THIRTY_360") else 365


def interest_for_position(tranche, position, start_iso, end_iso):
    """Per-position interest, rounded half-up to integer cents BEFORE summation."""
    days = interest_days(tranche["day_count_convention"], start_iso, end_iso)
    den_days = interest_year_denominator(tranche["day_count_convention"])
    num = position["principal_amount_cents"] * tranche["interest_rate_bps"] * days
    den = 10000 * den_days
    return round_half_up_ratio(num, den)


def compute_interest_gross(tranche, positions, start_iso, end_iso):
    return sum(interest_for_position(tranche, p, start_iso, end_iso)
               for p in positions)


def pro_rata_allocation(gross_cents, positions):
    """Largest-remainder pro-rata. Floor per line first, then distribute the
    remainder one cent at a time by fractional part DESC, tie-break
    created_at ASC then original_principal_cents DESC (never id).
    Returns {position_id: allocated_cents}."""
    eligible = list(positions)
    total = sum(p["principal_amount_cents"] for p in eligible)
    if not eligible:
        return {}
    if total <= 0:
        return {p["id"]: 0 for p in eligible}
    order = sorted(eligible,
                   key=lambda p: (p["created_at"],
                                  -p["original_principal_cents"]))
    floors = {}
    rems = {}
    for p in order:
        raw_num = gross_cents * p["principal_amount_cents"]
        floors[p["id"]] = raw_num // total
        rems[p["id"]] = raw_num % total
    remainder = gross_cents - sum(floors.values())
    by_rem = sorted(order,
                    key=lambda p: (-rems[p["id"]], p["created_at"],
                                   -p["original_principal_cents"]))
    alloc = dict(floors)
    for i in range(remainder):
        alloc[by_rem[i % len(by_rem)]["id"]] += 1
    return alloc


def extraordinary_fee_amount(indenture, hours):
    """Tiered extraordinary fee: first 10h at rate, beyond at 1.5x rate,
    round-half-up per tier, capped at 4x the annual admin fee."""
    rate = (indenture["default_hourly_rate_cents"]
            if indenture["status"] in ("DEFAULTED", "ACCELERATED")
            else indenture["extraordinary_hourly_rate_cents"])
    h = Decimal(str(hours))
    tier1 = min(h, Decimal(TIER1_HOURS))
    tier2 = max(h - Decimal(TIER1_HOURS), Decimal(0))
    u1 = (tier1 * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    u2 = (tier2 * rate * TIER2_MULTIPLIER).quantize(Decimal("1"),
                                                    rounding=ROUND_HALF_UP)
    uncapped = int(u1) + int(u2)
    cap = FEE_CAP_MULTIPLE * indenture["annual_admin_fee_cents"]
    return min(uncapped, cap)


def collateral_coverage_bps(indenture, pledged_items_excluding_subject, request):
    """Pinned evaluation order (scaffold calc collateral_coverage).
    All values kept in scaled integer units of cents*10000."""
    scaled_excl = sum(
        it["appraised_value_cents"] * (10000 - HAIRCUT_BPS[it["collateral_type"]])
        for it in pledged_items_excluding_subject
    )
    outstanding = indenture["outstanding_principal_cents"]
    if outstanding <= 0:
        return 0
    high_tier = scaled_excl >= 2 * 10000 * outstanding  # ratio >= 2.00
    sub_haircut = (SUBSTITUTE_HAIRCUT_HIGH_TIER_BPS if high_tier
                   else SUBSTITUTE_HAIRCUT_STANDARD_BPS)
    sub_scaled = 0
    if request.get("request_type") == "SUBSTITUTION":
        sub_scaled = (request["substitute_appraised_value_cents"]
                      * (10000 - sub_haircut))
    # floor( (cov + sub) * 10000 / outstanding ), values in scaled units
    return (scaled_excl + sub_scaled) // outstanding


def covenant_ratio_passes(obligation, certificate):
    """Inclusive boundary for both directions (PRD 3.3)."""
    threshold = obligation.get("threshold_value")
    if threshold is None:
        return True
    if obligation.get("measurement_basis") == "TTM":
        metric = certificate.get("ttm_metric_value")
    else:
        metric = certificate.get("metric_value")
    if metric is None:
        return False
    m = Decimal(str(metric))
    t = Decimal(str(threshold))
    if obligation.get("threshold_direction") == "MIN":
        return m >= t
    return m <= t


def quorum_effective(instruction_type, supporting, eligible):
    """Integer cross-multiplication only (calc quorum_tally)."""
    if instruction_type == "RESCIND_ACCELERATION":
        return supporting * 2 > eligible
    return supporting * 4 >= eligible


def consent_passed(consenting, threshold_bps, eligible):
    return consenting * 10000 >= threshold_bps * eligible


def record_date_cutoff(record_date_iso):
    """End of record date: 23:59:59.999 UTC."""
    d = parse_date_strict(record_date_iso)
    if d is None:
        return None
    return datetime.combine(d, time(23, 59, 59, 999000), tzinfo=timezone.utc)


def principal_as_of(position, cutoff_dt):
    """Latest principal_history entry with effective_from <= cutoff; 0 if the
    first entry postdates the record date."""
    best = None
    for entry in position.get("principal_history", []):
        eff = parse_datetime(entry.get("effective_from"))
        if eff is not None and eff <= cutoff_dt:
            if best is None or eff > best:
                best = eff
    if best is None:
        return 0
    for entry in position.get("principal_history", []):
        if parse_datetime(entry.get("effective_from")) == best:
            return entry["principal_cents"]
    return 0
