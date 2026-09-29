"""Calculation: filing_batch_totals_and_penalty (PRD 3.9)."""

import calendar
import re
from datetime import datetime, timedelta, timezone

import clock
import store
from moneyutil import dec, round_half_up

LATE_PENALTY_RATE = dec("0.10")
LATE_PENALTY_MIN_CENTS = 2500

_MONTHLY_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_QUARTERLY_RE = re.compile(r"^(\d{4})-Q([1-4])$")


def period_key_for(program, instant=None):
    """The filing period a new line falls into, per the state's calendar."""
    moment = (instant or clock.now()).astimezone(timezone.utc)
    if program.get("filing_frequency") == "QUARTERLY":
        quarter = (moment.month - 1) // 3 + 1
        return "%04d-Q%d" % (moment.year, quarter)
    return "%04d-%02d" % (moment.year, moment.month)


def period_key_valid(period_key, frequency):
    if not isinstance(period_key, str):
        return False
    if frequency == "MONTHLY":
        return bool(_MONTHLY_RE.match(period_key))
    if frequency == "QUARTERLY":
        return bool(_QUARTERLY_RE.match(period_key))
    return False


def period_end_date(period_key, frequency):
    """The last calendar day of the period named by period_key."""
    if frequency == "QUARTERLY":
        match = _QUARTERLY_RE.match(period_key)
        year = int(match.group(1))
        month = int(match.group(2)) * 3
    else:
        match = _MONTHLY_RE.match(period_key)
        year = int(match.group(1))
        month = int(match.group(2))
    last_day = calendar.monthrange(year, month)[1]
    return datetime(year, month, last_day, tzinfo=timezone.utc)


def due_date(period_key, program):
    """Period end plus filing_deadline_days calendar days, at 23:59:59.999Z."""
    end = period_end_date(period_key, program.get("filing_frequency"))
    day = end + timedelta(days=int(program.get("filing_deadline_days") or 0))
    return day.replace(hour=23, minute=59, second=59, microsecond=999000)


def sweepable_lines(batch):
    """Cross-aggregate sweep: OPEN lines for this state, period and brokerage."""
    rows = []
    for line in store.db.tax_filing_lines.values():
        if line.get("status") != "OPEN":
            continue
        if line.get("state_program_id") != batch.get("state_program_id"):
            continue
        if line.get("period_key") != batch.get("period_key"):
            continue
        policy = store.db.get("policies", line.get("policy_id"))
        if policy is None or policy.get("broker_id") != batch.get("broker_id"):
            continue
        rows.append(line)
    return store.sort_records(rows)


def penalty_for(total_tax_cents, late):
    if not late:
        return 0
    base = max(int(total_tax_cents), 0)
    return max(round_half_up(dec(base) * LATE_PENALTY_RATE), LATE_PENALTY_MIN_CENTS)


def totals(lines):
    total_tax = sum(int(line.get("tax_cents") or 0) for line in lines)
    total_fee = sum(int(line.get("stamping_fee_cents") or 0) for line in lines)
    return len(lines), total_tax, total_fee
