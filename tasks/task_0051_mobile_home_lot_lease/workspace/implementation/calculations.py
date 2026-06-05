from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR

# Rent-increase annual cap per state (SCAFFOLD §1.3 capped_rent_increase).
CAP_PCT = {
    "CA": Decimal("0.05"),
    "OR": Decimal("0.07"),
    "FL": Decimal("0.10"),
    "TX": None,  # no statutory cap
}

# Eviction cure window (days) per state (SCAFFOLD §1.3 cure_deadline_derivation).
CURE_DAYS = {
    "CA": 60,
    "OR": 30,
    "FL": 30,
    "TX": 14,
}

# NONPAYMENT eviction arrears threshold in cents (SCAFFOLD §1.3 resident_arrears).
ARREARS_THRESHOLD_CENTS = 50000


def capped_rent(prior_rent_cents, proposed_rent_cents, state_code):
    """Compute (new_rent_cents, cap_applied) for a rent schedule (PRD §3.4).

    For a capped state: max_allowed = floor(prior * (1 + cap_pct)).
    For TX (uncapped): max_allowed = proposed, so cap never binds.
    new_rent = min(proposed, max_allowed); cap_applied is true iff proposed is
    strictly greater than max_allowed.
    """
    pct = CAP_PCT.get(state_code)
    if pct is None:
        max_allowed = proposed_rent_cents
    else:
        # floor(prior * (1 + pct)) to whole cents.
        raw = Decimal(prior_rent_cents) * (Decimal(1) + pct)
        max_allowed = int(raw.to_integral_value(rounding=ROUND_FLOOR))
    new_rent = min(proposed_rent_cents, max_allowed)
    cap_applied = proposed_rent_cents > max_allowed
    return new_rent, cap_applied


def apportion(master_charge_cents, weighted_lots):
    """Largest-remainder apportionment (PRD §3.5 / §2.8).

    `weighted_lots` is a list of (lot_id, weight) tuples already ordered by the
    caller in the canonical apportionment order (created_at ASC, lot_number ASC).
    Returns a dict lot_id -> amount_cents whose values sum to exactly
    master_charge_cents.

    Each raw share is floored to whole cents; the leftover remainder is handed
    out one cent at a time in DESCENDING fractional-remainder order, ties broken
    by the caller's input order (created_at ASC).
    """
    total_weight = sum(Decimal(w) for _, w in weighted_lots)
    floors = {}
    frac_order = []  # (negative_fraction, input_index, lot_id) for stable sort
    master = Decimal(master_charge_cents)
    for idx, (lot_id, weight) in enumerate(weighted_lots):
        raw = master * Decimal(weight) / total_weight
        floor_cents = int(raw.to_integral_value(rounding=ROUND_FLOOR))
        floors[lot_id] = floor_cents
        fraction = raw - Decimal(floor_cents)
        frac_order.append((fraction, idx, lot_id))

    remainder = master_charge_cents - sum(floors.values())
    # Distribute the remainder: highest fractional remainder first; ties broken
    # by input index (created_at ASC) ascending.
    frac_order.sort(key=lambda t: (-t[0], t[1]))
    for i in range(remainder):
        _, _, lot_id = frac_order[i]
        floors[lot_id] += 1
    return floors


def cure_deadline(created_at_dt, state_code):
    """Derive cure_deadline (PRD §3.7).

    cure_deadline = end of (notice_date + CURE_DAYS[state]) where notice_date is
    the DATE portion of the case's created_at. Returned as a tz-aware datetime
    pinned to the very end of that day (23:59:59.999999 UTC) — the inclusive
    boundary: cure allowed while now <= deadline, adjudication while now >
    deadline.
    """
    notice_date = created_at_dt.date()
    deadline_date = notice_date + timedelta(days=CURE_DAYS[state_code])
    # End of the deadline day in UTC.
    from datetime import datetime, timezone
    return datetime(deadline_date.year, deadline_date.month, deadline_date.day,
                    23, 59, 59, 999999, tzinfo=timezone.utc)
