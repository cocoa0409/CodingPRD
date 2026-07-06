"""Calculation rules (PRD §3.8, SCAFFOLD §1.3).

All money in integer cents. Decimal arithmetic with ROUND_HALF_UP. Never float.
"""
from decimal import Decimal, ROUND_HALF_UP


def _round_half_up(value: Decimal) -> int:
    """Round a Decimal to whole cents, half up (PRD §2.9)."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def group_pct(n: int) -> Decimal:
    """Group-discount percentage by party count (PRD §3.8).

    <=1 -> 0; 2-3 -> 10%; 4-6 -> 20%; 7+ -> 30%."""
    if n <= 1:
        return Decimal("0.00")
    if n <= 3:
        return Decimal("0.10")
    if n <= 6:
        return Decimal("0.20")
    return Decimal("0.30")


def member_pct(tier) -> Decimal:
    """Membership percentage (PRD §3.8). none -> 0; BASIC -> 5%; PREMIUM -> 15%."""
    if tier == "BASIC":
        return Decimal("0.05")
    if tier == "PREMIUM":
        return Decimal("0.15")
    return Decimal("0.00")


def enrollment_estimate_price(planned_sessions, base_price_cents, party_size, tier):
    """Forward-looking estimate at creation (PRD §3.8): sum-then-round once.

    gross = planned_sessions * base_price_cents
    after_group = gross * (1 - group_pct(party_size))
    estimate = round_half_up(after_group * (1 - member_pct(tier)))
    """
    gross = Decimal(planned_sessions) * Decimal(base_price_cents)
    after_group = gross * (Decimal(1) - group_pct(party_size))
    after_member = after_group * (Decimal(1) - member_pct(tier))
    return _round_half_up(after_member)


def enrollment_final_price(attended_lines, base_price_cents, tier):
    """Chronological final price at completion (PRD §3.8): round-per-line then sum,
    then a final round after the membership discount.

    attended_lines: list of per-session ATTENDED group counts, in chronological
    order (the order itself doesn't affect the integer subtotal, but it matches
    the spec). For each, line = round_half_up(base * (1 - group_pct(count))).
    subtotal = sum(lines); final = round_half_up(subtotal * (1 - member_pct(tier))).
    """
    subtotal = 0
    for count in attended_lines:
        line_val = Decimal(base_price_cents) * (Decimal(1) - group_pct(count))
        subtotal += _round_half_up(line_val)
    after_member = Decimal(subtotal) * (Decimal(1) - member_pct(tier))
    return _round_half_up(after_member)


def required_instructors(enrolled_count, max_students_per_instructor):
    """Ratio ceiling (PRD §3.8). 0 when enrolled_count==0; else ceil(enrolled/cap)."""
    if enrolled_count == 0:
        return 0
    # integer ceiling division
    return -(-enrolled_count // max_students_per_instructor)


def rental_fee(hours, hourly_rate_cents):
    """Marginal tiered rental fee (PRD §3.8).

    First 2h at full rate; next 6h (hours 3-8) at 50%; 8h+ at 25%.
    Rounded half up to whole cents once at the end.
    """
    rate = Decimal(hourly_rate_cents)
    t1 = min(hours, 2)
    t2 = min(max(hours - 2, 0), 6)
    t3 = max(hours - 8, 0)
    fee = (Decimal(t1) * rate
           + Decimal(t2) * rate * Decimal("0.5")
           + Decimal(t3) * rate * Decimal("0.25"))
    return _round_half_up(fee)


def refund_cents(estimated_price_cents, lead_hours):
    """Lead-time waterfall refund (PRD §3.8).

    lead_hours None means no remaining bookings -> treat as infinite -> top tier.
    >=48 -> 100%; >=24 -> 50%; else 0%. Boundaries inclusive (>=).
    """
    if lead_hours is None or lead_hours >= 48:
        pct = Decimal("1.00")
    elif lead_hours >= 24:
        pct = Decimal("0.50")
    else:
        pct = Decimal("0.00")
    return _round_half_up(Decimal(estimated_price_cents) * pct)


def ceil_hours(start_dt, end_dt):
    """Whole-hour duration, ceil (PRD §3.8). ceil((ends - starts) seconds / 3600)."""
    import math
    seconds = (end_dt - start_dt).total_seconds()
    if seconds <= 0:
        return 0
    return math.ceil(seconds / 3600.0)


def lead_time_hours(start_dt, now_dt):
    """Hours from now to a future session start."""
    return (start_dt - now_dt).total_seconds() / 3600.0
