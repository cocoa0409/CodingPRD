"""Pure calculation rules and constants (SCAFFOLD 1.3, PRD 2.8-2.11, 3.6, 3.9)."""

import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- constants
ROTATION_EPOCH_DATE = date(2026, 1, 1)
PLATOON_ORDER = ("A", "B", "C", "D")
KELLY_CYCLE_LENGTH = 8

LEAVE_FLOOR_SLACK = 2
CLOSURE_TRIGGER_GAP = 2

SHIFT_START_HOUR = 8
SHIFT_HOURS = 24
CONTINUOUS_DUTY_FATIGUE_HOURS = 24
CONTINUOUS_DUTY_MAX_HOURS = 48

CERT_PREMIUM_PCT = {"NONE": 0, "PARAMEDIC": 12, "HAZMAT_TECH": 8, "TECHNICAL_RESCUE": 8}
FATIGUE_PREMIUM_PCT = 10
MODE_MIN_HOURS = {"VOLUNTARY": 0, "MANDATORY_HOLDOVER": 2, "CALLBACK": 3}
OT_MULTIPLIER = {
    "VOLUNTARY": Decimal("1.5"),
    "MANDATORY_HOLDOVER": Decimal("1.5"),
    "CALLBACK": Decimal("2.0"),
}

WITHIN_BAND_BP = 9000
WATCH_BAND_BP = 10000

FLSA_PERIOD_DAYS = 27
FLSA_THRESHOLD_HOURS = 204
FLSA_MAX_PERIOD_HOURS = 288
FLSA_PREMIUM_RATE = Decimal("0.5")

OFFER_RESPONSE_WINDOW_MINUTES = 120
OT_PASS_LIMIT = 3

MAX_OVERSTAFF_SEATS = 1
TRADE_LEAD_TIME_HOURS = 48

OT_MULTIPLIER_VOLUNTARY = Decimal("1.5")
INJURY_SHIFTS_PER_PERIOD = 9

PLATOON_COVERAGE_FACTOR = 4
INJURY_BODY_WEIGHT = 2
MONITOR_MAX = 8
RECRUIT_MAX = 20

LEAVE_TYPE_PRIORITY = {
    "INJURY": 1,
    "SICK": 2,
    "KELLY_DAY": 3,
    "BEREAVEMENT": 4,
    "VACATION": 5,
}
NON_DISCRETIONARY = ("INJURY", "SICK")

ROSTER_TYPE_FOR_MODE = {
    "VOLUNTARY": "VOLUNTARY_OT",
    "MANDATORY_HOLDOVER": "MANDATORY_HOLDOVER",
    "CALLBACK": "CALLBACK",
}


# ------------------------------------------------------------------ helpers
def rhu(value):
    """Round half up to a whole unit and return an int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    return Decimal(str(value))


def num(value):
    """Normalise integral floats so hour figures serialise as whole numbers."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def to_date(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))


def date_str(value):
    if isinstance(value, str):
        return value
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def date_diff_days(later, earlier):
    return (to_date(later) - to_date(earlier)).days


def add_days(value, days):
    return to_date(value) + timedelta(days=days)


# --------------------------------------------------- rotation_calendar (1.3)
def elapsed_days(shift_date):
    return (to_date(shift_date) - ROTATION_EPOCH_DATE).days


def platoon_on_duty(shift_date):
    return PLATOON_ORDER[elapsed_days(shift_date) % 4]


def kelly_slot(shift_date):
    return ((elapsed_days(shift_date) // 4) % KELLY_CYCLE_LENGTH) + 1


def is_kelly_day(member, shift_date):
    return (
        platoon_on_duty(shift_date) == member.get("platoon")
        and member.get("kelly_day_cycle_position") == kelly_slot(shift_date)
    )


# ----------------------------------------------------------------- intervals
def shift_start_instant(shift_date):
    d = to_date(shift_date)
    return datetime(d.year, d.month, d.day, SHIFT_START_HOUR, 0, 0, tzinfo=timezone.utc)


def interval_for(shift_date, hours):
    start = shift_start_instant(shift_date)
    return (start, start + timedelta(hours=float(hours)))


def intervals_overlap(a, b):
    return a[0] < b[1] and b[0] < a[1]


def merged_block_hours(existing, prospective):
    """calculations.continuous_duty_hours - half-open merge, zero gap merges."""
    intervals = sorted(list(existing) + [prospective], key=lambda iv: iv[0])
    merged = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    for start, end in merged:
        if start <= prospective[0] and prospective[1] <= end:
            return (end - start).total_seconds() / 3600.0
    return (prospective[1] - prospective[0]).total_seconds() / 3600.0


# ------------------------------------------------------- overtime_offer_cost
def price_offer(hourly_rate_cents, required_certification, hiring_mode, offer_hours,
                fatigue_applies):
    cert_pct = CERT_PREMIUM_PCT.get(required_certification or "NONE", 0)
    fatigue_pct = FATIGUE_PREMIUM_PCT if fatigue_applies else 0
    effective_rate_cents = rhu(
        dec(hourly_rate_cents) * dec(100 + cert_pct + fatigue_pct) / dec(100)
    )
    effective_hours = max(offer_hours, MODE_MIN_HOURS[hiring_mode])
    projected_cost_cents = rhu(
        dec(effective_rate_cents) * dec(effective_hours) * OT_MULTIPLIER[hiring_mode]
    )
    return effective_rate_cents, num(effective_hours), projected_cost_cents


def effective_offer_hours(hiring_mode, offer_hours):
    return num(max(offer_hours, MODE_MIN_HOURS[hiring_mode]))


# ---------------------------------------------------- station_budget_posture
def budget_posture(ot_actual_cents, ot_committed_cents, fiscal_ot_budget_cents):
    consumed = int(ot_actual_cents) + int(ot_committed_cents)
    if not fiscal_ot_budget_cents:
        return "WITHIN" if consumed <= 0 else "OVER"
    pct_bp = rhu(dec(consumed) * dec(10000) / dec(fiscal_ot_budget_cents))
    if pct_bp <= WITHIN_BAND_BP:
        return "WITHIN"
    if pct_bp <= WATCH_BAND_BP:
        return "WATCH"
    return "OVER"


# --------------------------------------------------------- staffing_posture
def staffing_posture(staffing_gap, certification_gap_count):
    if certification_gap_count > 0:
        return "CRITICAL"
    if staffing_gap == 0:
        return "FULLY_STAFFED"
    if staffing_gap <= CLOSURE_TRIGGER_GAP:
        return "SHORT"
    return "CRITICAL"


def multiset_difference(needed, held):
    """Per-value multiset difference; returns the remaining needed values."""
    remaining = list(needed)
    for value in held:
        if value in remaining:
            remaining.remove(value)
    return remaining


# ----------------------------------------------------------- FLSA / premium
def flsa_premium_cents(basis_hours, hourly_rate_cents):
    return rhu(dec(basis_hours) * dec(hourly_rate_cents) * FLSA_PREMIUM_RATE)


# ------------------------------------------------------ academy hiring signal
def academy_signal(open_vacancy_seats, injury_headcount):
    raw_need = open_vacancy_seats + injury_headcount * INJURY_BODY_WEIGHT
    recommended = int(math.ceil(float(raw_need) / PLATOON_COVERAGE_FACTOR))
    if recommended == 0:
        tier = "NONE"
    elif recommended <= MONITOR_MAX:
        tier = "MONITOR"
    elif recommended <= RECRUIT_MAX:
        tier = "RECRUIT"
    else:
        tier = "SURGE"
    return raw_need, recommended, tier
