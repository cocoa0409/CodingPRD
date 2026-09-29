"""Pure calculations (scaffold section 1.3). Every rounding order is pinned."""
from decimal import Decimal

from constants import (
    ACTIVITY_FLOOR,
    BASE_FEE_PER_MT,
    BASE_MARGIN_PCT,
    DECAY_PER_KMT,
    EER,
    ENERGY_DENSITY_MJ_PER_GAL,
    FEE_CAP_USD,
    FEE_FLOOR_USD,
    FREIGHT_PCT,
    GAL_PER_MT,
    H2_KG_PER_MT,
    LCFS_BENCHMARK_CI,
    PRETREAT_CI_ADDER,
    PROCESS_CI_ADDER,
    RIN_EQUIVALENCE,
    RIN_INVALID_RATE_CAP,
    SAF_CONVERSION_PENALTY,
    SAF_SEVERITY_FACTOR,
    TIER_T2_FLOOR_USD,
    TIER_T3_FLOOR_USD,
    TYPE_MULT,
    VERIFICATION_DISCOUNT,
    VOL_ADDER_PCT,
    WASTE_TYPES,
    YIELD_MASS_PCT,
    D,
)
from store import q, trunc

ZERO = Decimal("0")
TIER_NAMES = ["NONE", "LIGHT", "HEAVY"]


# ---------------------------------------------------------------------------
# pretreatment_tier_and_fee
# ---------------------------------------------------------------------------
def pretreatment_tier_and_fee(feedstock_type, mass_mt, ffa_pct, moisture_pct,
                              insolubles_ppm, phosphorus_ppm):
    ffa_idx = 2 if ffa_pct >= D("5.00") else (1 if ffa_pct >= D("2.00") else 0)
    moist_idx = 2 if moisture_pct >= D("1.00") else (1 if moisture_pct >= D("0.50") else 0)
    insol_idx = 2 if insolubles_ppm >= 1500 else (1 if insolubles_ppm >= 500 else 0)
    phos_idx = 2 if phosphorus_ppm >= 20 else (1 if phosphorus_ppm >= 10 else 0)

    out = {
        "ffa_tier_index": ffa_idx,
        "moisture_tier_index": moist_idx,
        "insolubles_tier_index": insol_idx,
        "phosphorus_tier_index": phos_idx,
    }

    if (ffa_pct > D("15.00") or moisture_pct > D("3.00")
            or insolubles_ppm > 5000 or phosphorus_ppm > 500):
        out["tier"] = "HEAVY"
        out["disposition"] = "REJECT"
        out["fee"] = q(ZERO, 2)
        return out

    tier_index = max(ffa_idx, moist_idx, insol_idx, phos_idx)
    if feedstock_type in WASTE_TYPES and phosphorus_ppm >= 10:
        tier_index = min(2, tier_index + 1)

    tier = TIER_NAMES[tier_index]
    out["tier"] = tier
    out["disposition"] = "PASS" if tier_index == 0 else "PRETREAT"

    if tier_index == 0:
        out["fee"] = q(ZERO, 2)
    else:
        linear = BASE_FEE_PER_MT[tier] * mass_mt * TYPE_MULT[feedstock_type]
        if linear < FEE_FLOOR_USD:
            linear = FEE_FLOOR_USD
        if linear > FEE_CAP_USD:
            linear = FEE_CAP_USD
        out["fee"] = q(linear, 2)
    return out


# ---------------------------------------------------------------------------
# blend_carbon_intensity / hydrogen_requirement
# ---------------------------------------------------------------------------
def blend_carbon_intensity(lines):
    """lines: iterable of (mass_mt, lot)."""
    lines = list(lines)
    if not lines:
        return None
    numerator = ZERO
    denominator = ZERO
    for mass, lot in lines:
        numerator += mass * (lot["attested_ci_gco2e_per_mj"]
                             + PRETREAT_CI_ADDER[lot["pretreatment_tier"]])
        denominator += mass
    if denominator == 0:
        return None
    return q(numerator / denominator, 2)


def hydrogen_requirement(lines, run_days, target_saf_share_pct):
    lines = list(lines)
    if not lines:
        return None
    total_mass = ZERO
    weighted = ZERO
    for mass, lot in lines:
        total_mass += mass
        weighted += mass * H2_KG_PER_MT[lot["feedstock_type"]]
    if total_mass == 0 or not run_days:
        return None
    weighted_h2 = weighted / total_mass
    daily_feed_mt = q(total_mass / Decimal(run_days), 3)
    uplift = Decimal(1) + SAF_SEVERITY_FACTOR * target_saf_share_pct / Decimal(100)
    return q(daily_feed_mt * weighted_h2 * uplift, 1)


# ---------------------------------------------------------------------------
# catalyst_activity_decay
# ---------------------------------------------------------------------------
def catalyst_activity_index(cumulative_throughput_mt):
    raw = Decimal(1) - DECAY_PER_KMT * (cumulative_throughput_mt / Decimal(1000))
    if raw < ACTIVITY_FLOOR:
        raw = ACTIVITY_FLOOR
    return q(raw, 4)


# ---------------------------------------------------------------------------
# run_yield_split
# ---------------------------------------------------------------------------
def blend_yield_pct(lines):
    lines = list(lines)
    total = ZERO
    weighted = ZERO
    for mass, lot in lines:
        total += mass
        weighted += mass * YIELD_MASS_PCT[lot["feedstock_type"]]
    if total == 0:
        return None
    return weighted / total


def provisional_split(lines, activity_index, reserved_mass_mt, target_saf_share_pct):
    blend = blend_yield_pct(lines)
    if blend is None:
        return None
    provisional_yield = q(blend * activity_index, 3)
    planned_total = q(reserved_mass_mt * provisional_yield / Decimal(100), 3)
    planned_saf = q(planned_total * (target_saf_share_pct / Decimal(100))
                    * SAF_CONVERSION_PENALTY, 3)
    planned_rd = q(planned_total - planned_saf, 3)
    return {
        "provisional_yield_pct": provisional_yield,
        "planned_total_product_mt": planned_total,
        "planned_rd_mt": planned_rd,
        "planned_saf_mt": planned_saf,
    }


def final_yield(measured_rd_mt, measured_saf_mt, consumed_mass_mt):
    if consumed_mass_mt == 0:
        return q(ZERO, 3)
    return q((measured_rd_mt + measured_saf_mt) / consumed_mass_mt * Decimal(100), 3)


# ---------------------------------------------------------------------------
# feedstock_settlement_cost
# ---------------------------------------------------------------------------
def settlement_line(mass_mt, purchase_price_usd_per_mt):
    return q(mass_mt * purchase_price_usd_per_mt * (Decimal(1) + FREIGHT_PCT), 2)


# ---------------------------------------------------------------------------
# hedge_margin_requirement
# ---------------------------------------------------------------------------
def hedge_margin(instrument, notional_units, strike_price_usd, tier_override=None):
    gross = q(notional_units * strike_price_usd, 2)
    base = q(gross * BASE_MARGIN_PCT[instrument], 2)
    if tier_override is not None:
        tier = tier_override
    elif base >= TIER_T3_FLOOR_USD:
        tier = "T3"
    elif base >= TIER_T2_FLOOR_USD:
        tier = "T2"
    else:
        tier = "T1"
    adder = q(base * VOL_ADDER_PCT[tier], 2)
    total = q(base + adder, 2)
    return {
        "gross_notional_usd": gross,
        "base_margin_usd": base,
        "volatility_tier": tier,
        "volatility_adder_usd": adder,
        "total_margin_usd": total,
    }


# ---------------------------------------------------------------------------
# product_volume_conversion
# ---------------------------------------------------------------------------
def product_volume(mass_mt, product_type):
    return q(mass_mt * GAL_PER_MT[product_type], 1)


# ---------------------------------------------------------------------------
# credit quantities
# ---------------------------------------------------------------------------
def provisional_ci(blend_ci):
    base = blend_ci if blend_ci is not None else ZERO
    return q(base + PROCESS_CI_ADDER, 2)


def provisional_rin(volume_gal, product_type):
    return trunc(volume_gal * RIN_EQUIVALENCE[product_type])


def verified_rin(volume_gal, product_type, provisional_ci_value, verified_ci):
    if provisional_ci_value == 0:
        drift = q(ZERO, 4)
    else:
        drift = q((verified_ci - provisional_ci_value) / provisional_ci_value, 4)
    rate = drift
    if rate < Decimal("0.0000"):
        rate = Decimal("0.0000")
    if rate > RIN_INVALID_RATE_CAP:
        rate = RIN_INVALID_RATE_CAP
    return trunc(volume_gal * RIN_EQUIVALENCE[product_type] * (Decimal(1) - rate))


def _lcfs(volume_gal, product_type, ci_value, discount):
    raw = ((LCFS_BENCHMARK_CI[product_type] - ci_value)
           * EER[product_type]
           * ENERGY_DENSITY_MJ_PER_GAL[product_type]
           * volume_gal / Decimal(1000000))
    if discount is not None:
        raw = raw * discount
    value = q(raw, 3)
    if value < Decimal("0.000"):
        value = Decimal("0.000")
    return value


def provisional_lcfs(volume_gal, product_type, provisional_ci_value):
    return _lcfs(volume_gal, product_type, provisional_ci_value, None)


def verified_lcfs(volume_gal, product_type, verified_ci):
    return _lcfs(volume_gal, product_type, verified_ci, VERIFICATION_DISCOUNT)
