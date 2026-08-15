"""Pre-built role headers for every role in the PRD (§2.1).

RenterOrgRep is entity-backed: its X-User-ID must equal the id of the
RenterOrganization it acts for. Use make_renter_headers(org_id) for any
ownership-gated call; the shared constant is a fallback for non-ownership
tests only. The other four roles are opaque operator identities.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, role denials).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "DistrictAdmin"),
    "director_headers": build_user_headers("test-director-1", "FacilitiesDirector"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "SiteCoordinator"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "CustodialSupervisor"),
    # entity_backed role: fallback for non-ownership tests only.
    "renter_headers": build_user_headers("test-renter-1", "RenterOrgRep"),
}


def make_renter_headers(user_id: str) -> dict:
    """For RenterOrgRep (entity-backed by RenterOrganization). Pass the actual
    RenterOrganization.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "RenterOrgRep")


def make_admin_headers(user_id: str) -> dict:
    """DistrictAdmin (opaque identity)."""
    return build_user_headers(user_id, "DistrictAdmin")


def make_director_headers(user_id: str) -> dict:
    """FacilitiesDirector (opaque identity). Use a distinct user_id when the
    segregation-of-duties rule must distinguish two operators."""
    return build_user_headers(user_id, "FacilitiesDirector")


def make_coordinator_headers(user_id: str) -> dict:
    """SiteCoordinator (opaque identity); the id is recorded as
    recorded_by_user_id on damage intake."""
    return build_user_headers(user_id, "SiteCoordinator")


def make_supervisor_headers(user_id: str) -> dict:
    """CustodialSupervisor (opaque identity)."""
    return build_user_headers(user_id, "CustodialSupervisor")
