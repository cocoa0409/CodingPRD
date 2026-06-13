"""Calculation rules (PRD §3.5, §3.6, §3.10, §3.12; SCAFFOLD §1.3).

All money is integer cents. The two products that can yield a fractional cent —
the escalation-adjusted fine total and the lien admin fee — are rounded half-up
exactly once on the final product (PRD §2.6).
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from services.constants import (
    ADMIN_TIER_CENTS,
    CHRONIC_THRESHOLD,
    REPEAT_THRESHOLD,
    ROLLING_WINDOW_DAYS,
    TIER_MULTIPLIER,
)


def round_half_up(value):
    """Round a numeric value to the nearest whole integer, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def whole_days_between(a, b):
    """floor((b - a) / 86400 seconds); negative -> 0 (PRD §3.6)."""
    delta_seconds = (b - a).total_seconds()
    if delta_seconds < 0:
        return 0
    return int(delta_seconds // 86400)


def fine_accrual(fee_schedule, escalation_multiplier, compliance_deadline, as_of):
    """Compute (fine_total_cents, days_overdue) for a notice (PRD §3.6).

    raw = base + daily_accrual * days_overdue
    capped_pre_mult = min(raw, max_total)
    fine_total = round_half_up(capped_pre_mult * escalation_multiplier)
    Rounding applied exactly once, after the cap and after the multiplier.
    """
    days_overdue = whole_days_between(compliance_deadline, as_of)
    raw = fee_schedule["base_fine_cents"] + fee_schedule["daily_accrual_cents"] * days_overdue
    capped = min(raw, fee_schedule["max_total_cents"])
    fine_total = round_half_up(Decimal(capped) * Decimal(str(escalation_multiplier)))
    return fine_total, days_overdue


def repeat_offender(owner_id, db, current_clock, exclude_notice_id=None):
    """Compute (repeat_tier, prior_violation_count, escalation_multiplier).

    prior_violation_count = count of the owner's ViolationNotices whose status is
    COMPLIED or UPHELD and whose effective_date is within the rolling window
    [current_clock - 365 days, current_clock]; the notice being issued is excluded
    (PRD §3.5).
    """
    window_start = current_clock - timedelta(days=ROLLING_WINDOW_DAYS)
    count = 0
    for n in db.notices.values():
        if exclude_notice_id is not None and n["id"] == exclude_notice_id:
            continue
        if n["owner_id"] != owner_id:
            continue
        if n["status"] not in ("COMPLIED", "UPHELD"):
            continue
        eff = n["effective_date"]
        if eff is None:
            continue
        if window_start <= eff <= current_clock:
            count += 1

    if count >= CHRONIC_THRESHOLD:
        tier = "CHRONIC"
    elif count >= REPEAT_THRESHOLD:
        tier = "REPEAT"
    else:
        tier = "FIRST"
    return tier, count, TIER_MULTIPLIER[tier]


def lien_amount(open_citation_cents, open_abatement_cents):
    """Compute (principal_cents, admin_fee_cents, total_cents) (PRD §3.12).

    principal = open_citation + open_abatement (exact sum)
    admin_rate = 0.05 if principal < ADMIN_TIER_CENTS else 0.10
    admin_fee = round_half_up(principal * admin_rate)
    total = principal + admin_fee
    """
    principal = open_citation_cents + open_abatement_cents
    admin_rate = Decimal("0.05") if principal < ADMIN_TIER_CENTS else Decimal("0.10")
    admin_fee = round_half_up(Decimal(principal) * admin_rate)
    total = principal + admin_fee
    return principal, admin_fee, total
