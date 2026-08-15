"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def territory_manager_headers():
    return TEST_USERS["territory_manager_headers"]


@pytest.fixture
def market_admin_headers():
    return TEST_USERS["market_admin_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def distributor_owner_headers():
    return TEST_USERS["distributor_owner_headers"]


@pytest.fixture
def route_driver_headers():
    return TEST_USERS["route_driver_headers"]


@pytest.fixture
def store_receiver_headers():
    return TEST_USERS["store_receiver_headers"]
