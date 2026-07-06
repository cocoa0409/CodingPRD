"""Pre-built role headers for every role in the PRD.

Only OrgAdmin is entity_backed (its X-User-ID is the acting Organization's id and is
compared against a resource's organization foreign key on ownership-gated calls). The other
four roles are opaque: the server records X-User-ID but never compares it to an entity id,
so a shared constant is always correct for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for non-ownership tests of OrgAdmin
# (e.g. 401/403/404/422 paths that never reach an ownership comparison).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "org_admin_headers": build_user_headers("test-org-admin-1", "OrgAdmin"),
    "audit_engineer_headers": build_user_headers("test-audit-engineer-1", "AuditEngineer"),
    "remediation_vendor_headers": build_user_headers("test-remediation-vendor-1", "RemediationVendor"),
    "compliance_manager_headers": build_user_headers("test-compliance-manager-1", "ComplianceManager"),
}


def make_org_admin_headers(organization_id: str) -> dict:
    """For OrgAdmin (entity_backed:Organization). Pass the actual Organization.id as the
    user id whenever the call is ownership-gated (creating/activating subscriptions, sites,
    training under that org)."""
    return build_user_headers(organization_id, "OrgAdmin")


# Opaque-role builders (parametrized RBAC tests may want an explicit id, but any id works).
def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_audit_engineer_headers(user_id: str = "test-audit-engineer-1") -> dict:
    return build_user_headers(user_id, "AuditEngineer")


def make_remediation_vendor_headers(user_id: str = "test-remediation-vendor-1") -> dict:
    return build_user_headers(user_id, "RemediationVendor")


def make_compliance_manager_headers(user_id: str = "test-compliance-manager-1") -> dict:
    return build_user_headers(user_id, "ComplianceManager")
