"""Pre-built role headers for every role in the PRD (§2.1).

Four roles carry an opaque X-User-ID (PublicWorksAdmin, RouteDispatcher,
SignageInspector, EnforcementOfficer): the value is an operator identifier not
tied to any persisted entity. For segregation-of-duties on citations, distinct
EnforcementOfficer identifiers matter (issuing vs. adjudicating), so use
make_officer_headers(user_id) to control the acting officer id.

Resident is the one entity-backed role: its X-User-ID is the id of the acting
Resident entity, and every complaint ownership check compares against it. For
ownership-gated calls (file, reopen) use make_resident_headers(resident_id) with
the real Resident.id — the shared constant below is a fallback for non-ownership
tests (e.g. RBAC-denial checks) only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "public_works_admin_headers": build_user_headers("test-admin-1", "PublicWorksAdmin"),
    "route_dispatcher_headers": build_user_headers("test-dispatcher-1", "RouteDispatcher"),
    "signage_inspector_headers": build_user_headers("test-inspector-1", "SignageInspector"),
    "enforcement_officer_headers": build_user_headers("officer-1", "EnforcementOfficer"),
    # entity_backed:Resident — shared constant never equals a real Resident.id, so
    # it is only valid for tests that do NOT exercise the ownership check.
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
}


def make_officer_headers(user_id: str) -> dict:
    """Headers for an EnforcementOfficer with a specific opaque operator id.
    Pass distinct ids for the issuing officer vs. the adjudicator so the
    segregation-of-duties check (§3.7) behaves as intended."""
    return build_user_headers(user_id, "EnforcementOfficer")


def make_resident_headers(resident_id: str) -> dict:
    """Headers for a Resident (entity_backed:Resident). Pass the acting
    Resident.id as user_id whenever the call is ownership-gated (§2.1)."""
    return build_user_headers(resident_id, "Resident")
