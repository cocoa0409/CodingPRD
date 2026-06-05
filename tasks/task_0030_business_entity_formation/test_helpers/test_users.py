"""Pre-built role headers for every role in the PRD (PRD §2.1).

Only the Filer role is entity_backed (Filer.X-User-ID == BusinessEntity.id).
Anonymous, StateAdmin, and ComplianceOfficer are opaque — the shared TEST_USERS
constants for those roles are the canonical form. Filer ownership-gated calls
MUST use `make_filer_headers(business_entity_id)` instead of the shared constant,
because the canonical-bug fallback uses a placeholder string that never matches
any real BusinessEntity.id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Anonymous — PRD §2.1: pre-formation requester, opaque X-User-ID.
    # The two anonymous endpoints (POST /business-entities and GET reads) still
    # require X-User-Role=Anonymous; X-User-ID is an opaque token.
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # Opaque roles — shared constants are canonical.
    "state_admin_headers": build_user_headers("test-state-admin-1", "StateAdmin"),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", "ComplianceOfficer"
    ),
    # Entity-backed Filer — shared fallback for non-ownership tests
    # (e.g., 401/403/404 paths or calls where the resource does not yet exist).
    "filer_headers": build_user_headers("test-filer-1", "Filer"),
}


def make_filer_headers(business_entity_id: str) -> dict:
    """Filer (entity_backed:BusinessEntity) headers bound to a specific
    BusinessEntity.id (PRD §2.1). Use this whenever the call is ownership-gated."""
    return build_user_headers(business_entity_id, "Filer")


def make_state_admin_headers(user_id: str = "test-state-admin-1") -> dict:
    """StateAdmin headers (opaque user-id)."""
    return build_user_headers(user_id, "StateAdmin")


def make_compliance_officer_headers(user_id: str = "test-compliance-officer-1") -> dict:
    """ComplianceOfficer headers (opaque user-id)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    """Anonymous headers (opaque user-id)."""
    return build_user_headers(user_id, "Anonymous")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
