"""Pre-built role headers for every role in the PRD (§2.1).

Five roles (EOCManager, LogisticsChief, OperationsChief, PlanningChief,
FinanceChief) are opaque operator identities — X-User-ID is never compared
to any entity id, so the shared TEST_USERS constants are the canonical form
for them.

JurisdictionLiaison is entity-backed: its X-User-ID must equal the id of an
acting Jurisdiction, and mutual-aid ownership checks compare that value to
the request's to_jurisdiction_id (PRD §2.1). Tests that exercise a liaison
ownership-gated call MUST use make_jurisdiction_liaison_headers(jurisdiction_id)
with the real Jurisdiction.id — never the shared constant, whose placeholder
id matches no jurisdiction and would fail every ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "eoc_manager_headers": build_user_headers("test-eoc-manager-1", "EOCManager"),
    "logistics_chief_headers": build_user_headers("test-logistics-chief-1", "LogisticsChief"),
    "operations_chief_headers": build_user_headers("test-operations-chief-1", "OperationsChief"),
    "planning_chief_headers": build_user_headers("test-planning-chief-1", "PlanningChief"),
    "finance_chief_headers": build_user_headers("test-finance-chief-1", "FinanceChief"),
    # Shared constant carries a placeholder X-User-ID. Safe only for negative
    # paths that do not exercise ownership; positive ownership paths must use
    # make_jurisdiction_liaison_headers(jurisdiction_id).
    "jurisdiction_liaison_headers": build_user_headers("test-liaison-1", "JurisdictionLiaison"),
}


def make_jurisdiction_liaison_headers(jurisdiction_id: str) -> dict:
    """Headers for a JurisdictionLiaison bound to a specific Jurisdiction.id (PRD §2.1).

    Pass the real Jurisdiction.id whenever the mutual-aid transition is
    ownership-gated (OFFERED / re-offer)."""
    return build_user_headers(jurisdiction_id, "JurisdictionLiaison")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
