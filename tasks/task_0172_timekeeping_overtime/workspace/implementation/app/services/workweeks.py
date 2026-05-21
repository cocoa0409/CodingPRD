"""Workweek service — upsert, anchor checks, pay-engine orchestration."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..calculations import compute_workweek_pay
from ..clock import format_iso_ms, parse_iso_utc
from ..errors import err_workweek_bad_anchor
from ..store import Store, new_id


def week_start_for(dt: datetime) -> datetime:
    """Compute the Sunday-00:00:00.000-UTC anchor for the week containing `dt`.

    Python's `weekday()` returns 0=Mon..6=Sun; we want Sunday-of-week-anchor.
    """
    dt = dt.astimezone(timezone.utc)
    # day_of_week: 0=Mon..6=Sun
    days_since_sunday = (dt.weekday() + 1) % 7  # Sun→0, Mon→1, ..., Sat→6
    sunday = dt - timedelta(days=days_since_sunday)
    sunday = sunday.replace(hour=0, minute=0, second=0, microsecond=0)
    return sunday


def is_sunday_midnight_utc(dt: datetime) -> bool:
    dt = dt.astimezone(timezone.utc)
    return (
        (dt.weekday() + 1) % 7 == 0
        and dt.hour == 0
        and dt.minute == 0
        and dt.second == 0
        and dt.microsecond == 0
    )


def upsert_workweek_for_shift(store: Store, employee_id: str, anchor_dt: datetime) -> Dict[str, Any]:
    """Find-or-create the Workweek for (employee_id, week_start_of(anchor_dt)).

    Returns the workweek row dict. Caller must hold store.lock.
    """
    week_start_dt = week_start_for(anchor_dt)
    week_start_iso = format_iso_ms(week_start_dt)
    key = (employee_id, week_start_iso)
    wid = store.workweek_index.get(key)
    if wid is not None and wid in store.workweeks:
        return store.workweeks[wid]
    # Create
    now_iso = format_iso_ms(anchor_dt)  # creation timestamp uses the trigger event time
    wid = new_id()
    row = {
        "id": wid,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
        "_seq": store.next_seq(),
        "employee_id": employee_id,
        "week_start": week_start_iso,
        "total_hours": 0.0,
        "regular_hours": 0.0,
        "overtime_hours": 0.0,
        "double_time_hours": 0.0,
        "gross_pay_cents": 0,
        "payroll_status": "OPEN",
    }
    store.workweeks[wid] = row
    store.workweek_index[key] = wid
    return row


def validate_week_start_anchor(iso: str) -> datetime:
    """Parse and verify Sunday-00:00:00.000Z. Raises ERR_WORKWEEK_BAD_ANCHOR."""
    try:
        dt = parse_iso_utc(iso)
    except Exception:
        raise err_workweek_bad_anchor("week_start is not a valid ISO 8601 timestamp.")
    if not is_sunday_midnight_utc(dt):
        raise err_workweek_bad_anchor("week_start must be Sunday 00:00:00.000 UTC.")
    return dt


def recompute_workweek(store: Store, workweek: Dict[str, Any], now_iso: str) -> None:
    """Recompute totals on a workweek by re-running the pay engine."""
    employee = store.employees.get(workweek["employee_id"])
    if not employee:
        return
    # Gather FINALIZED shifts in this workweek
    finalized: List[Dict[str, Any]] = []
    for s in store.shifts.values():
        if s.get("workweek_id") == workweek["id"] and s.get("state") == "FINALIZED":
            finalized.append(s)
    shift_meal_breaks: Dict[str, Optional[Dict[str, Any]]] = {}
    detention_events: List[Dict[str, Any]] = []
    tip_decls: List[Dict[str, Any]] = []
    for s in finalized:
        mb_id = store.shift_meal_break_index.get(s["id"])
        shift_meal_breaks[s["id"]] = store.meal_breaks.get(mb_id) if mb_id else None
        de_id = store.shift_detention_index.get(s["id"])
        if de_id:
            de = store.detention_events.get(de_id)
            if de:
                detention_events.append(de)
        td_id = store.shift_tip_decl_index.get(s["id"])
        if td_id:
            td = store.tip_declarations.get(td_id)
            if td:
                tip_decls.append(td)

    result = compute_workweek_pay(
        employee=employee,
        finalized_shifts=finalized,
        shift_meal_breaks=shift_meal_breaks,
        detention_events_for_shifts=detention_events,
        tip_declarations_for_shifts=tip_decls,
    )
    workweek["total_hours"] = result["total_hours"]
    workweek["regular_hours"] = result["regular_hours"]
    workweek["overtime_hours"] = result["overtime_hours"]
    workweek["double_time_hours"] = result["double_time_hours"]
    workweek["gross_pay_cents"] = result["gross_pay_cents"]
    workweek["updated_at"] = now_iso
    workweek["version"] = int(workweek.get("version", 1)) + 1


def all_sibling_shifts_finalized(store: Store, workweek_id: str) -> bool:
    """Return True iff every Shift bound to this workweek is FINALIZED.

    Shifts in VOIDED/DISPUTED are excluded from "completion" — we want every
    *non-terminal-VOIDED* shift to be FINALIZED. If there are no eligible
    shifts at all, we treat that as "not yet posted-worthy" — but the spec
    triggers POSTED on finalize, so at least one FINALIZED shift exists when
    this is called.
    """
    found_eligible = False
    for s in store.shifts.values():
        if s.get("workweek_id") != workweek_id:
            continue
        st = s.get("state")
        if st == "VOIDED":
            continue
        found_eligible = True
        if st != "FINALIZED":
            return False
    return found_eligible
