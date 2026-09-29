"""Header builders for each role (PRD §2.1).

Every request carries both ``X-User-ID`` and ``X-User-Role``. For the four
operator roles the ``X-User-ID`` is an opaque operator identifier; for
``EmployeeSelfService`` the ``X-User-ID`` *is* the Employee id, so its headers
must be built from a real Employee row.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Stable operator identities used across recipes. Two distinct ids exist per
# role so that segregation-of-duties rules (PRD §2.7) can be exercised.
COMPLIANCE_OFFICER_USER_ID = "co-1"
COMPLIANCE_OFFICER_2_USER_ID = "co-2"
BENEFITS_ADMIN_USER_ID = "ba-1"
PREPARER_USER_ID = "preparer-1"
PREPARER_2_USER_ID = "preparer-2"
FILING_AGENT_USER_ID = "agent-1"
FILING_AGENT_2_USER_ID = "agent-2"


def make_compliance_officer_headers(user_id=COMPLIANCE_OFFICER_USER_ID):
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_benefits_admin_headers(user_id=BENEFITS_ADMIN_USER_ID):
    return build_user_headers(user_id, UserRole.BENEFITS_ADMIN.value)


def make_preparer_headers(user_id=PREPARER_USER_ID):
    return build_user_headers(user_id, UserRole.PREPARER.value)


def make_filing_agent_headers(user_id=FILING_AGENT_USER_ID):
    return build_user_headers(user_id, UserRole.FILING_AGENT.value)


def make_employee_self_service_headers(employee_id):
    """``EmployeeSelfService`` identity is entity-backed: the header id is the
    Employee id, so callers must pass a real Employee row id."""
    return build_user_headers(employee_id, UserRole.EMPLOYEE_SELF_SERVICE.value)


TEST_USERS = {
    "compliance_officer": make_compliance_officer_headers(),
    "compliance_officer_2": make_compliance_officer_headers(COMPLIANCE_OFFICER_2_USER_ID),
    "benefits_admin": make_benefits_admin_headers(),
    "preparer": make_preparer_headers(),
    "preparer_2": make_preparer_headers(PREPARER_2_USER_ID),
    "filing_agent": make_filing_agent_headers(),
    "filing_agent_2": make_filing_agent_headers(FILING_AGENT_2_USER_ID),
}
