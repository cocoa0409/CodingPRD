"""Calculation rules (scaffold section 1.3 / PRD section 3)."""

from decimal import Decimal

from common import (
    dec,
    minutes_between,
    month_start,
    r2,
    r3,
    r4,
    trunc_int,
)

# --- reading_quality_classification ---------------------------------------
O2_WEIGHT = Decimal("4.0")
N2_WEIGHT = Decimal("0.35")
CH4_CREDIT_WEIGHT = Decimal("0.05")
TEMP_PIVOT_F = Decimal("130.0")
TEMP_WEIGHT = Decimal("0.25")
O2_ALARM_PCT = Decimal("5.00")
TEMP_ALARM_F = Decimal("145.0")
AII_ALARM = Decimal("24.00")
O2_WATCH_PCT = Decimal("2.00")
CH4_WATCH_PCT = Decimal("45.00")
AII_WATCH = Decimal("6.00")
THROTTLE_FACTOR = Decimal("0.60")

# --- injection_batch_gross_mmbtu ------------------------------------------
MMBTU_PER_MSCF_CH4 = Decimal("1.0122")

# --- rin_d3_generation ----------------------------------------------------
RINS_PER_MMBTU_D3 = Decimal("11.727")

# --- lcfs_credit_generation ----------------------------------------------
BASE_CI_LFG_RNG = Decimal("44.000")
FLARE_PENALTY_COEFF = Decimal("60.000")
CI_TIER_LOW = Decimal("20.000")
CI_TIER_MID = Decimal("40.000")
AVOIDED_TIER_A = Decimal("22.500")
AVOIDED_TIER_B = Decimal("15.000")
AVOIDED_TIER_C = Decimal("7.500")
CI_BENCHMARK = Decimal("91.980")
EER_CNG = Decimal("0.90")
MJ_PER_MMBTU = Decimal("1055.06")

# --- royalty_settlement ---------------------------------------------------
RIN_PRICE_USD = Decimal("2.85")
LCFS_PRICE_USD = Decimal("62.00")

# --- work_order_lockout_occupancy ----------------------------------------
LOCKOUT_BUFFER_MINUTES = 120


def air_intrusion_index(methane_pct, oxygen_pct, nitrogen_pct, temperature_f):
    excess = temperature_f - TEMP_PIVOT_F
    if excess < 0:
        excess = Decimal("0")
    raw = (
        (oxygen_pct * O2_WEIGHT)
        + (nitrogen_pct * N2_WEIGHT)
        - (methane_pct * CH4_CREDIT_WEIGHT)
        + (excess * TEMP_WEIGHT)
    )
    return r2(raw)


def quality_class(methane_pct, oxygen_pct, temperature_f, index):
    """Three-rung ladder, top down; the FIRST matching rung wins."""
    if (
        oxygen_pct >= O2_ALARM_PCT
        or temperature_f >= TEMP_ALARM_F
        or index >= AII_ALARM
    ):
        return "ALARM"
    if (
        oxygen_pct >= O2_WATCH_PCT
        or methane_pct < CH4_WATCH_PCT
        or index >= AII_WATCH
    ):
        return "WATCH"
    return "GOOD"


def throttled_flow(reading_flow, target_flow):
    cap = target_flow * THROTTLE_FACTOR
    return r2(reading_flow if reading_flow < cap else cap)


def gross_mmbtu(hourly_volumes, methane_pct):
    """Round EACH hour to 2 dp first, then sum, then round the sum to 2 dp."""
    methane_fraction = methane_pct / Decimal("100")
    total = Decimal("0")
    for volume in hourly_volumes:
        total += r2(volume * methane_fraction * MMBTU_PER_MSCF_CH4)
    return r2(total)


def _clip(interval, window):
    start = interval[0] if interval[0] > window[0] else window[0]
    end = interval[1] if interval[1] < window[1] else window[1]
    if end <= start:
        return None
    return (start, end)


def _merged_minutes(intervals):
    """Merge intervals that overlap OR merely touch; total length in minutes."""
    if not intervals:
        return Decimal("0")
    total = Decimal("0")
    current_start, current_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= current_end:
            if end > current_end:
                current_end = end
        else:
            total += minutes_between(current_start, current_end)
            current_start, current_end = start, end
    total += minutes_between(current_start, current_end)
    return total


def availability(closed_events, current_utc):
    """Returns (downtime_minutes_mtd, flare_minutes_mtd, availability_factor_pct)."""
    period_start = month_start(current_utc)
    window = (period_start, current_utc)

    ordered = sorted(closed_events, key=lambda e: (e["start_at"], e["created_at"], e["_seq"]))

    clipped_all = []
    clipped_flared = []
    for event in ordered:
        piece = _clip((event["start_at"], event["end_at"]), window)
        if piece is None:
            continue
        clipped_all.append(piece)
        if event["disposition"] == "FLARED":
            clipped_flared.append(piece)

    clipped_all.sort(key=lambda p: p[0])
    clipped_flared.sort(key=lambda p: p[0])

    downtime_minutes = r2(_merged_minutes(clipped_all))
    flare_minutes = r2(_merged_minutes(clipped_flared))

    elapsed = minutes_between(period_start, current_utc)
    if elapsed <= 0:
        factor = r2(Decimal("100"))
    else:
        factor = r2(Decimal("100") * (elapsed - downtime_minutes) / elapsed)
    return downtime_minutes, flare_minutes, factor


def eligibility_factor(availability_factor_pct):
    return r4(dec(availability_factor_pct) / Decimal("100"))


def rin_d3(energy_basis, factor):
    return trunc_int(energy_basis * RINS_PER_MMBTU_D3 * factor)


def lcfs(energy_basis, energy_injected, energy_flared):
    """Four-step carbon-intensity waterfall; the tier is picked from ci_pre."""
    denom = energy_injected + energy_flared
    if denom == 0:
        flare_fraction = Decimal("0.0000")
    else:
        flare_fraction = r4(energy_flared / denom)
    flare_penalty = r3(flare_fraction * FLARE_PENALTY_COEFF)
    ci_pre = r3(BASE_CI_LFG_RNG + flare_penalty)

    if ci_pre < CI_TIER_LOW:
        credit = AVOIDED_TIER_A
    elif ci_pre < CI_TIER_MID:
        credit = AVOIDED_TIER_B
    else:
        credit = AVOIDED_TIER_C

    ci_project = r3(ci_pre - credit)
    energy_mj = r2(energy_basis * MJ_PER_MMBTU)
    credits = r4(
        (CI_BENCHMARK - ci_project) * EER_CNG * energy_mj / Decimal("1000000")
    )
    return ci_project, credits


def hourly_rate(nominated_dth, gas_day_start, gas_day_end):
    hours = Decimal(str((gas_day_end - gas_day_start).total_seconds())) / Decimal("3600")
    return r4(nominated_dth / hours)
