"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def branch_manager_headers():
    return TEST_USERS["branch_manager_headers"]


@pytest.fixture
def rental_coordinator_headers():
    return TEST_USERS["rental_coordinator_headers"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_headers"]


@pytest.fixture
def yard_technician_headers():
    return TEST_USERS["yard_technician_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
