"""Shared helpers: timestamps, business-day arithmetic, OCC, serialization."""
import uuid
from datetime import datetime, timedelta, date

from db import db


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def logical_clock_dt():
    """Return the logical clock as an aware datetime (UTC)."""
    raw = db.clock
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)


def logical_clock_date():
    return logical_clock_dt().date()


def now_stamp():
    """Logical clock formatted with exactly 3 fractional digits, Z suffix."""
    dt = logical_clock_dt()
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{dt.microsecond // 1000:03d}Z"


def today_stamp():
    return logical_clock_date().isoformat()


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Business-day arithmetic (PRD §2.6)
# ---------------------------------------------------------------------------

def advance_bd(d: date, n: int, holidays: list) -> date:
    """Advance `d` by `n` business days, skipping Sat/Sun and holidays."""
    hset = set(holidays or [])
    for _ in range(n):
        d += timedelta(days=1)
        while d.weekday() >= 5 or d.isoformat() in hset:
            d += timedelta(days=1)
    return d


def add_calendar_months(d: date, months: int) -> date:
    """Add calendar months; clamp day to end of shorter month."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    # Last day of target month
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    last_day = (nxt - timedelta(days=1)).day
    return date(y, m, min(d.day, last_day))


# ---------------------------------------------------------------------------
# OCC helpers
# ---------------------------------------------------------------------------

def bump_version(entity):
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now_stamp()


def stamp_created(entity):
    ts = now_stamp()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["id"] = new_id()
    return entity


# ---------------------------------------------------------------------------
# Common field name lists
# ---------------------------------------------------------------------------

ISSUER_FIELDS = [
    "id", "name", "ticker", "cik", "edgar_ccc", "shares_outstanding",
    "fiscal_year_end_month", "holiday_dates", "next_earnings_filing_date",
    "created_at", "updated_at", "version",
]

PERSON_FIELDS = [
    "id", "issuer_id", "full_name", "person_cik", "is_director", "is_officer",
    "is_ten_pct_owner", "status", "designation_date", "exit_date",
    "late_filing_count", "delinquent_flag", "open_obligation_count",
    "created_at", "updated_at", "version",
]

TRANSACTION_FIELDS = [
    "id", "reporting_person_id", "issuer_id", "filing_id", "plan_id",
    "transaction_date", "transaction_code", "security_type", "shares",
    "price_per_share", "source", "direction", "shares_owned_after",
    "ingested_by_user_id", "status",
    "created_at", "updated_at", "version",
]

FILING_FIELDS = [
    "id", "issuer_id", "reporting_person_id", "form_type", "amends_filing_id",
    "filing_deadline", "is_late", "status", "prepared_by_user_id",
    "submitted_by_user_id", "submitted_at", "accepted_at",
    "accession_number", "rejection_reason",
    "created_at", "updated_at", "version",
]

PLAN_FIELDS = [
    "id", "reporting_person_id", "issuer_id", "plan_name",
    "first_trade_date", "expiration_date", "status", "adoption_date",
    "cooling_off_end_date", "termination_date",
    "created_at", "updated_at", "version",
]

BLACKOUT_FIELDS = [
    "id", "issuer_id", "start_date", "end_date", "reason",
    "created_at", "updated_at", "version",
]

HOLDER_FIELDS = [
    "id", "issuer_id", "holder_name", "holder_cik",
    "shares_beneficially_owned", "exercisable_derivative_shares",
    "current_pct", "fully_diluted_pct", "last_reported_pct",
    "schedule_type", "status",
    "created_at", "updated_at", "version",
]

POSITION_CHANGE_FIELDS = [
    "id", "holder_id", "shares_delta", "derivative_shares_delta",
    "effective_date", "note", "created_at",
]

SWEEP_FIELDS = [
    "id", "issuer_id", "fiscal_year", "fy_start_date", "fy_end_date",
    "status", "run_at", "results",
    "created_at", "updated_at", "version",
]

AUTHORIZATION_FIELDS = [
    "id", "issuer_id", "agent_user_id", "status",
    "created_at", "updated_at", "version",
]


def serialize(entity, fields):
    if entity is None:
        return None
    return {f: entity.get(f) for f in fields}


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def parse_pagination(args):
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset: offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def parse_date(s):
    """Parse YYYY-MM-DD; raise ValueError on malformed."""
    return datetime.strptime(s, "%Y-%m-%d").date()
