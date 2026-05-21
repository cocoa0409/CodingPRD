"""Calculations: rent cap, utility apportionment, outstanding balance, violation count, rent proration, conversion eligibility."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from ..clock import clock
from ..store import store


# -----------------------------
# 1. rent_cap_application
# -----------------------------


def compute_capped_new_rent_cents(current_rent_cents: int, proposed_rent_cents: int, state_code: str, master_cpi_pct: float) -> int:
    """Compute the capped new rent in cents per the state-specific rule.

    Order of operations:
      1) compute proposed_pct = ((proposed-current)/current)*100
      2) lookup max_pct by state
      3) compare; if no cap or proposed <= cap -> proposed passes through
      4) if capping required: apply percent to current then round half-up to cents.
    """
    current = current_rent_cents
    proposed = proposed_rent_cents
    if current <= 0:
        return proposed
    proposed_pct = ((proposed - current) / current) * 100.0

    cpi = float(master_cpi_pct or 0.0)
    if state_code == "CA":
        max_pct: Optional[float] = min(5.0 + cpi, 10.0)
    elif state_code == "OR":
        max_pct = min(7.0 + cpi, 10.0)
    elif state_code == "AZ":
        max_pct = 10.0
    elif state_code in ("FL", "TX"):
        max_pct = None
    else:
        # Unknown state: treat as uncapped to be permissive (state_code validation upstream)
        max_pct = None

    if max_pct is None or proposed_pct <= max_pct:
        return proposed
    # Cap activates: round half-up to nearest cent after applying percent
    capped = Decimal(current) * (Decimal(1) + (Decimal(str(max_pct)) / Decimal(100)))
    return int(capped.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# -----------------------------
# 2. utility_apportionment
# -----------------------------


def apportion_master_total(
    occupied_lots: list[dict[str, Any]],
    master_total_cents: int,
    method: str,
) -> list[int]:
    """Return per-lot share for the given occupied lots in their input order.

    The caller is responsible for sorting occupied_lots by lot_number ascending —
    we still re-sort to be safe, and the remainder is applied in that sorted order.
    """
    # Sort ascending by lot_number (tie-break for remainder distribution)
    indexed = list(enumerate(occupied_lots))
    indexed.sort(key=lambda pair: pair[1]["lot_number"])
    n = len(indexed)
    if n == 0:
        return []

    if method == "SUB_METER":
        readings = [float(lot.get("sub_meter_reading_kwh") or 0.0) for _, lot in indexed]
        total_kwh = sum(readings)
        if total_kwh <= 0.0:
            # Zero-reading edge case: equal split
            base = master_total_cents // n
            shares_sorted = [base for _ in range(n)]
            remainder = master_total_cents - sum(shares_sorted)
        else:
            raw_shares = [(r / total_kwh) * master_total_cents for r in readings]
            shares_sorted = [int(s) for s in raw_shares]  # floor (master_total >= 0; readings >= 0)
            remainder = master_total_cents - sum(shares_sorted)
    elif method == "EQUAL_SPLIT":
        base = master_total_cents // n
        shares_sorted = [base for _ in range(n)]
        remainder = master_total_cents - sum(shares_sorted)
    else:
        # Unknown method: default to EQUAL_SPLIT to be conservative
        base = master_total_cents // n
        shares_sorted = [base for _ in range(n)]
        remainder = master_total_cents - sum(shares_sorted)

    # Distribute remainder cent-by-cent to lots in ascending lot_number order
    for i in range(remainder):
        shares_sorted[i] += 1

    # Map back to the original ordering
    result = [0] * n
    for sorted_pos, (orig_idx, _lot) in enumerate(indexed):
        result[orig_idx] = shares_sorted[sorted_pos]
    return result


# -----------------------------
# 3. lease_outstanding_balance
# -----------------------------


def recompute_outstanding_balance(lease: dict[str, Any]) -> int:
    """Recompute Lease.outstanding_balance_cents and write it back. Returns the new value."""
    now = clock.now()
    total = 0
    for bill in store.utility_bills.values():
        if bill.get("lease_id") != lease["id"]:
            continue
        if bill.get("paid_at") is not None:
            continue
        end_dt = bill.get("billing_period_end")
        if isinstance(end_dt, str):
            end_dt = _parse_dt(end_dt)
        if end_dt is None or end_dt > now:
            continue
        total += bill.get("total_due_cents", 0)
    lease["outstanding_balance_cents"] = total
    return total


def _parse_dt(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


# -----------------------------
# 4. resident_violation_count_12mo
# -----------------------------


def _days_elapsed(now: datetime, updated_at_dt: datetime) -> int:
    """Whole calendar days between updated_at and now. PRD §3.1 talks
    about a window measured in days (boundary inclusive at 365,
    exclusive at 366), so the comparison is done in integer days
    rather than nanosecond-aware deltas — this avoids spurious
    boundary failures caused by sub-second wall-time elapsed between
    operations."""
    delta = now - updated_at_dt
    # Use floor-divide on total_seconds so a case at exactly 365 days
    # is counted (days==365), and one at 365 days plus any positive
    # remainder still rounds down to 365 within the same day window.
    total_seconds = delta.total_seconds()
    return int(total_seconds // 86400)


def recompute_violation_count_12mo(resident: dict[str, Any]) -> int:
    """Rolling count of FINALIZED_FOR_CAUSE eviction cases against this resident
    whose updated_at is within last 365 days (inclusive on the 365-day boundary).
    """
    now = clock.now()
    count = 0
    for case in store.eviction_cases.values():
        if case.get("status") != "FINALIZED_FOR_CAUSE":
            continue
        lease = store.leases.get(case.get("lease_id", ""))
        if lease is None:
            continue
        if lease.get("resident_id") != resident["id"]:
            continue
        updated_at = case.get("updated_at")
        if isinstance(updated_at, str):
            try:
                updated_at_dt = _parse_dt(updated_at)
            except Exception:
                continue
        else:
            updated_at_dt = updated_at
        if updated_at_dt is None:
            continue
        # PRD §3.1: inclusive at 365 days, exclusive at 366.
        if _days_elapsed(now, updated_at_dt) <= 365:
            count += 1
    resident["violation_count_12mo"] = count
    return count


def buyer_has_disqualifying_eviction(resident: dict[str, Any]) -> bool:
    """For HomeSaleTransfer approval: buyer must have zero EvictionCases
    in FILED/IN_CURE/FINALIZED_FOR_CAUSE within the last 365 days.
    """
    now = clock.now()
    disqualifying = {"FILED", "IN_CURE", "FINALIZED_FOR_CAUSE"}
    for case in store.eviction_cases.values():
        if case.get("status") not in disqualifying:
            continue
        lease = store.leases.get(case.get("lease_id", ""))
        if lease is None:
            continue
        if lease.get("resident_id") != resident["id"]:
            continue
        updated_at = case.get("updated_at")
        if isinstance(updated_at, str):
            try:
                updated_at_dt = _parse_dt(updated_at)
            except Exception:
                continue
        else:
            updated_at_dt = updated_at
        if updated_at_dt is None:
            continue
        if _days_elapsed(now, updated_at_dt) <= 365:
            return True
    return False


# -----------------------------
# 5. rent_due_calculation
# -----------------------------


def compute_rent_due_cents(
    lease: Optional[dict[str, Any]],
    billing_period_start: datetime,
    billing_period_end: datetime,
) -> int:
    if lease is None:
        return 0
    start_date = lease.get("start_date")
    if isinstance(start_date, str):
        start_date = _parse_dt(start_date)
    monthly_rent = int(lease.get("monthly_rent_cents") or 0)
    period_days = (billing_period_end - billing_period_start).days
    if period_days <= 0:
        return 0
    if start_date is None or start_date <= billing_period_start:
        return monthly_rent
    # start_date strictly after period_start -> prorate
    active_start = max(start_date, billing_period_start)
    active_days = (billing_period_end - active_start).days
    if active_days >= period_days:
        return monthly_rent
    if active_days <= 0:
        return 0
    return (monthly_rent * active_days) // period_days


# -----------------------------
# 6. conversion_buyout_eligibility
# -----------------------------


def conversion_offer_meets_threshold(offer_price_cents: int, assessed_value_cents: int) -> bool:
    return offer_price_cents >= assessed_value_cents


__all__ = [
    "compute_capped_new_rent_cents",
    "apportion_master_total",
    "recompute_outstanding_balance",
    "recompute_violation_count_12mo",
    "buyer_has_disqualifying_eviction",
    "compute_rent_due_cents",
    "conversion_offer_meets_threshold",
]
