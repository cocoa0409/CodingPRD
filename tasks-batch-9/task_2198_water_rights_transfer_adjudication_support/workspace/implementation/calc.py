"""Deterministic calculations. Every arithmetic step uses Decimal with
half-up rounding at the precision the specification pins."""
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")
ZERO2 = Decimal("0.00")

# --- historical consumptive use -------------------------------------------
DIVERSION_CU_FACTOR = Decimal("0.65")
CIR_CU_FACTOR = Decimal("2.10")
FACE_CAP_FACTOR = Decimal("0.65")
SHORT_HISTORY_MIN_YEARS = 3
SHORT_HISTORY_HAIRCUT = Decimal("0.85")
ADMISSIBLE_SOURCES = ("METER", "AERIAL_IMAGERY")

# --- injury ----------------------------------------------------------------
INSTANTANEOUS_BASE = Decimal("0.92")
DISTANCE_DECAY_PER_MILE = Decimal("0.015")
DISTANCE_FACTOR_FLOOR = Decimal("0.55")
SEASONAL_BASE = Decimal("0.78")
INJURY_MATERIALITY_AF = Decimal("0.01")

# --- mitigation fee --------------------------------------------------------
FEE_PER_AF = Decimal("125.00")
FEE_TIER_LOW_CEILING = Decimal("5000.00")
FEE_TIER_MID_CEILING = Decimal("20000.00")
FEE_TIER_LOW_PCT = Decimal("0.040")
FEE_TIER_MID_PCT = Decimal("0.070")
FEE_TIER_HIGH_PCT = Decimal("0.095")

# --- forfeiture ------------------------------------------------------------
LOOKBACK_YEARS = 10
USE_THRESHOLD_AF = Decimal("0.50")
NONUSE_WEIGHT = Decimal("9")
UNVERIFIED_WEIGHT = Decimal("25")
UNDERUSE_WEIGHT = Decimal("30")
METER_CREDIT = Decimal("10")
SUSPENDED_PENALTY = Decimal("12")
BAND_HIGH = Decimal("70")
BAND_ELEVATED = Decimal("40")
FORFEITURE_ELIGIBLE_YEARS = 5
UNVERIFIED_SOURCES = ("AFFIDAVIT", "NONE")

# --- lease -----------------------------------------------------------------
SEASON_BLOCK_DAYS = 30
LEASE_BUFFER_DAYS = 7

# --- bank posture ----------------------------------------------------------
LOW_CREDIT_THRESHOLD_AF = Decimal("5.00")

# --- adjudication ----------------------------------------------------------
OBJECTION_HAIRCUT = Decimal("0.90")
PRIORITY_MISMATCH_HAIRCUT = Decimal("0.90")
PRIORITY_DATE_TOLERANCE_DAYS = 366


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def q(value, places):
    """Half-up quantisation to `places` decimal places."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def q2(value):
    return q(value, 2)


def q3(value):
    return q(value, 3)


def q4(value):
    return q(value, 4)


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


# ---------------------------------------------------------------------------
# calculations.hcu_transferable_volume
# ---------------------------------------------------------------------------

def hcu_transferable_volume(method, records, authorized_diversion_af):
    """`records` are the admissible BeneficialUseRecord rows in use_year ASC.

    Returns a dict with qualifying_year_count, average_annual_cu_af,
    short_history_haircut_applied and transferable_cu_af.
    """
    count = len(records)
    if count == 0:
        return {
            "qualifying_year_count": 0,
            "average_annual_cu_af": Decimal("0.000"),
            "short_history_haircut_applied": False,
            "transferable_cu_af": ZERO2,
        }
    total = ZERO
    for rec in records:
        if method == "DIVERSION_BASED":
            per_year = q3(D(rec["reported_diversion_af"]) * DIVERSION_CU_FACTOR)
        else:
            per_year = q3(D(rec["irrigated_acres"]) * CIR_CU_FACTOR)
        total += per_year
    average = q3(total / Decimal(count))
    face_cap = q3(D(authorized_diversion_af) * FACE_CAP_FACTOR)
    capped = average if average <= face_cap else face_cap
    haircut_applied = count < SHORT_HISTORY_MIN_YEARS
    factor = SHORT_HISTORY_HAIRCUT if haircut_applied else Decimal("1")
    transferable = q2(capped * factor)
    return {
        "qualifying_year_count": count,
        "average_annual_cu_af": average,
        "short_history_haircut_applied": haircut_applied,
        "transferable_cu_af": transferable,
    }


def admissible_use_records(records, start_year, end_year):
    """Filter + order per calculations.hcu_transferable_volume."""
    selected = [
        r
        for r in records
        if start_year <= r["use_year"] <= end_year
        and r["verification_source"] in ADMISSIBLE_SOURCES
        and D(r["reported_diversion_af"]) > ZERO
    ]
    selected.sort(key=lambda r: (r["use_year"], r["_seq"]))
    return selected


# ---------------------------------------------------------------------------
# calculations.injury_net_analysis
# ---------------------------------------------------------------------------

def injury_gross_depletion(method, requested_af, pod_move_miles):
    if method == "INSTANTANEOUS_DEPLETION":
        factor = q4(Decimal("1") - DISTANCE_DECAY_PER_MILE * D(pod_move_miles))
        if factor < DISTANCE_FACTOR_FLOOR:
            factor = DISTANCE_FACTOR_FLOOR
        return q2(D(requested_af) * INSTANTANEOUS_BASE * factor)
    return q2(D(requested_af) * SEASONAL_BASE)


def injury_net(gross_af, offset_af, return_flow_credit_af):
    net = D(gross_af) - D(offset_af) - D(return_flow_credit_af)
    if net < ZERO:
        net = ZERO
    return q2(net)


# ---------------------------------------------------------------------------
# calculations.mitigation_fee
# ---------------------------------------------------------------------------

def mitigation_fee(required_af):
    base = q2(D(required_af) * FEE_PER_AF)
    if base < FEE_TIER_LOW_CEILING:
        pct = FEE_TIER_LOW_PCT
    elif base < FEE_TIER_MID_CEILING:
        pct = FEE_TIER_MID_PCT
    else:
        pct = FEE_TIER_HIGH_PCT
    admin = q2(base * pct)
    total = q2(base + admin)
    return {
        "base_fee_usd": base,
        "surcharge_pct": q3(pct),
        "admin_surcharge_usd": admin,
        "total_fee_usd": total,
    }


# ---------------------------------------------------------------------------
# calculations.forfeiture_risk_score
# ---------------------------------------------------------------------------

def forfeiture_assessment(records, authorized_diversion_af, right_status, current_year):
    """Ten-year look-back ending with the calendar year before the current one."""
    start_year = current_year - LOOKBACK_YEARS
    end_year = current_year - 1
    window = [r for r in records if start_year <= r["use_year"] <= end_year]
    by_year = {}
    for rec in window:
        by_year[rec["use_year"]] = rec

    nonuse_years = []
    for year in range(start_year, end_year + 1):
        rec = by_year.get(year)
        used = rec is not None and D(rec["reported_diversion_af"]) >= USE_THRESHOLD_AF
        nonuse_years.append(not used)

    nonuse_year_count = sum(1 for flag in nonuse_years if flag)
    longest = 0
    run = 0
    for flag in nonuse_years:
        if flag:
            run += 1
            if run > longest:
                longest = run
        else:
            run = 0

    n = len(window)
    denom = Decimal(max(1, n))
    unverified_count = sum(
        1 for r in window if r["verification_source"] in UNVERIFIED_SOURCES
    )
    unverified_ratio = q4(Decimal(unverified_count) / denom)
    reported_sum = ZERO
    for r in window:
        reported_sum += D(r["reported_diversion_af"])
    mean_reported = q3(reported_sum / denom)
    authorized = D(authorized_diversion_af)
    if authorized > ZERO:
        utilization = q4(mean_reported / authorized)
    else:
        utilization = Decimal("1.0000")
    if utilization > Decimal("1"):
        utilization = Decimal("1.0000")

    meter_credit = METER_CREDIT if any(
        r["verification_source"] == "METER" for r in window
    ) else ZERO
    suspended_penalty = SUSPENDED_PENALTY if right_status == "SUSPENDED" else ZERO

    nonuse_component = Decimal(longest) * NONUSE_WEIGHT
    unverified_component = unverified_ratio * UNVERIFIED_WEIGHT
    underuse_component = (Decimal("1") - utilization) * UNDERUSE_WEIGHT

    raw = (
        nonuse_component
        + unverified_component
        + underuse_component
        + suspended_penalty
        - meter_credit
    )
    score = q2(clamp(raw, ZERO, Decimal("100")))
    if score >= BAND_HIGH:
        band = "HIGH"
    elif score >= BAND_ELEVATED:
        band = "ELEVATED"
    else:
        band = "LOW"
    return {
        "lookback_start_year": start_year,
        "lookback_end_year": end_year,
        "nonuse_year_count": nonuse_year_count,
        "consecutive_nonuse_years": longest,
        "unverified_ratio": unverified_ratio,
        "mean_reported_af": mean_reported,
        "utilization": utilization,
        "nonuse_component": q2(nonuse_component),
        "unverified_component": q2(unverified_component),
        "underuse_component": q2(underuse_component),
        "suspended_penalty": q2(suspended_penalty),
        "meter_credit": q2(meter_credit),
        "forfeiture_risk_score": score,
        "forfeiture_risk_band": band,
        "forfeiture_eligible": longest >= FORFEITURE_ELIGIBLE_YEARS,
    }


# ---------------------------------------------------------------------------
# calculations.lease_settlement_credit
# ---------------------------------------------------------------------------

def lease_term_days(start_dt, end_dt):
    return (end_dt - start_dt).days


def lease_settlement(requested_af, start_dt, end_dt, now_dt, valuation_method,
                     from_reserved=False):
    term_days = lease_term_days(start_dt, end_dt)
    if from_reserved:
        used = ZERO2
        return {"used_af": used, "settlement_credit_af": q2(D(requested_af))}
    horizon = now_dt if now_dt < end_dt else end_dt
    elapsed_days = (horizon - start_dt).days
    if elapsed_days < 0:
        elapsed_days = 0
    if valuation_method == "PRO_RATA_DAILY":
        charged_days = elapsed_days
    else:
        if elapsed_days == 0:
            blocks = 0
        else:
            blocks = -(-elapsed_days // SEASON_BLOCK_DAYS)
        charged_days = blocks * SEASON_BLOCK_DAYS
        if charged_days > term_days:
            charged_days = term_days
    if term_days <= 0:
        used = ZERO2
    else:
        used = q2(q3(D(requested_af) * Decimal(charged_days) / Decimal(term_days)))
    credit = q2(D(requested_af) - used)
    return {"used_af": used, "settlement_credit_af": credit}


# ---------------------------------------------------------------------------
# calculations.bank_posture
# ---------------------------------------------------------------------------

def bank_posture(claimant_standing, suspended_lease_count, available_credit_af):
    if claimant_standing == "BARRED" or suspended_lease_count >= 1:
        return "FROZEN"
    if claimant_standing == "DELINQUENT" or D(available_credit_af) < LOW_CREDIT_THRESHOLD_AF:
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# calculations.decreed_volume
# ---------------------------------------------------------------------------

def decreed_volume(claimed_af, examiner_recommended_af, objection_count,
                   claimed_priority_dt, right_priority_dt):
    claimed = D(claimed_af)
    recommended = D(examiner_recommended_af)
    base = claimed if claimed <= recommended else recommended
    if objection_count >= 1:
        base = q3(base * OBJECTION_HAIRCUT)
    if claimed_priority_dt is not None and right_priority_dt is not None:
        delta = abs((claimed_priority_dt - right_priority_dt).days)
        if delta > PRIORITY_DATE_TOLERANCE_DAYS:
            base = q3(base * PRIORITY_MISMATCH_HAIRCUT)
    return q2(base)


# ---------------------------------------------------------------------------
# calculations.pod_concurrent_rate_load  (half-open overlap)
# ---------------------------------------------------------------------------

def intervals_overlap_half_open(a_start, a_end, b_start, b_end):
    return a_start < b_end and a_end > b_start


def pod_peak_rate(candidate_rate_cfs, existing_rates):
    total = D(candidate_rate_cfs)
    for rate in existing_rates:
        total += D(rate)
    return q3(total)
