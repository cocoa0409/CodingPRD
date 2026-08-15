"""In-memory data store and logical clock. Starts empty on every boot."""
import threading
from datetime import datetime, timezone

LOCK = threading.RLock()

# Logical clock: starts at exactly 2026-08-01T00:00:00Z and never reads the
# wall clock.
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


# Entity tables: dicts keyed by id. All start empty — nothing is seeded.
easements = {}
landowners = {}
baseline_reports = {}
monitoring_visits = {}
violations = {}
amendment_requests = {}
use_authorizations = {}
enforcement_actions = {}
succession_notices = {}
appraisals = {}
endowment_funds = {}
endowment_transactions = {}
