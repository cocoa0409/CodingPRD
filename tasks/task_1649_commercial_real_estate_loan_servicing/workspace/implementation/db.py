"""In-memory data store. Store starts empty on every boot."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def iso_now(clock):
    """Format the logical clock time as ISO 8601 UTC with 3 fractional digits."""
    return fmt_ts(clock)


def fmt_ts(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Logical servicing clock (datetime, tz-aware UTC). Startup default 2026-08-01T00:00:00Z.
CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def reset_clock():
    global CLOCK
    CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return CLOCK


def set_clock(dt):
    global CLOCK
    CLOCK = dt


# Entity stores: id -> dict
borrowers = {}
loans = {}
properties = {}
financial_statements = {}
covenant_assessments = {}
reserve_accounts = {}
disbursement_requests = {}
leases = {}
estoppels = {}
inspectors = {}
inspections = {}
insurance_policies = {}
assumption_requests = {}
extension_options = {}
watchlist_entries = {}
