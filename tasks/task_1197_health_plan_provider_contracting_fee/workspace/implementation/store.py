"""In-memory data store, logical clock, id/timestamp helpers, audit trail.

Storage is purely in-memory module state (dicts keyed by id). Nothing is
persisted to disk and nothing is seeded at startup: every collection starts
empty on every boot.
"""

import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Collections (entity id -> entity dict)
# ---------------------------------------------------------------------------
providers = {}
networks = {}
benchmarks = {}
parity_rules = {}
contracts = {}
versions = {}
entries = {}
carve_outs = {}
batches = {}
claims = {}
paid_claims = {}
runs = {}
adjustments = {}
notices = {}
cases = {}
audit_events = {}


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Wall-clock timestamps (created_at / updated_at) — strictly monotonic so
# created_at tie-breaks are deterministic.
# ---------------------------------------------------------------------------
_last_ts = None


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    global _last_ts
    now = datetime.now(timezone.utc)
    now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
    if _last_ts is not None and now <= _last_ts:
        now = _last_ts + timedelta(milliseconds=1)
    _last_ts = now
    return _fmt(now)


# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.6). Defaults to 2026-05-01T00:00:00Z; once set
# via POST /_clock/set_current_utc it never falls back to wall-clock time.
# ---------------------------------------------------------------------------
class LogicalClock:
    def __init__(self):
        self.current = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    def set(self, dt):
        self.current = dt

    def iso(self):
        return _fmt(self.current)

    def today(self):
        return self.current.date()


clock = LogicalClock()


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def stamp_new(obj):
    """Attach system-managed common fields to a freshly created resource."""
    ts = now_iso()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def touch(obj):
    """Register a mutation: refresh updated_at and increment version."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 0) + 1


def add_audit(contract_id, event_type, actor_role, actor_id, detail):
    """Append an immutable AuditEvent to a contract's log.

    occurred_at is stamped from the logical clock, created_at from the
    (monotonic) wall clock. Audit events carry no updated_at / version.
    """
    event = {
        "id": new_id(),
        "contract_id": contract_id,
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "detail": detail,
        "occurred_at": clock.iso(),
        "created_at": now_iso(),
    }
    audit_events[event["id"]] = event
    return event
