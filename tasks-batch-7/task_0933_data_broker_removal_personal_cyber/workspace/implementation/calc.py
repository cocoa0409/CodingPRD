"""Pure calculation rules -- SCAFFOLD §1.3 / PRD §2.9, §3.

All money is integer cents and never a float. Rounding methods and their
evaluation points are part of the specification.
"""

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

import constants as K


def round_half_up(value: Decimal, places: int) -> Decimal:
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def ceil_int(value: Decimal) -> int:
    return int(Decimal(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value: Decimal) -> int:
    return int(Decimal(value).to_integral_value(rounding=ROUND_FLOOR))


def half_up_int(value: Decimal) -> int:
    return int(Decimal(value).to_integral_value(rounding=ROUND_HALF_UP))


# --- hygiene_score ----------------------------------------------------------

def hygiene(open_findings, two_factor_attested: bool):
    """Six-step hygiene score. Cap BEFORE the multiplier, round AFTER it."""
    raw_penalty = sum(K.HYGIENE_WEIGHTS[f["finding_type"]] for f in open_findings)
    capped_penalty = min(raw_penalty, K.HYGIENE_PENALTY_CAP)
    multiplier = Decimal(
        K.HYGIENE_TWO_FACTOR_MULTIPLIER if two_factor_attested
        else K.HYGIENE_NO_TWO_FACTOR_MULTIPLIER
    )
    adjusted = round_half_up(Decimal(capped_penalty) * multiplier, 2)
    score = round_half_up(Decimal(K.HYGIENE_BASE_SCORE) - adjusted, 2)
    if score >= K.HYGIENE_BAND_STRONG_MIN:
        band = "STRONG"
    elif score >= K.HYGIENE_BAND_MODERATE_MIN:
        band = "MODERATE"
    elif score >= K.HYGIENE_BAND_WEAK_MIN:
        band = "WEAK"
    else:
        band = "CRITICAL"
    return {
        "variant": "TWO_FACTOR_ATTESTED" if two_factor_attested else "NO_TWO_FACTOR",
        "open_finding_count": len(open_findings),
        "raw_penalty": raw_penalty,
        "capped_penalty": capped_penalty,
        "adjusted_penalty": float(adjusted),
        "hygiene_score": float(score),
        "hygiene_band": band,
    }


# --- breach_alert_severity --------------------------------------------------

def severity_band(points: int) -> str:
    if points >= K.SEVERITY_BAND_CRITICAL_MIN:
        return "CRITICAL"
    if points >= K.SEVERITY_BAND_HIGH_MIN:
        return "HIGH"
    if points >= K.SEVERITY_BAND_MEDIUM_MIN:
        return "MEDIUM"
    return "LOW"


def breach_points(event, identifier, has_open_breached_password: bool) -> int:
    record_points = max(K.BREACH_POINTS[rt] for rt in event["record_types"])
    identifier_bonus = (
        K.SENSITIVE_IDENTIFIER_BONUS_POINTS
        if identifier["identifier_type"] == "SSN_LAST4"
        else K.IDENTIFIER_MATCH_BONUS_POINTS
    )
    hygiene_escalation = (
        K.OPEN_BREACHED_PASSWORD_ESCALATION_POINTS if has_open_breached_password else 0
    )
    return (
        int(event["base_severity_points"])
        + record_points
        + identifier_bonus
        + hygiene_escalation
    )


# --- broker_compliance_score ------------------------------------------------

def compliance_score(reappearances, expired, rejected, on_time):
    raw = (
        K.BROKER_COMPLIANCE_BASE_SCORE
        - K.COMPLIANCE_PENALTY_PER_REAPPEARANCE * reappearances
        - K.COMPLIANCE_PENALTY_PER_EXPIRED_REQUEST * expired
        - K.COMPLIANCE_PENALTY_PER_REJECTED_REQUEST * rejected
        + K.COMPLIANCE_BONUS_PER_ONTIME_COMPLETION * on_time
    )
    return max(K.COMPLIANCE_SCORE_FLOOR, min(K.COMPLIANCE_SCORE_CEILING, raw))


# --- plan_proration_amount --------------------------------------------------

def plan_proration_upgrade(fee_delta_cents: int, remaining_days: int) -> int:
    """UPGRADE variant: round the daily rate FIRST, then multiply."""
    daily_rate = half_up_int(Decimal(fee_delta_cents) / Decimal(K.PRORATION_DAY_BASIS))
    return daily_rate * remaining_days


def plan_proration_downgrade(fee_delta_cents: int, remaining_days: int) -> int:
    """DOWNGRADE variant: multiply FIRST, round once at the end."""
    return half_up_int(
        Decimal(fee_delta_cents) * Decimal(remaining_days) / Decimal(K.PRORATION_DAY_BASIS)
    )


# --- addon_proration_amount -------------------------------------------------

def addon_charge(per_seat_fee_cents: int, seats_total: int, inclusive_days: int) -> int:
    """SEAT_ADDED variant: charges round UP."""
    return ceil_int(
        Decimal(per_seat_fee_cents) * Decimal(seats_total) * Decimal(inclusive_days)
        / Decimal(K.ADDON_PRORATION_DAY_BASIS)
    )


def addon_credit(per_seat_fee_cents: int, seats_total: int, inclusive_days: int) -> int:
    """SEAT_RELEASED variant: credits round DOWN."""
    return floor_int(
        Decimal(per_seat_fee_cents) * Decimal(seats_total) * Decimal(inclusive_days)
        / Decimal(K.ADDON_PRORATION_DAY_BASIS)
    )


# --- cycle_total_charge -----------------------------------------------------

def cycle_totals(cycle):
    pre = (
        int(cycle["base_charge_cents"])
        + int(cycle["proration_charge_cents"])
        + int(cycle["addon_charge_cents"])
        - int(cycle["proration_credit_cents"])
        - int(cycle["addon_credit_cents"])
    )
    pre = max(0, pre)
    # The tier is chosen from the PRE-discount total and never re-chosen.
    if pre >= K.LOYALTY_TIER_3_THRESHOLD_CENTS:
        rate = Decimal(K.LOYALTY_TIER_3_RATE)
    elif pre >= K.LOYALTY_TIER_2_THRESHOLD_CENTS:
        rate = Decimal(K.LOYALTY_TIER_2_RATE)
    elif pre >= K.LOYALTY_TIER_1_THRESHOLD_CENTS:
        rate = Decimal(K.LOYALTY_TIER_1_RATE)
    else:
        rate = Decimal("0.00")
    discount = half_up_int(Decimal(pre) * rate)
    return pre, discount, pre - discount


# --- scan_coverage_ratio ----------------------------------------------------

def coverage_ratio(suppressed: int, total: int) -> float:
    if total == 0:
        return 0.0
    return float(round_half_up(Decimal(suppressed) / Decimal(total), 4))
