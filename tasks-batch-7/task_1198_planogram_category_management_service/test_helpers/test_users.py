"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise
# entity-backed identity. The CategoryCaptain role is entity_backed on Supplier,
# so a per-instance builder is required whenever the call is ownership-gated.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "retailer_admin_headers": build_user_headers("test-retailer-admin-1", "RetailerAdmin"),
    "category_manager_headers": build_user_headers("test-category-manager-1", "CategoryManager"),
    # Fallback for non-ownership captain contexts; prefer make_category_captain_headers.
    "category_captain_headers": build_user_headers("test-captain-1", "CategoryCaptain"),
    "field_auditor_headers": build_user_headers("test-field-auditor-1", "FieldAuditor"),
    "audit_reviewer_headers": build_user_headers("test-audit-reviewer-1", "AuditReviewer"),
    "reset_coordinator_headers": build_user_headers("test-reset-coordinator-1", "ResetCoordinator"),
}


def make_category_captain_headers(supplier_id: str) -> dict:
    """CategoryCaptain identity is entity_backed on Supplier.

    Per PRD §2.1: when X-User-Role is CategoryCaptain, X-User-ID must be the
    acting Supplier's id. Fixtures and tests MUST pass the actual supplier id
    here whenever the call's outcome depends on captain identity (submit,
    return-to-draft, and any ownership-gated workflow).
    """
    return build_user_headers(supplier_id, "CategoryCaptain")
