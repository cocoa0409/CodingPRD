"""Employee endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db
from middleware import authorized
from response import success_object
from routes.helpers import get_one, public
from services.core import new_record
from validate import get_body, opt_int, req_int, req_str

bp = Blueprint("employees", __name__)


@bp.post("/mobility/employees")
def create_employee():
    authorized(["MobilityAdmin"])
    body = get_body()
    rec = new_record("employees", {
        "employee_ref": req_str(body, "employee_ref"),
        "full_name": req_str(body, "full_name"),
        "home_country_code": req_str(body, "home_country_code"),
        "family_size": opt_int(body, "family_size", 1, minimum=1),
        "annual_base_salary_cents": req_int(body, "annual_base_salary_cents", minimum=0),
    })
    return success_object(public(rec), status=201)


@bp.get("/mobility/employees/<rid>")
def get_employee(rid):
    return get_one("employees", rid)
