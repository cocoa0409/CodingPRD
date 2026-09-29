"""Identity headers for the seven roles the programme recognises (PRD §2.1).

Six identities are opaque operator or consumer identifiers, so a shared constant per
role is enough. `RepairProviderTech` is the one entity-backed identity: it is resolved
to the acting provider through a `TrainingCertification` whose `technician_user_id`
equals the header value, so tests that act as a technician must build headers around
the technician user id whose certification names the intended provider.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------- #
# Shared identities, one per role.
# --------------------------------------------------------------------------- #
TEST_USERS = {
    "program_admin": build_user_headers("user_admin_001", UserRole.PROGRAM_ADMIN.value),
    "safety_reviewer": build_user_headers("user_safety_001", UserRole.SAFETY_REVIEWER.value),
    "safety_reviewer_alt": build_user_headers("user_safety_002", UserRole.SAFETY_REVIEWER.value),
    "documentation_engineer": build_user_headers(
        "user_docs_001", UserRole.DOCUMENTATION_ENGINEER.value
    ),
    "documentation_engineer_alt": build_user_headers(
        "user_docs_002", UserRole.DOCUMENTATION_ENGINEER.value
    ),
    "compliance_officer": build_user_headers(
        "user_compliance_001", UserRole.COMPLIANCE_OFFICER.value
    ),
    "self_repair_customer": build_user_headers(
        "user_customer_001", UserRole.SELF_REPAIR_CUSTOMER.value
    ),
    "self_repair_customer_alt": build_user_headers(
        "user_customer_002", UserRole.SELF_REPAIR_CUSTOMER.value
    ),
    "repair_provider_tech": build_user_headers(
        "user_tech_001", UserRole.REPAIR_PROVIDER_TECH.value
    ),
    "repair_provider_tech_alt": build_user_headers(
        "user_tech_002", UserRole.REPAIR_PROVIDER_TECH.value
    ),
    "failure_analysis_engineer": build_user_headers(
        "user_failure_001", UserRole.FAILURE_ANALYSIS_ENGINEER.value
    ),
    "failure_analysis_engineer_alt": build_user_headers(
        "user_failure_002", UserRole.FAILURE_ANALYSIS_ENGINEER.value
    ),
}

ADMIN = TEST_USERS["program_admin"]
SAFETY = TEST_USERS["safety_reviewer"]
SAFETY_ALT = TEST_USERS["safety_reviewer_alt"]
DOCS = TEST_USERS["documentation_engineer"]
DOCS_ALT = TEST_USERS["documentation_engineer_alt"]
COMPLIANCE = TEST_USERS["compliance_officer"]
CUSTOMER = TEST_USERS["self_repair_customer"]
CUSTOMER_ALT = TEST_USERS["self_repair_customer_alt"]
TECH = TEST_USERS["repair_provider_tech"]
TECH_ALT = TEST_USERS["repair_provider_tech_alt"]
FAILURE_ENGINEER = TEST_USERS["failure_analysis_engineer"]
FAILURE_ENGINEER_ALT = TEST_USERS["failure_analysis_engineer_alt"]

TECHNICIAN_USER_ID = "user_tech_001"
TECHNICIAN_USER_ID_ALT = "user_tech_002"

HEADERS_BY_ROLE = {
    UserRole.PROGRAM_ADMIN.value: ADMIN,
    UserRole.SAFETY_REVIEWER.value: SAFETY,
    UserRole.DOCUMENTATION_ENGINEER.value: DOCS,
    UserRole.COMPLIANCE_OFFICER.value: COMPLIANCE,
    UserRole.SELF_REPAIR_CUSTOMER.value: CUSTOMER,
    UserRole.REPAIR_PROVIDER_TECH.value: TECH,
    UserRole.FAILURE_ANALYSIS_ENGINEER.value: FAILURE_ENGINEER,
}


# --------------------------------------------------------------------------- #
# Per-instance builders.
# --------------------------------------------------------------------------- #
def make_repair_provider_tech_headers(technician_user_id):
    """Headers for a technician identity resolved through its training certification.

    `technician_user_id` must be the value stored as `technician_user_id` on a
    `TrainingCertification` of the provider the caller intends to act for.
    """
    return build_user_headers(technician_user_id, UserRole.REPAIR_PROVIDER_TECH.value)


def make_headers(user_id, role):
    """Headers for an arbitrary user id acting in an arbitrary role."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role):
    """Headers that declare a role but carry no `X-User-ID` value."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_role_only(role):
    """Alias kept for readability at call sites that test the missing-user-id rule."""
    return headers_without_user_id(role)
