"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # Opaque roles: the canonical form; the id is never compared to an entity id.
    "payroll_admin_headers": build_user_headers("admin-1", "PayrollAdmin"),
    "compliance_officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    # Entity-backed roles: fallback only for tests whose outcome never depends on
    # the caller owning the subject resource (e.g. 400 / 404 probes).
    "household_client_headers": build_user_headers("11111111-1111-1111-1111-111111111111", "HouseholdClient"),
    "worker_headers": build_user_headers("22222222-2222-2222-2222-222222222222", "Worker"),
}


def make_payroll_admin_headers(user_id: str = "admin-1") -> dict:
    """PayrollAdmin is an opaque role; any stable id works."""
    return build_user_headers(user_id, "PayrollAdmin")


def make_compliance_officer_headers(user_id: str = "officer-1") -> dict:
    """ComplianceOfficer is an opaque role; any stable id works."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_household_client_headers(employer_id: str) -> dict:
    """HouseholdClient is entity-backed: pass the acting HouseholdEmployer's id."""
    return build_user_headers(employer_id, "HouseholdClient")


def make_worker_headers(worker_id: str) -> dict:
    """Worker is entity-backed: pass the acting DomesticWorker's id."""
    return build_user_headers(worker_id, "Worker")
