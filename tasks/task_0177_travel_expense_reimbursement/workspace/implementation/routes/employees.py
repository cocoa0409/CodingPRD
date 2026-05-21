"""Employee endpoints."""
from __future__ import annotations

from flask import Blueprint

from core.auth import require_roles
from core.envelope import get_json_body, success_response
from core.errors import err_not_found, err_validation
from core.serializers import serialize_employee
from core.store import store
from core.utils import lock
from services.timestamps import stamp_create


bp = Blueprint("employees", __name__)


VALID_ROLES = {"TRAVELER", "MANAGER", "FINANCE_REVIEWER", "OOP_APPROVER", "ADMIN"}


@bp.post("/employees")
@require_roles("ADMIN")
def create_employee():
    body = get_json_body()
    required = ["full_name", "email", "role", "cost_center", "home_address_state"]
    for f in required:
        if body.get(f) is None or body.get(f) == "":
            raise err_validation(f"{f} is required.")

    if body["role"] not in VALID_ROLES:
        raise err_validation(f"role must be one of {sorted(VALID_ROLES)}.")

    manager_id = body.get("manager_id")
    if body["role"] == "TRAVELER":
        if not manager_id:
            raise err_validation("manager_id is required for TRAVELER.")
    if body["role"] == "ADMIN":
        if manager_id:
            raise err_validation("manager_id must be null for ADMIN.")

    if manager_id is not None and manager_id != "":
        mgr = store.employees.get(manager_id)
        if mgr is None:
            from core.errors import err_reference_not_found
            raise err_reference_not_found(f"manager_id {manager_id} not found.")

    # Email uniqueness (case-insensitive)
    email_lower = str(body["email"]).strip().lower()
    for e in store.employees.values():
        if (e.get("email") or "").strip().lower() == email_lower:
            raise err_validation("email must be unique.")

    with lock():
        rec = {
            "full_name": body["full_name"],
            "email": body["email"],
            "role": body["role"],
            "manager_id": manager_id if manager_id else None,
            "cost_center": body["cost_center"],
            "home_address_state": body["home_address_state"],
        }
        stamp_create(rec)
        store.employees[rec["id"]] = rec
    return success_response(serialize_employee(rec), status=201)


@bp.get("/employees/<emp_id>")
@require_roles("TRAVELER", "MANAGER", "FINANCE_REVIEWER", "OOP_APPROVER", "ADMIN")
def get_employee(emp_id):
    rec = store.employees.get(emp_id)
    if rec is None:
        raise err_not_found(f"Employee {emp_id} not found.")
    return success_response(serialize_employee(rec))
