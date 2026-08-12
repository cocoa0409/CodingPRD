"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; each test starts against a
freshly restarted, empty server.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def agency_admin_headers():
    return TEST_USERS["agency_admin_headers"]


@pytest.fixture
def contracts_manager_headers():
    return TEST_USERS["contracts_manager_headers"]


@pytest.fixture
def royalties_accountant_headers():
    return TEST_USERS["royalties_accountant_headers"]


@pytest.fixture
def agent_headers():
    """Shared Agent headers — only for tests that never exercise ownership."""
    return TEST_USERS["agent_headers"]
