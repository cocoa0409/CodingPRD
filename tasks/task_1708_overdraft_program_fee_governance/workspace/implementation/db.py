"""In-memory data store and logical clock.

The store starts completely empty on every boot — no seeding of any kind.
Time is logical: startup default is exactly 2026-08-01T00:00:00Z and the
clock is only moved by POST /v1/_clock/set_current_utc.
"""
import uuid
from datetime import datetime, timezone

store = {
    "programs": {},
    "accounts": {},
    "elections": {},
    "transactions": {},
    "batches": {},
    "fees": {},
    "waiver_requests": {},
    "waiver_items": {},
    "notices": {},
    "offers": {},
    "reports": {},
}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"
_clock = {"dt": datetime(2026, 8, 1, tzinfo=timezone.utc), "raw": DEFAULT_CLOCK_RAW}


def clock_dt():
    return _clock["dt"]


def set_clock(dt):
    _clock["dt"] = dt
    _clock["raw"] = fmt_ts(dt)


def clock_raw():
    return _clock["raw"]


def clock_date_str():
    return _clock["dt"].date().isoformat()


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.5)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def now_iso():
    return fmt_ts(_clock["dt"])


def parse_ts(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def new_id():
    return str(uuid.uuid4())


def new_entity(fields):
    """Base system fields per PRD §2.5: id, created_at, updated_at, version."""
    e = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "seq": next_seq(),
    }
    e.update(fields)
    return e


def new_item(fields):
    """WaiverRequestItem: immutable, carries only id and created_at (PRD §2.5)."""
    e = {"id": new_id(), "created_at": now_iso(), "seq": next_seq()}
    e.update(fields)
    return e


def touch(e):
    e["updated_at"] = now_iso()
    e["version"] += 1
