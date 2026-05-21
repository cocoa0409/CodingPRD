"""Shift service — lifecycle, punch processing, detention/meal recompute."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from ..calculations import (
    compute_detention,
    compute_meal_break_premium,
    compute_tip_credit_for_shift,
    recompute_meal_break_flags,
)
from ..clock import format_iso_ms, parse_iso_utc, get_clock
from ..errors import (
    err_exempt_not_eligible,
    err_invalid_input,
    err_meal_break_duplicate,
    err_not_found,
    err_punch_out_of_order,
    err_punch_outside_window,
    err_shift_already_open,
    err_shift_invalid_state,
)
from ..store import Store, new_id
from .workweeks import upsert_workweek_for_shift


# ──────────────────────────────────────────────────────────────────────────
# Shift creation
# ──────────────────────────────────────────────────────────────────────────

def create_shift(store: Store, payload: Dict[str, Any]) -> Dict[str, Any]:
    employee_id = payload.get("employee_id")
    if not isinstance(employee_id, str) or not employee_id:
        raise err_invalid_input("employee_id is required.")
    if employee_id not in store.employees:
        raise err_not_found("Employee does not exist.")
    employee = store.employees[employee_id]
    if employee.get("classification") == "EXEMPT":
        raise err_exempt_not_eligible(
            "Exempt employees cannot be scheduled into hourly shifts."
        )

    s_start = payload.get("scheduled_start")
    s_end = payload.get("scheduled_end")
    if not isinstance(s_start, str) or not isinstance(s_end, str):
        raise err_invalid_input("scheduled_start and scheduled_end are required ISO 8601 strings.")
    try:
        start_dt = parse_iso_utc(s_start)
        end_dt = parse_iso_utc(s_end)
    except Exception:
        raise err_invalid_input("scheduled_start/scheduled_end must be ISO 8601 timestamps.")
    if end_dt <= start_dt:
        raise err_invalid_input("scheduled_end must be strictly later than scheduled_start.")

    now = get_clock().now()
    now_iso = format_iso_ms(now)
    sid = new_id()

    shift = {
        "id": sid,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
        "_seq": store.next_seq(),
        "employee_id": employee_id,
        "scheduled_start": format_iso_ms(start_dt),
        "scheduled_end": format_iso_ms(end_dt),
        "actual_start": None,
        "actual_end": None,
        "state": "SCHEDULED",
        "workweek_id": None,
        "_pre_disputed_state": None,
        # Computed columns — set/reset on punch/recompute
        "requires_meal_break": _requires_meal_break(start_dt, end_dt),
        "meal_break_premium_owed_cents": 0,
        "detention_minutes": 0,
    }
    store.shifts[sid] = shift
    return shift


def _requires_meal_break(start_dt, end_dt) -> bool:
    return (end_dt - start_dt).total_seconds() / 3600.0 > 5.0


# ──────────────────────────────────────────────────────────────────────────
# Punch processing
# ──────────────────────────────────────────────────────────────────────────

def live_punches_for_shift(store: Store, shift_id: str) -> List[Dict[str, Any]]:
    """Return non-superseded punches for the shift, ordered by punched_at then _seq."""
    rows = [
        p for p in store.punches.values()
        if p.get("shift_id") == shift_id and not p.get("superseded_by_edit_id")
    ]
    rows.sort(key=lambda p: (p["punched_at"], p.get("_seq", 0)))
    return rows


def all_punches_for_shift(store: Store, shift_id: str) -> List[Dict[str, Any]]:
    rows = [p for p in store.punches.values() if p.get("shift_id") == shift_id]
    rows.sort(key=lambda p: (p.get("punched_at", ""), p.get("_seq", 0)))
    return rows


def record_punch(
    store: Store,
    shift_id: str,
    actor_user_id: str,
    actor_role: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Process POST /shifts/{id}/punches with full state + ordering enforcement.

    Returns the Punch view (after possible Shift state transition).
    """
    shift = store.shifts.get(shift_id)
    if not shift:
        raise err_not_found("Shift does not exist.")
    punch_type = payload.get("punch_type")
    if punch_type not in ("IN", "OUT", "MEAL_OUT", "MEAL_IN"):
        raise err_invalid_input("punch_type must be one of IN, OUT, MEAL_OUT, MEAL_IN.")

    employee = store.employees.get(shift["employee_id"])
    if not employee:
        # Shift orphaned — defensive, normally unreachable
        raise err_not_found("Owning employee no longer exists.")

    # §1.4 priority 11: exempt check
    if employee.get("classification") == "EXEMPT":
        raise err_exempt_not_eligible("Exempt employees cannot produce Shift punches.")

    now = get_clock().now()
    now_iso = format_iso_ms(now)

    # ──────────────────────────────────────────────────────────────────
    # State + ordering gates — priority order matters here:
    #   1. Shift state must allow punch (priority 6: ERR_SHIFT_INVALID_STATE)
    #   2. Ordering / meal-break-duplicate / punch-window (priority 12-14)
    # ──────────────────────────────────────────────────────────────────
    state = shift.get("state")
    if state in ("FINALIZED", "VOIDED"):
        raise err_shift_invalid_state(
            f"Cannot punch on shift in state {state}."
        )
    if state == "DISPUTED":
        raise err_shift_invalid_state(
            "Cannot punch on shift in state DISPUTED — resolve outstanding TimeEdits first."
        )

    live = live_punches_for_shift(store, shift_id)

    # IN punch flow ----------------------------------------------------
    if punch_type == "IN":
        if state == "OPEN" or shift.get("actual_start") is not None:
            raise err_shift_already_open(
                "Shift has already transitioned out of SCHEDULED."
            )
        if state != "SCHEDULED":
            raise err_shift_invalid_state("IN punch requires Shift in SCHEDULED state.")
        # Employee gating
        if employee.get("status") != "ACTIVE":
            raise err_exempt_not_eligible(
                "Only ACTIVE employees may clock in."
            ) if False else err_shift_invalid_state(
                "Owning employee is not ACTIVE."
            )
        # Punch window check (priority 14)
        start_dt = parse_iso_utc(shift["scheduled_start"])
        end_dt = parse_iso_utc(shift["scheduled_end"])
        if not (start_dt - timedelta(minutes=60) <= now <= end_dt + timedelta(minutes=60)):
            raise err_punch_outside_window(
                "IN punch outside [scheduled_start - 60m, scheduled_end + 60m]."
            )

        # All clear — transition SCHEDULED → OPEN
        shift["state"] = "OPEN"
        shift["actual_start"] = now_iso
        shift["updated_at"] = now_iso
        shift["version"] = int(shift.get("version", 1)) + 1
        # Assign workweek_id (upsert)
        ww = upsert_workweek_for_shift(store, shift["employee_id"], now)
        shift["workweek_id"] = ww["id"]

        punch = _insert_punch(
            store,
            shift_id=shift_id,
            employee_id=shift["employee_id"],
            punch_type="IN",
            punched_at=now_iso,
            source="TIMECLOCK",
        )
        return punch

    # MEAL_OUT flow ----------------------------------------------------
    if punch_type == "MEAL_OUT":
        if state != "OPEN":
            raise err_shift_invalid_state("MEAL_OUT requires Shift in state OPEN.")
        # Ordering: previous punches must be exactly [IN]
        seq = [p["punch_type"] for p in live]
        if seq != ["IN"]:
            raise err_punch_out_of_order(
                "MEAL_OUT must immediately follow IN (with no MEAL_OUT or OUT yet)."
            )
        # Meal-break duplicate check (priority 13)
        if store.shift_meal_break_index.get(shift_id):
            raise err_meal_break_duplicate(
                "A MealBreak already exists for this shift."
            )

        punch = _insert_punch(
            store,
            shift_id=shift_id,
            employee_id=shift["employee_id"],
            punch_type="MEAL_OUT",
            punched_at=now_iso,
            source="TIMECLOCK",
        )
        # Create the MealBreak shell row (still open until MEAL_IN closes it)
        mb_id = new_id()
        mb = {
            "id": mb_id,
            "created_at": now_iso,
            "_seq": store.next_seq(),
            "shift_id": shift_id,
            "meal_out_punch_id": punch["id"],
            "meal_in_punch_id": None,
            "duration_minutes": 0,
            "taken_before_fifth_hour": False,
        }
        store.meal_breaks[mb_id] = mb
        store.shift_meal_break_index[shift_id] = mb_id
        return punch

    # MEAL_IN flow -----------------------------------------------------
    if punch_type == "MEAL_IN":
        if state != "OPEN":
            raise err_shift_invalid_state("MEAL_IN requires Shift in state OPEN.")
        seq = [p["punch_type"] for p in live]
        if seq != ["IN", "MEAL_OUT"]:
            raise err_punch_out_of_order(
                "MEAL_IN must immediately follow MEAL_OUT."
            )
        punch = _insert_punch(
            store,
            shift_id=shift_id,
            employee_id=shift["employee_id"],
            punch_type="MEAL_IN",
            punched_at=now_iso,
            source="TIMECLOCK",
        )
        # Update the MealBreak row's pointers/computed flags
        mb_id = store.shift_meal_break_index.get(shift_id)
        if mb_id:
            mb = store.meal_breaks[mb_id]
            live_after = live_punches_for_shift(store, shift_id)
            recompute_meal_break_flags(shift, mb, live_after)
        return punch

    # OUT flow ---------------------------------------------------------
    # (punch_type == "OUT")
    if state != "OPEN":
        raise err_shift_invalid_state("OUT punch requires Shift in state OPEN.")
    # Ordering: any MEAL_OUT must have a matching MEAL_IN; no second IN; no OUT yet
    types = [p["punch_type"] for p in live]
    if "OUT" in types:
        raise err_punch_out_of_order("Shift already has an OUT punch.")
    if types.count("IN") != 1:
        raise err_punch_out_of_order("OUT requires exactly one preceding IN.")
    n_mo = types.count("MEAL_OUT")
    n_mi = types.count("MEAL_IN")
    if n_mo != n_mi:
        raise err_punch_out_of_order(
            "Dangling MEAL_OUT: every MEAL_OUT must have a matching MEAL_IN before OUT."
        )
    # Sequence must match canonical IN [MEAL_OUT MEAL_IN]? — we already block
    # MEAL_OUT after MEAL_IN in the MEAL flows; ensure order is monotonic.
    canonical_orderings = (["IN"], ["IN", "MEAL_OUT", "MEAL_IN"])
    if types not in canonical_orderings:
        raise err_punch_out_of_order("Punch sequence violates canonical order.")

    # Transition OPEN → CLOSED, stamp actual_end, run detention + meal-premium
    punch = _insert_punch(
        store,
        shift_id=shift_id,
        employee_id=shift["employee_id"],
        punch_type="OUT",
        punched_at=now_iso,
        source="TIMECLOCK",
    )
    shift["state"] = "CLOSED"
    shift["actual_end"] = now_iso
    shift["updated_at"] = now_iso
    shift["version"] = int(shift.get("version", 1)) + 1

    # Detention + meal break recompute
    recompute_shift_computeds(store, shift)
    return punch


def _insert_punch(
    store: Store,
    *,
    shift_id: str,
    employee_id: str,
    punch_type: str,
    punched_at: str,
    source: str,
) -> Dict[str, Any]:
    pid = new_id()
    row = {
        "id": pid,
        "created_at": punched_at,
        "_seq": store.next_seq(),
        "shift_id": shift_id,
        "employee_id": employee_id,
        "punch_type": punch_type,
        "punched_at": punched_at,
        "source": source,
        "superseded_by_edit_id": None,
    }
    store.punches[pid] = row
    return row


# ──────────────────────────────────────────────────────────────────────────
# Recompute helpers (post-close / post-edit-approve / post-revert)
# ──────────────────────────────────────────────────────────────────────────

def recompute_shift_computeds(store: Store, shift: Dict[str, Any]) -> None:
    """Recompute Shift.detention_minutes, meal_break_premium_owed_cents,
    and the DetentionEvent + MealBreak rows. Caller must set updated_at after."""
    employee = store.employees.get(shift["employee_id"])
    if not employee:
        return

    # Recompute meal_break duration_minutes / taken_before_fifth_hour based on live punches
    mb_id = store.shift_meal_break_index.get(shift["id"])
    meal_break = store.meal_breaks.get(mb_id) if mb_id else None
    if meal_break:
        recompute_meal_break_flags(shift, meal_break, live_punches_for_shift(store, shift["id"]))

    # Detention
    minutes_past, tier, premium_cents = compute_detention(shift, employee)
    shift["detention_minutes"] = minutes_past

    de_id = store.shift_detention_index.get(shift["id"])
    if de_id is None:
        de_id = new_id()
        store.detention_events[de_id] = {
            "id": de_id,
            "created_at": shift.get("actual_end") or shift["updated_at"],
            "_seq": store.next_seq(),
            "shift_id": shift["id"],
            "minutes_past_scheduled_end": minutes_past,
            "premium_owed_cents": premium_cents,
            "tier": tier,
        }
        store.shift_detention_index[shift["id"]] = de_id
    else:
        de = store.detention_events[de_id]
        de["minutes_past_scheduled_end"] = minutes_past
        de["premium_owed_cents"] = premium_cents
        de["tier"] = tier

    # Meal-break premium
    premium = compute_meal_break_premium(shift, employee, meal_break)
    shift["meal_break_premium_owed_cents"] = premium


def update_actual_start_or_end_from_edit(
    store: Store,
    shift: Dict[str, Any],
    target_punch: Dict[str, Any],
    proposed_dt_iso: str,
) -> None:
    """When a TimeEdit retires a target Punch and inserts an EDIT punch, the
    Shift's actual_start/actual_end may need to be refreshed.

    actual_start := punched_at of the live IN punch
    actual_end   := punched_at of the live OUT punch (if any)
    """
    live = live_punches_for_shift(store, shift["id"])
    in_punch = next((p for p in live if p["punch_type"] == "IN"), None)
    out_punch = next((p for p in live if p["punch_type"] == "OUT"), None)
    shift["actual_start"] = in_punch["punched_at"] if in_punch else None
    shift["actual_end"] = out_punch["punched_at"] if out_punch else None
