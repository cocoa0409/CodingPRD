"""All arithmetic rules (PRD sections 2.5, 3.4, 3.5, 3.6, 3.8).

Money is 2dp ROUND_HALF_UP; ratios and shares are 4dp ROUND_HALF_UP.
The single deliberate exception is the per-matter declination split, which
floors each share to whole cents (ROUND_DOWN) and gives the remainder to the
row for the first element of matter_types.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

D = Decimal
ZERO = D("0.00")
ZERO4 = D("0.0000")

# --- lookback / valuation constants -------------------------------------
LOOKBACK_YEARS = D("3")
REALIZATION_CAP = D("0.95")
PORTABILITY_HARD_CAP = D("0.90")
MIN_VERIFIED_RECORDS = 3
ROLE_FACTOR = {
    "BILLING_ATTORNEY": D("1.00"),
    "RELATIONSHIP_PARTNER": D("0.85"),
    "SERVICE_PARTNER": D("0.55"),
}
CONSENT_FACTOR = {
    "CONSENT_CONFIRMED": D("1.00"),
    "CONSENT_PENDING": D("0.60"),
}

# --- concentration constants --------------------------------------------
CONCENTRATION_HIGH_THRESHOLD = D("0.30")
CONCENTRATION_MEDIUM_THRESHOLD = D("0.20")
HAIRCUT = {"HIGH": D("0.15"), "MEDIUM": D("0.07"), "LOW": D("0.00")}

# --- expected contribution constants ------------------------------------
NOTICE_RAMP_THRESHOLD_DAYS = 60
RAMP_SHORT_NOTICE = D("0.85")
RAMP_LONG_NOTICE = D("0.70")
LEVERAGE_THRESHOLD = D("3.00")
LEVERAGE_UPLIFT = D("0.05")
RAMP_CAP = D("0.92")
RATE_ALIGNMENT_FLOOR = D("0.80")
RATE_ALIGNMENT_CEILING = D("1.10")

# --- net economics constants --------------------------------------------
OFFICE_BUILDOUT_COST_USD = D("50000.00")
PARALEGAL_SUPPORT_COST_USD = D("35000.00")
ONBOARDING_OVERHEAD_PCT = D("0.04")
TRUE_UP_HIGH_NET_THRESHOLD = D("500000.00")
TRUE_UP_HIGH_PCT = D("0.10")
TRUE_UP_LOW_PCT = D("0.05")

# --- search fee constants -----------------------------------------------
TAIL_OFF_DISCOUNT = D("0.50")

# --- committee constants ------------------------------------------------
QUORUM_FRACTION = D("0.60")
MIN_COMMITTEE_SIZE = 3
MAX_NEGOTIATION_ROUNDS = 3

# --- performance constants ----------------------------------------------
DAYS_PER_YEAR = D("365")
ON_PLAN_THRESHOLD = D("0.90")
WATCH_THRESHOLD = D("0.70")


def r2(value):
    return D(value).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def r4(value):
    return D(value).quantize(D("0.0001"), rounding=ROUND_HALF_UP)


def floor2(value):
    return D(value).quantize(D("0.01"), rounding=ROUND_DOWN)


def entry_baseline_portable_amount(entry, historical_base):
    """PRD 3.4 'Valuing one relationship'. Single rounding at the end."""
    avg_annual = r2(D(historical_base) / LOOKBACK_YEARS)
    role_factor = ROLE_FACTOR[entry["relationship_role"]]
    consent_factor = CONSENT_FACTOR[entry["client_consent_status"]]
    realization = min(entry["claimed_realization_rate"], REALIZATION_CAP)
    raw = avg_annual * role_factor * consent_factor * realization
    capped = min(raw, avg_annual * PORTABILITY_HARD_CAP)
    return r2(capped)


def self_reported_line(entry):
    return r2(entry["claimed_annual_billings_usd"] * entry["claimed_portability_pct"])


def variance_pct(self_reported_total, validated_total):
    if self_reported_total <= 0:
        return ZERO4
    return r4((self_reported_total - validated_total) / self_reported_total)


def concentration_shares(ranked_baselines, gross_baseline_total):
    """ranked_baselines is already ordered baseline DESC, created_at ASC."""
    if gross_baseline_total <= 0:
        return ZERO4, ZERO4
    top = r4(ranked_baselines[0] / gross_baseline_total) if ranked_baselines else ZERO4
    top3_sum = sum(ranked_baselines[:3], ZERO)
    top3 = r4(top3_sum / gross_baseline_total)
    return top, top3


def concentration_grade(top_client_share):
    if top_client_share >= CONCENTRATION_HIGH_THRESHOLD:
        return "HIGH"
    if top_client_share >= CONCENTRATION_MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def adjusted_total(governing_total, haircut_pct):
    return r2(governing_total * (D("1") - haircut_pct))


def rate_alignment_factor(target_rate, current_rate):
    quotient = D(target_rate) / D(current_rate)
    clamped = min(max(quotient, RATE_ALIGNMENT_FLOOR), RATE_ALIGNMENT_CEILING)
    return r4(clamped)


def expected_contribution(snapshot, notice_period_days, leverage_ratio,
                          target_rate, current_rate):
    ramp = RAMP_LONG_NOTICE if notice_period_days > NOTICE_RAMP_THRESHOLD_DAYS \
        else RAMP_SHORT_NOTICE
    uplift = LEVERAGE_UPLIFT if D(leverage_ratio) >= LEVERAGE_THRESHOLD else D("0.00")
    effective = min(ramp + uplift, RAMP_CAP)
    alignment = rate_alignment_factor(target_rate, current_rate)
    return r2(D(snapshot) * effective * alignment)


def declination_shares(baseline_amount, matter_type_count):
    """Floored per-matter share; the whole remainder goes to index 0."""
    count = int(matter_type_count)
    per_matter = floor2(D(baseline_amount) / D(count))
    remainder = D(baseline_amount) - (per_matter * count)
    shares = []
    for index in range(count):
        shares.append(per_matter + (remainder if index == 0 else ZERO))
    return shares


def quorum_minimum(eligible_voter_count):
    """CEIL(0.60 * eligible_voter_count) with exact integer arithmetic."""
    count = int(eligible_voter_count)
    return -((-3 * count) // 5)


def approval_met(approve_count, reject_count):
    return (approve_count * 3) >= (2 * (approve_count + reject_count))


def performance_flag(attainment):
    if attainment >= ON_PLAN_THRESHOLD:
        return "ON_PLAN"
    if attainment >= WATCH_THRESHOLD:
        return "WATCH"
    return "BELOW_PLAN"
