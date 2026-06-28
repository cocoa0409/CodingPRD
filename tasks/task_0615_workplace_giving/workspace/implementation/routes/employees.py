"""Employee endpoints (PRD §3.2) and tax-statement generation (PRD §3.9)."""
from flask import Blueprint, request

from db import db, parse_iso
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_EMPLOYEE_EMAIL,
)
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.common import (
    get_json_body,
    require_fields,
    require_string,
    require_positive_int,
    stamp_create,
    touch,
    serialize,
    find_or_404,
    paginate,
)

bp = Blueprint("employees", __name__)


def _email_in_use(program_id, email, exclude_id=None):
    for e in db.employees.values():
        if e["program_id"] != program_id:
            continue
        if exclude_id is not None and e["id"] == exclude_id:
            continue
        if e["status"] == "TERMINATED":
            continue
        if e["email"] == email:
            return True
    return False


@bp.route("/employees", methods=["POST"])
def enroll_employee():
    _uid, role = get_user_context()
    require_role(role, {"ProgramManager", "GivingAdmin"})
    body = get_json_body()
    require_fields(body, ["program_id", "email", "full_name", "annual_salary_cents"])
    program_id = require_string(body, "program_id")
    email = require_string(body, "email")
    full_name = require_string(body, "full_name")
    salary = require_positive_int(body, "annual_salary_cents")

    # Existence (priority 4) before business checks.
    find_or_404(db.programs, program_id)

    # Uniqueness: email within program among non-TERMINATED (priority business).
    if _email_in_use(program_id, email):
        raise err(ERR_DUPLICATE_EMPLOYEE_EMAIL,
                  "Email already used by a non-terminated employee in this program")

    rec = {
        "program_id": program_id,
        "email": email,
        "full_name": full_name,
        "annual_salary_cents": salary,
        "match_consumed_ytd_cents": 0,
        "dfd_consumed_ytd_cents": 0,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.employees[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/employees/<employee_id>", methods=["GET"])
def get_employee(employee_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    rec = find_or_404(db.employees, employee_id)
    return object_response(serialize(rec), 200)


@bp.route("/employees", methods=["GET"])
def list_employees():
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager"})
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = []
    for e in db.employees.values():
        if program_id is not None and e["program_id"] != program_id:
            continue
        if status is not None and e["status"] != status:
            continue
        items.append(e)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(e) for e in page], limit, offset, total, 200)


def _transition(employee_id, allowed_from, new_status):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager"})
    rec = find_or_404(db.employees, employee_id)
    if rec["status"] not in allowed_from:
        raise err(ERR_INVALID_STATE, f"Employee must be in {allowed_from} for this transition")
    rec["status"] = new_status
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/employees/<employee_id>/suspend", methods=["POST"])
def suspend_employee(employee_id):
    return _transition(employee_id, {"ACTIVE"}, "SUSPENDED")


@bp.route("/employees/<employee_id>/reinstate", methods=["POST"])
def reinstate_employee(employee_id):
    return _transition(employee_id, {"SUSPENDED"}, "ACTIVE")


@bp.route("/employees/<employee_id>/terminate", methods=["POST"])
def terminate_employee(employee_id):
    # Terminate frees email (uniqueness ignores TERMINATED) — automatic since
    # _email_in_use skips TERMINATED.
    return _transition(employee_id, {"ACTIVE", "SUSPENDED"}, "TERMINATED")


# ---------------------------------------------------------------------------
# Tax statements (PRD §3.9)
# ---------------------------------------------------------------------------
@bp.route("/employees/<employee_id>/tax-statement", methods=["POST"])
def generate_tax_statement(employee_id):
    uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "Employee"})
    employee = find_or_404(db.employees, employee_id)
    # Ownership for Employee role.
    if role == "Employee" and uid != employee["id"]:
        raise err(("ERR_NOT_RESOURCE_OWNER", 403),
                  "Employee may only act on own resources")

    program = db.programs.get(employee["program_id"])
    tax_year = program["tax_year"]

    deductible_total = 0
    line_count = 0
    for d in db.donations.values():
        if d["employee_id"] != employee_id:
            continue
        if d["status"] != "SETTLED":
            continue
        if not d.get("tax_deductible", True):
            continue
        if not d.get("settled_at"):
            continue
        if parse_iso(d["settled_at"]).year != tax_year:
            continue
        deductible_total += d["base_amount_cents"]
        line_count += 1

    matched_total = 0
    for m in db.matching_gifts.values():
        if m["employee_id"] != employee_id:
            continue
        if m["status"] != "SETTLED":
            continue
        donation = db.donations.get(m["donation_id"])
        if donation is None or not donation.get("settled_at"):
            continue
        if parse_iso(donation["settled_at"]).year != tax_year:
            continue
        matched_total += m["matched_amount_cents"]

    rec = {
        "program_id": employee["program_id"],
        "employee_id": employee_id,
        "tax_year": tax_year,
        "deductible_donations_cents": deductible_total,
        "matched_total_cents": matched_total,
        "line_count": line_count,
        "status": "GENERATED",
    }
    stamp_create(rec)
    db.tax_statements[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/tax-statements/<statement_id>", methods=["GET"])
def get_tax_statement(statement_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    rec = find_or_404(db.tax_statements, statement_id)
    return object_response(serialize(rec), 200)


@bp.route("/tax-statements", methods=["GET"])
def list_tax_statements():
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    program_id = request.args.get("program_id")
    employee_id = request.args.get("employee_id")
    tax_year = request.args.get("tax_year")
    items = []
    for s in db.tax_statements.values():
        if program_id is not None and s["program_id"] != program_id:
            continue
        if employee_id is not None and s["employee_id"] != employee_id:
            continue
        if tax_year is not None and str(s["tax_year"]) != str(tax_year):
            continue
        items.append(s)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(s) for s in page], limit, offset, total, 200)
