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
# Role-header fixtures. Per PRD §2.1, PropertyManager / LeasingAgent /
# FinanceOfficer are OPAQUE so shared constants are canonical. Tenant is
# entity_backed: tests that exercise ownership MUST use the per-instance
# builder make_tenant_headers(tenant['id']).
# ---------------------------------------------------------------------------
@pytest.fixture
def pm_headers():
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def pm_headers_alt():
    return TEST_USERS["property_manager_headers_alt"]


@pytest.fixture
def la_headers():
    return TEST_USERS["leasing_agent_headers"]


@pytest.fixture
def la_headers_alt():
    return TEST_USERS["leasing_agent_headers_alt"]


@pytest.fixture
def fo_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def fo_headers_alt():
    return TEST_USERS["finance_officer_headers_alt"]


@pytest.fixture
def tenant_headers():
    """Fallback Tenant headers — opaque X-User-ID 'tenant-fallback'.

    PRD §2.1: ownership-gated Tenant-role endpoints compare X-User-ID
    to the resource's tenant foreign-key field; this constant matches
    no real Tenant.id, so use it only for tests that do NOT exercise
    ownership (missing-auth, wrong-role, missing-resource scenarios).
    """
    return TEST_USERS["tenant_headers"]
