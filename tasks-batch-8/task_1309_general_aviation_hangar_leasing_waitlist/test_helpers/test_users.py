"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics (PRD §2.1): for `Applicant`, `X-User-ID` is the id of the
acting WaitlistApplication; for `Tenant`, the id of the acting Lease; for
`AirportManager` and `ComplianceOfficer` the id is an opaque operator
identifier never compared to any entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for entity-backed roles in
# tests that do not exercise ownership (e.g., 400/403/404 rejection paths
# decided before any ownership comparison).
TEST_USERS = {
    "manager_headers": build_user_headers("test-manager-1", "AirportManager"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    # Entity-backed roles: fallback for non-ownership-gated calls only
    # (e.g. POST /applications, where no application exists yet).
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
}


def make_applicant_headers(application_id: str) -> dict:
    """For Applicant (identity is the acting WaitlistApplication's id).

    Pass the actual application's id whenever the call is ownership-gated
    (withdraw, offer accept, offer decline).
    """
    return build_user_headers(application_id, "Applicant")


def make_tenant_headers(lease_id: str) -> dict:
    """For Tenant (identity is the acting Lease's id).

    Pass the actual lease's id whenever the call is ownership-gated
    (payments, aircraft, certificates, environmental records, cure,
    voluntary terminate).
    """
    return build_user_headers(lease_id, "Tenant")
