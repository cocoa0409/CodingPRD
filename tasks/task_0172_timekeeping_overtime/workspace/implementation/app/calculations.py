"""§1.3 Calculations — detention, meal-break premium, workweek pay engine, tip credit.

All monetary values are whole-cent integers. Wherever a fractional cent appears
during multiplication, we round half-up to the nearest whole cent using
`Decimal` semantics. Hours are kept as full-precision Python floats (or
Decimals) during accumulation and rounded only at the moment they multiply
into a cents line.
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from .clock import parse_iso_utc


# ──────────────────────────────────────────────────────────────────────────
# Rounding helpers
# ──────────────────────────────────────────────────────────────────────────

def round_half_up_cents(value) -> int:
    """Round a numeric value (int|float|Decimal) to the nearest whole cent
    using half-up convention (away from zero on exactly-half)."""
    if isinstance(value, Decimal):
        d = value
    else:
        # Use repr to avoid binary-float artifacts where possible
        d = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    quantized = d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(quantized)


# ──────────────────────────────────────────────────────────────────────────
# Shift worked-seconds & worked-hours
# ──────────────────────────────────────────────────────────────────────────

def meal_break_seconds(meal_break: Optional[Dict[str, Any]]) -> int:
    """Return the meal-break unpaid duration in *seconds* for a shift.

    duration_minutes is stored truncated to whole minutes per scaffold;
    we convert to seconds (× 60) for arithmetic consistency.
    """
    if not meal_break:
        return 0
    minutes = int(meal_break.get("duration_minutes") or 0)
    return minutes * 60


def shift_worked_seconds(shift: Dict[str, Any], meal_break: Optional[Dict[str, Any]]) -> int:
    """Worked seconds for a CLOSED/FINALIZED shift.

    = actual_end - actual_start - meal_break_seconds, floored at 0.
    """
    if not shift.get("actual_start") or not shift.get("actual_end"):
        return 0
    start = parse_iso_utc(shift["actual_start"])
    end = parse_iso_utc(shift["actual_end"])
    delta = int((end - start).total_seconds())
    delta -= meal_break_seconds(meal_break)
    return max(0, delta)


def shift_worked_hours(shift: Dict[str, Any], meal_break: Optional[Dict[str, Any]]) -> float:
    return shift_worked_seconds(shift, meal_break) / 3600.0


# ──────────────────────────────────────────────────────────────────────────
# §1.3.1 Detention
# ──────────────────────────────────────────────────────────────────────────

def detention_tier_for_minutes(minutes_past: int) -> str:
    if minutes_past < 15:
        return "NONE"
    if minutes_past < 60:
        return "TIER_1"
    if minutes_past < 120:
        return "TIER_2"
    return "TIER_3"


def compute_detention(shift: Dict[str, Any], employee: Dict[str, Any]) -> Tuple[int, str, int]:
    """Compute (minutes_past_scheduled_end, tier, premium_owed_cents).

    For EXEMPT employees the variant bypass kicks in: tier=NONE, premium=0.
    """
    if not shift.get("actual_end"):
        return 0, "NONE", 0
    if employee.get("classification") == "EXEMPT":
        return 0, "NONE", 0

    scheduled_end = parse_iso_utc(shift["scheduled_end"])
    actual_end = parse_iso_utc(shift["actual_end"])
    raw_seconds = (actual_end - scheduled_end).total_seconds()
    if raw_seconds <= 0:
        return 0, "NONE", 0
    minutes_past = math.ceil(raw_seconds / 60.0)
    minutes_past = max(0, minutes_past)
    tier = detention_tier_for_minutes(minutes_past)

    base_cents = int(employee.get("base_hourly_rate_cents") or 0)
    if tier == "NONE":
        premium = 0
    elif tier == "TIER_1":
        premium = round_half_up_cents(Decimal("0.5") * Decimal(base_cents))
    elif tier == "TIER_2":
        premium = round_half_up_cents(Decimal("1.0") * Decimal(base_cents))
    else:  # TIER_3
        premium = round_half_up_cents(Decimal("2.0") * Decimal(base_cents))
    return int(minutes_past), tier, premium


# ──────────────────────────────────────────────────────────────────────────
# §1.3.2 Meal-break premium
# ──────────────────────────────────────────────────────────────────────────

def compute_meal_break_premium(
    shift: Dict[str, Any],
    employee: Dict[str, Any],
    meal_break: Optional[Dict[str, Any]],
) -> int:
    """Return Shift.meal_break_premium_owed_cents per §1.3.

    Exempt or worked_hours <= 5 → 0.
    Else missing/short meal break → 1 hour at base.
    Else meal taken too late → 1 hour at base.
    Else → 0.
    """
    if employee.get("classification") == "EXEMPT":
        return 0
    if not shift.get("actual_start") or not shift.get("actual_end"):
        return 0
    worked_hours = shift_worked_hours(shift, meal_break)
    if worked_hours <= 5.0:
        return 0

    base_cents = int(employee.get("base_hourly_rate_cents") or 0)

    if not meal_break:
        return round_half_up_cents(Decimal("1.0") * Decimal(base_cents))
    duration = int(meal_break.get("duration_minutes") or 0)
    if duration < 30:
        return round_half_up_cents(Decimal("1.0") * Decimal(base_cents))
    if not meal_break.get("taken_before_fifth_hour", False):
        return round_half_up_cents(Decimal("1.0") * Decimal(base_cents))
    return 0


def recompute_meal_break_flags(shift: Dict[str, Any], meal_break: Dict[str, Any], live_punches: List[Dict[str, Any]]) -> None:
    """Update meal_break.duration_minutes and taken_before_fifth_hour in place.

    Only considers non-superseded punches (live_punches). Caller passes the
    live, ordered MEAL_OUT/MEAL_IN pair through that list.
    """
    meal_out = None
    meal_in = None
    for p in live_punches:
        if p["punch_type"] == "MEAL_OUT" and meal_out is None:
            meal_out = p
        elif p["punch_type"] == "MEAL_IN" and meal_in is None:
            meal_in = p
    if not meal_out or not meal_in:
        meal_break["duration_minutes"] = 0
        meal_break["taken_before_fifth_hour"] = False
        return
    mo_dt = parse_iso_utc(meal_out["punched_at"])
    mi_dt = parse_iso_utc(meal_in["punched_at"])
    delta_seconds = int((mi_dt - mo_dt).total_seconds())
    duration_min = max(0, delta_seconds // 60)  # truncate to whole minutes
    meal_break["meal_out_punch_id"] = meal_out["id"]
    meal_break["meal_in_punch_id"] = meal_in["id"]
    meal_break["duration_minutes"] = duration_min

    actual_start = parse_iso_utc(shift["actual_start"]) if shift.get("actual_start") else None
    if actual_start is None:
        meal_break["taken_before_fifth_hour"] = False
        return
    five_hours_after = actual_start.timestamp() + 18000
    taken_before = (mo_dt.timestamp() <= five_hours_after) and (duration_min >= 30)
    meal_break["taken_before_fifth_hour"] = bool(taken_before)


# ──────────────────────────────────────────────────────────────────────────
# §1.3.4 Tip-credit shortfall (per-line rounding ordering pinned)
# ──────────────────────────────────────────────────────────────────────────

def compute_tip_credit_for_shift(
    shift: Dict[str, Any],
    employee: Dict[str, Any],
    meal_break: Optional[Dict[str, Any]],
    declared_tips_cents: int,
) -> Tuple[int, int]:
    """Return (tip_credit_applied_cents, shortfall_topup_cents).

    Per-line rounding ordering (authoritative variant):
        cash_wage_cents   = round_half_up(worked_hours * tipped_cash_rate_cents)
        min_wage_required = round_half_up(worked_hours * applicable_minimum_wage_cents)
        tip_credit        = min(declared_tips, max(0, min_wage_required - cash_wage))
        shortfall_topup   = max(0, min_wage_required - cash_wage - tip_credit)
    """
    worked_seconds = shift_worked_seconds(shift, meal_break)
    worked_hours = Decimal(worked_seconds) / Decimal(3600)
    tipped_cash = int(employee.get("tipped_cash_rate_cents") or 0)
    min_wage_full = int(employee.get("applicable_minimum_wage_cents") or 0)

    cash_wage_cents = round_half_up_cents(worked_hours * Decimal(tipped_cash))
    min_wage_required = round_half_up_cents(worked_hours * Decimal(min_wage_full))

    gap = max(0, min_wage_required - cash_wage_cents)
    tip_credit_applied = min(int(declared_tips_cents), gap)
    shortfall_topup = max(0, min_wage_required - cash_wage_cents - tip_credit_applied)
    return tip_credit_applied, shortfall_topup


# ──────────────────────────────────────────────────────────────────────────
# §1.3.3 Workweek pay engine
# ──────────────────────────────────────────────────────────────────────────

def compute_workweek_pay(
    employee: Dict[str, Any],
    finalized_shifts: List[Dict[str, Any]],
    shift_meal_breaks: Dict[str, Optional[Dict[str, Any]]],
    detention_events_for_shifts: List[Dict[str, Any]],
    tip_declarations_for_shifts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute workweek totals and gross pay.

    `finalized_shifts` is the list of all FINALIZED shifts in the workweek,
    in any order. `shift_meal_breaks` maps shift_id -> meal_break|None.
    Returns dict with keys: total_hours, regular_hours, overtime_hours,
        double_time_hours, gross_pay_cents.
    """
    jurisdiction = employee.get("jurisdiction", "FED")
    base_cents = int(employee.get("base_hourly_rate_cents") or 0)

    # Step 1 — per-day hours.
    # Keyed by UTC ISO date string for determinism.
    per_day: Dict[str, float] = {}
    for s in finalized_shifts:
        if not s.get("actual_start") or not s.get("actual_end"):
            continue
        start_dt = parse_iso_utc(s["actual_start"])
        day_key = start_dt.strftime("%Y-%m-%d")
        worked_sec = shift_worked_seconds(s, shift_meal_breaks.get(s["id"]))
        per_day[day_key] = per_day.get(day_key, 0.0) + (worked_sec / 3600.0)

    total_hours = sum(per_day.values())

    # Step 2 — CA daily buckets.
    ca_regular: Dict[str, float] = {}
    ca_ot: Dict[str, float] = {}
    ca_double: Dict[str, float] = {}
    if jurisdiction == "CA":
        for d, h in per_day.items():
            ca_regular[d] = min(8.0, h)
            ca_ot[d] = max(0.0, min(4.0, h - 8.0))
            ca_double[d] = max(0.0, h - 12.0)
    else:
        for d, h in per_day.items():
            ca_regular[d] = h
            ca_ot[d] = 0.0
            ca_double[d] = 0.0

    # Step 3 — federal weekly OT applied to daily-regular bucket.
    cumulative_regular = 0.0
    fed_ot_hours = 0.0
    regular_hours = 0.0
    # Walk Sun..Sat in calendar order (sorted ISO date keys are chronological).
    for d in sorted(ca_regular.keys()):
        r = ca_regular[d]
        available_to_40 = max(0.0, 40.0 - cumulative_regular)
        regular_today = min(r, available_to_40)
        fed_ot_today = r - regular_today
        regular_hours += regular_today
        fed_ot_hours += fed_ot_today
        cumulative_regular += regular_today

    overtime_hours = fed_ot_hours + sum(ca_ot.values())
    double_time_hours = sum(ca_double.values())

    # Step 4 — gross pay (round per line, then sum).
    base_line = round_half_up_cents(Decimal(repr(regular_hours)) * Decimal(base_cents))
    ot_line = round_half_up_cents(
        Decimal(repr(overtime_hours)) * Decimal(base_cents) * Decimal("1.5")
    )
    dt_line = round_half_up_cents(
        Decimal(repr(double_time_hours)) * Decimal(base_cents) * Decimal("2.0")
    )

    premiums = 0
    for s in finalized_shifts:
        premiums += int(s.get("meal_break_premium_owed_cents") or 0)
    for d in detention_events_for_shifts:
        premiums += int(d.get("premium_owed_cents") or 0)

    tip_topup = 0
    for td in tip_declarations_for_shifts:
        tip_topup += int(td.get("shortfall_topup_cents") or 0)

    gross = base_line + ot_line + dt_line + premiums + tip_topup

    return {
        "total_hours": float(total_hours),
        "regular_hours": float(regular_hours),
        "overtime_hours": float(overtime_hours),
        "double_time_hours": float(double_time_hours),
        "gross_pay_cents": int(gross),
    }
