"""In-memory data store, logical clock, and timestamp/ID helpers.

The store is rebuilt empty on every process boot — no seeding anywhere.
"""
import uuid
from datetime import datetime, timezone

# --- entity tables (all start empty) ---
STORE = {
    "borrowers": {},
    "loans": {},
    "cases": {},
    "plans": {},
    "proposals": {},
    "collateral": {},
    "appraisals": {},
    "impairments": {},
    "referrals": {},
    "charge_offs": {},
    "recoveries": {},
    "exit_decisions": {},
}

_seq = [0]  # global insertion sequence, tiebreaks created_at ordering

# --- logical clock (PRD §2.5): startup default exactly 2026-08-01T00:00:00Z ---
CLOCK = {"current": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def logical_now():
    return CLOCK["current"]


def set_clock(dt):
    CLOCK["current"] = dt


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq[0] += 1
    return _seq[0]


def now_iso():
    """Wall-clock UTC timestamp with three fractional digits (PRD §2.2/§2.4)."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def fmt_clock(dt):
    """Logical-clock rendering: whole seconds unless fractional part is set."""
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO-8601 string into an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stamp(entity):
    """Set common system fields on a freshly created primary resource."""
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def stamp_ledger(entity):
    """Ledger-style resources: id + created_at only, no updated_at/version."""
    entity["created_at"] = now_iso()
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    """Every mutation refreshes updated_at and bumps version (PRD §2.4)."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()
