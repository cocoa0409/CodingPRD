"""Employee and DisbursementAccount endpoints (PRD §3.4).

Employee.total_weekly_deduction_cents is computed (sum of weekly_deduction_cents
over ACTIVE enrollments). Email is unique among an employer's EMPLOYED staff.
Terminating an employee cascades to ACTIVE enrollments and locked elections.
"""

from flask import Blueprint, request

import errors
import serializers
import services
from db import db
from middleware import require_roles
from response import success, list_success
from validation import (
    get_json_body, require_str, parse_pagination, paginate,
)

bp = Blueprint("employees", __name__)


# --------------------------------------------------------------------------- #
# Employee                                                                     #
# --------------------------------------------------------------------------- #

@bp.route("/benefits/employees", methods=["POST"])
@require_roles("BenefitsAdmin")
def create_employee():
    body = get_json_body()
    employer_id = require_str(body, "employer_id")
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")

    if services.find_employer(employer_id) is None:
        raise errors.not_found("Employer not found")

    with db.lock:
        # email unique per employer among EMPLOYED employees (PRD §3.4).
        for emp in db.employees.all():
            if (emp["employer_id"] == employer_id
                    and emp["employment_status"] == "EMPLOYED"
                    and emp["email"] == email):
                raise errors.invalid_request("email already in use for an employed worker")

        record = {
            "employer_id": employer_id,
            "full_name": full_name,
            "email": email,
            "employment_status": "EMPLOYED",
            "total_weekly_deduction_cents": 0,
        }
        db.employees.insert(record)
    return success(serializers.employee(record), 201)


@bp.route("/benefits/employees", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster")
def list_employees():
    limit, offset = parse_pagination()
    employer_id = request.args.get("employer_id")
    employment_status = request.args.get("employment_status")

    items = db.employees.all()
    if employer_id is not None:
        items = [e for e in items if e["employer_id"] == employer_id]
    if employment_status is not None:
        items = [e for e in items if e["employment_status"] == employment_status]

    page, total = paginate(items, limit, offset)
    return list_success([serializers.employee(e) for e in page], limit, offset, total)


@bp.route("/benefits/employees/<employee_id>", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def get_employee(employee_id):
    record = db.employees.get(employee_id)
    if record is None:
        raise errors.not_found("Employee not found")
    return success(serializers.employee(record), 200)


@bp.route("/benefits/employees/<employee_id>/terminate", methods=["POST"])
@require_roles("BenefitsAdmin")
def terminate_employee(employee_id):
    record = db.employees.get(employee_id)
    if record is None:
        raise errors.not_found("Employee not found")

    with db.lock:
        # employment_status -> TERMINATED; cascade ACTIVE enrollments -> TERMINATED
        # (each with full side effects), revoke locked elections, recompute the
        # aggregate deduction (PRD §3.6).
        record["employment_status"] = "TERMINATED"
        db.employees.touch(record)
        for enr in db.enrollments.all():
            if enr["employee_id"] == employee_id and enr["lifecycle_status"] == "ACTIVE":
                services.terminate_enrollment_core(enr)
        # terminate_enrollment_core recomputes the total each time; ensure the
        # final state is reconciled even if there were zero active enrollments.
        services.recompute_employee_total_deduction(record)
    return success(serializers.employee(record), 200)


# --------------------------------------------------------------------------- #
# DisbursementAccount                                                          #
# --------------------------------------------------------------------------- #

@bp.route("/benefits/disbursement-accounts", methods=["POST"])
@require_roles("BenefitsAdmin", "Employee")
def create_account():
    body = get_json_body()
    employee_id = require_str(body, "employee_id")
    routing_number = require_str(body, "routing_number")
    account_last4 = require_str(body, "account_last4")

    # 9-digit routing number is a field-level validation (PRD §3.4 / §2.10 p16).
    if not (routing_number.isdigit() and len(routing_number) == 9):
        raise errors.invalid_request("routing_number must be exactly 9 digits")

    if services.find_employee(employee_id) is None:
        raise errors.not_found("Employee not found")

    record = {
        "employee_id": employee_id,
        "routing_number": routing_number,
        "account_last4": account_last4,
        "verification_status": "UNVERIFIED",
        "is_default": False,
    }
    with db.lock:
        db.disbursement_accounts.insert(record)
    return success(serializers.disbursement_account(record), 201)


@bp.route("/benefits/disbursement-accounts", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def list_accounts():
    limit, offset = parse_pagination()
    employee_id = request.args.get("employee_id")
    verification_status = request.args.get("verification_status")

    items = db.disbursement_accounts.all()
    if employee_id is not None:
        items = [a for a in items if a["employee_id"] == employee_id]
    if verification_status is not None:
        items = [a for a in items if a["verification_status"] == verification_status]

    page, total = paginate(items, limit, offset)
    return list_success(
        [serializers.disbursement_account(a) for a in page], limit, offset, total
    )


@bp.route("/benefits/disbursement-accounts/<account_id>", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def get_account(account_id):
    record = db.disbursement_accounts.get(account_id)
    if record is None:
        raise errors.not_found("Disbursement account not found")
    return success(serializers.disbursement_account(record), 200)


@bp.route("/benefits/disbursement-accounts/<account_id>/verify", methods=["POST"])
@require_roles("BenefitsAdmin")
def verify_account(account_id):
    record = db.disbursement_accounts.get(account_id)
    if record is None:
        raise errors.not_found("Disbursement account not found")

    with db.lock:
        record["verification_status"] = "VERIFIED"
        # First account that becomes verified for the employee becomes default
        # (at most one verified default per employee) (PRD §3.4).
        already_default = any(
            a["employee_id"] == record["employee_id"]
            and a["id"] != record["id"]
            and a["verification_status"] == "VERIFIED"
            and a["is_default"]
            for a in db.disbursement_accounts.all()
        )
        if not already_default and not record["is_default"]:
            record["is_default"] = True
        db.disbursement_accounts.touch(record)
    return success(serializers.disbursement_account(record), 200)
