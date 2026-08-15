"""In-memory data store + logical clock.

Storage is process-local only: plain dicts keyed by id. No disk persistence of
any kind. Every boot of start.sh starts from a completely empty store.
"""
import uuid
from datetime import datetime, timezone

# --- entity stores (keyed by id, insertion-ordered) ---
vendors = {}
bank_accounts = {}
callback_verifications = {}
documents = {}
watchlist_entries = {}
screening_checks = {}
sanctions_cases = {}
invoices = {}
invoice_approvals = {}
approval_matrix_rules = {}
payment_runs = {}
payments = {}
vendor_merge_records = {}
audit_events = {}

# --- logical clock: reads exactly 2026-08-01T00:00:00Z before any set call ---
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt.astimezone(timezone.utc)


def now():
    return _clock


def today():
    return _clock.date()


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def touch(rec):
    """Every mutation of a versioned resource bumps version and refreshes updated_at."""
    rec["version"] += 1
    rec["updated_at"] = fmt_ts(now())


def stamp_new(rec):
    """Attach common system fields to a freshly created primary resource."""
    ts = fmt_ts(now())
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    return rec
