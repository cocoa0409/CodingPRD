"""Domain constants and the pinned arithmetic for every calculation.

All money / ratio arithmetic is exact rational arithmetic (fractions.Fraction),
rounded half-up at exactly the points the PRD pins.  No binary float is ever
used as an intermediate.
"""

from datetime import date, datetime, time, timedelta, timezone
from fractions import Fraction

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
CATEGORIES = ("LIFE_SAFETY", "GUEST_FACING", "BACK_OF_HOUSE")

TRIGGER_TYPES = ("POST_INSPECTION", "TRANSACTION_CHANGE_OF_OWNERSHIP", "RELICENSING")

FINANCING_SOURCES = ("RESERVE_DRAW", "TERM_LOAN", "OWNER_EQUITY", "MIXED")

TRADES = ("FIRE_PROTECTION", "FF_AND_E", "MEP", "GENERAL")

INSPECTION_TYPES = ("SCOPING", "PROGRESS", "COMPLETION", "RE_INSPECTION")

SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")

DISPUTE_BASES = ("SCOPE_REASONABLENESS", "COST_ESTIMATE", "STANDARDS_APPLICABILITY")

DISPUTE_RESOLUTIONS = ("UPHOLD", "REVISE", "REMOVE")

LEDGER_ENTRY_TYPES = (
    "SCOPE_ISSUED",
    "COST_REVISED",
    "ITEM_REMOVED",
    "EXTENSION_GRANTED",
    "DRAW_DISBURSED",
    "DRAW_REVERSED",
    "PUNCH_WAIVED",
    "DEFAULT_ISSUED",
    "DEFAULT_CURED",
    "PLAN_COMPLETED",
    "PLAN_TERMINATED",
)

OPEN_PLAN_STATUSES = (
    "ISSUED",
    "OWNER_ACKNOWLEDGED",
    "IN_EXECUTION",
    "READY_FOR_COMPLETION_INSPECTION",
)

EXECUTION_WINDOW_STATUSES = ("OWNER_ACKNOWLEDGED", "IN_EXECUTION")

# Items excluded from every plan aggregate.
EXCLUDED_ITEM_STATUSES = ("REMOVED_BY_DISPUTE", "VOIDED")

# Statuses that suppress the overdue flag.
NON_OVERDUE_ITEM_STATUSES = ("WORK_COMPLETE", "ACCEPTED", "REMOVED_BY_DISPUTE", "VOIDED")

ACTIVE_BUDGET_STATUSES = ("DRAFT", "APPROVED", "LOCKED", "UNDERFUNDED")

ENCUMBERING_DRAW_STATUSES = ("REQUESTED", "BRAND_CONSENTED")

OPEN_DEFECT_STATUSES = ("OPEN", "REMEDIATED")

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
CATEGORY_DEADLINE_DAYS = {
    "LIFE_SAFETY": 90,
    "GUEST_FACING": 270,
    "BACK_OF_HOUSE": 450,
}

CATEGORY_RANK = {"LIFE_SAFETY": 1, "GUEST_FACING": 2, "BACK_OF_HOUSE": 3}

CATEGORY_ESCALATION = {
    "LIFE_SAFETY": Fraction("1.00"),
    "GUEST_FACING": Fraction("1.075"),
    "BACK_OF_HOUSE": Fraction("1.035"),
}

CATEGORY_MAX_EXT_DAYS = {
    "LIFE_SAFETY": 30,
    "GUEST_FACING": 120,
    "BACK_OF_HOUSE": 180,
}

LD_RATE = {
    "LIFE_SAFETY": Fraction("0.15"),
    "GUEST_FACING": Fraction("0.08"),
    "BACK_OF_HOUSE": Fraction("0.03"),
}

DEFAULT_CONTINGENCY_PCT = Fraction("0.10")
MAX_CONTINGENCY_PCT = Fraction("0.50")

MAX_OOO_PCT = Fraction("0.25")
CHANGEOVER_BUFFER_DAYS = 2
PUNCH_CURE_DAYS = 14
CURE_MAX_DAYS = 60
LIFE_SAFETY_CURE_MAX_DAYS = 10
JUSTIFICATION_MIN_CHARS = 40
MAX_EXTENSION_ROUNDS = 3
COMPLIANT_MIN_SCORE = 80
PROJECTION_HORIZON_DAYS = 30
DEADLINE_PRESSURE_HORIZON_DAYS = 60
DEADLINE_PRESSURE_CLAMP_RATIO = Fraction("0.60")
DEADLINE_PRESSURE_CLAMP_MULTIPLIER = Fraction("0.5")

LS_OVERDUE_PENALTY = 25
LS_OVERDUE_PENALTY_CAP = 50
GF_OVERDUE_PENALTY = 8
BOH_OVERDUE_PENALTY = 3
MAJOR_DEFECT_PENALTY = 5
CRITICAL_DEFECT_PENALTY = 12
FUNDING_GAP_MINOR_PENALTY = 10
FUNDING_GAP_MAJOR_PENALTY = 25
FUNDING_GAP_MINOR_RATIO = Fraction("0.10")


# --------------------------------------------------------------------------
# Exact arithmetic helpers
# --------------------------------------------------------------------------
def frac(value):
    """Exact Fraction from an int / str / float-typed JSON number."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool):
        return Fraction(int(value))
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


def round_half_up(value, places=0):
    """Round half away from zero at `places` decimals; returns a Fraction."""
    value = frac(value)
    scale = Fraction(10) ** places
    scaled = value * scale
    negative = scaled < 0
    if negative:
        scaled = -scaled
    whole = scaled.numerator // scaled.denominator
    remainder = scaled - whole
    if remainder >= Fraction(1, 2):
        whole += 1
    if negative:
        whole = -whole
    return Fraction(whole) / scale


def round_cents(value):
    """Round half-up to a whole integer number of cents."""
    return int(round_half_up(value, 0))


def as_number(value, places):
    """Render a Fraction as a JSON number with the pinned decimal places."""
    value = round_half_up(value, places)
    if places <= 0:
        return int(value)
    return float(value)


def floor_div(value):
    value = frac(value)
    return value.numerator // value.denominator


# --------------------------------------------------------------------------
# Date helpers
# --------------------------------------------------------------------------
def parse_date(text):
    """Strict ISO-8601 calendar date; returns None when unparseable."""
    if not isinstance(text, str):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def fmt_date(value):
    return value.isoformat() if value is not None else None


def add_days(base, days):
    return base + timedelta(days=days)


def parse_datetime(text):
    """Strict ISO 8601 instant, normalised to UTC; returns None when unparseable."""
    if not isinstance(text, str) or not text:
        return None
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def day_start(day):
    """The 00:00:00Z instant of a calendar date."""
    return datetime.combine(day, time(0, 0, 0), tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# category_deadline_schedule
# --------------------------------------------------------------------------
def base_deadline(issued_date, category):
    return add_days(issued_date, CATEGORY_DEADLINE_DAYS[category])


# --------------------------------------------------------------------------
# funding_requirement (round each item, then sum)
# --------------------------------------------------------------------------
def item_funding_cents(approved_cost_cents, category, contingency_pct):
    raw = (
        frac(approved_cost_cents)
        * (Fraction(1) + frac(contingency_pct))
        * CATEGORY_ESCALATION[category]
    )
    return round_cents(raw)


# --------------------------------------------------------------------------
# liquidated_damages (sum exact products, round once at the end)
# --------------------------------------------------------------------------
def liquidated_damages_cents(breached_items):
    total = Fraction(0)
    for item in breached_items:
        total += frac(item["approved_cost_cents"]) * LD_RATE[item["category"]]
    return round_cents(total)


# --------------------------------------------------------------------------
# displacement_revenue_impact
# --------------------------------------------------------------------------
def recapture_pct(ooo_ratio):
    if ooo_ratio < Fraction("0.10"):
        return Fraction("0.30")
    if ooo_ratio < Fraction("0.25"):
        return Fraction("0.15")
    return Fraction("0.00")


def displacement_impact(rooms_out_of_service, start_date, end_date, room_count,
                        adr_baseline_cents, occupancy_baseline_pct):
    nights = (end_date - start_date).days + 1
    displaced_room_nights = rooms_out_of_service * nights
    ooo_ratio = (
        Fraction(0)
        if not room_count
        else Fraction(rooms_out_of_service, room_count)
    )
    recapture = recapture_pct(ooo_ratio)
    gross = round_cents(
        frac(displaced_room_nights) * frac(adr_baseline_cents) * frac(occupancy_baseline_pct)
    )
    impact = round_cents(frac(gross) * (Fraction(1) - recapture))
    return {
        "nights": nights,
        "displaced_room_nights": displaced_room_nights,
        "ooo_ratio": ooo_ratio,
        "recapture_pct": recapture,
        "gross_revenue_at_risk_cents": gross,
        "displacement_impact_cents": impact,
    }
