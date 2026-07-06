"""Pure calculation helpers (§1.3 / §3.6-3.9): equipment line pricing, crew labor
pricing, order totals, deposit sizing, and equipment availability.

Every monetary result is a whole-cent integer, rounded half up per line/assignment
before summation (§2.5).
"""
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal

from store import round_half_up

# --- constants (verbatim from §1.3) ---------------------------------------
STANDBY_RATE_FACTOR = Decimal("0.50")
MIN_CALL_HOURS = Decimal("4")
OT_THRESHOLD_HOURS = Decimal("10")
OT_MULTIPLIER = Decimal("1.5")
OPERATOR_PREMIUM = Decimal("1.20")
RUSH_WINDOW_DAYS = 7
RUSH_SURCHARGE_PCT = Decimal("0.08")
DEPOSIT_RATE = Decimal("0.20")
TURNAROUND_MINUTES = 60


# --- date / datetime parsing ----------------------------------------------
def parse_date(s):
    return date.fromisoformat(s)


def parse_dt(s):
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def billable_days(start_str, end_str):
    return (parse_date(end_str) - parse_date(start_str)).days + 1


# --- equipment line pricing ------------------------------------------------
def multi_day_tier(bdays):
    if bdays <= 2:
        return Decimal("0.00")
    if bdays <= 6:
        return Decimal("0.10")
    return Decimal("0.15")


def equipment_line_charge(daily_rate_cents, units, bdays, is_standby):
    raw = Decimal(daily_rate_cents) * Decimal(units) * Decimal(bdays)
    if is_standby:
        raw = raw * STANDBY_RATE_FACTOR
    tier = multi_day_tier(bdays)
    return round_half_up(raw * (Decimal(1) - tier))


# --- crew labor pricing ----------------------------------------------------
def crew_assignment_cost(hourly_rate_cents, hours, assignment_role):
    h = Decimal(str(hours))
    base_hours = h if h > MIN_CALL_HOURS else MIN_CALL_HOURS
    ot_hours = base_hours - OT_THRESHOLD_HOURS
    if ot_hours < 0:
        ot_hours = Decimal(0)
    reg_hours = base_hours - ot_hours
    role_mult = OPERATOR_PREMIUM if assignment_role == "OPERATOR" else Decimal("1.00")
    rate = Decimal(hourly_rate_cents)
    reg_pay = reg_hours * rate * role_mult
    ot_pay = ot_hours * rate * OT_MULTIPLIER * role_mult
    return round_half_up(reg_pay + ot_pay)


# --- order totals ----------------------------------------------------------
def volume_tier(subtotal_cents):
    if subtotal_cents < 100000:
        return Decimal("0.00")
    if subtotal_cents < 500000:
        return Decimal("0.05")
    return Decimal("0.10")


def volume_discount(subtotal_cents):
    return round_half_up(Decimal(subtotal_cents) * volume_tier(subtotal_cents))


def rush_surcharge(discounted_cents, clock_dt, event_start_str):
    days = (parse_date(event_start_str) - clock_dt.date()).days
    if days <= RUSH_WINDOW_DAYS:
        return round_half_up(Decimal(discounted_cents) * RUSH_SURCHARGE_PCT)
    return 0


def deposit_required(sum_replacement_exposure):
    return round_half_up(Decimal(sum_replacement_exposure) * DEPOSIT_RATE)
