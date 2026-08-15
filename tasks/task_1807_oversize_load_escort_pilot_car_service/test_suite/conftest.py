"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def route_surveyor_headers():
    return TEST_USERS["route_surveyor_headers"]


@pytest.fixture
def safety_manager_headers():
    return TEST_USERS["safety_manager_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def billing_clerk_checker_headers():
    return TEST_USERS["billing_clerk_checker_headers"]


@pytest.fixture
def finance_manager_headers():
    return TEST_USERS["finance_manager_headers"]


@pytest.fixture
def carrier_rep_headers():
    return TEST_USERS["carrier_rep_headers"]


@pytest.fixture
def escort_operator_headers():
    return TEST_USERS["escort_operator_headers"]
