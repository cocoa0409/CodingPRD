"""Shift routes — create, read, list, void, punches, finalize, tip-declaration."""
from __future__ import annotations

import copy

from flask import Blueprint, jsonify, request

from ..audit import append_audit
from ..auth import require_roles
from ..clock import format_iso_ms, get_clock
from ..errors import (
    err_forbidden,
    err_invalid_input,
    err_not_found,
    err_shift_invalid_state,
    err_time_edit_not_pending,
    err_workweek_locked,
)
from ..pagination import paginate, parse_pagination
from ..response import make_array_envelope, make_object_envelope
from ..serializers import punch_view, shift_view, tip_declaration_view
from ..services.shifts import create_shift, record_punch
from ..services.tips import create_tip_declaration, recompute_tip_credit_for_shift
from ..services.workweeks import (
    all_sibling_shifts_finalized,
    recompute_workweek,
    upsert_workweek_for_shift,
)
from ..store import get_store
from ._helpers import enforce_employee_self_access, parse_json_body


bp_shifts = Blueprint("shifts", __name__)


@bp_shifts.route("/timekeeping/shifts", methods=["POST"])
@require_roles("Supervisor", "PayrollAdmin")
def create_shift_route(actor_user_id: str, actor_role: str):
    payload = parse_json_body()
    store = get_store()
    with store.lock:
        shift = create_shift(store, payload)
    return jsonify(make_object_envelope(shift_view(shift))), 201


@bp_shifts.route("/timekeeping/shifts/<shift_id>", methods=["GET"])
@require_roles("Employee", "Supervisor", "PayrollAdmin")
def read_shift_route(actor_user_id: str, actor_role: str, shift_id: str):
    store = get_store()
    shift = store.shifts.get(shift_id)
    if not shift:
        raise err_not_found("Shift does not exist.")
    enforce_employee_self_access(actor_role, actor_user_id, shift["employee_id"])
    return jsonify(make_object_envelope(shift_view(shift))), 200


@bp_shifts.route("/timekeeping/shifts", methods=["GET"])
@require_roles("Employee", "Supervisor", "PayrollAdmin")
def list_shifts_route(actor_user_id: str, actor_role: str):
    limit, offset = parse_pagination()
    employee_id_q = request.args.get("employee_id")
    state_q = request.args.get("state")
    week_start_q = request.args.get("week_start")

    store = get_store()
    rows = list(store.shifts.values())
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))

    # Employee role: implicit ownership filter (only own shifts)
    if actor_role == "Employee":
        rows = [r for r in rows if r.get("employee_id") == actor_user_id]

    if employee_id_q is not None:
        if actor_role == "Employee" and employee_id_q != actor_user_id:
            raise err_forbidden("Employee may only filter to their own employee_id.")
        rows = [r for r in rows if r.get("employee_id") == employee_id_q]
    if state_q is not None:
        rows = [r for r in rows if r.get("state") == state_q]
    if week_start_q is not None:
        # Match against the shift's workweek's week_start
        wanted = week_start_q
        filtered = []
        for r in rows:
            wid = r.get("workweek_id")
            if not wid:
                continue
            ww = store.workweeks.get(wid)
            if ww and ww.get("week_start") == wanted:
                filtered.append(r)
        rows = filtered

    total = len(rows)
    page = paginate(rows, limit, offset)
    views = [shift_view(r) for r in page]
    return (
        jsonify(make_array_envelope(views, limit=limit, offset=offset, total_count=total)),
        200,
    )


@bp_shifts.route("/timekeeping/shifts/<shift_id>", methods=["DELETE"])
@require_roles("Supervisor", "PayrollAdmin")
def delete_shift_route(actor_user_id: str, actor_role: str, shift_id: str):
    store = get_store()
    with store.lock:
        shift = store.shifts.get(shift_id)
        if not shift:
            raise err_not_found("Shift does not exist.")
        if shift.get("state") != "SCHEDULED":
            raise err_shift_invalid_state("Only SCHEDULED shifts may be voided.")
        # No punch should exist
        has_punch = any(p.get("shift_id") == shift_id for p in store.punches.values())
        if has_punch:
            raise err_shift_invalid_state("Cannot void a shift that has punches.")
        shift["state"] = "VOIDED"
        shift["updated_at"] = format_iso_ms(get_clock().now())
        shift["version"] = int(shift.get("version", 1)) + 1
    return ("", 204)


@bp_shifts.route("/timekeeping/shifts/<shift_id>/punches", methods=["POST"])
@require_roles("Employee", "Supervisor")
def record_punch_route(actor_user_id: str, actor_role: str, shift_id: str):
    payload = parse_json_body()
    store = get_store()
    with store.lock:
        shift = store.shifts.get(shift_id)
        if not shift:
            raise err_not_found("Shift does not exist.")
        # Ownership for Employee role
        if actor_role == "Employee" and shift.get("employee_id") != actor_user_id:
            raise err_forbidden("Employee may only punch on their own shifts.")
        punch = record_punch(store, shift_id, actor_user_id, actor_role, payload)
    return jsonify(make_object_envelope(punch_view(punch))), 201


@bp_shifts.route("/timekeeping/shifts/<shift_id>/finalize", methods=["POST"])
@require_roles("PayrollAdmin")
def finalize_shift_route(actor_user_id: str, actor_role: str, shift_id: str):
    store = get_store()
    with store.lock:
        shift = store.shifts.get(shift_id)
        if not shift:
            raise err_not_found("Shift does not exist.")
        if shift.get("state") != "CLOSED":
            raise err_shift_invalid_state(
                f"Only CLOSED shifts may be finalized; current state {shift.get('state')}."
            )
        # No PENDING time edits
        for te in store.time_edits.values():
            if te.get("shift_id") == shift_id and te.get("state") == "PENDING":
                raise err_time_edit_not_pending(
                    "Cannot finalize while a PENDING TimeEdit exists on this shift."
                )
        # Workweek lock check (assign workweek if not already)
        now = get_clock().now()
        now_iso = format_iso_ms(now)
        if not shift.get("workweek_id"):
            # Should already be set by IN punch; defensive upsert.
            anchor = shift.get("actual_start")
            from ..clock import parse_iso_utc
            anchor_dt = parse_iso_utc(anchor) if anchor else now
            ww = upsert_workweek_for_shift(store, shift["employee_id"], anchor_dt)
            shift["workweek_id"] = ww["id"]
        ww = store.workweeks.get(shift["workweek_id"])
        if ww and ww.get("payroll_status") == "LOCKED":
            raise err_workweek_locked("Owning workweek is LOCKED; finalize forbidden.")

        before_shift = copy.deepcopy({k: v for k, v in shift.items() if not k.startswith("_")})

        # Transition CLOSED → FINALIZED
        shift["state"] = "FINALIZED"
        shift["updated_at"] = now_iso
        shift["version"] = int(shift.get("version", 1)) + 1

        # Run tip-credit shortfall (if tipped + tip declaration present)
        recompute_tip_credit_for_shift(store, shift)

        # Run workweek pay engine
        if ww:
            recompute_workweek(store, ww, now_iso)
            # If all sibling shifts FINALIZED → POSTED
            if ww.get("payroll_status") == "OPEN" and all_sibling_shifts_finalized(store, ww["id"]):
                ww["payroll_status"] = "POSTED"
                ww["updated_at"] = now_iso
                ww["version"] = int(ww.get("version", 1)) + 1

        # Audit
        append_audit(
            store,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action="SHIFT_FINALIZED",
            subject_entity="Shift",
            subject_id=shift["id"],
            before_snapshot=before_shift,
            after_snapshot=copy.deepcopy({k: v for k, v in shift.items() if not k.startswith("_")}),
        )
    return jsonify(make_object_envelope(shift_view(shift))), 200


@bp_shifts.route("/timekeeping/shifts/<shift_id>/tip-declaration", methods=["POST"])
@require_roles("Employee", "Supervisor", "PayrollAdmin")
def tip_declaration_route(actor_user_id: str, actor_role: str, shift_id: str):
    payload = parse_json_body()
    store = get_store()
    with store.lock:
        shift = store.shifts.get(shift_id)
        if not shift:
            raise err_not_found("Shift does not exist.")
        if actor_role == "Employee" and shift.get("employee_id") != actor_user_id:
            raise err_forbidden("Employee may only declare tips on their own shifts.")
        td = create_tip_declaration(store, shift_id, actor_user_id, actor_role, payload)
    return jsonify(make_object_envelope(tip_declaration_view(td))), 201
