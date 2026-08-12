"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin and Inspector are opaque identities: the shared constants are
canonical. Contractor, Homeowner, and Subcontractor are entity-backed: any
ownership-gated call MUST use the per-instance builder with the actual
entity's id — the shared constants are fallbacks for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    # Entity-backed roles — fallback for tests that do not exercise ownership.
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    "subcontractor_headers": build_user_headers("test-subcontractor-1", "Subcontractor"),
}


def make_contractor_headers(user_id: str) -> dict:
    """Contractor is entity-backed: pass the actual Contractor.id as user_id
    whenever the call is ownership-gated (project-scoped mutations)."""
    return build_user_headers(user_id, "Contractor")


def make_homeowner_headers(user_id: str) -> dict:
    """Homeowner is entity-backed: pass the actual Homeowner.id as user_id
    whenever the call is ownership-gated (approvals, selections, claims)."""
    return build_user_headers(user_id, "Homeowner")


def make_subcontractor_headers(user_id: str) -> dict:
    """Subcontractor is entity-backed: pass the actual Subcontractor.id as
    user_id whenever the call is ownership-gated (phase start/complete, logs)."""
    return build_user_headers(user_id, "Subcontractor")
