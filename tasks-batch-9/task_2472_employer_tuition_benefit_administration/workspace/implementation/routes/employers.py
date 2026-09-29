"""Employers, benefit policies and employees."""

import domain
import serialize
from auth import employee_scope, employer_scope, endpoint
from errors import fail, invalid
from store import db, new_record, touch
from validate import (
    EMPLOYMENT_STATUSES,
    JOB_FAMILIES,
    array_field,
    body,
    date_field,
    email_field,
    enum_field,
    int_field,
    number_field,
    pagination,
    POLICY_FUNDING_MODELS,
    bool_field,
    query_enum,
    string_field,
)

from .common import filter_eq, object_response, paged

POLICY_STATUSES = ["DRAFT", "ACTIVE", "SUPERSEDED"]
ELIGIBILITY_STATUSES = [
    "ELIGIBLE",
    "INELIGIBLE_NO_POLICY",
    "INELIGIBLE_EMPLOYMENT",
    "INELIGIBLE_TENURE",
    "INELIGIBLE_HOURS",
    "INELIGIBLE_JOB_FAMILY",
]


def register(app):
    # ----------------------------------------------------------------- employers
    @app.post("/employers")
    @endpoint(["PlatformAdmin"])
    def create_employer():
        data = body()
        row = new_record(
            {
                "legal_name": string_field(data, "legal_name", max_len=160),
                "benefit_admin_contact_email": email_field(data, "benefit_admin_contact_email"),
                "fiscal_year_start_month": int_field(
                    data, "fiscal_year_start_month", minimum=1, maximum=12
                ),
                "status": enum_field(
                    data, "status", ["ACTIVE", "SUSPENDED"], required=False, default="ACTIVE"
                ),
                "total_disbursed_cents": 0,
                "total_admin_fee_cents": 0,
                "total_imputed_income_cents": 0,
            }
        )
        db.employers[row["id"]] = row
        return object_response(serialize.employer(row), 201)

    @app.get("/employers/<employer_id>")
    @endpoint(["PlatformAdmin", "BenefitAdministrator"])
    def read_employer(employer_id):
        employer = domain.must(db.employers, employer_id, "ERR_EMPLOYER_NOT_FOUND")
        employer_scope(employer_id)
        return object_response(serialize.employer(employer))

    @app.get("/employers/<employer_id>/utilization-report")
    @endpoint(["BenefitAdministrator", "PlatformAdmin"])
    def utilization_report(employer_id):
        employer = domain.must(db.employers, employer_id, "ERR_EMPLOYER_NOT_FOUND")
        employer_scope(employer_id)
        return object_response(domain.utilization_report(employer))

    # ------------------------------------------------------------------ policies
    @app.post("/employers/<employer_id>/benefit-policies")
    @endpoint(["BenefitAdministrator"])
    def create_policy(employer_id):
        data = body()
        effective_from = date_field(data, "effective_from")
        effective_to = date_field(data, "effective_to")
        if effective_to <= effective_from:
            invalid("'effective_to' must be strictly after 'effective_from'")
        fields = {
            "employer_id": employer_id,
            "effective_from": effective_from.isoformat(),
            "effective_to": effective_to.isoformat(),
            "status": "DRAFT",
            "min_tenure_months": int_field(data, "min_tenure_months", minimum=0),
            "min_weekly_hours": number_field(data, "min_weekly_hours", minimum=0, decimals=2),
            "eligible_job_families": array_field(data, "eligible_job_families", JOB_FAMILIES),
            "annual_cap_cents": int_field(data, "annual_cap_cents", minimum=1),
            "funding_model": enum_field(data, "funding_model", POLICY_FUNDING_MODELS),
            "reimbursement_pct": number_field(
                data, "reimbursement_pct", exclusive_min=0, maximum=1, decimals=2
            ),
            "max_concurrent_credits": int_field(data, "max_concurrent_credits", minimum=1),
            "drop_window_days": int_field(data, "drop_window_days", minimum=0),
            "service_commitment_months": int_field(data, "service_commitment_months", minimum=1),
            "min_passing_grade_points": number_field(
                data,
                "min_passing_grade_points",
                required=False,
                minimum=0,
                maximum=4,
                decimals=2,
                default=2.00,
            ),
            "non_catalog_approval_required": bool_field(
                data, "non_catalog_approval_required", required=False, default=True
            ),
        }
        domain.must(db.employers, employer_id, "ERR_EMPLOYER_NOT_FOUND")
        employer_scope(employer_id)
        row = new_record(fields)
        db.policies[row["id"]] = row
        return object_response(serialize.policy(row), 201)

    @app.get("/employers/<employer_id>/benefit-policies")
    @endpoint(["BenefitAdministrator", "PlatformAdmin"])
    def list_policies(employer_id):
        limit, offset = pagination()
        status = query_enum("status", POLICY_STATUSES)
        domain.must(db.employers, employer_id, "ERR_EMPLOYER_NOT_FOUND")
        employer_scope(employer_id)
        rows = [p for p in db.policies.values() if p["employer_id"] == employer_id]
        rows = filter_eq(rows, "status", status)
        return paged(rows, serialize.policy, limit, offset)

    @app.post("/benefit-policies/<policy_id>/activate")
    @endpoint(["BenefitAdministrator"])
    def activate_policy(policy_id):
        policy = domain.must(db.policies, policy_id, "ERR_POLICY_NOT_FOUND")
        employer_scope(policy["employer_id"])
        if policy["status"] != "DRAFT":
            fail("ERR_POLICY_NOT_DRAFT", "policy is %s, not DRAFT" % policy["status"])

        from validate import iso_date

        start = iso_date(policy["effective_from"])
        end = iso_date(policy["effective_to"])
        for other in db.policies.values():
            if other["id"] == policy["id"] or other["employer_id"] != policy["employer_id"]:
                continue
            if other["status"] != "ACTIVE":
                continue
            other_start = iso_date(other["effective_from"])
            other_end = iso_date(other["effective_to"])
            if start < other_end and other_start < end:
                fail(
                    "ERR_POLICY_PERIOD_OVERLAP",
                    "window overlaps the ACTIVE policy %s" % other["id"],
                )

        policy["status"] = "ACTIVE"
        touch(policy)
        # every employee of the employer is reprocessed in created_at ASC order
        for employee in domain.employees_of(policy["employer_id"]):
            domain.refresh_employee(employee)
            touch(employee)
        return object_response(serialize.policy(policy))

    # ----------------------------------------------------------------- employees
    @app.post("/employers/<employer_id>/employees")
    @endpoint(["BenefitAdministrator"])
    def create_employee(employer_id):
        data = body()
        full_name = string_field(data, "full_name", max_len=160)
        work_email = email_field(data, "work_email")
        hire_date = date_field(data, "hire_date")
        weekly_hours = number_field(data, "weekly_hours", minimum=0, maximum=80, decimals=2)
        job_family = enum_field(data, "job_family", JOB_FAMILIES)
        employment_status = enum_field(
            data, "employment_status", EMPLOYMENT_STATUSES, required=False, default="ACTIVE"
        )
        termination_date = date_field(data, "termination_date", required=False, default=None)
        if employment_status == "TERMINATED" and termination_date is None:
            invalid("'termination_date' is required when employment_status is TERMINATED")
        if employment_status != "TERMINATED" and termination_date is not None:
            invalid("'termination_date' must be null unless employment_status is TERMINATED")

        domain.must(db.employers, employer_id, "ERR_EMPLOYER_NOT_FOUND")
        employer_scope(employer_id)

        row = new_record(
            {
                "employer_id": employer_id,
                "full_name": full_name,
                "work_email": work_email,
                "hire_date": hire_date.isoformat(),
                "weekly_hours": weekly_hours,
                "job_family": job_family,
                "employment_status": employment_status,
                "termination_date": termination_date.isoformat() if termination_date else None,
                "tenure_months": 0,
                "eligibility_status": "INELIGIBLE_NO_POLICY",
                "cap_plan_year": 0,
                "cap_reserved_cents": 0,
                "cap_disbursed_cents": 0,
                "cap_clawback_hold_cents": 0,
                "cap_available_cents": 0,
                "taxable_excluded_cents_ytd": 0,
                "imputed_income_cents_ytd": 0,
                "open_repayment_balance_cents": 0,
                "coaching_hold": False,
            }
        )
        db.employees[row["id"]] = row
        domain.refresh_employee(row)
        return object_response(serialize.employee(row), 201)

    @app.get("/employers/<employer_id>/employees")
    @endpoint(["BenefitAdministrator"])
    def list_employees(employer_id):
        limit, offset = pagination()
        eligibility_status = query_enum("eligibility_status", ELIGIBILITY_STATUSES)
        job_family = query_enum("job_family", JOB_FAMILIES)
        domain.must(db.employers, employer_id, "ERR_EMPLOYER_NOT_FOUND")
        employer_scope(employer_id)
        rows = [e for e in db.employees.values() if e["employer_id"] == employer_id]
        rows = filter_eq(rows, "eligibility_status", eligibility_status)
        rows = filter_eq(rows, "job_family", job_family)
        return paged(rows, serialize.employee, limit, offset)

    @app.get("/employees/<employee_id>")
    @endpoint(["Employee", "BenefitAdministrator", "Coach"])
    def read_employee(employee_id):
        employee = domain.must(db.employees, employee_id, "ERR_EMPLOYEE_NOT_FOUND")
        employee_scope(employee_id)
        employer_scope(employee["employer_id"])
        return object_response(serialize.employee(employee))

    @app.patch("/employees/<employee_id>")
    @endpoint(["BenefitAdministrator"])
    def patch_employee(employee_id):
        data = body()
        weekly_hours = number_field(
            data, "weekly_hours", required=False, minimum=0, maximum=80, decimals=2, default=None
        )
        job_family = enum_field(data, "job_family", JOB_FAMILIES, required=False, default=None)
        employment_status = enum_field(
            data, "employment_status", EMPLOYMENT_STATUSES, required=False, default=None
        )
        termination_date = date_field(data, "termination_date", required=False, default=None)
        if employment_status == "TERMINATED" and termination_date is None:
            invalid("'termination_date' is required when employment_status is set to TERMINATED")
        if termination_date is not None and employment_status != "TERMINATED":
            invalid("'termination_date' may only accompany a move to TERMINATED")

        employee = domain.must(db.employees, employee_id, "ERR_EMPLOYEE_NOT_FOUND")
        employer_scope(employee["employer_id"])

        if weekly_hours is not None:
            employee["weekly_hours"] = weekly_hours
        if job_family is not None:
            employee["job_family"] = job_family
        if employment_status is not None:
            employee["employment_status"] = employment_status
            if employment_status == "TERMINATED":
                employee["termination_date"] = termination_date.isoformat()
            else:
                employee["termination_date"] = None

        if employment_status == "TERMINATED":
            domain.cascade_employment_termination(employee, termination_date)

        touch(employee)
        domain.refresh_employee(employee)
        return object_response(serialize.employee(employee))
