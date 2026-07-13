"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; each test starts
against a freshly-restarted (empty-database) API per the per-test-server
isolation contract.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def eoc_manager_headers() -> dict:
    return TEST_USERS["eoc_manager_headers"]


@pytest.fixture
def logistics_chief_headers() -> dict:
    return TEST_USERS["logistics_chief_headers"]


@pytest.fixture
def operations_chief_headers() -> dict:
    return TEST_USERS["operations_chief_headers"]


@pytest.fixture
def planning_chief_headers() -> dict:
    return TEST_USERS["planning_chief_headers"]


@pytest.fixture
def finance_chief_headers() -> dict:
    return TEST_USERS["finance_chief_headers"]


@pytest.fixture
def jurisdiction_liaison_headers() -> dict:
    """Shared placeholder liaison headers. Safe only for non-ownership paths;
    ownership-gated calls must use make_jurisdiction_liaison_headers(id)."""
    return TEST_USERS["jurisdiction_liaison_headers"]
