"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests assume the server is
already reachable at API_BASE_URL.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def spec_author_headers():
    return TEST_USERS["spec_author_headers"]


@pytest.fixture
def quality_manager_headers():
    return TEST_USERS["quality_manager_headers"]


@pytest.fixture
def procurement_manager_headers():
    return TEST_USERS["procurement_manager_headers"]


@pytest.fixture
def sqe_headers():
    return TEST_USERS["sqe_headers"]


@pytest.fixture
def regulatory_affairs_headers():
    return TEST_USERS["regulatory_affairs_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
