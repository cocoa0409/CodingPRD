"""Logical clock advance + scheduled state sweep (PRD §2.5)."""

from datetime import timedelta

import db
from services import core


def sweep(new_now) -> None:
    """Run the time-driven transitions after the clock is set to new_now."""
    # Reps: ACTIVE with credential_expires_at <= now -> EXPIRED
    for rep in db.reps.values():
        if rep["credential_status"] == "ACTIVE":
            exp = db.parse_dt(rep.get("credential_expires_at"))
            if exp is not None and exp <= new_now:
                rep["credential_status"] = "EXPIRED"
                core.touch(rep)

    # Access passes: APPROVED with now >= window_end_at -> EXPIRED;
    # ADMITTED with now >= window_end_at -> EXITED
    for p in db.access_passes.values():
        end = db.parse_dt(p.get("window_end_at"))
        if end is None:
            continue
        if new_now >= end:
            if p["status"] == "APPROVED":
                p["status"] = "EXPIRED"
                core.touch(p)
            elif p["status"] == "ADMITTED":
                p["status"] = "EXITED"
                core.touch(p)

    # Sterilization turns: STERILIZING whose cycle has completed -> COOLDOWN,
    # stamping cycle_completed_at = cycle_started_at + unit.cycle_minutes.
    affected_requests = set()
    for turn in db.turns.values():
        if turn["status"] != "STERILIZING":
            continue
        unit = db.sterilizer_units.get(turn["sterilizer_unit_id"])
        if unit is None:
            continue
        started = db.parse_dt(turn["cycle_started_at"])
        if started is None:
            continue
        completed = started + timedelta(minutes=unit["cycle_minutes"])
        if completed <= new_now:
            turn["status"] = "COOLDOWN"
            turn["cycle_completed_at"] = db.fmt_ts(completed)
            core.touch(turn)
            tray = db.trays.get(turn["tray_id"])
            if tray is not None:
                core.recompute_tray_projection(tray)
                core.touch(tray)
                affected_requests.add(tray["request_id"])

    for request_id in affected_requests:
        request = db.requests.get(request_id)
        if request is not None:
            core.recompute_readiness(request)
