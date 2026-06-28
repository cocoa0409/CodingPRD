"""Calculation rules (PRD §2.6-§2.8, §3 / SCAFFOLD §1.3).

All money is integer cents; fractional cents are rounded half-up. Risk scores
are reals rounded to two decimal places, half-up. The multiplier table values
are exact two-decimal constants and are NOT rounded.
"""
from decimal import Decimal, ROUND_HALF_UP

# ---- shared constants (SCAFFOLD §1.3 footer + calc constants) ----
MIN_SCORING_TRIPS = 3
QUOTE_VALIDITY_DAYS = 14
CRASH_FNOL_SEVERITY = 4
MAX_CLAIM_REOPENS = 2

MULT_FLOOR = Decimal("0.85")
MULT_CEILING = Decimal("1.60")
TIER_SAFE_UPPER = Decimal("10.0")
TIER_STANDARD_UPPER = Decimal("25.0")
TIER_ELEVATED_UPPER = Decimal("50.0")

PERIODS_PER_YEAR = 12
RENEWAL_MAX_DISCOUNT_CENTS = 50000
SAFE_TRIP_MIN_MILES = Decimal("5.0")
SAFE_TRIP_DISCOUNT_CENTS = 250
RESERVE_BASE_CENTS = 100000


def _dec(value) -> Decimal:
    """Coerce a number to Decimal without binary-float artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    return Decimal(str(value))


def round_half_up_cents(value) -> int:
    """Round a (possibly fractional) cent amount to a whole cent, half-up."""
    return int(_dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_score(value) -> float:
    """Round a risk score to two decimal places, half-up. Returned as float."""
    d = _dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


# ---------------------------------------------------------------------------
# Risk scoring — DUAL VARIANT (PRD §2.7, §3.3, §3.5)
# ---------------------------------------------------------------------------
def provisional_risk_score(trips, plan) -> float:
    """TEST-DRIVE variant: per-100-miles normalization (PRD §3.3).

    `trips` is the list of ACCEPTED enrollment trips. total_miles > 0 is
    guaranteed by the MIN_SCORING_TRIPS rule at finalize time.
    """
    total_miles = sum(_dec(t["distance_miles"]) for t in trips)
    if total_miles == 0:
        return 0.0
    hb = sum(t["hard_brake_count"] for t in trips)
    sp = sum(t["speeding_count"] for t in trips)
    pu = sum(t["phone_use_count"] for t in trips)
    per100 = Decimal("100") / total_miles
    raw = (
        _dec(plan["hard_brake_weight"]) * (_dec(hb) * per100)
        + _dec(plan["speeding_weight"]) * (_dec(sp) * per100)
        + _dec(plan["phone_use_weight"]) * (_dec(pu) * per100)
    )
    return round_half_up_score(raw)


def operational_risk_score(trips, plan) -> float:
    """OPERATIONAL variant: absolute lifetime counts, no normalization (PRD §3.5).

    `trips` is the list of ACCEPTED policy trips.
    """
    hb = sum(t["hard_brake_count"] for t in trips)
    sp = sum(t["speeding_count"] for t in trips)
    pu = sum(t["phone_use_count"] for t in trips)
    raw = (
        _dec(plan["hard_brake_weight"]) * _dec(hb)
        + _dec(plan["speeding_weight"]) * _dec(sp)
        + _dec(plan["phone_use_weight"]) * _dec(pu)
    )
    return round_half_up_score(raw)


# ---------------------------------------------------------------------------
# Risk multiplier tiers (PRD §2.8)
# ---------------------------------------------------------------------------
def risk_multiplier(risk_score) -> float:
    """Convert a risk score to a premium multiplier via the half-open four-tier
    table, then clamp to [floor, ceiling] (PRD §2.8). Returned as float."""
    s = _dec(risk_score)
    if s < TIER_SAFE_UPPER:
        m = Decimal("0.85")
    elif s < TIER_STANDARD_UPPER:
        m = Decimal("1.00")
    elif s < TIER_ELEVATED_UPPER:
        m = Decimal("1.25")
    else:
        m = Decimal("1.60")
    # clamp(m, floor, ceiling) — nested min/max guard
    m = max(MULT_FLOOR, min(m, MULT_CEILING))
    return float(m)


# ---------------------------------------------------------------------------
# Premiums (PRD §3.4, §3.9)
# ---------------------------------------------------------------------------
def quoted_premium_cents(base_premium_cents, multiplier) -> int:
    """quoted_annual_premium_cents = round_half_up(base * multiplier) (PRD §3.4)."""
    return round_half_up_cents(_dec(base_premium_cents) * _dec(multiplier))


def renewal_premium_cents(base_premium_cents, multiplier) -> int:
    """recalculated_premium_cents = round_half_up(base * renewal_multiplier)."""
    return round_half_up_cents(_dec(base_premium_cents) * _dec(multiplier))


# ---------------------------------------------------------------------------
# Mileage premium (PRD §3.6) — rounding order PINNED: round each component to a
# whole cent independently, THEN sum.
# ---------------------------------------------------------------------------
def mileage_statement_charges(trips, policy, plan):
    """Returns (billed_miles, overage_miles, base_charge_cents, mileage_charge_cents).

    `trips` is the list of ACCEPTED policy trips whose billed_period_index equals
    the policy's current period_index.
    """
    billed_miles = sum(_dec(t["distance_miles"]) for t in trips)
    included = _dec(plan["included_miles_per_period"])
    overage_miles = billed_miles - included
    if overage_miles < 0:
        overage_miles = Decimal("0")

    base_raw = (_dec(policy["bound_premium_cents"]) / Decimal(PERIODS_PER_YEAR)) * _dec(
        policy["current_risk_multiplier"]
    )
    base_charge_cents = round_half_up_cents(base_raw)  # round component 1

    mileage_raw = overage_miles * _dec(plan["per_mile_rate_cents"])
    mileage_charge_cents = round_half_up_cents(mileage_raw)  # round component 2

    return (
        _num(billed_miles),
        _num(overage_miles),
        base_charge_cents,
        mileage_charge_cents,
    )


def _num(d: Decimal):
    """Render a Decimal as int when integral, else float (for mileage fields)."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Discount redemption at settlement (PRD §3.6) — pinned evaluation order.
# ---------------------------------------------------------------------------
def discount_redemption(available_cents, pre_discount_total):
    """Returns (applied_discount_cents, total_due_cents).

    applied = min(available, pre_discount_total); total_due = pre - applied.
    """
    applied = min(int(available_cents), int(pre_discount_total))
    if applied < 0:
        applied = 0
    total_due = int(pre_discount_total) - applied
    return applied, total_due


# ---------------------------------------------------------------------------
# Renewal banked discount (PRD §3.9)
# ---------------------------------------------------------------------------
def renewal_banked_discount(available_cents) -> int:
    return min(int(available_cents), RENEWAL_MAX_DISCOUNT_CENTS)


# ---------------------------------------------------------------------------
# Safe-trip discount threshold (PRD §3.5)
# ---------------------------------------------------------------------------
def safe_trip_earns(trip) -> bool:
    """True when a trip is clean (zero of each event type) AND its distance is
    >= SAFE_TRIP_MIN_MILES (inclusive)."""
    return (
        trip["hard_brake_count"] == 0
        and trip["speeding_count"] == 0
        and trip["phone_use_count"] == 0
        and _dec(trip["distance_miles"]) >= SAFE_TRIP_MIN_MILES
    )


# ---------------------------------------------------------------------------
# Claim reserve (PRD §3.8)
# ---------------------------------------------------------------------------
def claim_reserve_cents(reported_severity) -> int:
    return RESERVE_BASE_CENTS * int(reported_severity)
