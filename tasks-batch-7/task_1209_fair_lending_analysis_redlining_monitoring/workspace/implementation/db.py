"""In-memory data store + server logical clock.

Storage is process-local dicts keyed by id. The store starts empty on every
boot; all state is constructed via the API. No disk persistence of any kind.
"""
import uuid
from datetime import datetime, timezone

STORES = {
    "markets": {},
    "branches": {},
    "officers": {},
    "applications": {},
    "exceptions": {},
    "overrides": {},
    "benchmarks": {},
    "runs": {},
    "findings": {},
    "reviews": {},
    "caps": {},
    "payments": {},
    "self_tests": {},
    "reports": {},
}

# Logical clock: starts at exactly 2026-05-01T00:00:00Z and only advances via
# POST /_clock/set_current_utc. Never falls back to wall-clock time.
_clock = datetime(2026, 5, 1, 0, 0, 0)
_seq = 0
_cycle_index = 0


def parse_iso(s):
    """Parse an ISO 8601 datetime string into a naive UTC datetime."""
    txt = str(s).strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def now_dt():
    return _clock


def now_iso():
    """Logical clock as ISO 8601 UTC with exactly three fractional digits."""
    return _clock.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (_clock.microsecond // 1000)


def set_clock(s):
    global _clock
    _clock = parse_iso(s)
    return now_iso()


def next_seq():
    global _seq
    _seq += 1
    return _seq


def next_cycle():
    global _cycle_index
    _cycle_index += 1
    return _cycle_index


def new_record(fields=None):
    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    if fields:
        rec.update(fields)
    return rec


def touch(rec):
    """Record a mutation: version += 1 and updated_at restamped."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()


def public(rec):
    """Strip internal keys (prefixed with _) before serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
