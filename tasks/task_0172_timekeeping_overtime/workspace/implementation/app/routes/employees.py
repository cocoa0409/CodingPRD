"""Employee routes."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import require_roles
from ..clock import format_iso_ms, get_clock
from ..errors import err_invalid_input, err_not_found, err_forbidden
from ..pagination import paginate, parse_pagination
from ..response import make_array_envelope, make_object_envelope
from ..serializers import employee_view
from ..services.employees import (
    validate_employee_create_payload,
    validate_employee_patch_payload,
)
from ..store import get_store, new_id
from ._helpers import check_occ_version, enforce_employee_self_access, parse_json_body


bp_employees = Blueprint("employees", __name__)


@bp_employees.route("/timekeeping/employees", methods=["POST"])
@require_roles("PayrollAdmin")
def create_employee(actor_user_id: str, actor_role: str):
    payload = parse_json_body()
    fields = validate_employee_create_payload(payload)

    store = get_store()
    with store.lock:
        now_iso = format_iso_ms(get_clock().now())
        eid = new_id()
        row = {
            "id": eid,
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
            "_seq": store.next_seq(),
            "status": "ACTIVE",
            **fields,
        }
        store.employees[eid] = row
    return jsonify(make_object_envelope(employee_view(row))), 201


@bp_employees.route("/timekeeping/employees/<employee_id>", methods=["GET"])
@require_roles("Employee", "Supervisor", "PayrollAdmin")
def read_employee(actor_user_id: str, actor_role: str, employee_id: str):
    store = get_store()
    row = store.employees.get(employee_id)
    if not row:
        raise err_not_found("Employee does not exist.")
    enforce_employee_self_access(actor_role, actor_user_id, employee_id)
    return jsonify(make_object_envelope(employee_view(row))), 200


@bp_employees.route("/timekeeping/employees/<employee_id>", methods=["PATCH"])
@require_roles("PayrollAdmin")
def patch_employee(actor_user_id: str, actor_role: str, employee_id: str):
    payload = parse_json_body()
    store = get_store()
    with store.lock:
        row = store.employees.get(employee_id)
        if not row:
            raise err_not_found("Employee does not exist.")
        check_occ_version(payload, row)
        # Validate patch
        new_state = validate_employee_patch_payload(row, payload)
        # Apply patch
        for k in (
            "full_name",
            "jurisdiction",
            "classification",
            "base_hourly_rate_cents",
            "tipped_role",
            "tipped_cash_rate_cents",
            "applicable_minimum_wage_cents",
            "status",
        ):
            if k in new_state:
                row[k] = new_state[k]
        row["updated_at"] = format_iso_ms(get_clock().now())
        row["version"] = int(row.get("version", 1)) + 1
    return jsonify(make_object_envelope(employee_view(row))), 200


@bp_employees.route("/timekeeping/employees", methods=["GET"])
@require_roles("Supervisor", "PayrollAdmin")
def list_employees(actor_user_id: str, actor_role: str):
    limit, offset = parse_pagination()
    status_q = request.args.get("status")
    cls_q = request.args.get("classification")

    store = get_store()
    rows = list(store.employees.values())
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    if status_q is not None:
        rows = [r for r in rows if r.get("status") == status_q]
    if cls_q is not None:
        rows = [r for r in rows if r.get("classification") == cls_q]
    total = len(rows)
    page = paginate(rows, limit, offset)
    views = [employee_view(r) for r in page]
    return (
        jsonify(make_array_envelope(views, limit=limit, offset=offset, total_count=total)),
        200,
    )
