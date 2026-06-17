"""Employee routes: create, fetch, strike ledger, reinstate (PRD §3.6)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_DUPLICATE, ERR_INVALID_REQUEST
from middleware import require_role
from response import ok_object, ok_array
from routes._helpers import (
    parse_pagination, paginate, order_by_created, get_body, require_str,
    get_employee,
)
from services.common import stamp_new, touch, public, public_list
from services import calculations as calc

READ_ROLES = ("FacilityManager", "Analyst", "Receptionist", "Employee")

bp = Blueprint("employees", __name__)


@bp.post("/workplace/employees")
def create_employee():
    require_role("FacilityManager")
    body = get_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    team_code = require_str(body, "team_code")
    email_l = email.lower()
    for e in db.employees.values():
        if e["email"] == email_l:
            raise APIError(ERR_DUPLICATE, 409, "Employee email already exists")
    emp = {
        "email": email_l,
        "full_name": full_name,
        "team_code": team_code,
        "strike_score": 0,
        "booking_privilege": "ACTIVE",
        "status": "ACTIVE",
        "_reinstate_seq": 0,
    }
    stamp_new(emp)
    db.employees[emp["id"]] = emp
    return ok_object(public_employee(emp), 201)


def public_employee(emp):
    out = public(emp)
    out.pop("_reinstate_seq", None)
    return out


@bp.get("/workplace/employees/<eid>")
def get_employee_ep(eid):
    require_role(*READ_ROLES)
    emp = get_employee(eid)
    # ensure derived fields are current
    emp["strike_score"] = calc.compute_strike_score(emp)
    emp["booking_privilege"] = calc.derive_privilege(emp["strike_score"])
    return ok_object(public_employee(emp))


@bp.get("/workplace/employees/<eid>/no-show-events")
def list_employee_no_show(eid):
    require_role("FacilityManager", "Analyst")
    emp = get_employee(eid)
    limit, offset = parse_pagination()
    items = [ev for ev in db.no_show_events.values() if ev["employee_id"] == emp["id"]]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(public_list(page), limit, offset, total)


@bp.post("/workplace/employees/<eid>/reinstate")
def reinstate_employee(eid):
    require_role("FacilityManager")
    emp = get_employee(eid)
    # new reinstate baseline: exclude all current ledger rows from future sums
    emp["_reinstate_seq"] = db.next_seq()
    emp["strike_score"] = 0
    emp["booking_privilege"] = "ACTIVE"
    touch(emp)
    return ok_object(public_employee(emp))
