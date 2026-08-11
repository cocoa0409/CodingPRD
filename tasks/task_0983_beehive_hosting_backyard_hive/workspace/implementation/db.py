"""In-memory data store + server logical clock.

The store starts empty on every boot — no seeding of any kind. All entities
are constructed via the declared API surface by the tests.
"""
import threading
from datetime import datetime, timezone

lock = threading.RLock()

# Logical clock: default exactly 2026-05-01T00:00:00Z; never falls back to wall time.
_clock_state = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return _clock_state["now"]


def set_now(dt):
    _clock_state["now"] = dt


_seq_state = {"n": 0}


def next_seq():
    _seq_state["n"] += 1
    return _seq_state["n"]


seasons = {}
hosts = {}
sites = {}
agreements = {}
hives = {}
inspections = {}
treatments = {}
harvests = {}
allocations = {}
swarm_events = {}
removal_jobs = {}
subscriptions = {}
invoices = {}
enrollments = {}
incidents = {}
