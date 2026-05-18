"""Pure calculation helpers — money & ratio math.

Every function here is deterministic, takes plain Python primitives, and uses
``Decimal`` with ``ROUND_HALF_UP`` rather than IEEE-754 floats. The pinned
variants from SCAFFOLD.calculations live here.
"""
from __future__ import annotations

import math
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, List, Tuple

# ---- constants ----------
FLAT_FEE_CENTS = 2500
PCT_RATE = Decimal("0.015")
REGULAR_PERIOD_DAYS = 90
SPECIAL_PERIOD_DAYS = 30

LIEN_OVERDUE_FLOOR_CENTS = 180000
LIEN_OVERDUE_AGE_DAYS = 60
LIEN_COOLING_OFF_DAYS = 30
ACC_DEEMED_DECISION_DAYS = 30
VIOLATION_CURE_DAYS = 14

RESERVE_OK_THRESHOLD = Decimal("0.70")
RESERVE_RESTRICTED_THRESHOLD = Decimal("0.30")


def round_half_up(value: Decimal, places: int = 0) -> Decimal:
    quant = Decimal("1") if places == 0 else Decimal("1").scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


# ---- assessment cycle issuance ----------

def allocate_assessment_principal(
    total_levy_cents: int, units: List[Tuple[str, Decimal]]
) -> dict:
    """Allocate ``total_levy_cents`` across ``units``.

    ``units`` is a list of ``(unit_id, share_factor_decimal)`` ordered however
    the caller likes; the deterministic distribution sort happens here.

    Returns ``{unit_id: principal_cents_int}`` such that the values sum to
    exactly ``total_levy_cents``.
    """
    total = Decimal(total_levy_cents)
    raw = {uid: total * sf for uid, sf in units}
    rounded = {uid: int(round_half_up(raw[uid])) for uid in raw}
    remainder = total_levy_cents - sum(rounded.values())

    if remainder != 0:
        # Sort by share_factor DESC, then by unit_id ASC. Cycle through if
        # remainder magnitude exceeds the number of units.
        ordered = sorted(units, key=lambda x: (-x[1], x[0]))
        step = 1 if remainder > 0 else -1
        i = 0
        while remainder != 0:
            uid = ordered[i % len(ordered)][0]
            rounded[uid] += step
            remainder -= step
            i += 1
    return rounded


# ---- late fees ----------

def late_fee_for_charge(
    cycle_type: str,
    due_date: datetime,
    clock_now: datetime,
    principal_cents: int,
) -> int:
    """Return ``late_fee_cents`` per the per-cycle accrual variant.

    Returns 0 if clock_now <= due_date.
    """
    if clock_now <= due_date:
        return 0
    days_overdue = (clock_now - due_date).total_seconds() / 86400.0
    if cycle_type == "SPECIAL":
        period = SPECIAL_PERIOD_DAYS
    else:
        period = REGULAR_PERIOD_DAYS
    periods_missed = int(math.floor(days_overdue / period)) + 1
    pct_fee = round_half_up(Decimal(principal_cents) * PCT_RATE)
    per_period_fee = max(FLAT_FEE_CENTS, int(pct_fee))
    return per_period_fee * periods_missed


# ---- violation fines ----------

def violation_fine_for_occurrence(occurrence_index: int) -> int:
    if occurrence_index <= 1:
        return 0
    if occurrence_index == 2:
        return 5000
    if occurrence_index == 3:
        return 10000
    return 20000


# ---- reserve study ----------

def compute_full_funding_target(components: Iterable[dict]) -> int:
    """Sum of per-component round-half-up accrued depreciation, in whole cents."""
    total = 0
    for c in components:
        cost = Decimal(int(c["replacement_cost_cents"]))
        useful = int(c["useful_life_years"])
        remaining = int(c["remaining_life_years"])
        if useful <= 0:
            continue
        elapsed = useful - remaining
        if elapsed < 0:
            elapsed = 0
        if elapsed > useful:
            elapsed = useful
        raw = cost * Decimal(elapsed) / Decimal(useful)
        total += int(round_half_up(raw))
    return total


def compute_funded_ratio(current_reserve_balance_cents: int, full_funding_target_cents: int):
    """Return (ratio_or_None_as_float, posture_string)."""
    if full_funding_target_cents == 0:
        return None, "OK"
    raw = Decimal(current_reserve_balance_cents) / Decimal(full_funding_target_cents)
    ratio = round_half_up(raw, 4)
    if ratio >= RESERVE_OK_THRESHOLD:
        posture = "OK"
    elif ratio >= RESERVE_RESTRICTED_THRESHOLD:
        posture = "RESTRICTED"
    else:
        posture = "SPECIAL_ASSESSMENT_REQUIRED"
    # Return ratio as float for JSON; preserve four decimal precision via formatting.
    return float(ratio), posture
