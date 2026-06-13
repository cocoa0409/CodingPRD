"""Calculation rules (scaffold §1.3, PRD §3.3/§3.6/§3.7/§3.1/§3.9).

All money is integer cents. Hours kept as exact Decimal values; only the final
cents amounts are rounded half-up. Two pricing variants pin DIFFERENT rounding
orders:
  - provisional_quote_fee: round each component then sum (round-then-sum)
  - final_grant_fee:        sum raw components then round once (sum-then-round)
"""
from decimal import Decimal, ROUND_HALF_UP

# Cancellation refund constants (scaffold §1.3 cancellation_refund)
FULL_REFUND_LEAD_HOURS = Decimal(168)     # >= 7 days -> full fee refund
PARTIAL_REFUND_LEAD_HOURS = Decimal(48)   # >= 2 days and < 7 days -> 50% fee
FORFEIT_LEAD_HOURS = Decimal(24)          # < 1 day -> deposit forfeited

# Patron standing thresholds (scaffold §1.3 patron_standing, PRD §3.1)
PROBATION_STRIKES = 2
BARRED_STRIKES = 4

# Lottery weights (scaffold §1.3 lottery_selection, PRD §3.9)
WEIGHT_RESIDENT_VERIFIED = 2
WEIGHT_DEFAULT = 1

_SECONDS_PER_HOUR = Decimal(3600)


def _round_half_up(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def prime_overlap_hours(start_at, end_at, prime_start_hour, prime_end_hour):
    """Split [start_at, end_at) into prime and non-prime hours against the
    facility's daily prime window [prime_start_hour, prime_end_hour), half-open,
    interpreted per UTC calendar day. Returns (total, prime, non_prime) Decimals.

    Implemented by walking the window in fine slices keyed on the wall-clock hour
    of each instant; exact because every boundary aligns to whole hours/minutes.
    We integrate over seconds: a second at wall-clock hour h is prime iff
    prime_start_hour <= h < prime_end_hour.
    """
    total_seconds = Decimal((end_at - start_at).total_seconds())
    if total_seconds <= 0:
        return Decimal(0), Decimal(0), Decimal(0)

    # Walk segment by segment on hour boundaries to accumulate prime seconds.
    prime_seconds = Decimal(0)
    cur = start_at
    while cur < end_at:
        # Next UTC hour boundary after cur.
        nxt_hour = cur.replace(minute=0, second=0, microsecond=0)
        # advance to the next whole hour strictly after cur
        from datetime import timedelta
        nxt = nxt_hour + timedelta(hours=1)
        if nxt > end_at:
            nxt = end_at
        h = cur.hour
        seg_seconds = Decimal((nxt - cur).total_seconds())
        if prime_start_hour <= h < prime_end_hour:
            prime_seconds += seg_seconds
        cur = nxt

    prime_hours = prime_seconds / _SECONDS_PER_HOUR
    total_hours = total_seconds / _SECONDS_PER_HOUR
    non_prime_hours = total_hours - prime_hours
    return total_hours, prime_hours, non_prime_hours


def effective_rate(facility, tier):
    """Effective hourly rate in cents (Decimal) for a residency tier."""
    base = Decimal(facility["hourly_rate_cents"])
    if tier == "RESIDENT":
        disc = Decimal(str(facility["resident_discount_pct"]))
        return base * (Decimal(1) - disc)
    return base


def resolve_residency(patron):
    """RESIDENT only when residency == RESIDENT and residency_verified true."""
    if patron["residency"] == "RESIDENT" and patron.get("residency_verified"):
        return "RESIDENT"
    return "NON_RESIDENT"


def provisional_quote_fee(facility, tier, prime_hours, non_prime_hours):
    """Round each component to whole cents independently, THEN sum."""
    rate = effective_rate(facility, tier)
    mult = Decimal(str(facility["prime_multiplier"]))
    nonprime_cents = _round_half_up(non_prime_hours * rate)
    prime_cents = _round_half_up(prime_hours * rate * mult)
    return nonprime_cents + prime_cents


def final_grant_fee(facility, tier, prime_hours, non_prime_hours):
    """Sum the raw component amounts, THEN round once."""
    rate = effective_rate(facility, tier)
    mult = Decimal(str(facility["prime_multiplier"]))
    raw = (non_prime_hours * rate) + (prime_hours * rate * mult)
    return _round_half_up(raw)


def cancellation_refund(final_fee_cents, deposit_held_cents, lead_hours):
    """Tiered fee refund + deposit handling. lead_hours is a Decimal/number."""
    lead = Decimal(str(lead_hours))
    if lead >= FULL_REFUND_LEAD_HOURS:
        fee_pct = Decimal("1.00")
    elif lead >= PARTIAL_REFUND_LEAD_HOURS:
        fee_pct = Decimal("0.50")
    else:
        fee_pct = Decimal("0.00")
    fee_refund = _round_half_up(Decimal(final_fee_cents) * fee_pct)
    deposit_refund = deposit_held_cents if lead >= FORFEIT_LEAD_HOURS else 0
    total = fee_refund + deposit_refund
    return fee_refund, deposit_refund, total


def patron_standing(no_show_strikes):
    if no_show_strikes >= BARRED_STRIKES:
        return "BARRED"
    if no_show_strikes >= PROBATION_STRIKES:
        return "PROBATION"
    return "GOOD"


def lottery_priority_weight(patron):
    if patron["residency"] == "RESIDENT" and patron.get("residency_verified"):
        return WEIGHT_RESIDENT_VERIFIED
    return WEIGHT_DEFAULT


def lead_hours(start_at, current_clock):
    """(start_at - current_clock) in hours, as a Decimal."""
    return Decimal((start_at - current_clock).total_seconds()) / _SECONDS_PER_HOUR
