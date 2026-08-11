"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle is managed by prd-bench-local-runner: the API under test
is restarted before every test, so each test starts from an empty database
and the default logical clock (2026-05-01T00:00:00Z, PRD §2.5).
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def farm_manager_headers():
    return TEST_USERS["farm_manager_headers"]


@pytest.fixture
def mgr_1_headers():
    return TEST_USERS["mgr_1_headers"]


@pytest.fixture
def mgr_2_headers():
    return TEST_USERS["mgr_2_headers"]


@pytest.fixture
def mgr_3_headers():
    return TEST_USERS["mgr_3_headers"]


@pytest.fixture
def landlord_headers():
    """Shared Landlord identity — only for calls that do not exercise
    entity-backed ownership (the id matches no persisted landlord)."""
    return TEST_USERS["landlord_headers"]


@pytest.fixture
def tenant_headers():
    """Shared Tenant identity — only for calls that do not exercise
    entity-backed ownership (the id matches no persisted tenant)."""
    return TEST_USERS["tenant_headers"]
