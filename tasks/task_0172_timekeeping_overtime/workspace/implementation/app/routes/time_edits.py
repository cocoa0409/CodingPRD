"""TimeEdit routes — submit, read, list, approve, reject, revert."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import require_roles
from ..errors import err_forbidden, err_not_found
from ..pagination import paginate, parse_pagination
from ..response import make_array_envelope, make_object_envelope
from ..serializers import time_edit_view
from ..services.time_edits import (
    approve_time_edit,
    reject_time_edit,
    revert_time_edit,
    submit_time_edit,
)
from ..store import get_store
from ._helpers import parse_json_body


bp_time_edits = Blueprint("time_edits", __name__)


@bp_time_edits.route("/timekeeping/time-edits", methods=["POST"])
@require_roles("Employee", "Supervisor", "PayrollAdmin")
def submit_time_edit_route(actor_user_id: str, actor_role: str):
    payload = parse_json_body()
    store = get_store()
    with store.lock:
        row, _was_replay = submit_time_edit(store, actor_user_id, actor_role, payload)
    return jsonify(make_object_envelope(time_edit_view(row))), 201


@bp_time_edits.route("/timekeeping/time-edits/<time_edit_id>", methods=["GET"])
@require_roles("Employee", "Supervisor", "PayrollAdmin")
def read_time_edit_route(actor_user_id: str, actor_role: str, time_edit_id: str):
    store = get_store()
    te = store.time_edits.get(time_edit_id)
    if not te:
        raise err_not_found("TimeEdit does not exist.")
    # Ownership for Employee: must own the shift
    if actor_role == "Employee":
        shift = store.shifts.get(te["shift_id"])
        if not shift or shift.get("employee_id") != actor_user_id:
            raise err_forbidden(
                "Employee may only view time edits on their own shifts."
            )
    return jsonify(make_object_envelope(time_edit_view(te))), 200


@bp_time_edits.route("/timekeeping/time-edits", methods=["GET"])
@require_roles("Supervisor", "PayrollAdmin")
def list_time_edits_route(actor_user_id: str, actor_role: str):
    limit, offset = parse_pagination()
    shift_id_q = request.args.get("shift_id")
    state_q = request.args.get("state")
    reason_q = request.args.get("reason_code")

    store = get_store()
    rows = list(store.time_edits.values())
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    if shift_id_q is not None:
        rows = [r for r in rows if r.get("shift_id") == shift_id_q]
    if state_q is not None:
        rows = [r for r in rows if r.get("state") == state_q]
    if reason_q is not None:
        rows = [r for r in rows if r.get("reason_code") == reason_q]
    total = len(rows)
    page = paginate(rows, limit, offset)
    views = [time_edit_view(r) for r in page]
    return (
        jsonify(make_array_envelope(views, limit=limit, offset=offset, total_count=total)),
        200,
    )


@bp_time_edits.route("/timekeeping/time-edits/<time_edit_id>/approve", methods=["POST"])
@require_roles("Supervisor", "PayrollAdmin")
def approve_time_edit_route(actor_user_id: str, actor_role: str, time_edit_id: str):
    store = get_store()
    with store.lock:
        te = approve_time_edit(store, actor_user_id, actor_role, time_edit_id)
    return jsonify(make_object_envelope(time_edit_view(te))), 200


@bp_time_edits.route("/timekeeping/time-edits/<time_edit_id>/reject", methods=["POST"])
@require_roles("Supervisor", "PayrollAdmin")
def reject_time_edit_route(actor_user_id: str, actor_role: str, time_edit_id: str):
    store = get_store()
    with store.lock:
        te = reject_time_edit(store, actor_user_id, actor_role, time_edit_id)
    return jsonify(make_object_envelope(time_edit_view(te))), 200


@bp_time_edits.route("/timekeeping/time-edits/<time_edit_id>/revert", methods=["POST"])
@require_roles("PayrollAdmin")
def revert_time_edit_route(actor_user_id: str, actor_role: str, time_edit_id: str):
    store = get_store()
    with store.lock:
        te = revert_time_edit(store, actor_user_id, actor_role, time_edit_id)
    return jsonify(make_object_envelope(time_edit_view(te))), 200
