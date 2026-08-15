"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_headers"]


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def site_operator_headers():
    return TEST_USERS["site_operator_headers"]


@pytest.fixture
def network_admin_headers():
    return TEST_USERS["network_admin_headers"]
