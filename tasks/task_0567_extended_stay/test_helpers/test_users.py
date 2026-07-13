"""Pre-built role headers for every role in the PRD (§2.1).

- PropertyManager is opaque: X-User-ID is an operator identifier not tied to any
  entity, so the shared constant is the canonical form.
- CorporateAdmin is entity_backed:CorporateAccount — X-User-ID must be the acting
  CorporateAccount.id for ownership checks. Use make_corporate_admin_headers(account_id).
- Employee is entity_backed:Employee — X-User-ID must be the acting Employee.id.
  Use make_employee_headers(employee_id) whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque role — shared constant is canonical
    "property_manager_headers": build_user_headers("test-pm-1", "PropertyManager"),
    # entity_backed fallbacks — only for non-ownership tests (403-role / 404 / 400)
    "corporate_admin_headers": build_user_headers("test-ca-1", "CorporateAdmin"),
    "employee_headers": build_user_headers("test-emp-1", "Employee"),
}


def make_property_manager_headers(user_id: str = "test-pm-1") -> dict:
    return build_user_headers(user_id, "PropertyManager")


def make_corporate_admin_headers(account_id: str) -> dict:
    """For CorporateAdmin (entity_backed:CorporateAccount). Pass the acting
    CorporateAccount.id so ownership checks (own roster / leases / stays) pass."""
    return build_user_headers(account_id, "CorporateAdmin")


def make_employee_headers(employee_id: str) -> dict:
    """For Employee (entity_backed:Employee). Pass the acting Employee.id so
    ownership checks on the employee's own stay pass."""
    return build_user_headers(employee_id, "Employee")
