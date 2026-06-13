"""Pre-built role headers for every role in the COBRA Administration PRD (§2.1).

Four of the five roles — PlanAdministrator, PlanSponsor, BillingAgent, System —
are opaque operator identities: X-User-ID is never compared against any entity
id, so the shared constants below are the canonical form for those callers.

QualifiedBeneficiary is the one identity-bound role: X-User-ID is the id of the
acting beneficiary, and ownership checks on elect / payment compare the targeted
record's beneficiary_id to X-User-ID (PRD §2.1, §2.7). For those calls use the
per-instance builder make_beneficiary_headers(beneficiary_id) with the real
beneficiary id — falling back to the shared constant would make every ownership
check reject the request.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "plan_administrator_headers": build_user_headers("test-admin-1", "PlanAdministrator"),
    "plan_sponsor_headers": build_user_headers("test-sponsor-1", "PlanSponsor"),
    "billing_agent_headers": build_user_headers("test-billing-1", "BillingAgent"),
    # Shared constant for QualifiedBeneficiary: a fallback for non-ownership
    # tests only (e.g., calls expected to 404 before ownership is checked).
    "qualified_beneficiary_headers": build_user_headers("test-beneficiary-1", "QualifiedBeneficiary"),
}


def make_beneficiary_headers(beneficiary_id: str) -> dict:
    """For QualifiedBeneficiary (entity_backed:QualifiedBeneficiary). Pass the
    actual QualifiedBeneficiary.id as X-User-ID whenever the call (elect /
    payment) is ownership-gated (PRD §2.7)."""
    return build_user_headers(beneficiary_id, "QualifiedBeneficiary")


def make_role_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary operator id under a given role. Used by
    negative auth tests that must control the (id, role) pair."""
    return build_user_headers(user_id, role)
