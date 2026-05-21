"""TimeEdit service — submit / approve / reject / revert with cascades.

State machine:
  PENDING → APPROVED  via /approve   (Supervisor or PayrollAdmin)
  PENDING → REJECTED  via /reject    (Supervisor or PayrollAdmin)
  APPROVED → REVERTED via /revert    (PayrollAdmin only)

Cascades on approve/revert:
  - May insert/remove an EDIT punch tied to target_punch.
  - Recomputes Shift.detention_minutes and Shift.meal_break_premium_owed_cents.
  - If Shift was FINALIZED, drops it back to CLOSED and flips owning
    Workweek POSTED → OPEN.
"""
from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any, Dict, List, Optional

from ..audit import append_audit
from ..clock import format_iso_ms, get_clock, parse_iso_utc
from ..errors import (
    err_duplicate_idempotency_key,
    err_forbidden,
    err_fraud_requires_admin,
    err_invalid_input,
    err_not_found,
    err_punch_out_of_order,
    err_segregation_of_duties,
    err_shift_invalid_state,
    err_time_edit_not_pending,
    err_time_edit_out_of_range,
    err_workweek_locked,
)
from ..store import Store, new_id
from .shifts import (
    live_punches_for_shift,
    recompute_shift_computeds,
    update_actual_start_or_end_from_edit,
)


VALID_REASON_CODES = ("CLERICAL", "MISSED_PUNCH", "EQUIPMENT_FAILURE", "FRAUD_CORRECTION")


# ──────────────────────────────────────────────────────────────────────────
# Submit
# ──────────────────────────────────────────────────────────────────────────

def submit_time_edit(
    store: Store,
    actor_user_id: str,
    actor_role: str,
    payload: Dict[str, Any],
) -> tuple[Dict[str, Any], bool]:
    """Create a PENDING TimeEdit row. Returns (row, was_replay).

    `was_replay` is True iff an existing row with the same (shift_id,
    idempotency_key) and byte-identical payload was returned.
    """
    shift_id = payload.get("shift_id")
    if not isinstance(shift_id, str) or not shift_id:
        raise err_invalid_input("shift_id is required.")
    shift = store.shifts.get(shift_id)
    if not shift:
        raise err_not_found("Shift does not exist.")
    target_punch_id = payload.get("target_punch_id")
    if not isinstance(target_punch_id, str) or not target_punch_id:
        raise err_invalid_input("target_punch_id is required.")
    target_punch = store.punches.get(target_punch_id)
    if not target_punch:
        raise err_not_found("Target punch does not exist.")
    if target_punch.get("shift_id") != shift_id:
        raise err_invalid_input("target_punch_id does not belong to shift_id.")

    proposed = payload.get("proposed_punched_at")
    if not isinstance(proposed, str) or not proposed:
        raise err_invalid_input("proposed_punched_at is required.")
    try:
        proposed_dt = parse_iso_utc(proposed)
    except Exception:
        raise err_invalid_input("proposed_punched_at must be ISO 8601.")
    # Time-edit window check (priority 15)
    sched_start = parse_iso_utc(shift["scheduled_start"])
    sched_end = parse_iso_utc(shift["scheduled_end"])
    lo = sched_start - timedelta(hours=4)
    hi = sched_end + timedelta(hours=6)
    if not (lo <= proposed_dt <= hi):
        raise err_time_edit_out_of_range(
            "proposed_punched_at outside [scheduled_start - 4h, scheduled_end + 6h]."
        )

    reason_code = payload.get("reason_code")
    if reason_code not in VALID_REASON_CODES:
        raise err_invalid_input(
            f"reason_code must be one of {', '.join(VALID_REASON_CODES)}."
        )
    idempotency_key = payload.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not (1 <= len(idempotency_key) <= 64):
        raise err_invalid_input("idempotency_key must be a string of 1..64 chars.")

    # Ownership check for Employee role (priority 5)
    if actor_role == "Employee":
        if shift.get("employee_id") != actor_user_id:
            raise err_forbidden(
                "Employee may only submit time edits on their own shifts."
            )

    # Idempotency lookup
    key = (shift_id, idempotency_key)
    existing_id = store.time_edit_idempotency_index.get(key)
    if existing_id and existing_id in store.time_edits:
        existing = store.time_edits[existing_id]
        # Compare input payload identity
        same = (
            existing["target_punch_id"] == target_punch_id
            and existing["proposed_punched_at"] == format_iso_ms(proposed_dt)
            and existing["reason_code"] == reason_code
        )
        if same:
            return existing, True
        raise err_duplicate_idempotency_key(
            "Idempotency key reused with conflicting payload."
        )

    # PRD §3.6: "Once locked, further time-edit approvals on the
    # workweek's shifts are rejected with `ERR_WORKWEEK_LOCKED`,
    # finalize is rejected with the same code, and revert is likewise
    # rejected." Submission is NOT listed — a locked workweek may still
    # receive a PENDING TimeEdit row (which will fail to approve).
    # Therefore no workweek-LOCKED gate fires at submit time.

    # Create the row
    now = get_clock().now()
    now_iso = format_iso_ms(now)
    tid = new_id()
    row = {
        "id": tid,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
        "_seq": store.next_seq(),
        "shift_id": shift_id,
        "target_punch_id": target_punch_id,
        "proposed_punched_at": format_iso_ms(proposed_dt),
        "reason_code": reason_code,
        "requested_by_user_id": actor_user_id,
        "requested_by_role": actor_role,
        "approved_by_user_id": None,
        "state": "PENDING",
        "idempotency_key": idempotency_key,
        "applied_at": None,
        "_shift_pre_dispute_state": None,
    }
    store.time_edits[tid] = row
    store.time_edit_idempotency_index[key] = tid

    # Audit submission
    append_audit(
        store,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action="TIME_EDIT_SUBMITTED",
        subject_entity="TimeEdit",
        subject_id=tid,
        before_snapshot={},
        after_snapshot=copy.deepcopy(_snapshot(row)),
    )

    # Shift may transition OPEN/CLOSED → DISPUTED
    if shift["state"] in ("OPEN", "CLOSED"):
        row["_shift_pre_dispute_state"] = shift["state"]
        shift["state"] = "DISPUTED"
        shift["updated_at"] = now_iso
        shift["version"] = int(shift.get("version", 1)) + 1
    # FINALIZED shifts remain FINALIZED at submit; transition deferred to approve.

    return row, False


def _snapshot(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return a JSON-safe shallow copy used for audit snapshots."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


# ──────────────────────────────────────────────────────────────────────────
# Approve
# ──────────────────────────────────────────────────────────────────────────

def approve_time_edit(
    store: Store,
    actor_user_id: str,
    actor_role: str,
    time_edit_id: str,
) -> Dict[str, Any]:
    te = store.time_edits.get(time_edit_id)
    if not te:
        raise err_not_found("TimeEdit does not exist.")
    if te.get("state") != "PENDING":
        raise err_time_edit_not_pending(
            "TimeEdit is not in PENDING state."
        )
    shift = store.shifts.get(te["shift_id"])
    if not shift:
        raise err_not_found("Owning shift does not exist.")
    # Workweek lock check (priority 8)
    if shift.get("workweek_id"):
        ww = store.workweeks.get(shift["workweek_id"])
        if ww and ww.get("payroll_status") == "LOCKED":
            raise err_workweek_locked(
                "Owning workweek is LOCKED; approve forbidden."
            )
    # Segregation of duties (priority 9)
    if actor_user_id == te.get("requested_by_user_id"):
        raise err_segregation_of_duties(
            "Approver must differ from requester."
        )
    # Fraud-requires-admin (priority 10)
    if te.get("reason_code") == "FRAUD_CORRECTION" and actor_role != "PayrollAdmin":
        raise err_fraud_requires_admin(
            "FRAUD_CORRECTION TimeEdits require PayrollAdmin approver."
        )
    # Shift state must be in allowed set
    if shift.get("state") not in ("OPEN", "DISPUTED", "CLOSED", "FINALIZED"):
        raise err_shift_invalid_state(
            f"TimeEdit cannot be approved on shift in state {shift.get('state')}."
        )

    now = get_clock().now()
    now_iso = format_iso_ms(now)
    before_te = copy.deepcopy(_snapshot(te))
    before_shift = copy.deepcopy({k: v for k, v in shift.items() if not k.startswith("_")})

    # Was shift FINALIZED before approval? If yes, after recompute we drop it back to CLOSED.
    was_finalized = (shift.get("state") == "FINALIZED")

    # 1. Insert EDIT punch with punched_at = proposed_punched_at
    target_punch = store.punches.get(te["target_punch_id"])
    if not target_punch:
        raise err_not_found("Target punch no longer exists.")
    edit_pid = new_id()
    edit_punch = {
        "id": edit_pid,
        "created_at": now_iso,
        "_seq": store.next_seq(),
        "shift_id": shift["id"],
        "employee_id": target_punch["employee_id"],
        "punch_type": target_punch["punch_type"],
        "punched_at": te["proposed_punched_at"],
        "source": "EDIT",
        "superseded_by_edit_id": None,
    }
    store.punches[edit_pid] = edit_punch
    # 2. Mark target Punch.superseded_by_edit_id
    target_punch["superseded_by_edit_id"] = te["id"]

    # 3. Update TimeEdit fields
    te["state"] = "APPROVED"
    te["approved_by_user_id"] = actor_user_id
    te["applied_at"] = now_iso
    te["updated_at"] = now_iso
    te["version"] = int(te.get("version", 1)) + 1

    # 4. Refresh Shift.actual_start/actual_end if affected punch was IN/OUT
    update_actual_start_or_end_from_edit(store, shift, target_punch, te["proposed_punched_at"])
    # 5. Recompute detention + meal_break_premium
    recompute_shift_computeds(store, shift)

    # 6. Resolve Shift state cascade
    # First: was the shift DISPUTED on this edit's submission? If so, recompute
    # whether any PENDING TimeEdit remains. If none → leave DISPUTED.
    pending_remaining = any(
        t.get("shift_id") == shift["id"] and t.get("state") == "PENDING"
        for t in store.time_edits.values()
    )
    if was_finalized:
        # Drop FINALIZED → CLOSED and flip workweek POSTED → OPEN
        shift["state"] = "CLOSED"
        if shift.get("workweek_id"):
            ww = store.workweeks.get(shift["workweek_id"])
            if ww and ww.get("payroll_status") == "POSTED":
                ww["payroll_status"] = "OPEN"
                ww["updated_at"] = now_iso
                ww["version"] = int(ww.get("version", 1)) + 1
    elif shift.get("state") == "DISPUTED" and not pending_remaining:
        # Return shift to its pre-DISPUTED state (CLOSED if OUT had landed, else OPEN)
        # If we have a live OUT punch, the shift is CLOSED; otherwise OPEN.
        live = live_punches_for_shift(store, shift["id"])
        has_out = any(p["punch_type"] == "OUT" for p in live)
        # Use pre-DISPUTED state if recorded; otherwise derive
        pre = te.get("_shift_pre_dispute_state")
        if pre in ("OPEN", "CLOSED"):
            shift["state"] = pre
        else:
            shift["state"] = "CLOSED" if has_out else "OPEN"

    shift["updated_at"] = now_iso
    shift["version"] = int(shift.get("version", 1)) + 1

    # 7. Audit
    append_audit(
        store,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action="TIME_EDIT_APPROVED",
        subject_entity="TimeEdit",
        subject_id=te["id"],
        before_snapshot=before_te,
        after_snapshot=copy.deepcopy(_snapshot(te)),
    )

    return te


# ──────────────────────────────────────────────────────────────────────────
# Reject
# ──────────────────────────────────────────────────────────────────────────

def reject_time_edit(
    store: Store,
    actor_user_id: str,
    actor_role: str,
    time_edit_id: str,
) -> Dict[str, Any]:
    te = store.time_edits.get(time_edit_id)
    if not te:
        raise err_not_found("TimeEdit does not exist.")
    if te.get("state") != "PENDING":
        raise err_time_edit_not_pending(
            "TimeEdit is not in PENDING state."
        )
    shift = store.shifts.get(te["shift_id"])
    if not shift:
        raise err_not_found("Owning shift does not exist.")
    # SoD applies on reject path too
    if actor_user_id == te.get("requested_by_user_id"):
        raise err_segregation_of_duties(
            "Approver must differ from requester."
        )

    now = get_clock().now()
    now_iso = format_iso_ms(now)
    before_te = copy.deepcopy(_snapshot(te))

    te["state"] = "REJECTED"
    te["updated_at"] = now_iso
    te["version"] = int(te.get("version", 1)) + 1

    # If shift was DISPUTED and this was the last pending edit, return to prior state
    pending_remaining = any(
        t.get("shift_id") == shift["id"] and t.get("state") == "PENDING" and t["id"] != te["id"]
        for t in store.time_edits.values()
    )
    if shift.get("state") == "DISPUTED" and not pending_remaining:
        pre = te.get("_shift_pre_dispute_state")
        if pre in ("OPEN", "CLOSED"):
            shift["state"] = pre
        else:
            # Derive from punches
            live = live_punches_for_shift(store, shift["id"])
            has_out = any(p["punch_type"] == "OUT" for p in live)
            shift["state"] = "CLOSED" if has_out else "OPEN"
        shift["updated_at"] = now_iso
        shift["version"] = int(shift.get("version", 1)) + 1

    append_audit(
        store,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action="TIME_EDIT_REJECTED",
        subject_entity="TimeEdit",
        subject_id=te["id"],
        before_snapshot=before_te,
        after_snapshot=copy.deepcopy(_snapshot(te)),
    )
    return te


# ──────────────────────────────────────────────────────────────────────────
# Revert
# ──────────────────────────────────────────────────────────────────────────

def revert_time_edit(
    store: Store,
    actor_user_id: str,
    actor_role: str,
    time_edit_id: str,
) -> Dict[str, Any]:
    te = store.time_edits.get(time_edit_id)
    if not te:
        raise err_not_found("TimeEdit does not exist.")
    if te.get("state") != "APPROVED":
        raise err_time_edit_not_pending(
            "TimeEdit is not in APPROVED state; cannot revert."
        )
    shift = store.shifts.get(te["shift_id"])
    if not shift:
        raise err_not_found("Owning shift does not exist.")
    if shift.get("workweek_id"):
        ww = store.workweeks.get(shift["workweek_id"])
        if ww and ww.get("payroll_status") == "LOCKED":
            raise err_workweek_locked(
                "Owning workweek is LOCKED; revert forbidden."
            )

    now = get_clock().now()
    now_iso = format_iso_ms(now)
    before_te = copy.deepcopy(_snapshot(te))

    was_finalized = (shift.get("state") == "FINALIZED")

    # 1. Remove the EDIT punch that this TimeEdit produced
    # The EDIT punch is the one with source=EDIT, shift_id=shift.id, that
    # superseded a punch which now back-references te.id.
    target_punch = store.punches.get(te["target_punch_id"])
    if target_punch and target_punch.get("superseded_by_edit_id") == te["id"]:
        target_punch["superseded_by_edit_id"] = None

    # Remove EDIT punch(es) inserted by this TimeEdit. We identify them as
    # punches with source=EDIT whose punched_at == te.proposed_punched_at,
    # shift_id == te.shift_id, and which are currently live (no further
    # supersession). Simpler approach: any source=EDIT punch on this shift
    # whose timestamp matches the time edit's proposed_punched_at.
    to_remove = [
        pid for pid, p in store.punches.items()
        if p.get("shift_id") == shift["id"]
        and p.get("source") == "EDIT"
        and p.get("punched_at") == te["proposed_punched_at"]
    ]
    for pid in to_remove:
        del store.punches[pid]

    # 2. Update TimeEdit fields
    te["state"] = "REVERTED"
    te["updated_at"] = now_iso
    te["version"] = int(te.get("version", 1)) + 1

    # 3. Refresh actual_start/actual_end + recompute
    update_actual_start_or_end_from_edit(store, shift, target_punch or {}, te["proposed_punched_at"])
    recompute_shift_computeds(store, shift)

    # 4. If shift was FINALIZED, drop to CLOSED and flip workweek POSTED→OPEN
    if was_finalized:
        shift["state"] = "CLOSED"
        if shift.get("workweek_id"):
            ww = store.workweeks.get(shift["workweek_id"])
            if ww and ww.get("payroll_status") == "POSTED":
                ww["payroll_status"] = "OPEN"
                ww["updated_at"] = now_iso
                ww["version"] = int(ww.get("version", 1)) + 1

    shift["updated_at"] = now_iso
    shift["version"] = int(shift.get("version", 1)) + 1

    append_audit(
        store,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action="TIME_EDIT_REVERTED",
        subject_entity="TimeEdit",
        subject_id=te["id"],
        before_snapshot=before_te,
        after_snapshot=copy.deepcopy(_snapshot(te)),
    )
    return te
