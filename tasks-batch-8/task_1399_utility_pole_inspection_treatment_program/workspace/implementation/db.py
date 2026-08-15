import threading
import uuid
from datetime import datetime, timezone

UTC = timezone.utc

lock = threading.RLock()

# In-memory stores — empty on every boot; no seeding.
budgets = {}
cycles = {}
poles = {}
tasks = {}
treatments = {}
claims = {}
crews = {}
replacements = {}
audits = {}
snapshots = {}

# Logical clock: server startup default is exactly 2026-08-01T00:00:00Z and
# never falls back to wall-clock time.
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
_seq = 0


def clock_now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_record(with_version=True):
    n = clock_now()
    rec = {"id": str(uuid.uuid4()), "created_at": n, "_seq": next_seq()}
    if with_version:
        rec["updated_at"] = n
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutated resource."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = clock_now()
