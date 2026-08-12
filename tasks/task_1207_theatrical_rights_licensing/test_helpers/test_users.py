"""Pre-built role headers for every role in the PRD (§2.1).

The Applicant role is entity-backed by Organization: X-User-ID must be the
acting Organization's id whenever the call is ownership-gated. The four
remaining roles are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise ownership (400-on-bad-payload, 404-on-missing-resource, or calls
# by opaque roles).
TEST_USERS = {
    "rights_admin_headers": build_user_headers("test-rights-admin-1", "RightsAdmin"),
    "licensing_officer_headers": build_user_headers(
        "test-licensing-officer-1", "LicensingOfficer"
    ),
    "materials_clerk_headers": build_user_headers(
        "test-materials-clerk-1", "MaterialsClerk"
    ),
    "finance_officer_headers": build_user_headers(
        "test-finance-officer-1", "FinanceOfficer"
    ),
    # Entity-backed role: shared constant is a fallback for non-ownership
    # tests only (e.g., calling an endpoint where no org-scoped resource is
    # touched, or RBAC-denial probes).
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


def make_applicant_headers(user_id: str) -> dict:
    """For Applicant (entity-backed: Organization). Pass the actual
    Organization.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Applicant")
