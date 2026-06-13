"""Pre-built role headers for every role in the Identity Governance PRD (§2.1).

All five roles — CatalogAdmin, AccessManager, AccessApprover, CampaignAdmin,
Certifier — are opaque operator identities: X-User-ID is never compared against
any entity id as an ownership check. The shared constants below are therefore
the canonical form for ordinary calls.

The ONE place X-User-ID matters is separation of duties (§3.3, §3.4): the
approver/returner/rejecter X-User-ID is compared against the request's stored
requester_user_id and against the target identity. For those scenarios use the
per-operator builder make_role_headers(user_id, role) to pin distinct (or
deliberately colliding) operator ids.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "catalog_admin_headers": build_user_headers("test-catalog-admin-1", "CatalogAdmin"),
    "access_manager_headers": build_user_headers("test-access-manager-1", "AccessManager"),
    "access_approver_headers": build_user_headers("test-access-approver-1", "AccessApprover"),
    "campaign_admin_headers": build_user_headers("test-campaign-admin-1", "CampaignAdmin"),
    "certifier_headers": build_user_headers("test-certifier-1", "Certifier"),
}


def make_role_headers(user_id: str, role: str) -> dict:
    """Build headers for a specific operator id under a given role. Used by
    separation-of-duties tests that must control which X-User-ID raises vs.
    decides a request, and by negative auth tests using an arbitrary role
    string."""
    return build_user_headers(user_id, role)


def make_access_manager_headers(user_id: str) -> dict:
    """AccessManager headers bound to a specific operator id — the requester
    side of a separation-of-duties scenario (§3.3)."""
    return build_user_headers(user_id, "AccessManager")


def make_access_approver_headers(user_id: str) -> dict:
    """AccessApprover headers bound to a specific operator id — the decider
    side of a separation-of-duties scenario (§3.4)."""
    return build_user_headers(user_id, "AccessApprover")
