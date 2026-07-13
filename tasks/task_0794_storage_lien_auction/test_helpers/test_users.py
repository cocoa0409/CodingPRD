"""Pre-built role headers for every role in the PRD (§2.1).

Roles: PlatformAdmin (opaque identity), FacilityOperator (entity_backed:Facility),
Buyer (entity_backed:Buyer), Tenant (entity_backed:Tenant).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque PlatformAdmin role, and for tests that
# do not exercise ownership (e.g. 404-on-missing, 422-on-bad-payload).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "facility_operator_headers": build_user_headers("test-facility-op-1", "FacilityOperator"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
}


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin identity is opaque; any id works."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_facility_operator_headers(facility_id: str) -> dict:
    """For FacilityOperator (entity_backed:Facility). Pass the actual Facility.id
    whenever the call is ownership-gated on the target unit's facility_id."""
    return build_user_headers(facility_id, "FacilityOperator")


def make_buyer_headers(buyer_id: str) -> dict:
    """For Buyer (entity_backed:Buyer). Pass the actual Buyer.id whenever the call
    is ownership-gated (bid, retract, pay, cleanout, fund-deposit)."""
    return build_user_headers(buyer_id, "Buyer")


def make_tenant_headers(tenant_id: str) -> dict:
    """For Tenant (entity_backed:Tenant). Pass the actual Tenant.id whenever the
    call is ownership-gated (cure, raise dispute)."""
    return build_user_headers(tenant_id, "Tenant")
