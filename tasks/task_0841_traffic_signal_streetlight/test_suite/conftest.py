"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def traffic_engineer_headers():
    return TEST_USERS["traffic_engineer_headers"]


@pytest.fixture
def utility_coordinator_headers():
    return TEST_USERS["utility_coordinator_headers"]


@pytest.fixture
def fieldtech_headers():
    return TEST_USERS["fieldtech_headers"]
