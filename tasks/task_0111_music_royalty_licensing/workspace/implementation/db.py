"""In-memory data store.

All state lives in module-level dicts keyed by id. The store starts EMPTY on
every boot — no seeding, no preload. Tests build every entity via the API.

Per PRD §2.4: id is a server-minted UUID with no type prefix; created_at /
updated_at are ISO 8601 UTC with three fractional digits; version is an integer
starting at its initial value and incrementing by one on every mutation.
"""
import threading
import uuid
from datetime import datetime, timezone

# One dict per entity collection.
rightsholders = {}
works = {}
composition_shares = {}
recordings = {}
recording_shares = {}
rights_windows = {}
usage_events = {}
sync_licenses = {}
advances = {}
statements = {}
ledger_entries = {}
payouts = {}

# Monotonic insertion counter to provide a stable creation order (used for
# default sort and for advance chronological recoupment tie-breaking).
_seq_lock = threading.Lock()
_seq = 0

# Logical server clock (PRD §3.9). None means "uninitialized"; tests pin it.
_clock = {"now": None}


def reset():
    """Wipe all state. Module import already starts empty; provided for safety."""
    for d in (rightsholders, works, composition_shares, recordings,
              recording_shares, rights_windows, usage_events, sync_licenses,
              advances, statements, ledger_entries, payouts):
        d.clear()
    global _seq
    _seq = 0
    _clock["now"] = None


def next_seq():
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def new_id():
    return str(uuid.uuid4())


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def set_clock(iso_value):
    _clock["now"] = iso_value


def get_clock():
    return _clock["now"]
