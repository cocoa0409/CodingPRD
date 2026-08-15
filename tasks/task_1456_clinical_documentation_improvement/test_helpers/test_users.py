"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "cdi_manager_headers": build_user_headers("test-cdi-manager-1", "CDIManager"),
    "cdi_specialist_headers": build_user_headers("test-cdi-specialist-1", "CDISpecialist"),
    "him_coder_headers": build_user_headers("test-him-coder-1", "HIMCoder"),
    "compliance_auditor_headers": build_user_headers("test-compliance-auditor-1", "ComplianceAuditor"),
    "system_admin_headers": build_user_headers("test-system-admin-1", "SystemAdmin"),
    # Provider is entity_backed: shared constant is a fallback for non-ownership tests only.
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
}


def make_provider_headers(provider_id: str) -> dict:
    """For Provider (entity_backed:Provider). Pass the actual Provider.id as
    user_id whenever the call is ownership-gated (e.g., responding to a query)."""
    return build_user_headers(provider_id, "Provider")
