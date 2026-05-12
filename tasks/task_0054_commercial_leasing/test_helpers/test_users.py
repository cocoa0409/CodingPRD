"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- PropertyManager / LeasingAgent / FinanceOfficer carry OPAQUE
  X-User-IDs. 'When X-User-Role is PropertyManager, LeasingAgent, or
  FinanceOfficer, X-User-ID is an opaque operator identifier not tied to
  any persisted entity. The server may record it (for example, as
  actor_id on an AuditEvent row whose actor_role records which of these
  three roles acted) but does not compare it to any entity's id.'
  Shared constants are safe for these roles.

- Tenant is ENTITY-BACKED. 'When X-User-Role is Tenant, X-User-ID is the
  id of the acting Tenant; ownership checks on any resource that
  references a Tenant — a Lease, a Deposit, a FeeBill, a MoveOutRequest,
  or a Unit reached through one of those — compare the resource's tenant
  foreign-key field to X-User-ID, and a tenant acting on a resource that
  belongs to another tenant is rejected with ERR_FORBIDDEN.' Every
  ownership-gated Tenant-role call MUST use make_tenant_headers(
  tenant['id']) — passing a shared fallback constant guarantees the
  ownership check fails for any real tenant id, cascading 'Setup failed'
  into every downstream test.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants and a non-binding Tenant fallback.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — canonical constants.
    "property_manager_headers": build_user_headers(
        "property-manager-001", "PropertyManager",
    ),
    "property_manager_headers_alt": build_user_headers(
        "property-manager-002", "PropertyManager",
    ),
    "leasing_agent_headers": build_user_headers(
        "leasing-agent-001", "LeasingAgent",
    ),
    "leasing_agent_headers_alt": build_user_headers(
        "leasing-agent-002", "LeasingAgent",
    ),
    "finance_officer_headers": build_user_headers(
        "finance-officer-001", "FinanceOfficer",
    ),
    "finance_officer_headers_alt": build_user_headers(
        "finance-officer-002", "FinanceOfficer",
    ),
    # Tenant fallback — use ONLY for tests that do not exercise
    # ownership. Per PRD §2.1 the real X-User-ID must equal Tenant.id
    # for any ownership-gated call; the per-instance builder below is
    # the correct path in fixtures.
    "tenant_headers": build_user_headers(
        "tenant-fallback", "Tenant",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. Required for the entity_backed Tenant role.
# ---------------------------------------------------------------------------
def make_tenant_headers(tenant_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Tenant, X-User-ID is the id of the
    acting Tenant.' Pass the actual Tenant.id returned by POST /tenants
    whenever the downstream call is ownership-gated (top-up, pay,
    dispute, move-out-request, get-own-resource)."""
    return build_user_headers(tenant_id, "Tenant")


def make_property_manager_headers(
    user_id: str = "property-manager-001",
) -> Dict[str, str]:
    """PRD §2.1: PropertyManager X-User-ID is an opaque operator id."""
    return build_user_headers(user_id, "PropertyManager")


def make_leasing_agent_headers(
    user_id: str = "leasing-agent-001",
) -> Dict[str, str]:
    """PRD §2.1: LeasingAgent X-User-ID is an opaque operator id."""
    return build_user_headers(user_id, "LeasingAgent")


def make_finance_officer_headers(
    user_id: str = "finance-officer-001",
) -> Dict[str, str]:
    """PRD §2.1: FinanceOfficer X-User-ID is an opaque operator id."""
    return build_user_headers(user_id, "FinanceOfficer")


__all__ = [
    "TEST_USERS",
    "make_tenant_headers",
    "make_property_manager_headers",
    "make_leasing_agent_headers",
    "make_finance_officer_headers",
]
