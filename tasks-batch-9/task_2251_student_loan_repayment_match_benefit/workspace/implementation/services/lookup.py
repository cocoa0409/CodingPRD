"""Identifier resolution (PRD 2.5) and Employee ownership scoping (PRD 2.1)."""

import db
from errors import fail


def _get(collection, identifier, error_id):
    if not isinstance(identifier, str) or identifier == "":
        fail(error_id, "identifier not found")
    row = getattr(db.db, collection).get(identifier)
    if row is None:
        fail(error_id, "identifier %s not found" % identifier)
    return row


def plan_year(identifier):
    return _get("plan_years", identifier, "ERR_PLAN_YEAR_NOT_FOUND")


def employee(identifier):
    return _get("employees", identifier, "ERR_EMPLOYEE_NOT_FOUND")


def payroll_period(identifier):
    return _get("payroll_periods", identifier, "ERR_PAYROLL_PERIOD_NOT_FOUND")


def loan_account(identifier):
    return _get("loan_accounts", identifier, "ERR_LOAN_ACCOUNT_NOT_FOUND")


def certification(identifier):
    return _get("loan_certifications", identifier,
                "ERR_CERTIFICATION_NOT_FOUND")


def allocation(identifier):
    return _get("match_allocations", identifier, "ERR_ALLOCATION_NOT_FOUND")


def funding_batch(identifier):
    return _get("funding_batches", identifier, "ERR_FUNDING_BATCH_NOT_FOUND")


def amendment(identifier):
    return _get("plan_amendments", identifier, "ERR_AMENDMENT_NOT_FOUND")


def test(identifier):
    return _get("nondiscrimination_tests", identifier, "ERR_TEST_NOT_FOUND")


def audit_row(collection, identifier):
    return _get(collection, identifier, "ERR_RECORD_NOT_FOUND")


# --------------------------------------------------------------------------

def require_owner(role, user_id, employee_id):
    """Ordinal 14 -- ERR_NOT_RESOURCE_OWNER for the Employee role only."""
    if role == "Employee" and employee_id != user_id:
        fail("ERR_NOT_RESOURCE_OWNER",
             "the acting employee does not own this resource")


def scope_to_owner(rows, role, user_id, key="employee_id"):
    """An Employee-role list is always scoped to its own employee_id."""
    if role != "Employee":
        return rows
    return [r for r in rows if r.get(key) == user_id]
