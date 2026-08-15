"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def shop_manager_headers():
    return TEST_USERS["shop_manager_headers"]


@pytest.fixture
def estimator_headers():
    return TEST_USERS["estimator_headers"]


@pytest.fixture
def customer_rep_headers():
    return TEST_USERS["customer_rep_headers"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def qc_inspector_headers():
    return TEST_USERS["qc_inspector_headers"]


@pytest.fixture
def inventory_clerk_headers():
    return TEST_USERS["inventory_clerk_headers"]
