"""Employee endpoints."""

from flask import Blueprint, request

from db import db
from middleware import get_auth, require_role, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.validate import body, req_string, get_or_404
from services.entities import make_employee, pub, touch
from errors import (
    err409, ERR_DUPLICATE_EMPLOYEE_REF, ERR_INVALID_STATE_TRANSITION,
    ERR_STORE_CLOSED,
)

bp = Blueprint("employees", __name__)


@bp.route("/employees", methods=["POST"])
def create_employee():
    user_id, role = get_auth()
    require_role(role, {"HRPartner"})
    data = body()
    store_id = req_string(data, "store_id")
    employee_ref = req_string(data, "employee_ref")
    full_name = req_string(data, "full_name")
    store = get_or_404(db.stores, store_id, "store")
    if store["status"] != "ACTIVE":
        raise err409(ERR_STORE_CLOSED, "Store is CLOSED")
    for e in db.employees.values():
        if e["employee_ref"] == employee_ref:
            raise err409(ERR_DUPLICATE_EMPLOYEE_REF,
                         "employee_ref %s already exists" % employee_ref)
    emp = make_employee(store_id, employee_ref, full_name)
    db.employees[emp["id"]] = emp
    return success_object(pub(emp), status=201)


@bp.route("/employees", methods=["GET"])
def list_employees():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    store_id = _opt_query("store_id")
    status = _opt_query("status")
    items = sorted(db.employees.values(), key=lambda e: (e["created_at"], e["id"]))
    if store_id is not None:
        items = [e for e in items if e["store_id"] == store_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pub(e) for e in page], limit, offset, total)


@bp.route("/employees/<employee_id>", methods=["GET"])
def get_employee(employee_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    emp = get_or_404(db.employees, employee_id, "employee")
    return success_object(pub(emp))


@bp.route("/employees/<employee_id>/suspend", methods=["POST"])
def suspend_employee(employee_id):
    user_id, role = get_auth()
    require_role(role, {"HRPartner"})
    emp = get_or_404(db.employees, employee_id, "employee")
    if emp["status"] != "ACTIVE":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Employee must be ACTIVE to suspend")
    emp["status"] = "SUSPENDED"
    touch(emp)
    return success_object(pub(emp))


@bp.route("/employees/<employee_id>/reinstate", methods=["POST"])
def reinstate_employee(employee_id):
    user_id, role = get_auth()
    require_role(role, {"HRPartner"})
    emp = get_or_404(db.employees, employee_id, "employee")
    if emp["status"] != "SUSPENDED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Employee must be SUSPENDED to reinstate")
    emp["status"] = "ACTIVE"
    touch(emp)
    return success_object(pub(emp))


def _opt_query(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None
