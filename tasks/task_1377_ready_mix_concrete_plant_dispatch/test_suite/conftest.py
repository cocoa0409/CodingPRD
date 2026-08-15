"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def batch_operator_headers():
    return TEST_USERS["batch_operator_headers"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_headers"]


@pytest.fixture
def qc_tech_headers():
    return TEST_USERS["qc_a_headers"]


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]
