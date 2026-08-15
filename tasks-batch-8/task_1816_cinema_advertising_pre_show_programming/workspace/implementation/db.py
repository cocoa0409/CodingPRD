"""In-memory data store. Everything lives in module-level dicts; restarting the
process (start.sh re-invocation) wipes all state. No disk persistence anywhere.
"""
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5). Startup default is exactly 2026-08-01T00:00:00Z.
# The server never falls back to wall-clock time for logical-clock purposes.
# ---------------------------------------------------------------------------
CLOCK_DEFAULT_STR = "2026-08-01T00:00:00Z"
clock_dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
clock_str = CLOCK_DEFAULT_STR


def set_clock(dt, raw):
    global clock_dt, clock_str
    clock_dt = dt
    clock_str = raw


def get_clock():
    return clock_dt, clock_str


# ---------------------------------------------------------------------------
# Entity stores: id -> record dict. Records carry internal keys prefixed with
# "_" (e.g. _seq, _starts_dt) that are never serialized.
# ---------------------------------------------------------------------------
theaters = {}
screens = {}
features = {}
showtimes = {}
reels = {}
slots = {}
playlogs = {}
advertisers = {}
campaigns = {}
attendance_reports = {}
invoices = {}
make_goods = {}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock timestamp for created_at/updated_at/meta: ISO 8601 UTC with
    exactly three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def new_record():
    """Common fields for every resource (PRD 2.4)."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    """PRD 2.4/2.10: every mutation refreshes updated_at and bumps version."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1
