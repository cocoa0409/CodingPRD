"""In-memory data store. All state lives in module-level dicts and the logical
clock. No on-disk persistence of any kind; every boot starts empty."""

import uuid
from datetime import datetime, timezone, timedelta


def _store():
    return {
        "properties": {},
        "leases": {},
        "rent_schedule_lines": {},
        "escalation_steps": {},
        "recovery_pools": {},
        "recovery_billings": {},
        "reconciliations": {},
        "critical_dates": {},
        "compliance_docs": {},
        "amendments": {},
        "tenant_challenges": {},
        "audit_rights": {},
    }


db = _store()

START_CLOCK = "2026-05-01T00:00:00Z"


def _parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _iso_ms(dt):
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def _iso_s(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    def __init__(self):
        self.now = _parse_dt(START_CLOCK)
        # Timestamp seed for created_at / updated_at: starts at the logical
        # clock and strictly advances 1ms per mutation so ordering is stable.
        self.ts = self.now

    def current(self):
        return self.now

    def current_iso(self):
        return _iso_s(self.now)

    def set(self, dt):
        self.now = dt
        if dt > self.ts:
            self.ts = dt

    def next_ts(self):
        self.ts = self.ts + timedelta(milliseconds=1)
        return self.ts

    def next_ts_iso(self):
        return _iso_ms(self.next_ts())


clock = LogicalClock()


def reset_all():
    """Reset the entire store and logical clock (test-driving support)."""
    global db
    for k in db:
        db[k].clear()
    clock.now = _parse_dt(START_CLOCK)
    clock.ts = clock.now


def new_id():
    return str(uuid.uuid4())


def new_resource():
    rid = new_id()
    ts = clock.next_ts_iso()
    return rid, {"id": rid, "created_at": ts, "updated_at": ts, "version": 1}


def touch(res):
    """Refresh updated_at and bump version on any mutation."""
    res["updated_at"] = clock.next_ts_iso()
    res["version"] = res.get("version", 1) + 1
