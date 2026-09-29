"""Employee enrolment, dependents, entitlement projection and ledger surfaces."""

from flask import Blueprint

from db import db
from errors import ApiError
from middleware import assert_employee_scope, auth, json_body
from response import ok, paginate
from util import opt_enum, opt_str, parse_date_value, present, req_enum, req_str

from services.calc import entitlement_projection
from services.core import (
    employee_ledger,
    new_row,
    s_dependent,
    s_employee,
    s_ledger,
    s_reservation,
    sort_created,
    touch,
)
from routes._common import (
    DEPENDENT_STATUSES,
    DEPENDENT_TYPES,
    ELIGIBILITY_STATUSES,
    EMPLOYMENT_STATUSES,
    BILLING_STATUSES,
    FULFILLMENT_STATUSES,
    LEDGER_ENTRY_TYPES,
    keep,
    need,
    qs_date,
    qs_enum,
    qs_str,
)

bp = Blueprint("employees", __name__)


def _eligibility_filter(rows, eligibility):
    if eligibility is None:
        return rows
    from services.core import employee_eligibility

    return [r for r in rows if employee_eligibility(r) == eligibility]


@bp.post("/employees")
def create_employee():
    body = json_body()
    employer_id = req_str(body, "employer_id")
    benefit_plan_id = req_str(body, "benefit_plan_id")
    external_id = req_str(body, "employee_external_id", 80)
    user_id = req_str(body, "user_id", 80)
    email = req_str(body, "email", 200)
    if "@" not in email:
        raise ApiError("ERR_INVALID_REQUEST")
    full_name = req_str(body, "full_name", 200)
    employment_status = opt_enum(body, "employment_status", EMPLOYMENT_STATUSES)

    auth("benefits_admin")

    employer = db.employers.get(employer_id)
    if employer is None:
        raise ApiError("ERR_EMPLOYER_NOT_FOUND")
    plan = db.benefit_plans.get(benefit_plan_id)
    if plan is None:
        raise ApiError("ERR_BENEFITPLAN_NOT_FOUND")

    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE")
    if plan["employer_id"] != employer_id:
        raise ApiError("ERR_PLAN_EMPLOYER_MISMATCH")

    for row in db.employees.values():
        if row["user_id"] == user_id:
            raise ApiError("ERR_DUPLICATE_KEY")
        if (
            row["employer_id"] == employer_id
            and row["employee_external_id"] == external_id
        ):
            raise ApiError("ERR_DUPLICATE_KEY")

    employee = new_row(
        {
            "employer_id": employer_id,
            "benefit_plan_id": benefit_plan_id,
            "employee_external_id": external_id,
            "user_id": user_id,
            "email": email,
            "full_name": full_name,
            "employment_status": employment_status or "ACTIVE",
        }
    )
    db.employees[employee["id"]] = employee
    return ok(s_employee(employee), 201)


@bp.get("/employees/<row_id>")
def get_employee(row_id):
    user_id, role = auth(
        "network_admin", "benefits_admin", "care_coordinator", "employee_user"
    )
    employee = need(db.employees, row_id, "ERR_EMPLOYEE_NOT_FOUND")
    assert_employee_scope(user_id, role, employee["id"])
    return ok(s_employee(employee))


@bp.get("/employees")
def list_employees():
    auth("network_admin", "benefits_admin", "care_coordinator")
    employer_id = qs_str("employer_id")
    benefit_plan_id = qs_str("benefit_plan_id")
    employment_status = qs_enum("employment_status", EMPLOYMENT_STATUSES)
    eligibility = qs_enum("eligibility_status", ELIGIBILITY_STATUSES)
    rows = sort_created(list(db.employees.values()))
    rows = keep(rows, "employer_id", employer_id)
    rows = keep(rows, "benefit_plan_id", benefit_plan_id)
    rows = keep(rows, "employment_status", employment_status)
    rows = _eligibility_filter(rows, eligibility)
    return paginate(rows, s_employee)


@bp.patch("/employees/<row_id>")
def patch_employee(row_id):
    body = json_body()
    employment_status = opt_enum(body, "employment_status", EMPLOYMENT_STATUSES)
    benefit_plan_id = opt_str(body, "benefit_plan_id")
    email = opt_str(body, "email", 200)
    if email is not None and "@" not in email:
        raise ApiError("ERR_INVALID_REQUEST")

    auth("benefits_admin")
    employee = need(db.employees, row_id, "ERR_EMPLOYEE_NOT_FOUND")

    if benefit_plan_id is not None:
        plan = db.benefit_plans.get(benefit_plan_id)
        if plan is None:
            raise ApiError("ERR_BENEFITPLAN_NOT_FOUND")
        if plan["status"] != "ACTIVE":
            raise ApiError("ERR_PLAN_NOT_ACTIVE")
        if plan["employer_id"] != employee["employer_id"]:
            raise ApiError("ERR_PLAN_EMPLOYER_MISMATCH")
        employee["benefit_plan_id"] = benefit_plan_id
    if employment_status is not None:
        employee["employment_status"] = employment_status
    if email is not None:
        employee["email"] = email
    touch(employee)
    return ok(s_employee(employee))


@bp.get("/employees/<row_id>/entitlement")
def employee_entitlement(row_id):
    user_id, role = auth(
        "network_admin", "benefits_admin", "care_coordinator", "employee_user"
    )
    employee = need(db.employees, row_id, "ERR_EMPLOYEE_NOT_FOUND")
    assert_employee_scope(user_id, role, employee["id"])
    return ok(entitlement_projection(employee))


@bp.get("/employees/<row_id>/dependents")
def employee_dependents(row_id):
    user_id, role = auth(
        "network_admin", "benefits_admin", "care_coordinator", "employee_user"
    )
    employee = need(db.employees, row_id, "ERR_EMPLOYEE_NOT_FOUND")
    assert_employee_scope(user_id, role, employee["id"])
    dependent_type = qs_enum("dependent_type", DEPENDENT_TYPES)
    status = qs_enum("status", DEPENDENT_STATUSES)
    rows = [d for d in db.dependents.values() if d["employee_id"] == employee["id"]]
    rows = keep(rows, "dependent_type", dependent_type)
    rows = keep(rows, "status", status)
    return paginate(sort_created(rows), s_dependent)


@bp.post("/employees/<row_id>/dependents")
def create_dependent(row_id):
    body = json_body()
    full_name = req_str(body, "full_name", 200)
    dependent_type = req_enum(body, "dependent_type", DEPENDENT_TYPES)
    if not present(body, "date_of_birth"):
        raise ApiError("ERR_INVALID_REQUEST")
    date_of_birth = parse_date_value(body["date_of_birth"])
    relationship = req_str(body, "relationship", 40)
    care_notes = opt_str(body, "care_notes", 2000, allow_empty=True)
    status = opt_enum(body, "status", DEPENDENT_STATUSES)

    user_id, role = auth("benefits_admin", "employee_user")
    employee = need(db.employees, row_id, "ERR_EMPLOYEE_NOT_FOUND")
    assert_employee_scope(user_id, role, employee["id"])

    dependent = new_row(
        {
            "employee_id": employee["id"],
            "full_name": full_name,
            "dependent_type": dependent_type,
            "date_of_birth": date_of_birth.isoformat(),
            "relationship": relationship,
            "care_notes": "" if care_notes is None else care_notes,
            "status": status or "ACTIVE",
        }
    )
    db.dependents[dependent["id"]] = dependent
    return ok(s_dependent(dependent), 201)


@bp.get("/employees/<row_id>/reservations")
def employee_reservations(row_id):
    user_id, role = auth(
        "network_admin", "benefits_admin", "care_coordinator", "employee_user"
    )
    employee = need(db.employees, row_id, "ERR_EMPLOYEE_NOT_FOUND")
    assert_employee_scope(user_id, role, employee["id"])
    fulfillment_status = qs_enum("fulfillment_status", FULFILLMENT_STATUSES)
    billing_status = qs_enum("billing_status", BILLING_STATUSES)
    care_date = qs_date("care_date")
    rows = [r for r in db.reservations.values() if r["employee_id"] == employee["id"]]
    rows = keep(rows, "fulfillment_status", fulfillment_status)
    rows = keep(rows, "billing_status", billing_status)
    rows = keep(rows, "care_date", care_date)
    return paginate(sort_created(rows), s_reservation)


@bp.get("/employees/<row_id>/ledger-entries")
def employee_ledger_entries(row_id):
    user_id, role = auth(
        "network_admin", "benefits_admin", "care_coordinator", "employee_user"
    )
    employee = need(db.employees, row_id, "ERR_EMPLOYEE_NOT_FOUND")
    assert_employee_scope(user_id, role, employee["id"])
    entry_type = qs_enum("entry_type", LEDGER_ENTRY_TYPES)
    benefit_year_start = qs_date("benefit_year_start")
    rows = employee_ledger(employee["id"])
    rows = keep(rows, "entry_type", entry_type)
    rows = keep(rows, "benefit_year_start", benefit_year_start)
    return paginate(rows, s_ledger)


# --------------------------------------------------------------------------- #
# Dependent
# --------------------------------------------------------------------------- #

@bp.get("/dependents/<row_id>")
def get_dependent(row_id):
    user_id, role = auth(
        "network_admin", "benefits_admin", "care_coordinator", "employee_user"
    )
    dependent = need(db.dependents, row_id, "ERR_DEPENDENT_NOT_FOUND")
    assert_employee_scope(user_id, role, dependent["employee_id"])
    return ok(s_dependent(dependent))


@bp.patch("/dependents/<row_id>")
def patch_dependent(row_id):
    body = json_body()
    full_name = opt_str(body, "full_name", 200)
    relationship = opt_str(body, "relationship", 40)
    care_notes = opt_str(body, "care_notes", 2000, allow_empty=True)
    status = opt_enum(body, "status", DEPENDENT_STATUSES)

    user_id, role = auth("benefits_admin", "employee_user")
    dependent = need(db.dependents, row_id, "ERR_DEPENDENT_NOT_FOUND")
    assert_employee_scope(user_id, role, dependent["employee_id"])

    if full_name is not None:
        dependent["full_name"] = full_name
    if relationship is not None:
        dependent["relationship"] = relationship
    if care_notes is not None:
        dependent["care_notes"] = care_notes
    if status is not None:
        dependent["status"] = status
    touch(dependent)
    return ok(s_dependent(dependent))
