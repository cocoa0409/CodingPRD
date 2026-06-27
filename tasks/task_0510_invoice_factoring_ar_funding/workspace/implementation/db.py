"""In-memory data store + logical clock.

All state lives in module-level dicts keyed by id. The store starts EMPTY on
every boot — no seeding, no preloading. The test harness relaunches the server
before every test, which wipes all of this.
"""

import uuid
from datetime import datetime, timezone

# Logical clock startup default (§1.5 / PRD §2.4).
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Entity collections (id -> record dict)
# ---------------------------------------------------------------------------
programs = {}
clients = {}
debtors = {}
relationships = {}
invoices = {}
purchase_batches = {}
verifications = {}
collection_postings = {}
adjustments = {}
buybacks = {}
settlements = {}
ledger_entries = {}

# Monotonic creation sequence to provide a stable secondary sort key when two
# records share an identical created_at timestamp.
_seq = 0

# Logical clock, stored as a timezone-aware UTC datetime.
_clock = None


def reset():
    """Clear all state. Not called at startup in production; useful for tests."""
    global _seq, _clock
    for coll in (programs, clients, debtors, relationships, invoices,
                 purchase_batches, verifications, collection_postings,
                 adjustments, buybacks, settlements, ledger_entries):
        coll.clear()
    _seq = 0
    _clock = None


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq
    _seq += 1
    return _seq


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def _parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    """Current logical clock as a tz-aware UTC datetime."""
    global _clock
    if _clock is None:
        _clock = _parse_iso(CLOCK_DEFAULT_ISO)
    return _clock


def set_clock(iso_str):
    global _clock
    _clock = _parse_iso(iso_str)
    return _clock


def parse_iso(s):
    return _parse_iso(s)
