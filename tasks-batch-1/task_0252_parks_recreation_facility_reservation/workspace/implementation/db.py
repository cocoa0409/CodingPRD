"""In-memory data store. Starts empty on every boot — no seeding.

Each primary resource carries system fields id (UUID, no prefix), created_at,
updated_at (ISO 8601 UTC, 3 frac digits), and version (int starting at 1,
incremented on every mutation) per PRD §2.4.
"""
import uuid
from datetime import timezone

from clock import now as _clock_now


class Store:
    def __init__(self):
        self.patrons = {}
        self.facilities = {}
        self.insurance_certificates = {}
        self.league_series = {}
        self.permits = {}
        self.payments = {}
        self.refunds = {}
        self.lottery_rounds = {}
        self.lottery_entries = {}
        # Per-round monotonic entry sequence counter.
        self._entry_seq = {}

    def next_entry_seq(self, round_id):
        n = self._entry_seq.get(round_id, 0) + 1
        self._entry_seq[round_id] = n
        return n


db = Store()


def reset():
    global db
    db = Store()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_create(rec):
    """Set id/created_at/updated_at/version on a fresh record."""
    n = _clock_now()
    rec["id"] = new_id()
    rec["created_at"] = n
    rec["updated_at"] = n
    rec["version"] = 1
    return rec


def touch(rec):
    """Mark a record mutated: refresh updated_at, bump version."""
    rec["updated_at"] = _clock_now()
    rec["version"] = rec.get("version", 0) + 1
    return rec
