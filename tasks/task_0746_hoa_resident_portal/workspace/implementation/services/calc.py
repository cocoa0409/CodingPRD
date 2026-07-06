"""Pure calculation kernels — see PRD §3.2 (proration, late fee, delinquency score),
§3.4 (ARC finalisation fee), §3.6 (amenity capacity check)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from utils import parse_iso, round_half_up


# ---------------- Assessment proration (§3.2 FULL_MONTH / DAILY_PRORATE) ---------------- #

def assessment_prorate(monthly_dues_cents, billing_start_iso, billing_end_iso, prorate_from_iso):
    """Return amount_due_cents per PRD §3.2 proration rules."""
    start = parse_iso(billing_start_iso)
    end = parse_iso(billing_end_iso)
    if prorate_from_iso is None:
        return monthly_dues_cents
    prorate_from = parse_iso(prorate_from_iso)
    if prorate_from <= start:
        return monthly_dues_cents
    if prorate_from >= end:
        # Edge: prorate_from at/after end -> 0 included days.
        return 0
    days_in_period = (end - start).days
    included_days = (end - prorate_from).days
    if days_in_period <= 0:
        return 0
    raw = Decimal(monthly_dues_cents) * Decimal(included_days) / Decimal(days_in_period)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------- Late fee (§3.2 tiered_pricing) ---------------- #

_TIER_TABLE = [
    # (min_days_inclusive, max_days_exclusive_or_None, rate, floor, cap)
    (1, 14, Decimal("0.02"), 1000, 2500),
    (14, 30, Decimal("0.05"), 1000, 5000),
    (30, 60, Decimal("0.10"), 2500, 10000),
    (60, None, Decimal("0.15"), 5000, 25000),
]

_STANDING_MULT = {
    "GOOD_STANDING": Decimal("1.0"),
    "MARGINAL": Decimal("1.5"),
    "DELINQUENT": Decimal("2.0"),
}


def late_fee(amount_due_cents, amount_paid_cents, due_date_iso, current_utc_dt, homeowner_standing):
    """Compute late_fee_cents per PRD §3.2 tier table.
    Assumes the assessment is at or past due (caller decides). If days_overdue < 1
    per the floor rule, no tier applies — returns 0."""
    due = parse_iso(due_date_iso)
    delta = (current_utc_dt - due).total_seconds()
    days_overdue = max(0, int(delta // 86400))
    if days_overdue < 1:
        return 0
    outstanding = max(0, amount_due_cents - amount_paid_cents)
    if outstanding <= 0:
        # Fully paid — the tier still ostensibly applies (floor/cap), but per the
        # formula base = round_half_up(0 * rate) = 0, then scaled = 0, then
        # min(max(0, floor), cap) = floor. This matches the spec literally.
        pass
    # Select tier
    tier = None
    for tmin, tmax, rate, floor, cap in _TIER_TABLE:
        if days_overdue >= tmin and (tmax is None or days_overdue < tmax):
            tier = (rate, floor, cap)
            break
    if tier is None:
        return 0
    rate, floor, cap = tier
    base = round_half_up(Decimal(outstanding) * rate)
    mult = _STANDING_MULT.get(homeowner_standing, Decimal("1.0"))
    scaled = round_half_up(Decimal(base) * mult)
    return min(max(scaled, floor), cap)


# ---------------- Delinquency score (§3.2 STRICT / LENIENT) ---------------- #

def delinquency_score(homeowner_assessments, grace_policy, current_utc_dt):
    """Return an integer dollar score per PRD §3.2 STRICT/LENIENT variant.

    `homeowner_assessments` is an iterable of Assessment rows whose status ∈
    {OPEN, PARTIALLY_PAID, OVERDUE, DELINQUENT}. Caller filters."""
    total_cents = Decimal("0")
    for a in homeowner_assessments:
        due = parse_iso(a["due_date"])
        seconds = (current_utc_dt - due).total_seconds()
        age_days = max(0, int(seconds // 86400))
        if grace_policy == "LENIENT" and age_days < 30:
            continue
        # weight = 1.0 + (age_days // 30) * 0.5
        weight = Decimal("1.0") + (Decimal(age_days // 30) * Decimal("0.5"))
        outstanding = a["amount_due_cents"] - a["amount_paid_cents"] + a.get("late_fee_cents", 0)
        contribution = Decimal(outstanding) * weight
        total_cents += contribution
    dollars = total_cents / Decimal("100")
    return int(dollars.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def standing_from_score(score):
    if score < 500:
        return "GOOD_STANDING"
    if score < 1500:
        return "MARGINAL"
    return "DELINQUENT"


def booking_privilege_from_standing(standing):
    return "FROZEN" if standing == "DELINQUENT" else "ALLOWED"


# ---------------- ARC finalisation fee (§3.4 SUM_THEN_ROUND) ---------------- #

_ARC_BASE = {"SIMPLE": 2500, "MEDIUM": 10000, "COMPLEX": 25000}
_ARC_REVIEW_RATE = Decimal("0.10725")


def arc_finalization_fee(category, current_revision_reviews):
    """Sum first, then round — PRD §3.4."""
    base = _ARC_BASE[category]
    total_raw = Decimal(base)
    for r in current_revision_reviews:
        contribution = Decimal(r["weight"]) * Decimal(base) * _ARC_REVIEW_RATE
        total_raw += contribution
    return int(total_raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------- Amenity capacity check (§3.6 interval_merge) ---------------- #

def amenity_capacity_ok(candidate_start_dt, candidate_end_dt, candidate_guests, capacity,
                        existing_reservations_dt):
    """Return True iff the candidate fits under capacity for its window.

    `existing_reservations_dt` is a list of (start_dt, end_dt, guest_count) tuples
    for reservations on the same amenity whose status ∈ {BOOKED, CHECKED_IN}.
    The candidate is not included in this list."""
    # Filter to strictly-overlapping intervals (half-open on the right).
    overlap = [
        (s, e, g) for (s, e, g) in existing_reservations_dt
        if s < candidate_end_dt and e > candidate_start_dt
    ]
    # Boundary points to evaluate: candidate.start_ts ∪ {R.start_ts for R in Overlap}
    boundaries = [candidate_start_dt] + [s for (s, _, _) in overlap]
    peak = 0
    for t in boundaries:
        concurrent = candidate_guests
        for (s, e, g) in overlap:
            if s <= t < e:
                concurrent += g
        if concurrent > peak:
            peak = concurrent
    return peak <= capacity
