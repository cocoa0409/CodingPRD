"""Workweek routes — read, list, lock."""
from __future__ import annotations

import copy

from flask import Blueprint, jsonify, request

from ..audit import append_audit
from ..auth import require_roles
from ..clock import format_iso_ms, get_clock
from ..errors import (
    err_forbidden,
    err_not_found,
    err_time_edit_not_pending,
    err_workweek_locked,
)
from ..pagination import paginate, parse_pagination
from ..response import make_array_envelope, make_object_envelope
from ..serializers import workweek_view
from ..store import get_store
from ._helpers import enforce_employee_self_access


bp_workweeks = Blueprint("workweeks", __name__)


@bp_workweeks.route("/timekeeping/workweeks/<workweek_id>", methods=["GET"])
@require_roles("Employee", "Supervisor", "PayrollAdmin")
def read_workweek_route(actor_user_id: str, actor_role: str, workweek_id: str):
    store = get_store()
    ww = store.workweeks.get(workweek_id)
    if not ww:
        raise err_not_found("Workweek does not exist.")
    enforce_employee_self_access(actor_role, actor_user_id, ww["employee_id"])
    return jsonify(make_object_envelope(workweek_view(ww))), 200


@bp_workweeks.route("/timekeeping/workweeks", methods=["GET"])
@require_roles("Supervisor", "PayrollAdmin")
def list_workweeks_route(actor_user_id: str, actor_role: str):
    limit, offset = parse_pagination()
    employee_id_q = request.args.get("employee_id")
    payroll_status_q = request.args.get("payroll_status")
    week_start_q = request.args.get("week_start")

    store = get_store()
    rows = list(store.workweeks.values())
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    if employee_id_q is not None:
        rows = [r for r in rows if r.get("employee_id") == employee_id_q]
    if payroll_status_q is not None:
        rows = [r for r in rows if r.get("payroll_status") == payroll_status_q]
    if week_start_q is not None:
        rows = [r for r in rows if r.get("week_start") == week_start_q]
    total = len(rows)
    page = paginate(rows, limit, offset)
    views = [workweek_view(r) for r in page]
    return (
        jsonify(make_array_envelope(views, limit=limit, offset=offset, total_count=total)),
        200,
    )


@bp_workweeks.route("/timekeeping/workweeks/<workweek_id>/lock", methods=["POST"])
@require_roles("PayrollAdmin")
def lock_workweek_route(actor_user_id: str, actor_role: str, workweek_id: str):
    store = get_store()
    with store.lock:
        ww = store.workweeks.get(workweek_id)
        if not ww:
            raise err_not_found("Workweek does not exist.")
        if ww.get("payroll_status") == "LOCKED":
            raise err_workweek_locked("Workweek is already LOCKED.")
        if ww.get("payroll_status") != "POSTED":
            raise err_workweek_locked(
                f"Cannot lock workweek in payroll_status {ww.get('payroll_status')}."
            )
        # No PENDING TimeEdits on any constituent shift
        for te in store.time_edits.values():
            if te.get("state") != "PENDING":
                continue
            shift = store.shifts.get(te.get("shift_id"))
            if shift and shift.get("workweek_id") == workweek_id:
                raise err_time_edit_not_pending(
                    "Cannot lock workweek while a PENDING TimeEdit exists on a constituent shift."
                )
        now_iso = format_iso_ms(get_clock().now())
        before_ww = copy.deepcopy({k: v for k, v in ww.items() if not k.startswith("_")})
        ww["payroll_status"] = "LOCKED"
        ww["updated_at"] = now_iso
        ww["version"] = int(ww.get("version", 1)) + 1
        append_audit(
            store,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action="WORKWEEK_LOCKED",
            subject_entity="Workweek",
            subject_id=workweek_id,
            before_snapshot=before_ww,
            after_snapshot=copy.deepcopy({k: v for k, v in ww.items() if not k.startswith("_")}),
        )
    return jsonify(make_object_envelope(workweek_view(ww))), 200
