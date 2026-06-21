"""Pure calculations: franchise tax, late fee, BOI deadline (SCAFFOLD §1.3)."""
from __future__ import annotations

import datetime as _dt

import db

SUPPORTED_STATES = {"CA", "DE", "NY", "TX", "FL", "WY"}

BASE_BY_STATE = {
    "CA": {"LLC": 80000, "CORP": 80000, "LP": 80000},
    "DE": {"LLC": 30000, "CORP": 17500, "LP": 30000},
    "NY": {"LLC": 2500, "CORP": 2500, "LP": 2500},
    "TX": {"LLC": 0, "CORP": 0, "LP": 0},
    "FL": {"LLC": 13875, "CORP": 15000, "LP": 50000},
    "WY": {"LLC": 6000, "CORP": 6000, "LP": 10000},
}

TIER_MULT_X100 = {
    "ZERO": 100,
    "MICRO": 100,
    "SMALL": 110,
    "MEDIUM": 125,
    "LARGE": 150,
}

MIN_FLOOR_BY_STATE = {
    "CA": 80000,
    "DE": 17500,
    "NY": 2500,
    "TX": 0,
    "FL": 13875,
    "WY": 6000,
}

DAILY_RATE_BY_STATE_X100 = {
    "CA": 5550,
    "DE": 11100,
    "NY": 2250,
    "TX": 0,
    "FL": 7775,
    "WY": 3325,
}

LATE_FEE_CAP_CENTS = 25000000  # $250,000

GRACE_DAYS_BY_TRIGGER = {
    "FORMATION": 90,
    "AMENDMENT": 30,
    "ANNUAL_REFRESH": 30,
}

# Cumulative cap for franchise tax safety check. The scaffold names the
# constant `CUMULATIVE_CAP_CENTS` but the PRD does not give a literal value.
# Use a sentinel large enough that ordinary tests pass through, small enough
# that pathological large-state * many-years scenarios trip it. The scaffold
# §1.4 priority 90 rule says "must be < CUMULATIVE_CAP_CENTS"; we use 10
# million dollars = 1,000,000,000 cents as a deliberate ceiling.
CUMULATIVE_CAP_CENTS = 1_000_000_000


def franchise_tax_cents(formation_state_code: str, entity_type: str, revenue_band: str) -> int:
    base_cents = BASE_BY_STATE[formation_state_code][entity_type]
    mult = TIER_MULT_X100[revenue_band]
    raw_cents = (base_cents * mult) // 100
    floor_cents = MIN_FLOOR_BY_STATE[formation_state_code]
    return max(raw_cents, floor_cents)


def annual_report_deadline_utc(period_year: int) -> _dt.datetime:
    return _dt.datetime(period_year + 1, 4, 15, 23, 59, 59, tzinfo=_dt.timezone.utc)


def late_fee_cents(formation_state_code: str, period_year: int, filed_utc: _dt.datetime) -> int:
    deadline_utc = annual_report_deadline_utc(period_year)
    if filed_utc <= deadline_utc:
        return 0
    delta_seconds = int((filed_utc - deadline_utc).total_seconds())
    days_late = max(1, (delta_seconds + 86399) // 86400)
    daily_x100 = DAILY_RATE_BY_STATE_X100[formation_state_code]
    per_day_fee = (daily_x100 + 50) // 100
    accrued = per_day_fee * days_late
    return min(accrued, LATE_FEE_CAP_CENTS)


def boi_filing_deadline_utc(
    triggering_event: str,
    business_entity_formed_at: _dt.datetime,
    created_clock_utc: _dt.datetime,
) -> _dt.datetime:
    if triggering_event == "FORMATION":
        base = business_entity_formed_at
    else:
        base = created_clock_utc
    grace = GRACE_DAYS_BY_TRIGGER[triggering_event]
    return base + _dt.timedelta(days=grace)
