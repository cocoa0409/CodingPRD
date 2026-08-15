"""Pre-built role headers for every role in the PRD.

All five roles use opaque operator identities (PRD section 2.1): no role's
X-User-ID is the id of any persisted entity. Shared constants are therefore
canonical; the per-user builders exist for tests that must control the exact
X-User-ID recorded on a resource (e.g. submitted_by_user_id segregation).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "project_manager_headers": build_user_headers("pm-1", "ProjectManager"),
    "site_supervisor_headers": build_user_headers("sup-1", "SiteSupervisor"),
    "safety_officer_headers": build_user_headers("so-1", "SafetyOfficer"),
    "payroll_clerk_headers": build_user_headers("pay-1", "PayrollClerk"),
    "customer_rep_headers": build_user_headers("cust-1", "CustomerRep"),
}

# A request without an X-User-Role header (PRD section 2.1 ERR_UNAUTHENTICATED).
ANONYMOUS_HEADERS = {"X-User-ID": "anon-1", "Content-Type": "application/json"}


def make_project_manager_headers(user_id: str) -> dict:
    """ProjectManager headers with a caller-chosen opaque user id."""
    return build_user_headers(user_id, "ProjectManager")


def make_site_supervisor_headers(user_id: str) -> dict:
    """SiteSupervisor headers; pass the id that should land in submitted_by_user_id."""
    return build_user_headers(user_id, "SiteSupervisor")


def make_safety_officer_headers(user_id: str) -> dict:
    """SafetyOfficer headers with a caller-chosen opaque user id."""
    return build_user_headers(user_id, "SafetyOfficer")


def make_payroll_clerk_headers(user_id: str) -> dict:
    """PayrollClerk headers; must differ from the entry's submitter id on approve."""
    return build_user_headers(user_id, "PayrollClerk")


def make_customer_rep_headers(user_id: str) -> dict:
    """CustomerRep headers; the id lands in signed_off_by_user_id at sign-off."""
    return build_user_headers(user_id, "CustomerRep")
