"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. For entity-backed roles (EmployerContact, Instructor) these are
# fallbacks only; ownership-gated calls MUST use the per-instance builders.
TEST_USERS = {
    "admin_headers": build_user_headers("adm-01", "CollegeAdmin"),
    "coordinator_headers": build_user_headers("wc-01", "WorkforceCoordinator"),
    "credential_officer_headers": build_user_headers("co-01", "CredentialOfficer"),
    "grant_officer_headers": build_user_headers("go-01", "GrantOfficer"),
    "billing_clerk_headers": build_user_headers("bc-01", "BillingClerk"),
    # entity_backed fallbacks (non-ownership tests only):
    "employer_contact_headers": build_user_headers("emp-unknown", "EmployerContact"),
    "instructor_headers": build_user_headers("ins-unknown", "Instructor"),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CollegeAdmin")


def make_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WorkforceCoordinator")


def make_credential_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CredentialOfficer")


def make_grant_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GrantOfficer")


def make_billing_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_employer_contact_headers(user_id: str) -> dict:
    """For EmployerContact (entity_backed:Employer). Pass the actual
    Employer.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "EmployerContact")


def make_instructor_headers(user_id: str) -> dict:
    """For Instructor (entity_backed:Instructor). Pass the actual
    Instructor.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Instructor")
