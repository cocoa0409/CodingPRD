"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def salesrep_headers():
    return TEST_USERS["salesrep_headers"]


@pytest.fixture
def trafficmanager_headers():
    return TEST_USERS["trafficmanager_headers"]


@pytest.fixture
def copycoordinator_headers():
    return TEST_USERS["copycoordinator_headers"]


@pytest.fixture
def billingclerk_headers():
    return TEST_USERS["billingclerk_headers"]


@pytest.fixture
def stationadmin_headers():
    return TEST_USERS["stationadmin_headers"]
