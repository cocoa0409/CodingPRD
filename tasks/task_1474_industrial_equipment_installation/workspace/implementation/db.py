"""In-memory data store. Starts empty on every boot; no seeding, no persistence."""
import itertools
from datetime import datetime, timezone

projects = {}
site_surveys = {}
safety_plans = {}
lockout_windows = {}
rigging_plans = {}
lift_permits = {}
alignment_records = {}
checklists = {}
labor_entries = {}
invoices = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


# Logical clock (PRD section 2.5). Startup default exactly 2026-08-01T00:00:00Z;
# the server never falls back to wall-clock time for business logic.
_DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = _DEFAULT_CLOCK


def clock_now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt
