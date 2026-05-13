"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped api client.
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Role-header fixtures. Per PRD §2.1, PlatformAdmin and BillingOperator are
# OPAQUE so shared constants are canonical. TenantAdmin is entity_backed:
# tests that exercise ownership MUST use the per-instance builder
# make_tenant_admin_headers(tenant['id']).
# ---------------------------------------------------------------------------
@pytest.fixture
def pa_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def pa_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def bo_headers():
    return TEST_USERS["billing_operator_headers"]


@pytest.fixture
def bo_headers_alt():
    return TEST_USERS["billing_operator_headers_alt"]


@pytest.fixture
def tenant_admin_headers():
    """Fallback TenantAdmin headers — X-User-ID 'tenant-admin-fallback'.

    PRD §2.1: TenantAdmin ownership-gated endpoints compare X-User-ID
    to the path tenant_id; this constant matches no real Tenant.id, so
    use it only for tests that do NOT exercise ownership (missing-auth,
    wrong-role, missing-resource, or cross-tenant scenarios).
    """
    return TEST_USERS["tenant_admin_headers"]
