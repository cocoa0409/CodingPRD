"""Pre-built role headers for every role in the PRD.

Only Homeowner is entity-backed: when X-User-Role is Homeowner, X-User-ID must be the
acting Homeowner entity's id. Ownership-gated calls MUST use make_homeowner_headers(homeowner_id).
The other five roles (SalesDesigner, PermitOfficer, Manufacturer, InstallManager, Inspector)
are opaque operator identities — a shared constant is the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only
    # (e.g. ERR_FORBIDDEN_ROLE / ERR_UNAUTHENTICATED tests that never reach an ownership check).
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    # opaque roles: shared constant is the canonical form.
    "sales_designer_headers": build_user_headers("test-sales-1", "SalesDesigner"),
    "permit_officer_headers": build_user_headers("test-permit-1", "PermitOfficer"),
    "manufacturer_headers": build_user_headers("test-manufacturer-1", "Manufacturer"),
    "install_manager_headers": build_user_headers("test-install-1", "InstallManager"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
}


def make_homeowner_headers(user_id: str) -> dict:
    """For Homeowner (entity_backed:Homeowner). Pass the actual Homeowner.id as user_id
    whenever the call is ownership-gated (cancel project, accept/reject quote, submit
    financing, resubmit permit)."""
    return build_user_headers(user_id, "Homeowner")
