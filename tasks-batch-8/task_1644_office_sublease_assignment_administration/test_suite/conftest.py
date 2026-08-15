"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def asset_manager_headers():
    return TEST_USERS["asset_manager_headers"]


@pytest.fixture
def broker_1_headers():
    return TEST_USERS["broker_1_headers"]


@pytest.fixture
def broker_2_headers():
    return TEST_USERS["broker_2_headers"]
