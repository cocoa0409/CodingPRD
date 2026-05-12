"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes roles by identity binding:

- PlatformAdmin, WaterAdmin, Operator, DeviceAgent: 'X-User-ID is an
  opaque operator identifier not tied to any persisted entity.' The
  shared TEST_USERS constants are canonical for these roles.

- Tenant: PRD §2.1: 'When X-User-Role is Tenant, X-User-ID is the id of
  the acting Tenant entity; ownership checks on any resource that
  references a Tenant (a Plot, a WaterQuota reached via its plot_id, a
  WaterBill) compare the resource's tenant_id to X-User-ID.' Tenant is
  entity-backed: ownership-gated calls (POST /water-bills/{id}/dispute,
  POST /water-bills/{id}/payments by Tenant, GET /water-bills/{id} as
  Tenant, etc.) MUST use make_tenant_headers(tenant_id) with the actual
  Tenant.id.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants. For the four opaque roles, these are canonical. For
# Tenant (entity-backed), the constant is a fallback for tests that don't
# exercise ownership comparison (e.g., ERR_FORBIDDEN_ROLE wrong-role tests,
# ERR_NOT_FOUND on missing resource).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — canonical shared constants.
    "platform_admin_headers": build_user_headers(
        "platform-admin-001", "PlatformAdmin"
    ),
    "platform_admin_headers_alt": build_user_headers(
        "platform-admin-002", "PlatformAdmin"
    ),
    "water_admin_headers": build_user_headers(
        "water-admin-001", "WaterAdmin"
    ),
    "water_admin_headers_alt": build_user_headers(
        "water-admin-002", "WaterAdmin"
    ),
    "operator_headers": build_user_headers(
        "operator-001", "Operator"
    ),
    "operator_headers_alt": build_user_headers(
        "operator-002", "Operator"
    ),
    "device_agent_headers": build_user_headers(
        "device-agent-001", "DeviceAgent"
    ),
    "device_agent_headers_alt": build_user_headers(
        "device-agent-002", "DeviceAgent"
    ),
    # Fallback for Tenant — only for non-ownership tests (e.g., RBAC
    # wrong-role checks, ERR_NOT_FOUND on missing resource). Ownership-gated
    # tests must build per-instance headers via make_tenant_headers.
    "tenant_headers": build_user_headers(
        "tenant-fallback-001", "Tenant"
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder for the entity-backed role.
# ---------------------------------------------------------------------------
def make_tenant_headers(tenant_id: str) -> Dict[str, str]:
    """Tenant headers. PRD §2.1: 'When X-User-Role is Tenant, X-User-ID is
    the id of the acting Tenant entity; ownership checks on any resource
    that references a Tenant (a Plot, a WaterQuota reached via its
    plot_id, a WaterBill) compare the resource's tenant_id to X-User-ID.'

    Pass the actual Tenant.id whenever the call is ownership-gated.
    """
    return build_user_headers(tenant_id, "Tenant")


# ---------------------------------------------------------------------------
# Per-instance builders for opaque roles (lets a test pin a specific
# X-User-ID, e.g. for audit-log actor_id assertions).
# ---------------------------------------------------------------------------
def make_platform_admin_headers(
    admin_id: str = "platform-admin-001",
) -> Dict[str, str]:
    return build_user_headers(admin_id, "PlatformAdmin")


def make_water_admin_headers(
    admin_id: str = "water-admin-001",
) -> Dict[str, str]:
    return build_user_headers(admin_id, "WaterAdmin")


def make_operator_headers(
    operator_id: str = "operator-001",
) -> Dict[str, str]:
    return build_user_headers(operator_id, "Operator")


def make_device_agent_headers(
    device_id: str = "device-agent-001",
) -> Dict[str, str]:
    return build_user_headers(device_id, "DeviceAgent")


__all__ = [
    "TEST_USERS",
    "make_tenant_headers",
    "make_platform_admin_headers",
    "make_water_admin_headers",
    "make_operator_headers",
    "make_device_agent_headers",
]
