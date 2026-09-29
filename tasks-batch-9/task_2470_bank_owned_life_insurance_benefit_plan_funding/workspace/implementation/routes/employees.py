"""Prospective insureds (PRD 3.2)."""

from flask import Blueprint

from response import resource_response
from store import create_record, db, touch
from validation import (
    authorize,
    find_employee,
    get_bool,
    get_enum,
    get_money,
    get_string,
    json_body,
)

bp = Blueprint("employees", __name__)

EMPLOYMENT_STATUSES = ("ACTIVE", "TERMINATED", "DECEASED")


@bp.post("/employees")
def register_employee():
    authorize(("BenefitsAnalyst",))
    body = json_body()
    full_name = get_string(body, "full_name")
    employee_number = get_string(body, "employee_number")
    annual_salary = get_money(body, "annual_salary_usd", positive_only=True)
    officer_flag = get_bool(body, "officer_flag", required=False, default=False)

    employee = create_record(
        db.employees,
        {
            "full_name": full_name,
            "employee_number": employee_number,
            "annual_salary_usd": annual_salary,
            "officer_flag": officer_flag,
            "insurable_interest_status": "NOT_ESTABLISHED",
            "employment_status": "ACTIVE",
        },
    )
    return resource_response(employee, 201)


@bp.get("/employees/<employee_id>")
def read_employee(employee_id):
    authorize(("BenefitsAnalyst", "RiskOfficer", "ClaimsAdministrator", "TreasuryController"))
    return resource_response(find_employee(employee_id))


@bp.post("/employees/<employee_id>/employment-status")
def set_employment_status(employee_id):
    authorize(("BenefitsAnalyst",))
    body = json_body()
    employment_status = get_enum(body, "employment_status", EMPLOYMENT_STATUSES)
    employee = find_employee(employee_id)
    employee["employment_status"] = employment_status
    touch(employee)
    return resource_response(employee)
