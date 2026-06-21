"""Pre-built role headers for every role in the Rent-To-Own Home PRD (§2.1).

The system recognizes exactly three roles: `Landlord`, `Tenant`, `EscrowAgent`.
Landlord and Tenant are entity-backed (X-User-ID must equal the acting entity's id
for ownership checks); EscrowAgent is opaque (X-User-ID not tied to any entity).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do NOT exercise
# ownership (e.g. 401/404/422 paths). Entity-backed roles fall back to these only
# when ownership is not on the success path.
TEST_USERS = {
    "landlord_headers": build_user_headers("test-landlord-1", "Landlord"),
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
    # EscrowAgent is opaque: the shared constant is the canonical form.
    "escrow_headers": build_user_headers("test-escrow-1", "EscrowAgent"),
}


def make_landlord_headers(user_id: str) -> dict:
    """For Landlord (entity_backed:Landlord). Pass the actual Landlord.id as user_id
    whenever the call is ownership-gated (property/agreement landlord checks)."""
    return build_user_headers(user_id, "Landlord")


def make_tenant_headers(user_id: str) -> dict:
    """For Tenant (entity_backed:Tenant). Pass the actual Tenant.id as user_id
    whenever the call is ownership-gated (agreement/payment/ticket/exercise checks)."""
    return build_user_headers(user_id, "Tenant")


def make_escrow_headers(user_id: str = "test-escrow-1") -> dict:
    """For EscrowAgent (opaque). X-User-ID is an operator identifier, not an entity id."""
    return build_user_headers(user_id, "EscrowAgent")
