"""In-memory data store. Starts empty on every boot."""
import uuid
from datetime import datetime, timezone
from threading import RLock


# --- store ---
members = {}                  # id -> dict
skill_offers = {}
skill_requests = {}
exchanges = {}
ledger_entries = {}           # id -> dict; NOTE: no version/updated_at
redemptions = {}
verification_credentials = {}
group_projects = {}
project_shifts = {}
shift_assignments = {}
disputes = {}
impact_reports = {}

# Monotonic per-request event counter — provides deterministic ordering of
# LedgerEntry.created_at within the same wall-clock millisecond.
_event_seq = 0

# Logical clock. Default per §2.5 = 2026-03-01T00:00:00Z.
_clock_iso = "2026-03-01T00:00:00.000Z"

_lock = RLock()


def reset():
    """Reset everything back to boot state — never called at runtime; provided
    for test hooks / debugging. The Flask process starts with these empties."""
    global _event_seq, _clock_iso
    with _lock:
        members.clear()
        skill_offers.clear()
        skill_requests.clear()
        exchanges.clear()
        ledger_entries.clear()
        redemptions.clear()
        verification_credentials.clear()
        group_projects.clear()
        project_shifts.clear()
        shift_assignments.clear()
        disputes.clear()
        impact_reports.clear()
        _event_seq = 0
        _clock_iso = "2026-03-01T00:00:00.000Z"


def new_id() -> str:
    return str(uuid.uuid4())


def _now_wall_iso() -> str:
    """Wall-clock ISO8601 UTC with three fractional digits — used for
    resource-level created_at / updated_at (§2.4)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def next_seq() -> int:
    global _event_seq
    with _lock:
        _event_seq += 1
        return _event_seq


def stamp_new(entity: dict) -> dict:
    """Set common_fields on a newly-created entity: id/created_at/updated_at/version."""
    ts = _now_wall_iso()
    entity.setdefault("id", new_id())
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def touch(entity: dict) -> dict:
    """Bump version + updated_at on a mutation."""
    entity["updated_at"] = _now_wall_iso()
    entity["version"] = entity.get("version", 1) + 1
    return entity


# --- Logical clock ---

def get_clock_iso() -> str:
    return _clock_iso


def set_clock_iso(iso: str):
    global _clock_iso
    _clock_iso = iso


def parse_iso(iso: str) -> datetime:
    """Parse ISO 8601 UTC. Accepts 'Z' or explicit +00:00. Returns aware datetime."""
    if not isinstance(iso, str) or not iso:
        raise ValueError("iso must be non-empty string")
    s = iso.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_dt() -> datetime:
    return parse_iso(_clock_iso)
