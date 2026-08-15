"""In-memory data store. Starts completely empty on every boot — no seeding."""
import threading
from datetime import datetime, timezone

lock = threading.RLock()

STORE = {
    "issuers": {},
    "accounts": {},
    "positions": {},
    "certificates": {},
    "transfer_requests": {},
    "claims": {},
    "declarations": {},
    "payments": {},
    "legend_requests": {},
    "escheatment_cases": {},
    "inquiries": {},
    "freeze_windows": {},
}

AUDIT_EVENTS = []

_seq = [0]

# Logical clock: startup default exactly 2026-08-01T00:00:00Z, never wall-clock.
_clock = [datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def get_clock():
    return _clock[0]


def set_clock(dt):
    _clock[0] = dt
