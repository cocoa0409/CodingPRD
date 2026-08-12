"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def board_director_headers():
    return TEST_USERS["board_director_headers"]


@pytest.fixture
def rate_analyst_headers():
    return TEST_USERS["rate_analyst_headers"]


@pytest.fixture
def program_operator_headers():
    return TEST_USERS["program_operator_headers"]


@pytest.fixture
def customer_service_headers():
    return TEST_USERS["customer_service_headers"]


@pytest.fixture
def portfolio_manager_headers():
    return TEST_USERS["portfolio_manager_headers"]


@pytest.fixture
def billing_coordinator_headers():
    return TEST_USERS["billing_coordinator_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def utility_liaison_headers():
    return TEST_USERS["utility_liaison_headers"]
