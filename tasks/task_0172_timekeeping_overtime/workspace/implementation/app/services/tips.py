"""Tip-declaration service — create + shortfall computation."""
from __future__ import annotations

from typing import Any, Dict

from ..calculations import compute_tip_credit_for_shift
from ..clock import format_iso_ms, get_clock
from ..errors import (
    err_invalid_input,
    err_meal_break_duplicate,
    err_not_found,
    err_shift_invalid_state,
    err_tips_not_applicable,
)
from ..store import Store, new_id


def create_tip_declaration(
    store: Store,
    shift_id: str,
    actor_user_id: str,
    actor_role: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    shift = store.shifts.get(shift_id)
    if not shift:
        raise err_not_found("Shift does not exist.")
    employee = store.employees.get(shift["employee_id"])
    if not employee:
        raise err_not_found("Owning employee does not exist.")
    if not employee.get("tipped_role", False):
        raise err_tips_not_applicable("Employee is not a tipped role.")
    declared = payload.get("declared_tips_cents")
    if not isinstance(declared, int) or isinstance(declared, bool):
        raise err_invalid_input("declared_tips_cents must be an integer.")
    if declared < 0:
        raise err_tips_not_applicable("declared_tips_cents must be >= 0.")

    # At most one TipDeclaration per shift
    if store.shift_tip_decl_index.get(shift_id):
        # The PRD doesn't define a separate error for duplicate tip decl;
        # closest semantic is meal-break-duplicate-equivalent at 409. We
        # use ERR_TIPS_NOT_APPLICABLE for "tips can't be applied (again)".
        raise err_tips_not_applicable(
            "A TipDeclaration already exists for this shift."
        )

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
        "declared_tips_cents": declared,
        "tip_credit_applied_cents": 0,
        "shortfall_topup_cents": 0,
    }
    store.tip_declarations[tid] = row
    store.shift_tip_decl_index[shift_id] = tid
    return row


def recompute_tip_credit_for_shift(store: Store, shift: Dict[str, Any]) -> None:
    """Run §3.7 tip-credit-shortfall for the given shift (if applicable).

    Updates the shift's TipDeclaration in place. Safe to call on shifts
    without a TipDeclaration (no-op).
    """
    td_id = store.shift_tip_decl_index.get(shift["id"])
    if not td_id:
        return
    td = store.tip_declarations.get(td_id)
    if not td:
        return
    employee = store.employees.get(shift["employee_id"])
    if not employee or not employee.get("tipped_role"):
        return
    mb_id = store.shift_meal_break_index.get(shift["id"])
    meal_break = store.meal_breaks.get(mb_id) if mb_id else None
    applied, shortfall = compute_tip_credit_for_shift(
        shift=shift,
        employee=employee,
        meal_break=meal_break,
        declared_tips_cents=int(td["declared_tips_cents"]),
    )
    td["tip_credit_applied_cents"] = int(applied)
    td["shortfall_topup_cents"] = int(shortfall)
    td["updated_at"] = format_iso_ms(get_clock().now())
    td["version"] = int(td.get("version", 1)) + 1
