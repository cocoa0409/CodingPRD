"""In-memory data store + logical clock.

Storage is module-level Python dicts only. The process boots empty on every
start (per-test-server isolation kills and re-launches the server before each
test); nothing is seeded.
"""
import uuid
from datetime import datetime, timezone

# Logical clock startup default: exactly 2026-08-01T00:00:00Z (never wall clock).
_DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

employees = {}
teams = {}
agents = {}
categories = {}
sla_policies = {}
articles = {}
article_views = {}
tickets = {}
ticket_events = {}
dcrs = {}
fraud_verifications = {}
surveys = {}
staffing_windows = {}
agent_shifts = {}
audit_entries = {}

# Monotonic insertion counter for deterministic tie-breaking (not exposed).
_seq = [0]

# Logical clock state.
_now = [_DEFAULT_NOW]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def now():
    return _now[0]


def set_now(dt):
    _now[0] = dt


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def stamp_created(rec):
    ts = now()
    rec['id'] = new_id()
    rec['created_at'] = ts
    rec['_seq'] = next_seq()
    return rec


def stamp_common(rec):
    """Common fields for versioned resources."""
    stamp_created(rec)
    rec['updated_at'] = rec['created_at']
    rec['version'] = 1
    return rec


def bump(rec):
    """Mutation: version +1 and updated_at refreshed."""
    rec['version'] += 1
    rec['updated_at'] = now()
