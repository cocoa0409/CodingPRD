"""In-memory data store. The store starts empty on every boot; no seeding."""
import itertools
import uuid
from datetime import datetime, timezone

DB = {
    "plans": {},
    "participants": {},
    "enrollments": {},
    "dividend_events": {},
    "purchase_windows": {},
    "purchase_orders": {},
    "ledger_entries": {},
    "tax_lots": {},
    "fee_assessments": {},
    "notices": {},
    "transfers": {},
    # Internal-only records (never serialized directly): per-enrollment,
    # per-year tax-report inputs recorded at execution time.
    "_dispositions": [],    # {enrollment_id, year, proceeds_cents, basis_cents, gain_cents}
    "_dividend_income": [],  # {enrollment_id, year, amount_cents}
}

# The logical clock (PRD section 2.4). Startup default is exactly
# 2026-08-01T00:00:00Z and it never falls back to wall-clock time.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
CLOCK = {"current": DEFAULT_CLOCK}

_seq = itertools.count(1)


def next_seq():
    """Monotonic insertion sequence used as a created_at tiebreak."""
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp (3 fractional digits) — response meta only."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def clock_dt():
    """Current logical-clock instant as an aware datetime."""
    from util import parse_dt

    return parse_dt(CLOCK["current"])


def logical_now_iso():
    """Logical-clock instant, ISO 8601 UTC with three fractional digits."""
    n = clock_dt().astimezone(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
