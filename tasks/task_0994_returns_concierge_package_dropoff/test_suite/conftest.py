"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin2_headers():
    return TEST_USERS["platform_admin2_headers"]


@pytest.fixture
def support_agent_headers():
    return TEST_USERS["support_agent_headers"]


@pytest.fixture
def support_agent2_headers():
    return TEST_USERS["support_agent2_headers"]


@pytest.fixture
def carrier_dispatcher_headers():
    return TEST_USERS["carrier_dispatcher_headers"]


@pytest.fixture
def shopper_headers():
    return TEST_USERS["shopper_headers"]


@pytest.fixture
def merchant_admin_headers():
    return TEST_USERS["merchant_admin_headers"]


@pytest.fixture
def location_operator_headers():
    return TEST_USERS["location_operator_headers"]
