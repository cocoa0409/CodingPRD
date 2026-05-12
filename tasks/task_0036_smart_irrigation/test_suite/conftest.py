"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start, readiness, shutdown) is managed by the
prd-bench-local-runner framework. PYTHONPATH points at the parent
directory so `test_helpers` is importable directly.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Base URL supplied by the runner."""
    return api_client


# --- Opaque-role headers (PRD §2.1) -------------------------------------
@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def water_admin_headers():
    return TEST_USERS["water_admin_headers"]


@pytest.fixture
def water_admin_headers_alt():
    return TEST_USERS["water_admin_headers_alt"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def operator_headers_alt():
    return TEST_USERS["operator_headers_alt"]


@pytest.fixture
def device_agent_headers():
    return TEST_USERS["device_agent_headers"]


@pytest.fixture
def device_agent_headers_alt():
    return TEST_USERS["device_agent_headers_alt"]


# --- Fallback headers for entity-backed Tenant role ----------------------
# Used only by tests that don't exercise an ownership comparison
# (RBAC ERR_FORBIDDEN_ROLE, ERR_MISSING_AUTH_HEADERS).
@pytest.fixture
def tenant_headers_fallback():
    return TEST_USERS["tenant_headers"]
