"""Lazy time-gated auto-transitions fired on every clock advance (§2.5)."""
import db
from db import parse_iso
from services import balance, ledger


def _shift_end_dt(shift):
    return parse_iso(shift["shift_start_utc"]).timestamp() + shift["duration_minutes"] * 60


def sweep():
    """Fire time-gated transitions in the pinned order from §2.5. Called after
    every clock advance."""
    now = db.clock_dt()
    now_ts = now.timestamp()

    # (a) SkillRequest OPEN -> EXPIRED
    for r in list(db.skill_requests.values()):
        if r["status"] == "OPEN" and parse_iso(r["latest_start_utc"]).timestamp() < now_ts:
            r["status"] = "EXPIRED"
            db.touch(r)

    # (b) ShiftAssignment CONFIRMED past shift end without check-in -> NO_SHOW
    #     ShiftAssignment CHECKED_IN past shift end             -> COMPLETED
    for a in list(db.shift_assignments.values()):
        shift = db.project_shifts.get(a["shift_id"])
        if shift is None:
            continue
        end_ts = _shift_end_dt(shift)
        if now_ts >= end_ts:
            if a["status"] == "CONFIRMED" and a.get("check_in_utc") is None:
                a["status"] = "NO_SHOW"
                db.touch(a)
            elif a["status"] == "CHECKED_IN":
                a["status"] = "COMPLETED"
                db.touch(a)

    # (c) ProjectShift FILLED -> COMPLETED when all assignments terminal and at
    #     least one COMPLETED and clock past shift end. Also post EARNED entries.
    for s in list(db.project_shifts.values()):
        if s["status"] != "FILLED":
            continue
        end_ts = _shift_end_dt(s)
        if now_ts < end_ts:
            continue
        assigns = [a for a in db.shift_assignments.values() if a["shift_id"] == s["id"]]
        if not assigns:
            continue
        if not all(a["status"] in ("COMPLETED", "NO_SHOW", "CANCELLED") for a in assigns):
            continue
        if not any(a["status"] == "COMPLETED" for a in assigns):
            continue
        s["status"] = "COMPLETED"
        db.touch(s)
        # Post EARNED entry for each COMPLETED assignment
        for a in assigns:
            if a["status"] == "COMPLETED":
                ledger.post_entry(
                    member_id=a["member_id"],
                    entry_kind="EARNED",
                    delta_minutes=s["duration_minutes"],
                    memo=f"shift:{s['id']}",
                )
                balance.recompute_member_snapshot(a["member_id"], bump_version=True)

    # (d) Recompute strikes for anyone affected by the NO_SHOW roll.
    #     Just iterate all members (in-memory, cheap).
    for m_id in list(db.members.keys()):
        balance.recompute_member_snapshot(m_id, bump_version=False)

    # (e) Recompute all project aggregate_states (also handles OPEN->IN_PROGRESS
    #     and end-of-window resolution).
    from services import projects as project_svc
    for p in list(db.group_projects.values()):
        project_svc.recompute_aggregate_state(p)
