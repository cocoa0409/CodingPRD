"""The nine pinned calculations (PRD 2.6 + 3.x).

All money and index arithmetic runs through decimal.Decimal with ROUND_HALF_UP.
No float ever participates in a computation.
"""

from decimal import Decimal

from store import clamp, dec, rh

ZERO = Decimal(0)

# --- 1. trial performance index -------------------------------------
YIELD_WEIGHT = Decimal("0.40")
VIGOR_WEIGHT = Decimal("0.20")
UNIFORMITY_WEIGHT = Decimal("0.20")
DISEASE_WEIGHT = Decimal("0.20")

PASS_INDEX_THRESHOLD = Decimal("72.00")
PASS_RATE_THRESHOLD = Decimal("0.9500")


def trial_performance_index(yield_index, vigor_score, uniformity_score,
                            disease_resistance_score, propagation_pass_rate):
    """Four weighted components, each rounded to 2dp, summed, then scaled by
    the propagation pass rate and rounded to 2dp again."""
    c_yield = rh(dec(yield_index) * YIELD_WEIGHT, 2)
    c_vigor = rh(dec(vigor_score) * VIGOR_WEIGHT, 2)
    c_uniformity = rh(dec(uniformity_score) * UNIFORMITY_WEIGHT, 2)
    c_disease = rh(dec(disease_resistance_score) * DISEASE_WEIGHT, 2)
    raw = c_yield + c_vigor + c_uniformity + c_disease
    return rh(raw * dec(propagation_pass_rate), 2)


def mean_index(values):
    if not values:
        return Decimal("0.00")
    total = ZERO
    for value in values:
        total += dec(value)
    return rh(total / Decimal(len(values)), 2)


# --- 3. annuity total due -------------------------------------------
def annuity_amounts(annuity_base_cents, days_late):
    """Returns (surcharge, volume_credit, total_due) in whole cents."""
    base = Decimal(int(annuity_base_cents))
    if days_late <= 0:
        surcharge_pct = Decimal("0")
    elif days_late <= 30:
        surcharge_pct = Decimal("0.05")
    elif days_late <= 60:
        surcharge_pct = Decimal("0.12")
    else:
        surcharge_pct = Decimal("0.20")
    surcharge = rh(base * surcharge_pct, 0)
    pre_credit = base + surcharge
    if pre_credit < Decimal(200000):
        credit_pct = Decimal("0")
    elif pre_credit <= Decimal(499999):
        credit_pct = Decimal("0.03")
    else:
        credit_pct = Decimal("0.06")
    credit = rh(pre_credit * credit_pct, 0)
    total = pre_credit - credit
    return int(surcharge), int(credit), int(total)


# --- 4. effective royalty rate --------------------------------------
TIER_MULTIPLIER = {
    "TIER_A": Decimal("1.15"),
    "TIER_B": Decimal("1.00"),
    "TIER_C": Decimal("0.85"),
}

TERRITORY_MULTIPLIER = {
    "EXPORT": Decimal("1.25"),
    "DOMESTIC": Decimal("1.00"),
}

RATE_FLOOR_FACTOR = Decimal("0.75")
RATE_CAP_FACTOR = Decimal("1.50")


def volume_multiplier(billable_units):
    units = int(billable_units)
    if units <= 10000:
        return Decimal("1.00")
    if units <= 50000:
        return Decimal("0.95")
    return Decimal("0.90")


def performance_multiplier(regional_performance_index):
    excess = (dec(regional_performance_index) - Decimal("72.00")) / Decimal(100)
    return Decimal(1) + clamp(excess, Decimal("0.00"), Decimal("0.10"))


def effective_royalty_rate(base_rate_cents, quality_tier, territory_class,
                           billable_units, regional_performance_index):
    base = dec(base_rate_cents)
    tier = TIER_MULTIPLIER[quality_tier]
    territory = TERRITORY_MULTIPLIER[territory_class]
    volume = volume_multiplier(billable_units)
    performance = performance_multiplier(regional_performance_index)
    raw = rh(base * tier * territory * volume * performance, 4)
    floor_rate = rh(base * RATE_FLOOR_FACTOR, 4)
    cap_rate = rh(base * RATE_CAP_FACTOR, 4)
    bounded = min(cap_rate, max(floor_rate, raw))
    return rh(bounded, 4)


def line_amount_cents(billable_units, effective_rate_cents):
    return int(rh(Decimal(int(billable_units)) * dec(effective_rate_cents), 0))


LATE_FEE_RATE = Decimal("0.02")


def late_fee_cents(final_total_cents):
    return int(rh(Decimal(int(final_total_cents)) * LATE_FEE_RATE, 0))


# --- 6. compliance scoring ------------------------------------------
PENALTY_LATE_REPORT = 6
PENALTY_QUOTA_OVERRUN = 15
PENALTY_MINOR_AUDIT_FINDING = 10
PENALTY_MATERIAL_AUDIT_FINDING = 25
PENALTY_CONFIRMED_UNAUTH_MATCH = 30

COMPLIANCE_WINDOW_DAYS = 120
COMPLIANCE_SUSPEND_THRESHOLD = 70


def score_from_points(points):
    return int(clamp(100 - int(points), 0, 100))


# --- 7. damages waterfall -------------------------------------------
BREEDER_SHARE = Decimal("0.70")


def damages_waterfall(recovered_damages_cents, enforcement_cost_cents):
    recovered = int(recovered_damages_cents)
    cost = int(enforcement_cost_cents)
    recovery = min(recovered, cost)
    remainder = recovered - recovery
    breeder_target = int(rh(Decimal(recovered) * BREEDER_SHARE, 0))
    breeder_pool = min(remainder, breeder_target)
    propagator_credit = remainder - breeder_pool
    return recovery, breeder_pool, propagator_credit


# PRD 3.9 -- the genetic-match threshold is inclusive at exactly 0.9000.
MATCH_THRESHOLD = Decimal("0.9000")
