"""In-memory data store + logical clock. Fresh per process boot."""

from datetime import datetime, timezone

# Logical clock: fixed at startup, never wall-clock.
_DEFAULT_NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_now = _DEFAULT_NOW


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt


# Insertion sequence for deterministic ordering under a frozen logical clock.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


# Entity stores, keyed by id. All start empty; no seeding.
events = {}
agreements = {}
units = {}
participants = {}
equipment = {}
inspections = {}
areas = {}
allocations = {}
slots = {}
orders = {}
passes = {}
vendors = {}
alerts = {}
