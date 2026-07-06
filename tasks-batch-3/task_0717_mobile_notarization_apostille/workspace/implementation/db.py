"""In-memory data store and logical clock.

Store starts EMPTY on every boot. No seeding, no preloaded entities.
"""
import threading
import uuid
from datetime import datetime, timezone

LOCK = threading.RLock()

# One dict per entity type, keyed by id.
fee_schedules = {}
accounts = {}
notaries = {}
signers = {}
requests = {}
documents = {}
assignments = {}
ron_sessions = {}
id_verifications = {}
journal_entries = {}
apostille_orders = {}
loan_packages = {}
retention_records = {}

# Logical clock — starts at exactly this default, never falls back to wall time.
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"
_clock = {"value": DEFAULT_CLOCK}

_seq = {"n": 0}


def reset():
    for d in (fee_schedules, accounts, notaries, signers, requests, documents,
              assignments, ron_sessions, id_verifications, journal_entries,
              apostille_orders, loan_packages, retention_records):
        d.clear()
    _clock["value"] = DEFAULT_CLOCK
    _seq["n"] = 0


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def now_iso():
    """Wall-clock timestamp for created_at/updated_at (server-minted records)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def get_clock():
    return _clock["value"]


def set_clock(iso):
    _clock["value"] = iso


def clock_dt():
    return parse_iso(_clock["value"])


def parse_iso(s):
    """Parse an ISO 8601 instant into an aware datetime (UTC)."""
    if s is None:
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
