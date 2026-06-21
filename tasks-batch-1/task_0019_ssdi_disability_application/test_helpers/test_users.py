"""Pre-built role headers for every role in the PRD (PRD §2.1).

The Claimant role is entity-backed: X-User-ID must equal the persisted
Claimant.id for any ownership-gated call. Tests must therefore call
make_claimant_headers(claimant["id"]) with the actual id of the created
claimant rather than falling back to the shared constant.

The other four roles — DDSExaminer, ALJ, BenefitsAdmin, SSAAdmin — are
opaque operator identifiers: X-User-ID is not compared to any entity id.
Shared constants are the canonical form for those roles.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that don't
# exercise Claimant ownership.
TEST_USERS = {
    "ssa_admin_headers":     build_user_headers("admin_alice",  "SSAAdmin"),
    "ssa_admin_2_headers":   build_user_headers("admin_bob",    "SSAAdmin"),
    "dds_examiner_headers":  build_user_headers("dds_dave",     "DDSExaminer"),
    "dds_examiner_2_headers": build_user_headers("dds_evan",    "DDSExaminer"),
    "alj_headers":           build_user_headers("alj_jane",     "ALJ"),
    "alj_2_headers":         build_user_headers("alj_kate",     "ALJ"),
    "benefits_admin_headers": build_user_headers("ba_carol",    "BenefitsAdmin"),
    "benefits_admin_2_headers": build_user_headers("ba_chuck",  "BenefitsAdmin"),
    # claimant shared constant — used ONLY where ownership is not checked
    # (e.g., 401 unauthenticated tests, 403 forbidden tests, RBAC denial).
    "claimant_headers":      build_user_headers("claimant_x",   "Claimant"),
}


def make_claimant_headers(claimant_id: str) -> dict:
    """For Claimant (entity_backed). Pass the actual Claimant.id whenever
    the call is ownership-gated (creating an application for self,
    submitting, attaching evidence, requesting reconsideration / hearing,
    cancelling a hearing, creating a child auxiliary)."""
    return build_user_headers(claimant_id, "Claimant")


def make_headers(user_id: str, role: str) -> dict:
    """Build a header set with a specific X-User-ID — used for tests that
    must compare a stamped opaque user id (e.g., DDSExaminer recorded into
    examiner_user_id) or for RBAC tests where the calling identity differs."""
    return build_user_headers(user_id, role)


def make_unauthenticated_headers() -> dict:
    """Empty headers — used for the authentication test (PRD §2.1)."""
    return {}
