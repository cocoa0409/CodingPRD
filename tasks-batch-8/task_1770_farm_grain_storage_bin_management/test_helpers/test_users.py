"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership tests.
# The applicator shared constant is a FALLBACK for RBAC-denial tests only;
# ownership-gated calls (fumigation create/clear) must use
# make_applicator_headers(applicator_id) with the real entity id.
TEST_USERS = {
    "site_manager_headers": build_user_headers("mgr-1", "SiteManager"),
    "farm_owner_headers": build_user_headers("owner-1", "FarmOwner"),
    "certified_applicator_headers": build_user_headers(
        "applicator-shared-fallback", "CertifiedApplicator"
    ),
    "safety_officer_headers": build_user_headers("so-1", "SafetyOfficer"),
}


def make_site_manager_headers(user_id: str) -> dict:
    """SiteManager is opaque; use when a test wants a distinct identity
    (e.g. permit requester who must differ from the approver)."""
    return build_user_headers(user_id, "SiteManager")


def make_farm_owner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FarmOwner")


def make_applicator_headers(applicator_id: str) -> dict:
    """CertifiedApplicator is entity_backed: X-User-ID must equal the
    Applicator.id for any ownership-gated call (create/clear fumigation)."""
    return build_user_headers(applicator_id, "CertifiedApplicator")


def make_safety_officer_headers(user_id: str) -> dict:
    """SafetyOfficer is opaque; pass a distinct user_id when exercising
    permit segregation (approver != requester)."""
    return build_user_headers(user_id, "SafetyOfficer")
