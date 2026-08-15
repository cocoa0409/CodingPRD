"""In-memory data store. Starts completely empty on every boot — no seeding.

All stores are plain dicts keyed by resource id (UUID string). Every record
carries an internal `_seq` insertion counter (never serialized) used as the
final deterministic tie-break for ordering when logical-clock timestamps tie.
"""
from datetime import datetime, timezone

customers = {}
materials = {}
package_specs = {}
cut_programs = {}
toolings = {}
drop_tests = {}
production_orders = {}
inventory_programs = {}
release_orders = {}
scrap_batches = {}

_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4). Server startup default is exactly
# 2026-08-01T00:00:00Z; before any set call the clock reads this default and
# never falls back to wall-clock time.
# ---------------------------------------------------------------------------
_DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"


def _parse(value):
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_clock_raw = _DEFAULT_CLOCK_RAW  # echoed verbatim by POST /_clock/set_current_utc
_clock_dt = _parse(_DEFAULT_CLOCK_RAW)  # parsed form used for all stamping/comparison


def clock_raw():
    return _clock_raw


def now_dt():
    return _clock_dt


def set_clock(raw):
    global _clock_raw, _clock_dt
    _clock_dt = _parse(raw)
    _clock_raw = raw
