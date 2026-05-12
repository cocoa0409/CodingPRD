"""Pure calculations: priority score, SLA-due minutes, density, rates."""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP

from config import (
    SEVERITY_WEIGHT, IMPACT_WEIGHT,
    AGE_DIVISOR_HIGH, AGE_DIVISOR_LOW,
    AGE_CAP_HIGH, AGE_CAP_LOW,
    REOPEN_MULTIPLIER,
    SEV_BLOCKER, SEV_CRITICAL,
    RESPONSE_SLA_BASE, RESOLUTION_SLA_BASE,
    MULT_URGENT_THRESHOLD, MULT_STANDARD_THRESHOLD,
    DENSITY_WEIGHT,
)


def compute_priority_score(*, effective_severity: str, business_impact: str,
                           reopen_count: int, current_clock_minute: int,
                           report_clock_minute: int) -> int:
    sev_w = SEVERITY_WEIGHT[effective_severity]
    impact_w = IMPACT_WEIGHT[business_impact]
    age_minutes = max(0, current_clock_minute - report_clock_minute)
    if effective_severity in (SEV_BLOCKER, SEV_CRITICAL):
        age_factor = min(AGE_CAP_HIGH, age_minutes // AGE_DIVISOR_HIGH)
    else:
        age_factor = min(AGE_CAP_LOW, age_minutes // AGE_DIVISOR_LOW)
    reopen_bonus = reopen_count * REOPEN_MULTIPLIER
    return int(sev_w + impact_w + age_factor + reopen_bonus)


def compute_effective_sla(effective_severity: str, priority_score: int) -> tuple[int, int]:
    if priority_score >= MULT_URGENT_THRESHOLD:
        multiplier = 0.5
    elif priority_score >= MULT_STANDARD_THRESHOLD:
        multiplier = 1.0
    else:
        multiplier = 1.5
    base_resp = RESPONSE_SLA_BASE[effective_severity]
    base_res = RESOLUTION_SLA_BASE[effective_severity]
    # ceil to next whole minute
    effective_resp = math.ceil(base_resp * multiplier)
    effective_res = math.ceil(base_res * multiplier)
    return effective_resp, effective_res


def round_half_up(value, decimals: int) -> float:
    """Round half-up (away from zero at the half) to N decimals."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(10) ** -decimals
    return float(value.quantize(q, rounding=ROUND_HALF_UP))


def density_per_defect_contribution(effective_severity: str) -> Decimal:
    return Decimal(DENSITY_WEIGHT[effective_severity])


def compute_density(contributions: list[Decimal], kloc: float) -> float:
    # Step 1: per-line round to 1 decimal half-up
    rounded = [Decimal(str(round_half_up(c, 1))) for c in contributions]
    # Step 2: sum
    total = sum(rounded, Decimal("0"))
    # Step 3: divide by kloc
    kloc_dec = Decimal(str(kloc))
    if kloc_dec == 0:
        return 0.0
    quotient = total / kloc_dec
    # Step 4: round final to 2 decimals half-up
    return round_half_up(quotient, 2)


def compute_rate_4dp(num: int, denom: int) -> float:
    if denom == 0:
        return 0.0
    return round_half_up(Decimal(num) / Decimal(denom), 4)
