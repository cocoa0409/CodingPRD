"""Ops checkpoint and logical-clock routes."""
from datetime import datetime, time, timedelta, timezone

from flask import Blueprint

from domain import (
    by_seq,
    cancel_planned_box,
    copy_backs_box_slot,
    global_sweep,
    promote_for_copy,
    release_reserved_copy,
    touch,
)
from envelope import ok_object
from serializers import paused_days_used  # noqa: F401  (documented helper)
from store import DB, clock, clock_date, set_clock
from timestamps import iso3, parse_datetime
from validate import F, authenticate, authorize, body, finalize_shape, parse_fields

bp = Blueprint("ops", __name__)


def _expire_stale_holds(promoted):
    expired = 0
    for e in by_seq(DB.wishlist_entries.values()):
        if e["status"] != "HELD":
            continue
        if e["hold_expires_at"] is None or e["hold_expires_at"] > clock():
            continue
        held_copy_id = e["held_copy_id"]
        e["status"] = "EXPIRED"
        e["held_copy_id"] = None
        touch(e)
        expired += 1
        copy = DB.copies.get(held_copy_id) if held_copy_id else None
        if (
            copy is not None
            and copy["status"] == "RESERVED"
            and copy["reserved_member_id"] == e["member_id"]
            and not copy_backs_box_slot(copy["id"])
        ):
            winner = release_reserved_copy(copy)
            if winner is not None:
                promoted.append(winner)
    return expired


def _activate_due_pauses(promoted):
    """Activate scheduled windows whose start has arrived.  Returns count."""
    activated = 0
    today = clock_date()
    for s in by_seq(DB.subscriptions.values()):
        if s["status"] != "ACTIVE":
            continue
        due = [
            w for w in s["pause_windows"]
            if not w["closed"] and w["start_date"] <= today
        ]
        if not due:
            continue
        due.sort(key=lambda w: w["start_date"])
        w = due[0]
        s["status"] = "PAUSED"
        s["current_pause_end"] = datetime.combine(
            w["end_date"], time.min, tzinfo=timezone.utc)
        touch(s)
        activated += 1
        for b in by_seq([b for b in DB.boxes.values()
                         if b["subscription_id"] == s["id"]]):
            if b["status"] == "PLANNED":
                cancel_planned_box(b, released=promoted)
    return activated


def _auto_resume():
    """Resume PAUSED subscriptions whose pause end the clock has reached."""
    resumed = 0
    now = clock()
    today = clock_date()
    for s in by_seq(DB.subscriptions.values()):
        if s["status"] != "PAUSED":
            continue
        if s["current_pause_end"] is None or now < s["current_pause_end"]:
            continue
        for w in s["pause_windows"]:
            if not w["closed"] and w["start_date"] <= today:
                consumed = max(0, (min(today, w["end_date"]) - w["start_date"]).days)
                w["consumed_days"] = consumed
                w["closed"] = True
                s["next_cycle_due_at"] = s["next_cycle_due_at"] + timedelta(days=consumed)
                break
        s["current_pause_end"] = None
        s["status"] = "ACTIVE"
        touch(s)
        resumed += 1
    return resumed


@bp.post("/toy-rental/ops/allocation-runs")
def allocation_run():
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    data = body()
    shape = parse_fields(data, [])
    finalize_shape(shape)
    promoted = []
    # 1. Global allocation sweep.
    promoted.extend(global_sweep())
    # 2. Expire stale holds (releasing + re-sweeping each copy).
    expired = _expire_stale_holds(promoted)
    # 3+4. Activate due pause windows, auto-resume finished ones; iterate so
    # that a fully-elapsed window hands off to a chained due window.
    resumed = 0
    for _ in range(100):
        activated = _activate_due_pauses(promoted)
        r = _auto_resume()
        resumed += r
        if activated == 0 and r == 0:
            break
    return ok_object({
        "promoted_count": len(promoted),
        "expired_count": expired,
        "resumed_count": resumed,
        "promoted_entry_ids": [e["id"] for e in promoted],
    })


@bp.post("/toy-rental/_clock/set_current_utc")
def set_current_utc():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    data = body()
    shape = parse_fields(data, [F("to_iso8601", True, "datetime")])
    finalize_shape(shape)
    raw = shape.values["to_iso8601"]
    dt = parse_datetime(raw)
    set_clock(dt, raw)
    return ok_object({"current_utc": DB.clock_verbatim})
