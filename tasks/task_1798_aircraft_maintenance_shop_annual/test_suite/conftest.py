"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def shop_manager_headers():
    return TEST_USERS["shop_manager_headers"]


@pytest.fixture
def parts_clerk_headers():
    return TEST_USERS["parts_clerk_headers"]


@pytest.fixture
def mechanic_headers():
    return TEST_USERS["mechanic_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]
