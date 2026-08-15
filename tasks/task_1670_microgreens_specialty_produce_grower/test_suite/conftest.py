"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def grower_headers():
    return TEST_USERS["grower_headers"]


@pytest.fixture
def ops_manager_headers():
    return TEST_USERS["ops_manager_headers"]


@pytest.fixture
def chef_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["chef_headers"]
