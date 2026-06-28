"""Pre-built role headers for every role in the PRD.

Per PRD §2.1, the Estimator, ProjectManager, and FinanceOfficer roles are each
backed by a StaffMember, and HomeownerClient is backed by a HomeownerClient
entity. For any ownership/identity check, X-User-ID must equal the backing
entity's id. The per-instance builders below MUST be used (with a real entity
id) for ownership-gated calls; the shared TEST_USERS constants are only safe for
non-ownership tests (e.g. 400-on-bad-payload, 404-on-missing-resource, or the
opaque Anonymous role).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership of a specific entity.
TEST_USERS = {
    "anonymous_headers": None,  # Anonymous: no auth headers (opaque, public endpoints).
    "estimator_headers": build_user_headers("test-estimator-1", "Estimator"),
    "project_manager_headers": build_user_headers("test-pm-1", "ProjectManager"),
    "homeowner_client_headers": build_user_headers("test-client-1", "HomeownerClient"),
    "finance_officer_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
}


# Per-instance builders — required for every entity_backed role. Pass the actual
# backing entity id (StaffMember.id or HomeownerClient.id) whenever the call is
# ownership/identity gated.
def make_estimator_headers(staff_id: str) -> dict:
    """For Estimator (entity_backed:StaffMember). Pass the acting StaffMember.id."""
    return build_user_headers(staff_id, "Estimator")


def make_project_manager_headers(staff_id: str) -> dict:
    """For ProjectManager (entity_backed:StaffMember). Pass the acting StaffMember.id."""
    return build_user_headers(staff_id, "ProjectManager")


def make_finance_officer_headers(staff_id: str) -> dict:
    """For FinanceOfficer (entity_backed:StaffMember). Pass the acting StaffMember.id."""
    return build_user_headers(staff_id, "FinanceOfficer")


def make_homeowner_client_headers(client_id: str) -> dict:
    """For HomeownerClient (entity_backed:HomeownerClient). Pass the acting HomeownerClient.id."""
    return build_user_headers(client_id, "HomeownerClient")
