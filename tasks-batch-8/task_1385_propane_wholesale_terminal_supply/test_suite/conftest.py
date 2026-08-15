"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def supply_admin_headers():
    return TEST_USERS["supply_admin_headers"]


@pytest.fixture
def supply_planner_headers():
    return TEST_USERS["supply_planner_headers"]


@pytest.fixture
def pricing_desk_headers():
    return TEST_USERS["pricing_desk_headers"]


@pytest.fixture
def credit_manager_headers():
    return TEST_USERS["credit_manager_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def dealer_user_headers():
    return TEST_USERS["dealer_user_headers"]
