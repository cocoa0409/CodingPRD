"""Pre-built role headers for every role in the PRD (§2.1).

All five roles use opaque operator identifiers: the server never matches
`X-User-ID` against a stored entity `id`. For `TenantRep`, the identifier is
stamped as `tenant_rep_id` on each requirement and tour the representative
creates, and ownership checks compare that field to `X-User-ID` — so the rep
constants below double as ownership tokens and fixtures thread them by name.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # TenantRep identifiers — ownership tokens for rep-scoped writes.
    "tenant_rep_1_headers": build_user_headers("rep-001", "TenantRep"),
    "tenant_rep_2_headers": build_user_headers("rep-002", "TenantRep"),
    # Developer-side desks (opaque identifiers).
    "leasing_manager_headers": build_user_headers("lm-001", "LeasingManager"),
    "project_manager_headers": build_user_headers("pm-001", "ProjectManager"),
    "asset_manager_headers": build_user_headers("am-001", "AssetManager"),
    "compliance_officer_headers": build_user_headers("co-001", "ComplianceOfficer"),
}


def make_tenant_rep_headers(user_id: str) -> dict:
    """TenantRep headers for an arbitrary rep id. Use when a test needs a rep
    other than rep-001/rep-002; the same id must drive every ownership-gated
    call on resources that rep creates."""
    return build_user_headers(user_id, "TenantRep")


def make_leasing_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LeasingManager")


def make_project_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectManager")


def make_asset_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AssetManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
