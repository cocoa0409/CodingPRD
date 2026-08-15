"""In-memory data store and logical clock. The store starts empty on every
boot; no entity is seeded at startup (PRD: every resource is created through
the declared API surface)."""
import uuid
from datetime import datetime, timezone

DB = {
    "producers": {},
    "carriers": {},
    "products": {},
    "schedules": {},
    "policies": {},
    "invoices": {},
    "statements": {},
    "entries": {},
    "chargebacks": {},
    "disclosures": {},
    "payouts": {},
    "taxforms": {},
}

_SEQ = [0]

# Logical clock (PRD section 2.4): startup default is exactly
# 2026-08-01T00:00:00Z and never falls back to wall-clock time.
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    """Monotonic creation counter; creation order == created_at order."""
    _SEQ[0] += 1
    return _SEQ[0]


def now_dt():
    return CLOCK["now"]


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_dt(CLOCK["now"])


def today():
    return CLOCK["now"].date()
