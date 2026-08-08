"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (ComplianceReviewer, PlatformAdmin)
# and for tests that do not exercise ownership. Host/Tenant are entity_backed,
# so ownership-gated calls MUST use the per-instance builders below.
TEST_USERS = {
    "host_headers": build_user_headers("test-host-1", "Host"),
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
    "compliance_reviewer_headers": build_user_headers("test-reviewer-1", "ComplianceReviewer"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}

# Anonymous self-registration carries no auth headers at all (§2.1).
ANONYMOUS_HEADERS: dict = {}


def make_host_headers(user_id: str) -> dict:
    """For Host (entity_backed:Host). Pass the actual Host.id whenever the call
    is ownership-gated (create/transition a unit, decide bookings, file claims)."""
    return build_user_headers(user_id, "Host")


def make_tenant_headers(user_id: str) -> dict:
    """For Tenant (entity_backed:Tenant). Pass the actual Tenant.id whenever the
    call is ownership-gated (request/cancel bookings, submit/resubmit
    verifications, request/withdraw extensions, dispute claims)."""
    return build_user_headers(user_id, "Tenant")


def make_admin_headers(user_id: str) -> dict:
    """For PlatformAdmin (opaque). The X-User-ID is recorded as
    scheduled_by_user_id on a payout and drives the maker-checker SoD check, so
    payout tests build distinct admin identities with this."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_reviewer_headers(user_id: str) -> dict:
    """For ComplianceReviewer (opaque)."""
    return build_user_headers(user_id, "ComplianceReviewer")
