"""Business calculations, implemented exactly per PRD/scaffold.

Money is always integer cents; rounding is Decimal ROUND_HALF_UP at the pinned
rounding points. Exact rational accumulation uses Fraction where the PRD pins
"no intermediate rounding".
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from db import store, clock


# --- Constants ---
FATIGUE_CAP_MINUTES = 720
REST_WINDOW_HOURS = 10
WEEKLY_STANDBY_SOFT_CAP_MINUTES = 2400
CALLOUT_MINIMUM_MINUTES = 120
RELOCATION_ADMIN_FEE_CENTS = 15000
OVERAGE_NIGHT_MULTIPLIER = Fraction(5, 4)  # 1.25
TECH_SELF_AUTH_CAP_CENTS = 50000
SUPERVISOR_AUTH_CAP_CENTS = 250000
INCIDENT_VENDOR_CAP_CENTS = 500000
INVOICE_OVERAGE_NUM = 11000
INVOICE_OVERAGE_DEN = 10000
INSURANCE_NOTIFY_THRESHOLD_CENTS = 100000
INSURANCE_NOTIFY_WINDOW_HOURS = 24

ACK_LEVEL_1_MINUTES = 15
ACK_LEVEL_2_MINUTES = 30


def round_half_up_cents(value):
    """Round a Decimal/Fraction/int to whole cents, half-up."""
    if isinstance(value, Fraction):
        # Convert exactly: value.numerator / value.denominator
        d = Decimal(value.numerator) / Decimal(value.denominator)
    elif isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(value)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# SLA target
# ---------------------------------------------------------------------------

def sla_target_for_category(category):
    if category in ("GAS_LEAK", "FLOOD"):
        return 30
    if category in ("NO_HEAT", "NO_POWER"):
        return 60
    return 120


# ---------------------------------------------------------------------------
# Callback pay (ticket close)
# ---------------------------------------------------------------------------

def is_night(dt):
    """Night window: time-of-day in [22:00, 06:00) UTC, half-open."""
    return dt.hour >= 22 or dt.hour < 6


def is_weekend(dt):
    """Saturday=5, Sunday=6."""
    return dt.weekday() in (5, 6)


def compute_callback_pay(ticket, technician):
    billed_minutes = max(ticket["callback_minutes"], CALLOUT_MINIMUM_MINUTES)
    dispatched_at = ticket["dispatched_at"]
    rate = Fraction(technician["base_hourly_rate_cents"])
    if is_night(dispatched_at):
        rate *= Fraction(3, 2)  # 1.5
    if is_weekend(dispatched_at):
        rate *= Fraction(5, 4)  # 1.25
    if ticket["category"] in ("GAS_LEAK", "FLOOD"):
        rate *= Fraction(3, 2)  # 1.5
    pay = Fraction(billed_minutes, 60) * rate
    return round_half_up_cents(pay)


# ---------------------------------------------------------------------------
# Standby pay provisional (shift completion)
# ---------------------------------------------------------------------------

def compute_standby_provisional(shift, technician):
    duration_minutes = int((shift["end_at"] - shift["start_at"]).total_seconds() // 60)
    callback_overlap = 0
    for t in store.call_tickets.values():
        if (
            t["assigned_technician_id"] == shift["technician_id"]
            and t["dispatched_at"] is not None
            and shift["start_at"] <= t["dispatched_at"] < shift["end_at"]
            and t["status"] in ("MITIGATED", "CLOSED")
            and t["callback_minutes"] is not None
        ):
            callback_overlap += t["callback_minutes"]
    standby_minutes = max(duration_minutes - callback_overlap, 0)
    pay = (
        Fraction(standby_minutes, 60)
        * Fraction(technician["base_hourly_rate_cents"])
        * (1 + Fraction(technician["on_call_differential_bp"], 10000))
    )
    return standby_minutes, round_half_up_cents(pay)


# ---------------------------------------------------------------------------
# Standby pay final (pay period close) — chronological tier split
# ---------------------------------------------------------------------------

def compute_standby_final(shifts, technician):
    """shifts: list of COMPLETED shift dicts (already filtered to period).

    Returns (standby_minutes_total, standby_pay_final_cents).
    """
    ordered = sorted(shifts, key=lambda s: (s["start_at"], s["created_at"], s["_seq"]))
    full_remaining = WEEKLY_STANDBY_SOFT_CAP_MINUTES
    acc = Fraction(0)
    total_minutes = 0
    base = Fraction(technician["base_hourly_rate_cents"])
    diff_bp = technician["on_call_differential_bp"]
    for s in ordered:
        m = s["standby_minutes"]
        total_minutes += m
        m_full = min(m, full_remaining)
        m_half = m - m_full
        full_remaining -= m_full
        acc += Fraction(m_full, 60) * base * (1 + Fraction(diff_bp, 10000))
        acc += Fraction(m_half, 60) * base * (1 + Fraction(diff_bp, 20000))
    return total_minutes, round_half_up_cents(acc)


# ---------------------------------------------------------------------------
# Relocation cost
# ---------------------------------------------------------------------------

def relocation_estimate(start_date, end_date, nightly_rate_cents):
    planned_nights = int((end_date - start_date).total_seconds() // 86400)
    est = planned_nights * nightly_rate_cents + RELOCATION_ADMIN_FEE_CENTS
    return planned_nights, est


def relocation_actual(start_date, actual_end_date, planned_nights, nightly_rate_cents):
    actual_nights = int((actual_end_date - start_date).total_seconds() // 86400)
    overage_nights = max(0, actual_nights - planned_nights)
    normal_nights = actual_nights - overage_nights
    overage_night_rate = round_half_up_cents(
        Fraction(nightly_rate_cents) * OVERAGE_NIGHT_MULTIPLIER
    )
    return (
        normal_nights * nightly_rate_cents
        + overage_nights * overage_night_rate
        + RELOCATION_ADMIN_FEE_CENTS
    )


# ---------------------------------------------------------------------------
# Vendor invoice settlement
# ---------------------------------------------------------------------------

def _qty_fraction(q):
    """Exact Fraction for a JSON quantity: ints direct, floats via their
    decimal spelling so 1.5 means 3/2 (not a binary-float expansion)."""
    if isinstance(q, int):
        return Fraction(q)
    return Fraction(str(q))


def invoice_settlement(lines, overhead_markup_bp, amount_cents):
    """Returns (subtotal, markup, total, ceiling)."""
    subtotal = 0
    for line in lines:
        line_total = round_half_up_cents(
            _qty_fraction(line["quantity"]) * Fraction(line["unit_cost_cents"])
        )
        subtotal += line_total
    markup = round_half_up_cents(Fraction(subtotal * overhead_markup_bp, 10000))
    total = subtotal + markup
    ceiling = round_half_up_cents(
        Fraction(amount_cents * INVOICE_OVERAGE_NUM, INVOICE_OVERAGE_DEN)
    )
    return subtotal, markup, total, ceiling


# ---------------------------------------------------------------------------
# Fatigue
# ---------------------------------------------------------------------------

def compute_callback_minutes_168h(technician_id, now):
    """Sum callback_minutes over the technician's MITIGATED/CLOSED tickets with
    mitigated_at in the left-open window (now-168h, now]."""
    window_start = now - timedelta(hours=168)
    total = 0
    for t in store.call_tickets.values():
        if (
            t["assigned_technician_id"] == technician_id
            and t["status"] in ("MITIGATED", "CLOSED")
            and t["mitigated_at"] is not None
            and window_start < t["mitigated_at"] <= now
            and t["callback_minutes"] is not None
        ):
            total += t["callback_minutes"]
    return total


def fatigue_blocked(technician, reference_time):
    """Live block check: blocked iff fatigue_block_until is not null and > reference."""
    fbu = technician["fatigue_block_until"]
    return fbu is not None and fbu > reference_time
