"""Employee endpoints (PRD §3.1)."""

from flask import Blueprint, request

import config
from db import store
from errors import raise_err
from middleware import require_role
from response import ok, paginate
from services.audit import log_event
from services.serializers import employee_view
from services.cascades import terminate_employee_cascade

from . import _helpers as H

bp = Blueprint("employees", __name__)


def _email_collides(email: str, exclude_id: str = None) -> bool:
    for e in store.employees.values():
        if e["id"] == exclude_id:
            continue
        if e["email"] == email and e["status"] in config.LIVE_EMPLOYEE_STATUSES:
            return True
    return False


def _validate_manager_ref(mid, self_id=None):
    if mid is None:
        return None
    if not isinstance(mid, str):
        raise_err("ERR_VALIDATION", "manager_employee_id must be a string.")
    if self_id is not None and mid == self_id:
        raise_err("ERR_VALIDATION", "manager_employee_id cannot equal own id.")
    mgr = store.employees.get(mid)
    if not mgr:
        raise_err("ERR_REFERENCE_NOT_FOUND", f"manager_employee_id '{mid}' not found.")
    if mgr["status"] not in config.LIVE_EMPLOYEE_STATUSES:
        raise_err("ERR_REFERENCE_NOT_FOUND", "manager_employee_id refers to a non-live employee.")
    return mid


@bp.route("/employees", methods=["POST"])
@require_role("Admin", "HRBP")
def create_employee():
    with store.lock:
        body = H.get_body()
        full_name = H.require_str(H.require_field(body, "full_name"), "full_name", 1, 200)
        email = H.require_str(H.require_field(body, "email"), "email", 1, 320)
        department = H.require_str(H.require_field(body, "department"), "department", 1, 200)
        job_level = H.require_int(H.require_field(body, "job_level"), "job_level", 1, 10)
        manager_id = body.get("manager_employee_id")
        if manager_id is not None:
            _validate_manager_ref(manager_id)
        base_salary_cents = H.require_int(
            H.require_field(body, "base_salary_cents"), "base_salary_cents", 1,
        )
        equity_units = body.get("equity_units_outstanding", 0)
        if equity_units is None:
            equity_units = 0
        equity_units = H.require_int(equity_units, "equity_units_outstanding", 0)
        hire_date = H.require_iso(H.require_field(body, "hire_date"), "hire_date")

        # Email uniqueness across live employees
        if _email_collides(email):
            raise_err("ERR_EMAIL_TAKEN", f"Email '{email}' is already in use.")

        emp = H.new_entity({
            "full_name": full_name,
            "email": email,
            "department": department,
            "job_level": job_level,
            "manager_employee_id": manager_id,
            "base_salary_cents": base_salary_cents,
            "equity_units_outstanding": equity_units,
            "status": "ACTIVE",
            "hire_date": hire_date,
        })
        store.employees[emp["id"]] = emp
        log_event("Employee", emp["id"], "employee.create", payload=body)
        return ok(employee_view(emp), status=201)


@bp.route("/employees", methods=["GET"])
@require_role("Admin", "HRBP", "Manager", "Approver")
def list_employees():
    with store.lock:
        status = request.args.get("status")
        department = request.args.get("department")
        manager_id = request.args.get("manager_employee_id")
        limit, offset = H.pagination_params()

        items = list(store.employees.values())
        if status is not None:
            if status not in config.EMPLOYEE_STATUSES:
                raise_err("ERR_VALIDATION", "Invalid status filter.")
            items = [e for e in items if e["status"] == status]
        if department is not None:
            items = [e for e in items if e["department"] == department]
        if manager_id is not None:
            items = [e for e in items if e.get("manager_employee_id") == manager_id]

        items.sort(key=lambda e: e["created_at"])
        sliced, page_meta = paginate(items, limit, offset)
        return ok([employee_view(e) for e in sliced], pagination=page_meta)


@bp.route("/employees/<employee_id>", methods=["GET"])
@require_role("Admin", "HRBP", "Manager", "Approver", "Reviewer")
def read_employee(employee_id):
    with store.lock:
        emp = H.get_employee_or_404(employee_id)
        return ok(employee_view(emp))


@bp.route("/employees/<employee_id>", methods=["PATCH"])
@require_role("Admin", "HRBP")
def patch_employee(employee_id):
    with store.lock:
        emp = H.get_employee_or_404(employee_id)
        body = H.get_body()

        # OCC last per validation priority 120
        supplied_version = body.get("version")

        if "department" in body and body["department"] is not None:
            emp_new_dept = H.require_str(body["department"], "department", 1, 200)
        else:
            emp_new_dept = None

        if "manager_employee_id" in body:
            mid = body["manager_employee_id"]
            if mid is not None:
                _validate_manager_ref(mid, self_id=emp["id"])
        else:
            mid = "__unset__"

        if "base_salary_cents" in body and body["base_salary_cents"] is not None:
            new_base = H.require_int(body["base_salary_cents"], "base_salary_cents", 1)
        else:
            new_base = None

        H.check_version(emp, supplied_version)

        if emp_new_dept is not None:
            emp["department"] = emp_new_dept
        if mid != "__unset__":
            emp["manager_employee_id"] = mid
        if new_base is not None:
            emp["base_salary_cents"] = new_base
        H.bump(emp) if any([
            emp_new_dept is not None, mid != "__unset__", new_base is not None
        ]) else None

        log_event("Employee", emp["id"], "employee.patch", payload=body)
        return ok(employee_view(emp))


@bp.route("/employees/<employee_id>/terminate", methods=["POST"])
@require_role("Admin", "HRBP")
def terminate_employee(employee_id):
    with store.lock:
        emp = H.get_employee_or_404(employee_id)
        if emp["status"] == "TERMINATED":
            # idempotent — return current state
            return ok(employee_view(emp))
        terminate_employee_cascade(emp)
        log_event("Employee", emp["id"], "employee.terminate", payload={})
        return ok(employee_view(emp))
