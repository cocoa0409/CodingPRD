"""Fee and turnaround calculations (scaffold §1.3 / PRD §3.2, §3.3, §3.7).

All money is integer cents. Round-half-up is applied at exactly the pinned
steps: scoped_base, then expedite_component (on the rounded scoped_base), and
per-item deferred fees (before summing). Tier arithmetic is exact in cents.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# --- fee constants (scaffold §1.3) ---
VAL_T1_LIMIT = 10_000_000        # cents ($100,000)
VAL_T1_RATE = Decimal("0.01")
VAL_T2_LIMIT = 50_000_000        # cents ($500,000 cumulative)
VAL_T2_RATE = Decimal("0.0075")
VAL_T3_RATE = Decimal("0.005")

SQFT_RATE = {
    "RESIDENTIAL": 40,
    "COMMERCIAL": 55,
    "INDUSTRIAL": 45,
    "ESSENTIAL_FACILITY": 70,
}

MIN_BASE_FEE_CENTS = 50_000

SCOPE_MULT = {
    "FULL_REVIEW": Decimal("1.0"),
    "LATERAL_ONLY": Decimal("0.6"),
    "PEER_REVIEW": Decimal("0.8"),
}

EXPEDITE_SURCHARGE_RATE = Decimal("0.5")

RESUBMITTAL_FEE_CENTS = 75_000
DEFERRED_ITEM_FEE_RATE = Decimal("0.05")


def _round_half_up_cents(dec_value):
    """Round a Decimal to integer cents, half up."""
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_scoped_base_and_expedite(engagement):
    """Compute (scoped_base, expedite_component) in integer cents from the
    engagement's CURRENT fee inputs and pinned fee method."""
    if engagement["pinned_fee_method"] == "VALUATION":
        v = engagement["declared_valuation_cents"]
        tier1 = min(v, VAL_T1_LIMIT) * VAL_T1_RATE
        tier2 = max(0, min(v, VAL_T2_LIMIT) - VAL_T1_LIMIT) * VAL_T2_RATE
        tier3 = max(0, v - VAL_T2_LIMIT) * VAL_T3_RATE
        base = tier1 + tier2 + tier3   # Decimal, exact in cents
    else:  # SQUARE_FOOTAGE
        base = Decimal(engagement["floor_area_sqft"]) * SQFT_RATE[engagement["building_type"]]

    if base < MIN_BASE_FEE_CENTS:
        base = Decimal(MIN_BASE_FEE_CENTS)

    # rounding step 1
    scoped_base = _round_half_up_cents(base * SCOPE_MULT[engagement["scope"]])

    # rounding step 2, on the ROUNDED scoped_base
    if engagement.get("requested_expedite", False):
        expedite_component = _round_half_up_cents(
            Decimal(scoped_base) * EXPEDITE_SURCHARGE_RATE
        )
    else:
        expedite_component = 0

    return scoped_base, expedite_component


def compute_estimated_fee(engagement):
    """Estimated fee at registration: scoped_base + expedite_component.
    cycle_count = 0 and zero approved deferred items, so the resubmittal and
    deferred components are always 0. Never recomputed afterwards."""
    scoped_base, expedite_component = compute_scoped_base_and_expedite(engagement)
    return scoped_base + expedite_component


def compute_final_fee(engagement, deferred_items):
    """Final fee at record seal. Uses current (possibly amended) fee inputs,
    actual cycle_count, and approved deferred items.

    deferred_items: iterable of DeferredSubmittal dicts with status APPROVED.
    Per-item deferred fees are rounded BEFORE summing (pinned order)."""
    scoped_base, expedite_component = compute_scoped_base_and_expedite(engagement)

    billable_cycles = max(
        0,
        engagement["cycle_count"] - engagement["pinned_free_resubmittal_cycles"],
    )
    resubmittal_component = RESUBMITTAL_FEE_CENTS * billable_cycles

    deferred_component = 0
    for _item in deferred_items:
        deferred_component += _round_half_up_cents(
            Decimal(scoped_base) * DEFERRED_ITEM_FEE_RATE
        )

    return scoped_base + expedite_component + resubmittal_component + deferred_component


# ---------------------------------------------------------------------------
# Turnaround SLA (scaffold §1.3 turnaround_sla / PRD §3.3)
# ---------------------------------------------------------------------------

def compute_due_at(received_at, pinned_turnaround_days, pinned_sla_mode, requested_expedite):
    """Compute the cycle due_at.

    Pinned order: halve the day count FIRST (ceil) when expedited, THEN apply
    the day-counting mode."""
    if requested_expedite:
        # ceil(pinned_turnaround_days / 2)
        effective_days = -(-pinned_turnaround_days // 2)
    else:
        effective_days = pinned_turnaround_days

    if pinned_sla_mode == "CALENDAR":
        return received_at + timedelta(days=effective_days)

    # BUSINESS mode: count from the calendar DATE of received_at; the received
    # day itself is never counted; skip Saturdays/Sundays; land at end of day.
    d = received_at.date()
    remaining = effective_days
    while remaining > 0:
        d = d + timedelta(days=1)
        # weekday(): Mon=0 ... Sat=5, Sun=6
        while d.weekday() >= 5:
            d = d + timedelta(days=1)
        remaining -= 1
    return type(received_at)(d.year, d.month, d.day, 23, 59, 59, 999000,
                             tzinfo=received_at.tzinfo)
