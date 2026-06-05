"""Calculation rules (PRD §2.9, §3.2, §3.5, §3.8 and SCAFFOLD §1.3).

All money is integer cents. Fractional cents are rounded half up. Hour
quantities (shoot-hour overage and second-shooter billable hours) are rounded
UP to whole hours before pricing. These hour-rounding and cent-rounding steps
are independent and both apply.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---- constants (SCAFFOLD §1.3) ----------------------------------------------
MIN_DEPOSIT_CENTS = 5000
ALBUM_BINDING_SURCHARGE_CENTS = 3500
PRINT_TIER2_RATE = Decimal("0.90")
PRINT_TIER3_RATE = Decimal("0.80")
LICENSE_BASE_CENTS = 20000
TIER_EARLY_DAYS = 14
TIER_MID_DAYS = 7
SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600

LICENSE_SCOPE_MULT = {
    "PERSONAL": Decimal("1.0"),
    "COMMERCIAL": Decimal("2.5"),
    "EDITORIAL": Decimal("1.8"),
    "EXCLUSIVE": Decimal("4.0"),
}
LICENSE_TERRITORY_MULT = {
    "LOCAL": Decimal("1.0"),
    "NATIONAL": Decimal("1.5"),
    "WORLDWIDE": Decimal("2.2"),
}


def round_half_up(value: Decimal) -> int:
    """Round a Decimal half up to the nearest whole cent (integer)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant (tolerating a trailing 'Z')."""
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---- booking_total_fee (PRD §3.2) -------------------------------------------
def booking_total_fee(package: dict, requested_shoot_hours, addon_orders: list,
                      assignments: list) -> int:
    """base_fee + ceil(overage) * overage_rate + ORDERED add-on line totals
    + ASSIGNED second-shooter fees. CANCELLED add-ons and RELEASED
    assignments contribute nothing."""
    overage_hours = max(0, _num(requested_shoot_hours) - _num(package["included_shoot_hours"]))
    overage_whole = math.ceil(overage_hours) if overage_hours > 0 else 0
    overage_charge = overage_whole * int(package["overage_hourly_rate_cents"])
    base = int(package["base_fee_cents"]) + overage_charge

    addon_sum = sum(int(a["line_total_cents"]) for a in addon_orders
                    if a["status"] == "ORDERED")
    shooter_sum = sum(int(s["assignment_fee_cents"]) for s in assignments
                      if s["status"] == "ASSIGNED")
    return base + addon_sum + shooter_sum


# ---- deposit_due (PRD §3.2) -------------------------------------------------
def deposit_due(total_fee_cents: int, deposit_pct) -> int:
    """round_half_up(total * deposit_pct), then clamp:
    min(total_fee_cents, max(rounded, MIN_DEPOSIT_CENTS))."""
    raw = Decimal(int(total_fee_cents)) * Decimal(str(deposit_pct))
    pct_amount = round_half_up(raw)
    clamped = min(int(total_fee_cents), max(pct_amount, MIN_DEPOSIT_CENTS))
    return clamped


# ---- balance_due / amount_paid (PRD §3.2, §3.6) -----------------------------
def amount_paid(payments: list) -> int:
    captured = sum(int(p["amount_cents"]) for p in payments
                   if p["status"] == "SETTLED" and p["kind"] in ("DEPOSIT", "BALANCE"))
    refunded = sum(int(p["amount_cents"]) for p in payments
                   if p["status"] == "SETTLED" and p["kind"] == "REFUND")
    return captured - refunded


def balance_due(total_fee_cents: int, amount_paid_cents: int) -> int:
    return max(0, int(total_fee_cents) - int(amount_paid_cents))


# ---- cancellation_fee (PRD §3.8) --------------------------------------------
def cancellation_fee(deposit_due_cents: int, schedule_start_utc: str,
                     current_utc: str) -> int:
    """Forward-looking lead-time tier off the live clock.
    lead_days = floor((start - now) / 86400 s);
    >=14 -> 0.25, >=7 -> 0.50, else 1.00. fee = round_half_up(deposit * pct)."""
    start = parse_iso(schedule_start_utc)
    now = parse_iso(current_utc)
    delta_seconds = (start - now).total_seconds()
    lead_days = math.floor(delta_seconds / SECONDS_PER_DAY)
    if lead_days >= TIER_EARLY_DAYS:
        pct = Decimal("0.25")
    elif lead_days >= TIER_MID_DAYS:
        pct = Decimal("0.50")
    else:
        pct = Decimal("1.00")
    return round_half_up(Decimal(int(deposit_due_cents)) * pct)


# ---- addon_line_total (PRD §3.8) --------------------------------------------
def addon_line_total(line_kind: str, quantity: int, unit_price_cents: int) -> int:
    quantity = int(quantity)
    unit = int(unit_price_cents)
    if line_kind == "PRINT":
        t1 = min(quantity, 10)
        t2 = max(0, min(quantity, 50) - 10)
        t3 = max(0, quantity - 50)
        sub1 = round_half_up(Decimal(t1) * Decimal(unit) * Decimal("1.00"))
        sub2 = round_half_up(Decimal(t2) * Decimal(unit) * PRINT_TIER2_RATE)
        sub3 = round_half_up(Decimal(t3) * Decimal(unit) * PRINT_TIER3_RATE)
        return sub1 + sub2 + sub3
    # ALBUM: flat per-unit plus fixed binding surcharge, no discount.
    return quantity * unit + ALBUM_BINDING_SURCHARGE_CENTS


# ---- second_shooter_fee (PRD §3.5) ------------------------------------------
def second_shooter_billable_hours(start_utc: str, end_utc: str) -> int:
    duration_seconds = (parse_iso(end_utc) - parse_iso(start_utc)).total_seconds()
    return math.ceil(duration_seconds / SECONDS_PER_HOUR)


def second_shooter_fee(billable_hours: int, hourly_rate_cents: int) -> int:
    return int(billable_hours) * int(hourly_rate_cents)


# ---- license_fee (PRD §3.8) -------------------------------------------------
def license_fee(usage_scope: str, territory: str, term_months: int) -> int:
    """base * scope_mult * terr_mult * term_factor; round_half_up ONCE at end.
    term_factor = 1.0 + (effective_months / 12) * 0.10;
    perpetual (term_months == 0) treated as a 60-month term."""
    scope_mult = LICENSE_SCOPE_MULT[usage_scope]
    terr_mult = LICENSE_TERRITORY_MULT[territory]
    effective_months = 60 if int(term_months) == 0 else int(term_months)
    term_factor = Decimal("1.0") + (Decimal(effective_months) / Decimal(12)) * Decimal("0.10")
    raw = Decimal(LICENSE_BASE_CENTS) * scope_mult * terr_mult * term_factor
    return round_half_up(raw)


def _num(v):
    """Coerce a JSON number (int or float) to a Python number, preserving int."""
    if isinstance(v, bool):
        return int(v)
    return v
