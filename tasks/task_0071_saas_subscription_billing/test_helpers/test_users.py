"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- PlatformAdmin and BillingOperator carry OPAQUE X-User-IDs.
  "When `X-User-Role` is `PlatformAdmin`, the `X-User-ID` is an opaque
  operator identifier not tied to any persisted entity... The same holds
  when `X-User-Role` is `BillingOperator`."
  Shared constants are safe for these two roles.

- TenantAdmin is ENTITY-BACKED.
  "When `X-User-Role` is `TenantAdmin`, however, `X-User-ID` is the `id`
  of the acting `Tenant`; ownership checks on any tenant-scoped resource
  compare the path's `tenant_id` to `X-User-ID`, and a mismatch yields
  `ERR_CROSS_TENANT_ACCESS`."
  Every ownership-gated TenantAdmin call MUST use
  make_tenant_admin_headers(tenant['id']) — passing a shared fallback
  constant guarantees the ownership check fails for any real tenant id
  and cascades 'Setup failed' into every downstream test.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants and a non-binding TenantAdmin fallback.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — canonical constants.
    "platform_admin_headers": build_user_headers(
        "platform-admin-001", "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        "platform-admin-002", "PlatformAdmin",
    ),
    "billing_operator_headers": build_user_headers(
        "billing-operator-001", "BillingOperator",
    ),
    "billing_operator_headers_alt": build_user_headers(
        "billing-operator-002", "BillingOperator",
    ),
    # TenantAdmin fallback — use ONLY for tests that do not exercise
    # ownership. Per PRD §2.1 the real X-User-ID must equal Tenant.id
    # for any ownership-gated call; the per-instance builder below is
    # the correct path in fixtures.
    "tenant_admin_headers": build_user_headers(
        "tenant-admin-fallback", "TenantAdmin",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. Required for the entity_backed TenantAdmin role.
# ---------------------------------------------------------------------------
def make_tenant_admin_headers(tenant_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is TenantAdmin... X-User-ID is the id
    of the acting Tenant.' Pass the actual Tenant.id returned by
    POST /tenants whenever the downstream call is ownership-gated."""
    return build_user_headers(tenant_id, "TenantAdmin")


def make_platform_admin_headers(
    user_id: str = "platform-admin-001",
) -> Dict[str, str]:
    """PRD §2.1: PlatformAdmin X-User-ID is an opaque operator id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_billing_operator_headers(
    user_id: str = "billing-operator-001",
) -> Dict[str, str]:
    """PRD §2.1: BillingOperator X-User-ID is an opaque operator id."""
    return build_user_headers(user_id, "BillingOperator")


__all__ = [
    "TEST_USERS",
    "make_tenant_admin_headers",
    "make_platform_admin_headers",
    "make_billing_operator_headers",
]
