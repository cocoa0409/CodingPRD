"""In-memory data store + logical clock. No persistence, no seeding."""
import threading
from datetime import datetime, timezone

lock = threading.RLock()

# Entity tables: dicts keyed by id. All start empty — every entity is
# constructed via API calls.
nonprofits = {}
bylaws = {}
amendments = {}
members = {}
terms = {}
committees = {}
appointments = {}
meetings = {}
motions = {}
votes = {}
disclosures = {}
evaluations = {}
succession_plans = {}
filings = {}
registrations = {}
policies = {}

_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


# Logical clock: starts at exactly 2026-08-01T00:00:00Z and never falls back
# to wall-clock time.
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt
