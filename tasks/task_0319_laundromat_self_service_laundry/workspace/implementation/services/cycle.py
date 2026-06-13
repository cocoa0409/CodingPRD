"""Machine cycle completion helpers (PRD §2.5, §3.2)."""
from datetime import datetime, timezone

from db import db, touch


def parse_iso(s):
    """Parse an ISO 8601 UTC timestamp (with optional trailing Z) to datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def complete_machine_cycle(machine):
    """RUNNING -> DONE: occupying vend COMPLETED, lifetime_vend_count++.

    Caller must have verified preconditions. Touches machine + vend.
    """
    vend = db.vends.get(machine.get("current_vend_id"))
    if vend is not None and vend["cycle_status"] == "RUNNING":
        vend["cycle_status"] = "COMPLETED"
        touch(vend)
    machine["status"] = "DONE"
    machine["lifetime_vend_count"] += 1
    touch(machine)


def complete_due_cycles(clock_dt):
    """Every RUNNING machine whose cycle_ends_at <= clock is completed."""
    for machine in db.machines.values():
        if machine["status"] != "RUNNING":
            continue
        ends_at = machine.get("cycle_ends_at")
        if ends_at is None:
            continue
        if parse_iso(ends_at) <= clock_dt:
            complete_machine_cycle(machine)
