"""Pre-built role headers for every role in the PRD.

Roles:
- PropertyManager (opaque): X-User-ID is an opaque operator id, never matched to an entity.
- Accountant (opaque): same — but segregation of duties requires the posting Accountant's
  X-User-ID to differ from the submitting user's, so distinct opaque ids are provided.
- Tenant (entity_backed:Tenant): X-User-ID MUST equal the acting Tenant entity's id for
  any ownership-gated call (dispute, estoppel respond). Use make_tenant_headers(tenant_id).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that do not exercise
# tenant ownership. For ownership-gated tenant calls, use make_tenant_headers().
TEST_USERS = {
    "property_manager_headers": build_user_headers("pm-001", "PropertyManager"),
    "accountant_headers": build_user_headers("acct-001", "Accountant"),
    # A second, distinct Accountant id for segregation-of-duties posting flows.
    "accountant2_headers": build_user_headers("acct-002", "Accountant"),
    # A Tenant shared constant only useful where ownership is irrelevant (e.g. an
    # opaque-id 401/403 probe). Real tenant actions must use make_tenant_headers().
    "tenant_headers": build_user_headers("tenant-unowned-001", "Tenant"),
}


def make_property_manager_headers(user_id: str) -> dict:
    """PropertyManager (opaque). Pass a chosen operator id; used to pin the
    submitter identity for segregation-of-duties scenarios."""
    return build_user_headers(user_id, "PropertyManager")


def make_accountant_headers(user_id: str) -> dict:
    """Accountant (opaque). Pass a chosen operator id; the posting accountant's id
    must differ from the submitter's id (segregation of duties)."""
    return build_user_headers(user_id, "Accountant")


def make_tenant_headers(user_id: str) -> dict:
    """Tenant (entity_backed:Tenant). Pass the actual Tenant entity's id as user_id
    for any ownership-gated call (dispute a reconciliation, respond to an estoppel)."""
    return build_user_headers(user_id, "Tenant")
