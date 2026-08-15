"""In-memory data store. Starts completely empty on every boot — no seeding."""
from datetime import datetime, timezone

banks = {}
customers = {}
agreements = {}
sites = {}
formats = {}
schedules = {}
batches = {}
items = {}
exceptions = {}
image_requests = {}
cycles = {}
line_items = {}
incidents = {}
credits = {}

# Logical clock: starts at 2026-08-01T00:00:00Z, never falls back to wall clock.
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]
