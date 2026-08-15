"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def feedyard_manager_headers():
    return TEST_USERS["feedyard_manager_headers"]


@pytest.fixture
def feed_manager_headers():
    return TEST_USERS["feed_manager_headers"]


@pytest.fixture
def cattle_health_tech_headers():
    return TEST_USERS["cattle_health_tech_headers"]


@pytest.fixture
def risk_manager_headers():
    return TEST_USERS["risk_manager_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def claims_treasurer_headers():
    return TEST_USERS["claims_treasurer_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
